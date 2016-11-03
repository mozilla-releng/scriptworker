#!/usr/bin/env python
"""Chain of Trust artifact validation.

Attributes:
    log (logging.Logger): the log object for this module.
"""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from frozendict import frozendict
import json
import logging
import os
import pprint
import re
# import shlex
from urllib.parse import unquote, urljoin, urlparse
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.exceptions import CoTError, ScriptWorkerGPGException
from scriptworker.gpg import get_body, GPG
from scriptworker.task import download_artifacts, get_decision_task_id, get_worker_type, get_task_id
from scriptworker.utils import get_hash, makedirs, raise_future_exceptions
from taskcluster.exceptions import TaskclusterFailure

log = logging.getLogger(__name__)


# ChainOfTrust {{{1
class ChainOfTrust(object):
    """The master Chain of Trust, tracking all the various `LinkOfTrust`s.

    Attributes:
        context (scriptworker.context.Context): the scriptworker context
        cot_dir (str): the local path containing this link's artifacts
        decision_task_id (str): the task_id of self.task's decision task
        links (list): the list of `LinkOfTrust`s
        name (str): the name of the task (e.g., signing.decision)
        task_id (str): the taskId of the task
    """
    def __init__(self, context, name, task_id=None):
        self.name = name
        self.context = context
        self.task_id = task_id or get_task_id(context.claim_task)
        self.task = context.task
        self.decision_task_id = get_decision_task_id(self.task)
        self.links = []

    def dependent_task_ids(self):
        """Helper method to get all `task_id`s for all `LinkOfTrust` tasks.

        Returns:
            list: the list of `task_id`s
        """
        return [x.task_id for x in self.links]

    def all_tasks(self):
        """The list of task definitions for all `self.links` + `self`

        Returns:
            list of dicts: the task definitions for all links + self
        """
        return [self.task] + [x.task for x in self.links]

    def is_try(self):
        """Helper method to determine if any task in the chain is a try task.

        Returns:
            bool: True if a task is a try task.
        """
        result = is_try(self.task)
        for link in self.links:
            if link.is_try:
                result = True
                break
        return result

    def get_link(self, task_id):
        """Get a `LinkOfTrust` by task id.

        Args:
            task_id (str): the task id to find.

        Returns:
            LinkOfTrust: the link matching the task id.

        Raises:
            CoTError: if no `LinkOfTrust` matches.
        """
        links = [x for x in self.links if x.task_id == task_id]
        if len(links) != 1:
            raise CoTError("No single Link matches task_id {}!\n{}".format(task_id, self.dependent_task_ids()))
        return links[0]


# LinkOfTrust {{{1
class LinkOfTrust(object):
    """Each LinkOfTrust represents a task in the Chain of Trust and its status.

    Attributes:
        chain (ChainOfTrust): the ChainOfTrust object.
        context (scriptworker.context.Context): the scriptworker context
        cot_dir (str): the local path containing this link's artifacts
        decision_task_id (str): the task_id of self.task's decision task
        is_try (bool): whether the task is a try task
        name (str): the name of the task (e.g., signing.decision)
        task_id (str): the taskId of the task
        worker_impl (str): the taskcluster worker class (e.g., docker-worker) of the task
    """
    _task = None
    _cot = None
    status = None

    def __init__(self, context, name, task_id):
        self.name = name
        self.context = context
        self.task_id = task_id
        self.cot_dir = os.path.join(
            context.config['artifact_dir'], 'public', 'cot', self.task_id
        )

    def _set(self, prop_name, value):
        prev = getattr(self, prop_name)
        if prev is not None:
            raise CoTError(
                "LinkOfTrust {}: re-setting {} to {} when it is already set to {}!".format(
                    str(self.name), prop_name, value, prev
                )
            )
        return setattr(self, prop_name, value)

    @property
    def task(self):
        """frozendict: the task definition.

        When set, the task dict is converted to a frozendict, and we also set
        `self.decision_task_id`, `self.worker_impl`, and `self.is_try` based
        on the task definition.
        """
        return self._task

    @task.setter
    def task(self, task):
        self._set('_task', task)
        self.decision_task_id = get_decision_task_id(self.task)
        self.worker_impl = guess_worker_impl(self)
        self.is_try = is_try(self.task)

    @property
    def cot(self):
        """frozendict: the chain of trust json body.

        When set, the chain of trust dict is converted to a frozendict.
        """
        return self._cot

    @cot.setter
    def cot(self, cot):
        self._set('_cot', cot)


# raise_on_errors {{{1
def raise_on_errors(errors):
    """Raise a CoTError if errors.

    Helper function because I had this code block everywhere.

    Args:
        errors (list): the error errors

    Raises:
        CoTError: if errors is non-empty
    """
    if errors:
        log.critical("\n".join(errors))
        raise CoTError("\n".join(errors))


# audit_log_handler {{{1
@contextmanager
def audit_log_handler(context):
    """Add an audit.log for `scriptworker.cot.verify` with a contextmanager for cleanup.

    Args:
        context (scriptworker.context.Context): the scriptworker context

    Yields:
        None: but cleans up the handler afterwards.
    """
    parent_path = os.path.join(context.config['artifact_dir'], 'public', 'cot')
    makedirs(parent_path)
    log_path = os.path.join(parent_path, 'audit.log')
    audit_handler = logging.FileHandler(log_path, encoding='utf-8')
    audit_handler.setLevel(logging.DEBUG)
    audit_handler.setFormatter(
        logging.Formatter(fmt='%(asctime)s %(levelname)8s - %(message)s')
    )
    log.addHandler(audit_handler)
    yield
    log.removeHandler(audit_handler)


# guess_worker_impl {{{1
def guess_worker_impl(link):
    """Given a task, determine which worker implementation (e.g., docker-worker) it was run on.

    Currently there are no task markers for generic-worker and
    taskcluster-worker hasn't been rolled out.  Those need to be populated here
    once they're ready.

    * docker-worker: `task.payload.image` is not None
    * check for scopes beginning with the worker type name.

    Args:
        link (LinkOfTrust or ChainOfTrust): the link to check.

    Returns:
        str: the worker type.

    Raises:
        CoTError: on inability to determine the worker implementation
    """
    worker_impls = []
    task = link.task
    name = link.name
    errors = []

    if task['payload'].get("image"):
        worker_impls.append("docker-worker")
    if task['provisionerId'] in link.context.config['scriptworker_provisioners']:
        worker_impls.append("scriptworker")
    if task['workerType'] in link.context.config['scriptworker_worker_types']:
        worker_impls.append("scriptworker")

    for scope in task['scopes']:
        if scope.startswith("docker-worker:"):
            worker_impls.append("docker-worker")

    if not worker_impls:
        errors.append("guess_worker_impl: can't find a worker_impl for {}!\n{}".format(name, task))
    if len(set(worker_impls)) > 1:
        errors.append("guess_worker_impl: too many matches for {}: {}!\n{}".format(name, set(worker_impls), task))
    raise_on_errors(errors)
    return worker_impls[0]


def guess_task_type(name):
    """Guess the task type of the task.

    Args:
        name (str): the name of the task.

    Returns:
        str: the task_type.

    Raises:
        CoTError: on invalid task_type.
    """
    parts = name.split(':')
    task_type = parts[-1]
    if task_type.startswith('build'):
        task_type = 'build'
    if task_type not in get_valid_task_types():
        raise CoTError(
            "Invalid task type for {}!".format(name)
        )
    return task_type


# get_valid_task_types {{{1
def get_valid_task_types():
    """Get the valid task types, e.g. signing.

    No longer a constant, due to code ordering issues.

    Returns:
        frozendict: maps the valid task types (e.g., signing) to their validation functions.
    """
    # TODO support the rest of the task types... balrog, apkpush, beetmover, hgpush, etc.
    return frozendict({
        'build': verify_build_task,
        'decision': verify_decision_task,
        'docker-image': verify_docker_image_task,
        'signing': verify_signing_task,
    })


# is_try {{{1
def _is_try_url(url):
    parsed = urlparse(url)
    path = unquote(parsed.path).lstrip('/')
    parts = path.split('/')
    if parts[0] == "try":
        return True
    return False


def is_try(task):
    """Determine if a task is a 'try' task (restricted privs).

    XXX do we want this, or just do this behavior for any non-allowlisted repo?

    This checks for the following things::

        * `task.payload.env.GECKO_HEAD_REPOSITORY` == "https://hg.mozilla.org/try/"
        * `task.payload.env.MH_BRANCH` == "try"
        * `task.metadata.source` == "https://hg.mozilla.org/try/..."
        * `task.schedulerId` in ("gecko-level-1", )

    Args:
        task (dict): the task definition to check

    Returns:
        bool: True if it's try
    """
    result = False
    if task['payload']['env'].get("GECKO_HEAD_REPOSITORY"):
        result = result or _is_try_url(task['payload']['env']['GECKO_HEAD_REPOSITORY'])
    if task['payload']['env'].get("MH_BRANCH"):
        result = result or task['payload']['env']['MH_BRANCH'] == 'try'
    if task['metadata'].get('source'):
        result = result or _is_try_url(task['metadata']['source'])
    result = result or task['schedulerId'] in ("gecko-level-1", )
    return result


# check_interactive_docker_worker {{{1
def check_interactive_docker_worker(task, name):
    """Given a task, make sure the task was not defined as interactive.

    * `task.payload.features.interactive` must be absent or False.
    * `task.payload.env.TASKCLUSTER_INTERACTIVE` must be absent or False.

    Args:
        task (dict): the task definition to check.
        name (str): the name of the task, used for error message strings.

    Returns:
        list: the list of error errors.  Success is an empty list.
    """
    errors = []
    try:
        if task['payload']['features'].get('interactive'):
            errors.append("{} is interactive: task.payload.features.interactive!".format(name))
        if task['payload']['env'].get('TASKCLUSTER_INTERACTIVE'):
            errors.append("{} is interactive: task.payload.env.TASKCLUSTER_INTERACTIVE!".format(name))
    except KeyError:
        errors.append("check_interactive_docker_worker: {} task definition is malformed!".format(name))
    return errors


# check_docker_image_sha {{{1
def check_docker_image_sha(context, cot, name):
    """Verify that pre-built docker shas are in allowlists.

    Decision and docker-image tasks use pre-built docker images from docker hub.
    Verify that these pre-built docker image shas are in the allowlists.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        cot (dict): the chain of trust json dict.
        name (str): the name of the task.  This must be in
            `context.config['docker_image_allowlists']`.

    Raises:
        CoTError: on failure.
        KeyError: on malformed config / cot
    """
    # XXX we will need some way to allow trusted developers to update these
    # allowlists
    if cot['environment']['imageHash'] not in context.config['docker_image_allowlists'][name]:
        raise CoTError("{} docker imageHash {} not in the allowlist!\n{}".format(name, cot['environment']['imageHash'], cot))


# find_task_dependencies {{{1
def find_task_dependencies(task, name, task_id):
    """Find the taskIds of the chain of trust dependencies of a given task.

    Args:
        task (dict): the task definition to inspect.
        name (str): the name of the task, for logging and naming children.
        task_id (str): the taskId of the task.

    Returns:
        dict: mapping dependent task `name` to dependent task `taskId`.
    """
    log.info("find_task_dependencies {}".format(name))
    decision_task_id = get_decision_task_id(task)
    decision_key = '{}:decision'.format(name)
    dep_dict = {}
    for key, val in task['extra'].get('chainOfTrust', {}).get('inputs', {}).items():
        dep_dict['{}:{}'.format(name, key)] = val
    # XXX start hack: remove once all signing tasks have task.extra.chainOfTrust.inputs
    if 'unsignedArtifacts' in task['payload']:
        build_ids = []
        for url in task['payload']['unsignedArtifacts']:
            parts = urlparse(url)
            path = unquote(parts.path)
            m = re.search(DEFAULT_CONFIG['valid_artifact_rules'][0]['path_regexes'][0], path)
            path_info = m.groupdict()
            if path_info['taskId'] not in build_ids:
                build_ids.append(path_info['taskId'])
        if len(build_ids) > 1:
            for count, build_id in enumerate(build_ids):
                dep_dict['{}:build{}'.format(name, count)] = build_id
        else:
            dep_dict['{}:build'.format(name)] = build_ids[0]
    # XXX end hack
    if decision_task_id != task_id:
        dep_dict[decision_key] = decision_task_id
    log.info(dep_dict)
    return dep_dict


# build_task_dependencies {{{1
async def build_task_dependencies(chain, task, name, my_task_id):
    """Recursively build the task dependencies of a task.

    Args:
        chain (ChainOfTrust): the chain of trust to add to.
        task (dict): the task definition to operate on.
        name (str): the name of the task to operate on.
        my_task_id (str): the taskId of the task to operate on.

    Raises:
        KeyError: on failure.
    """
    log.info("build_task_dependencies {}".format(name))
    if name.count(':') > 5:
        raise CoTError("Too deep recursion!\n{}".format(name))
    deps = find_task_dependencies(task, name, my_task_id)
    task_names = sorted(deps.keys())
    # make sure we deal with the decision task first, or we may populate
    # signing:build0:decision before signing:decision
    decision_key = "{}:decision".format(name)
    if decision_key in task_names:
        task_names = [decision_key] + sorted([x for x in task_names if x != decision_key])
    for task_name in task_names:
        task_id = deps[task_name]
        if task_id not in chain.dependent_task_ids():
            link = LinkOfTrust(chain.context, task_name, task_id)
            try:
                task_defn = await chain.context.queue.task(task_id)
                # TODO write task to cot_dir?
                link.task = task_defn
                link.chain = chain
                chain.links.append(link)
                await build_task_dependencies(chain, task_defn, task_name, task_id)
            except TaskclusterFailure as exc:
                raise CoTError(str(exc))


# get_artifact_url {{{1
def get_artifact_url(context, task_id, path):
    """Get a TaskCluster artifact url.

    Args:
        context (scriptworker.context.Context): the scriptworker context
        task_id (str): the task id of the task that published the artifact
        path (str): the relative path of the artifact

    Returns:
        str: the artifact url

    Raises:
        TaskClusterFailure: on failure.
    """
    url = urljoin(
        context.queue.options['baseUrl'],
        'v1/' +
        unquote(context.queue.makeRoute('getLatestArtifact', replDict={
            'taskId': task_id,
            'name': path
        }))
    )
    return url


# download_cot {{{1
async def download_cot(chain):
    """Download the signed chain of trust artifacts.

    Args:
        chain (ChainOfTrust): the chain of trust to add to.

    Raises:
        DownloadError: on failure.
    """
    async_tasks = []
    # only deal with chain.links, which are previously finished tasks with
    # signed chain of trust artifacts.  `chain.task` is the current running
    # task, and will not have a signed chain of trust artifact yet.
    for link in chain.links:
        task_id = link.task_id
        url = get_artifact_url(chain.context, task_id, 'public/chainOfTrust.json.asc')
        parent_dir = link.cot_dir
        try:
            # XXX await download_artifacts(
            async_tasks.append(
                asyncio.ensure_future(
                    download_artifacts(
                        chain.context, [url], parent_dir=parent_dir,
                        valid_artifact_task_ids=[task_id]
                    )
                )
            )
            await raise_future_exceptions(async_tasks)
        except Exception:
            log.exception("boo")

# download_cot_artifacts {{{1
async def download_cot_artifacts(chain, task_id, paths):
    """Download artifacts and verify their SHAs against the chain of trust.

    Args:
        chain (ChainOfTrust): the chain of trust object
        task_id (str): the task ID to download from
        paths (list): the list of artifacts to download

    Returns:
        list: the full paths of the artifacts

    Raises:
        CoTError: on failure.
    """
    full_paths = []
    urls = []
    link = chain.get_link(task_id)
    for path in paths:
        log.debug("Verifying {} is in {} cot artifacts...".format(path, task_id))
        if path not in link.cot['artifacts']:
            raise CoTError("path {} not in {} chain of trust artifacts!".format(path, link.name))
        url = get_artifact_url(chain.context, task_id, path)
        urls.append(url)
    log.info("Downloading Chain of Trust artifacts:\n" + "\n".join(urls))
    await download_artifacts(
        chain.context, urls, parent_dir=link.cot_dir, valid_artifact_task_ids=[task_id]
    )
    for path in paths:
        full_path = os.path.join(link.cot_dir, path)
        full_paths.append(full_path)
        for alg, expected_sha in link.cot['artifacts'][path].items():
            if alg not in chain.context.config['valid_hash_algorithms']:
                raise CoTError("BAD HASH ALGORITHM: {}: {} {}!".format(link.name, alg, full_path))
            real_sha = get_hash(full_path, hash_alg=alg)
            if expected_sha != real_sha:
                raise CoTError("BAD HASH: {}: Expected {} {}; got {}!".format(link.name, alg, expected_sha, real_sha))
    return full_paths


# verify_cot_signatures {{{1
def verify_cot_signatures(chain):
    """Verify the signatures of the chain of trust artifacts populated in `download_cot`.

    Populate each link.cot with the chain of trust json body.

    Args:
        chain (ChainOfTrust): the chain of trust to add to.

    Raises:
        CoTError: on failure.
    """
    for link in chain.links:
        if link.task_id == chain.task_id:
            continue
        path = os.path.join(link.cot_dir, 'public/chainOfTrust.json.asc')
        gpg = GPG(
            chain.context,
            gpg_home=os.path.join(
                chain.context.config['base_gpg_home_dir'], link.worker_impl
            )
        )
        try:
            with open(path, "r") as fh:
                contents = fh.read()
        except OSError as exc:
            raise CoTError("Can't read {}: {}!".format(path, str(exc)))
        try:
            # TODO remove verify_sig pref and kwarg when git repo pubkey
            # verification works reliably!
            body = get_body(
                gpg, contents,
                verify_sig=chain.context.config['verify_cot_signature']
            )
        except ScriptWorkerGPGException as exc:
            raise CoTError("GPG Error verifying chain of trust for {}: {}!".format(path, str(exc)))
        link.cot = json.loads(body)


# verify_link_in_task_graph {{{1
def verify_link_in_task_graph(chain, decision_link, task_link):
    """Compare the runtime task definition against the decision task graph.

    Args:
        chain (ChainOfTrust): the chain we're operating on.
        decision_link (LinkOfTrust):

    Raises:
        CoTError: on failure.
    """
    log.info("Verifying the {} {} task definition is part of the {} {} task graph...".format(
        task_link.name, task_link.task_id, decision_link.name, decision_link.task_id
    ))
    ignore_keys = ("created", "deadline", "expires", "dependencies", "schedulerId")
    errors = []
    runtime_defn = deepcopy(task_link.task)
    graph_defn = deepcopy(decision_link.task_graph[task_link.task_id])
    # dependencies
    bad_deps = set(graph_defn['task']['dependencies']).symmetric_difference(set(runtime_defn['dependencies']))
    if bad_deps and runtime_defn['dependencies'] != [task_link.decision_task_id]:
        errors.append("{} {} dependencies don't line up!\n{}".format(
            task_link.name, task_link.task_id, bad_deps
        ))
    # payload - eliminate the 'expires' key from artifacts because the datestring
    # will change
    for payload in (runtime_defn['payload'], graph_defn['task']['payload']):
        for key, value in payload.get('artifacts', {}).items():
            if isinstance(value, dict) and 'expires' in value:
                del(value['expires'])
    # test all non-ignored key/value pairs in the task defn
    for key, value in graph_defn['task'].items():
        if key in ignore_keys:
            continue
        if value != runtime_defn[key]:
            errors.append("{} {} {} differs!\n graph: {}\n task: {}".format(
                task_link.name, task_link.task_id, key,
                pprint.pformat(value), pprint.pformat(runtime_defn[key])
            ))
    raise_on_errors(errors)


# verify_decision_task {{{1
async def verify_decision_task(chain, link):
    """Verify decision tasks in the chain.

    TODO check the command
    "/home/worker/bin/run-task",
    "--vcs-checkout=/home/worker/checkouts/gecko",
    "--",
    "bash",
    "-cx",
    "cd /home/worker/checkouts/gecko &&
    ln -s /home/worker/artifacts artifacts &&
    ./mach --log-no-times taskgraph decision --pushlog-id='83445' --pushdate='1478146854'
    --project='mozilla-inbound' --message=' ' --owner='cpeterson@mozilla.com' --level='3'
    --base-repository='https://hg.mozilla.org/mozilla-central'
    --head-repository='https://hg.mozilla.org/integration/mozilla-inbound/'
    --head-ref='e7023fe48f7c48e33ef3b91747647f0873e306d6'
    --head-rev='e7023fe48f7c48e33ef3b91747647f0873e306d6'
    --revision-hash='e3e8f6327079496707658adc381c142c6575b280'\n"

    "/home/worker/bin/run-task",
    "--vcs-checkout=/home/worker/checkouts/gecko",
    "--",
    "bash",
    "-cx",
    "cd /home/worker/checkouts/gecko &&
    ln -s /home/worker/artifacts artifacts &&
    ./mach --log-no-times taskgraph decision --pushlog-id='0' --pushdate='0' --project='date'
    --message='try: -b o -p foo -u none -t none' --owner='amiyaguchi@mozilla.com' --level='2'
    --base-repository=$GECKO_BASE_REPOSITORY --head-repository=$GECKO_HEAD_REPOSITORY
    --head-ref=$GECKO_HEAD_REF --head-rev=$GECKO_HEAD_REV --revision-hash=$GECKO_HEAD_REV
    --triggered-by='nightly' --target-tasks-method='nightly_linux'\n"


    Args:
        chain (ChainOfTrust): the chain we're operating on.
        link (LinkOfTrust): the task link we're checking.

    Raises:
        CoTError: on chain of trust verification error.
    """
    errors = []
    worker_type = get_worker_type(link.task)
    if worker_type not in chain.context.config['valid_decision_worker_types']:
        errors.append("{} is not a valid decision workerType!".format(worker_type))
    # make sure all tasks generated from this decision task match the published task-graph.json
    paths = await download_cot_artifacts(chain, link.task_id, ["public/task-graph.json"])
    with open(paths[0], "r") as fh:
        link.task_graph = json.load(fh)
    for target_link in [chain] + chain.links:
        if target_link.decision_task_id == link.task_id and target_link.task_id != link.task_id:
            verify_link_in_task_graph(chain, link, target_link)
    # limit what can be in payload.env
    for key in link.task['payload'].get('env', {}).keys():
        if key not in link.context.config['valid_decision_env_vars']:
            errors.append("{} {} illegal env var {}!".format(link.name, link.task_id, key))
    # TODO limit what can be in payload.command -- this is going to be tricky
    raise_on_errors(errors)


# verify_build_task {{{1
async def verify_build_task(chain, link):
    """Verify the build task definition.

    The main points of concern are tested elsewhere:
    The task is the same as the task graph task; the command;
    the docker-image for docker-worker builds; the revision and repo.

    TODO command
    "/home/worker/bin/run-task",
    "--chown-recursive",
    "/home/worker/workspace",
    "--chown-recursive",
    "/home/worker/tooltool-cache",
    "--vcs-checkout",
    "/home/worker/workspace/build/src",
    "--tools-checkout",
    "/home/worker/workspace/build/tools",
    "--",
    "/home/worker/workspace/build/src/taskcluster/scripts/builder/build-linux.sh"

    Args:
        chain (ChainOfTrust): the chain we're operating on.
        link (LinkOfTrust): the task link we're checking.
    """
    errors = []
    if link.worker_impl == 'docker-worker':
        for key in link.task['payload'].get('env', {}).keys():
            if key not in link.context.config['valid_docker_worker_build_env_vars']:
                errors.append("{} {} illegal env var {}!".format(link.name, link.task_id, key))
    raise_on_errors(errors)


# TODO verify_docker_image_task {{{1
async def verify_docker_image_task(chain, obj):
    """
    """
    # TODO
    pass


# verify_signing_task {{{1
async def verify_signing_task(chain, obj):
    """Verify the signing task definition.

    Currently the only check is to make sure it was run on a scriptworker.

    Args:
        chain (ChainOfTrust): the chain we're operating on
        obj (ChainOfTrust or LinkOfTrust): the trust object for the signing task.
    """
    errors = []
    if guess_worker_impl(obj) != "scriptworker":
        errors.append("{} {} must be run from scriptworker!".format(obj.name, obj.task_id))
    raise_on_errors(errors)


def check_num_tasks(chain, task_count):
    """
    """
    errors = []
    # hardcode for now.  If we need a different set of constraints, either
    # go by cot_product settings or by task_count['docker-image'] + 1
    min_decision_tasks = 1
    max_decision_tasks = 2
    if task_count['decision'] < min_decision_tasks:
        errors.append("{} decision tasks; we must have at least {}!".format(
            task_count['decision'], min_decision_tasks
        ))
    elif task_count['decision'] > max_decision_tasks:
        errors.append("{} decision tasks; we must have at most {}!".format(
            task_count['decision'], max_decision_tasks
        ))
    raise_on_errors(errors)


# verify_task_types {{{1
async def verify_task_types(chain):
    """
    """
    valid_task_types = get_valid_task_types()
    task_count = {}
    for obj in [chain] + chain.links:
        task_type = guess_task_type(obj.name)
        log.info("Verifying {} {} as a {} task...".format(obj.name, obj.task_id, task_type))
        task_count.setdefault(task_type, 0)
        task_count[task_type] += 1
        # Run tests synchronously for now.  We can parallelize if efficiency
        # is more important than a single simple logfile.
        await valid_task_types[task_type](chain, obj)
    return task_count


# build_chain_of_trust {{{1
async def verify_chain_of_trust(chain):
    """Build and verify the chain of trust.
    """
    with audit_log_handler(chain.context):
        try:
            # build LinkOfTrust objects
            await build_task_dependencies(chain, chain.task, chain.name, chain.task_id)
            # download the signed chain of trust artifacts
            await download_cot(chain)
            # verify the signatures and populate the `link.cot`s
            verify_cot_signatures(chain)
            task_count = await verify_task_types(chain)
            check_num_tasks(chain, task_count)
            # TODO verify worker types
            # verify_worker_types(chain)
            # TODO verify command for docker_worker
            # TODO add tests for docker image -- either in sha whitelist or trace to
            #   docker image task in chain
            # TODO trace back to tree
            # - allowlisted repo/branch/revision
        except CoTError:
            log.critical("Chain of Trust verification error!", exc_info=True)
            raise
        log.info("Good.")
