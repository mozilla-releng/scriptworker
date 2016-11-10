#!/usr/bin/env python
"""Chain of Trust artifact verification.

Attributes:
    log (logging.Logger): the log object for this module.
"""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from frozendict import frozendict
import logging
import os
import pprint
import re
import shlex
from urllib.parse import unquote, urlparse
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.exceptions import CoTError, DownloadError, ScriptWorkerGPGException
from scriptworker.gpg import get_body, GPG
from scriptworker.task import download_artifacts, get_artifact_url, get_decision_task_id, get_worker_type, get_task_id
from scriptworker.utils import format_json, get_hash, load_json, makedirs, match_url_regex, raise_future_exceptions
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
        task_type (str): the task type of the task (e.g., decision, build)
        worker_impl (str): the taskcluster worker class (e.g., docker-worker) of the task
    """
    def __init__(self, context, name, task_id=None):
        self.name = name
        self.task_type = guess_task_type(name)
        self.context = context
        self.task_id = task_id or get_task_id(context.claim_task)
        self.task = context.task
        self.worker_impl = guess_worker_impl(self)  # this should be scriptworker
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
        task_type (str): the task type of the task (e.g., decision, build)
        worker_impl (str): the taskcluster worker class (e.g., docker-worker) of the task
    """
    _task = None
    _cot = None
    status = None

    def __init__(self, context, name, task_id):
        self.name = name
        self.task_type = guess_task_type(name)
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


# get_valid_worker_impls {{{1
def get_valid_worker_impls():
    """Get the valid worker_impls, e.g. docker-worker.

    No longer a constant, due to code ordering issues.

    Returns:
        frozendict: maps the valid worker_impls (e.g., docker-worker) to their
            validation functions.
    """
    # TODO support the rest of the worker impls... generic worker, taskcluster worker
    return frozendict({
        'docker-worker': verify_docker_worker_task,
        'scriptworker': verify_scriptworker_task,
    })


# guess_task_type {{{1
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

    This goes further than get_firefox_source_url.  We may or may not want
    to keep this.

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
    env = task['payload'].get('env', {})
    if env.get("GECKO_HEAD_REPOSITORY"):
        result = result or _is_try_url(task['payload']['env']['GECKO_HEAD_REPOSITORY'])
    if env.get("MH_BRANCH"):
        result = result or task['payload']['env']['MH_BRANCH'] == 'try'
    if task['metadata'].get('source'):
        result = result or _is_try_url(task['metadata']['source'])
    result = result or task['schedulerId'] in ("gecko-level-1", )
    return result


# check_interactive_docker_worker {{{1
def check_interactive_docker_worker(link):
    """Given a task, make sure the task was not defined as interactive.

    * `task.payload.features.interactive` must be absent or False.
    * `task.payload.env.TASKCLUSTER_INTERACTIVE` must be absent or False.

    Args:
        link (LinkOfTrust): the task link we're checking.

    Returns:
        list: the list of error errors.  Success is an empty list.
    """
    errors = []
    try:
        if link.task['payload']['features'].get('interactive'):
            errors.append("{} is interactive: task.payload.features.interactive!".format(link.name))
        if link.task['payload']['env'].get('TASKCLUSTER_INTERACTIVE'):
            errors.append("{} is interactive: task.payload.env.TASKCLUSTER_INTERACTIVE!".format(link.name))
    except CoTError:
        errors.append("check_interactive_docker_worker: {} task definition is malformed!".format(link.name))
    return errors


# verify_docker_image_sha {{{1
def verify_docker_image_sha(chain, link):
    """Verify that pre-built docker shas are in allowlists.

    Decision and docker-image tasks use pre-built docker images from docker hub.
    Verify that these pre-built docker image shas are in the allowlists.

    Args:
        chain (ChainOfTrust): the chain we're operating on.
        link (LinkOfTrust): the task link we're checking.

    Raises:
        CoTError: on failure.
    """
    cot = link.cot
    task = link.task
    errors = []
    image_hash = cot['environment']['imageHash']
    if isinstance(task['payload'].get('image'), dict):
        # Using pre-built image from docker-image task
        docker_image_task_id = task['extra']['chainOfTrust']['inputs']['docker-image']
        if docker_image_task_id != task['payload']['image']['taskId']:
            errors.append("{} {} docker-image taskId isn't consistent!: {} vs {}".format(
                link.name, link.task_id, docker_image_task_id,
                task['payload']['image']['taskId']
            ))
        else:
            path = task['payload']['image']['path']
            # we need change the hash alg everywhere if we change, and recreate
            # the docker images...
            alg, sha = image_hash.split(':')
            docker_image_link = chain.get_link(docker_image_task_id)
            upstream_sha = docker_image_link.cot['artifacts'][path].get(alg)
            if upstream_sha is None:
                errors.append("{} {} docker-image docker sha {} is missing! {}".format(
                    link.name, link.task_id, alg,
                    docker_image_link.cot['artifacts'][path]
                ))
            elif upstream_sha != sha:
                # TODO make this an error once we fix bug 1315415
                message = "{} {} docker-image docker sha doesn't match! {} {} vs {}".format(
                    link.name, link.task_id, alg, sha, upstream_sha
                )
                log.warning("Known issue:\n{}".format(message))
                # errors.append(message)
    else:
        # Using downloaded image from docker hub
        task_type = link.task_type
        # XXX we will need some way to allow trusted developers to update these
        # allowlists
        if image_hash not in link.context.config['docker_image_allowlists'][task_type]:
            errors.append("{} {} docker imageHash {} not in the allowlist!\n{}".format(
                link.name, link.task_id, image_hash, cot
            ))
    raise_on_errors(errors)


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
        CoTError: on failure.
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
            json_path = os.path.join(link.cot_dir, 'task.json')
            try:
                task_defn = await chain.context.queue.task(task_id)
                link.task = task_defn
                link.chain = chain
                chain.links.append(link)
                # write task json to disk
                makedirs(os.path.dirname(json_path))
                with open(json_path, 'w') as fh:
                    fh.write(format_json(task_defn))
                await build_task_dependencies(chain, task_defn, task_name, task_id)
            except TaskclusterFailure as exc:
                raise CoTError(str(exc))


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
        async_tasks.append(
            asyncio.ensure_future(
                download_artifacts(
                    chain.context, [url], parent_dir=parent_dir,
                    valid_artifact_task_ids=[task_id]
                )
            )
        )
        await raise_future_exceptions(async_tasks)


# download_cot_artifact {{{1
async def download_cot_artifact(chain, task_id, path):
    """Download an artifact and verify its SHA against the chain of trust.

    Args:
        chain (ChainOfTrust): the chain of trust object
        task_id (str): the task ID to download from
        path (str): the relative path to the artifact to download

    Returns:
        str: the full path of the downloaded artifact

    Raises:
        CoTError: on failure.
    """
    link = chain.get_link(task_id)
    log.debug("Verifying {} is in {} cot artifacts...".format(path, task_id))
    if path not in link.cot['artifacts']:
        raise CoTError("path {} not in {} {} chain of trust artifacts!".format(path, link.name, link.task_id))
    url = get_artifact_url(chain.context, task_id, path)
    log.info("Downloading Chain of Trust artifact:\n{}".format(url))
    await download_artifacts(
        chain.context, [url], parent_dir=link.cot_dir, valid_artifact_task_ids=[task_id]
    )
    full_path = os.path.join(link.cot_dir, path)
    for alg, expected_sha in link.cot['artifacts'][path].items():
        if alg not in chain.context.config['valid_hash_algorithms']:
            raise CoTError("BAD HASH ALGORITHM: {}: {} {}!".format(link.name, alg, full_path))
        real_sha = get_hash(full_path, hash_alg=alg)
        if expected_sha != real_sha:
            raise CoTError("BAD HASH: {}: Expected {} {}; got {}!".format(link.name, alg, expected_sha, real_sha))
    return full_path


# download_cot_artifacts {{{1
async def download_cot_artifacts(chain, artifact_dict):
    """Call `download_cot_artifact` in parallel for each key/value in `artifact_dict`

    Args:
        chain (ChainOfTrust): the chain of trust object
        artifact_dict (dict): maps task_id to list of paths of artifacts to download

    Returns:
        list: list of full paths to artifacts

    Raises:
        CoTError: on chain of trust sha validation error
        DownloadError: on download error
    """
    tasks = []
    for task_id, paths in artifact_dict.items():
        for path in paths:
            tasks.append(
                asyncio.ensure_future(
                    download_cot_artifact(
                        chain, task_id, path
                    )
                )
            )
    full_paths = await raise_future_exceptions(tasks)
    return full_paths


# download_gecko_cot_artifacts {{{1
async def download_firefox_cot_artifacts(chain):
    """Download artifacts needed for firefox chain of trust verification.

    This is only task-graph.json so far.

    Args:
        chain (ChainOfTrust): the chain of trust object

    Returns:
        list: list of full paths to artifacts

    Raises:
        CoTError: on chain of trust sha validation error
        DownloadError: on download error
    """
    artifact_dict = {}
    for link in chain.links:
        task_type = link.task_type
        if task_type == 'decision':
            artifact_dict.setdefault(link.task_id, [])
            artifact_dict[link.task_id].append('public/task-graph.json')
    return await download_cot_artifacts(chain, artifact_dict)


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
        link.cot = load_json(
            body, exception=CoTError,
            message="{} {}: Invalid cot json body! %(exc)s".format(link.name, link.task_id)
        )
        unsigned_path = os.path.join(link.cot_dir, 'chainOfTrust.json')
        with open(unsigned_path, "w") as fh:
            fh.write(format_json(link.cot))


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


# verify_firefox_decision_command {{{1
def verify_firefox_decision_command(decision_link):
    """Verify the decision command for a firefox decision task.

    Some example commands::

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

    This is very firefox-centric and potentially fragile, but decision tasks are
    important enough to need to monitor.  The ideal fix would maybe be to simplify
    the commandline if possible.

    Args:
        decision_link (LinkOfTrust): the decision link to test.
    """
    log.info("Verifying {} {} command...".format(decision_link.name, decision_link.task_id))
    errors = []
    command = decision_link.task['payload']['command']
    allowed_args = ('--', 'bash', '-cx')
    if command[0] != '/home/worker/bin/run-task':
        errors.append("{} {} command must start with /home/worker/bin/run-task!".format(
            decision_link.name, decision_link.task_id
        ))
    for item in command[1:-1]:
        if item in allowed_args:
            continue
        if item.startswith('--vcs-checkout='):
            continue
        errors.append("{} {} illegal option {} in the command!".format(
            decision_link.name, decision_link.task_id
        ))
    bash_commands = command[-1].split('&&')
    allowed_commands = ('cd', 'ln')
    allowed_mach_args = ['./mach', 'taskgraph', 'decision']
    for bash_command in bash_commands:
        parts = shlex.split(bash_command)
        if parts[0] in allowed_commands:
            continue
        for part in parts:
            if part.startswith('--'):
                continue
            if not allowed_mach_args or part != allowed_mach_args.pop(0):
                errors.append("{} {} Illegal command `{}`".format(
                    decision_link.name, decision_link.task_id, bash_command
                ))
    raise_on_errors(errors)


# verify_decision_task {{{1
async def verify_decision_task(chain, link):
    """Verify the decision task Link.

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
    path = os.path.join(link.cot_dir, "public", "task-graph.json")
    if not os.path.exists(path):
        errors.append("{} {}: {} doesn't exist!".format(link.name, link.task_id, path))
        raise_on_errors(errors)
    link.task_graph = load_json(
        path, is_path=True, exception=CoTError, message="Can't load {}! %(exc)s".format(path)
    )
    for target_link in [chain] + chain.links:
        if target_link.decision_task_id == link.task_id and target_link.task_id != link.task_id:
            verify_link_in_task_graph(chain, link, target_link)
    # limit what can be in payload.env
    for key in link.task['payload'].get('env', {}).keys():
        if key not in link.context.config['valid_decision_env_vars']:
            errors.append("{} {} illegal env var {}!".format(link.name, link.task_id, key))
    verify_firefox_decision_command(link)
    raise_on_errors(errors)


# verify_build_task {{{1
async def verify_build_task(chain, link):
    """Verify the build Link.

    The main points of concern are tested elsewhere:
    The task is the same as the task graph task; the command;
    the docker-image for docker-worker builds; the revision and repo.

    TODO verify / limit what can go in command?
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


# verify_docker_image_task {{{1
async def verify_docker_image_task(chain, link):
    """Verify the docker image Link.

    Args:
        chain (ChainOfTrust): the chain we're operating on.
        link (LinkOfTrust): the task link we're checking.
    """
    errors = []
    # workerType
    worker_type = get_worker_type(link.task)
    if worker_type not in chain.context.config['valid_docker_image_worker_types']:
        errors.append("{} is not a valid docker-image workerType!".format(worker_type))
    # env
    for key in link.task['payload'].get('env', {}).keys():
        if key not in link.context.config['valid_docker_image_env_vars']:
            errors.append("{} {} illegal env var {}!".format(link.name, link.task_id, key))
    # command
    if link.task['payload']['command'] != ["/bin/bash", "-c", "/home/worker/bin/build_image.sh"]:
        errors.append("{} {} illegal command {}!".format(link.name, link.task_id, link.task['payload']['command']))
    raise_on_errors(errors)


# verify_signing_task {{{1
async def verify_signing_task(chain, obj):
    """Verify the signing trust object.

    Currently the only check is to make sure it was run on a scriptworker.

    Args:
        chain (ChainOfTrust): the chain we're operating on
        obj (ChainOfTrust or LinkOfTrust): the trust object for the signing task.
    """
    errors = []
    if obj.worker_impl != "scriptworker":
        errors.append("{} {} must be run from scriptworker!".format(obj.name, obj.task_id))
    raise_on_errors(errors)


def check_num_tasks(chain, task_count):
    """Make sure there are a specific number of specific task types.

    Currently we only check decision tasks.

    Args:
        chain (ChainOfTrust): the chain we're operating on
        task_count (dict): mapping task type to the number of links.

    Raises:
        CoTError: on failure.
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
    """Verify the task type (e.g. decision, build) of each link in the chain.

    Args:
        chain (ChainOfTrust): the chain we're operating on

    Returns:
        dict: mapping task type to the number of links.
    """
    valid_task_types = get_valid_task_types()
    task_count = {}
    # check the chain object (current task) as well
    for obj in [chain] + chain.links:
        task_type = obj.task_type
        log.info("Verifying {} {} as a {} task...".format(obj.name, obj.task_id, task_type))
        task_count.setdefault(task_type, 0)
        task_count[task_type] += 1
        # Run tests synchronously for now.  We can parallelize if efficiency
        # is more important than a single simple logfile.
        await valid_task_types[task_type](chain, obj)
    return task_count


# verify_docker_worker_task {{{1
async def verify_docker_worker_task(chain, link):
    """Docker-worker specific checks.

    Args:
        chain (ChainOfTrust): the chain we're operating on
        obj (ChainOfTrust or LinkOfTrust): the trust object for the signing task.

    Raises:
        CoTError: on failure.
    """
    check_interactive_docker_worker(link)
    verify_docker_image_sha(chain, link)


# verify_scriptworker_task {{{1
async def verify_scriptworker_task(chain, obj):
    """Verify the scriptworker object.

    Noop for now.

    Args:
        chain (ChainOfTrust): the chain we're operating on
        obj (ChainOfTrust or LinkOfTrust): the trust object for the signing task.
    """
    pass


# verify_worker_impls {{{1
async def verify_worker_impls(chain):
    """Verify the task type (e.g. decision, build) of each link in the chain.

    Args:
        chain (ChainOfTrust): the chain we're operating on

    Raises:
        CoTError: on failure
    """
    valid_worker_impls = get_valid_worker_impls()
    for obj in [chain] + chain.links:
        worker_impl = obj.worker_impl
        log.info("Verifying {} {} as a {} task...".format(obj.name, obj.task_id, worker_impl))
        # Run tests synchronously for now.  We can parallelize if efficiency
        # is more important than a single simple logfile.
        await valid_worker_impls[worker_impl](chain, obj)
        if isinstance(obj, ChainOfTrust) and obj.worker_impl != "scriptworker":
            raise CoTError("ChainOfTrust object is not a scriptworker impl!")


# get_firefox_source_url {{{1
def get_firefox_source_url(obj):
    """Get the firefox source url for a Trust object.

    Args:
        obj (ChainOfTrust or LinkOfTrust): the trust object to inspect

    Returns:
        str: the source url.

    Raises:
        CoTError: if repo and source are defined and don't match
    """
    task = obj.task
    log.debug("Getting firefox source url for {} {}...".format(obj.name, obj.task_id))
    repo = task['payload'].get('env', {}).get('GECKO_HEAD_REPOSITORY')
    source = task['metadata']['source']
    # We hit this for hooks.
    if repo and not source.startswith(repo):
        log.info("{} {}: GECKO_HEAD_REPOSITORY {} doesn't match source {}... returning {}".format(
            obj.name, obj.task_id, repo, source, repo
        ))
        return repo
    return source


# trace_back_to_firefox_tree {{{1
async def trace_back_to_firefox_tree(chain):
    """
    task.metadata.source: "https://hg.mozilla.org/projects/date//file/a80373508881bfbff67a2a49297c328ff8052572/taskcluster/ci/build"
    task.payload.env.GECKO_HEAD_REPOSITORY "https://hg.mozilla.org/projects/date/"
    """
    errors = []
    repos = {}
    restricted_privs = None
    scope_rules = chain.context.config['cot_restricted_scopes'][chain.name]

    def callback(match):
        path_info = match.groupdict()
        if 'path' in path_info:
            return path_info['path']

    # a repo_path of None means we have no restricted privs.
    # a string repo_path may mean we have higher privs
    for obj in [chain] + chain.links:
        source_url = get_firefox_source_url(obj)
        repo_path = match_url_regex(chain.context.config['valid_vcs_rules'], source_url, callback)
        repos[obj] = repo_path
    # check for restricted scopes.
    my_repo = repos[chain]
    for scope in chain.task['scopes']:
        if scope in scope_rules:
            log.info("Found privileged scope {}".format(scope))
            restricted_privs = True
            if my_repo not in scope_rules[scope]:
                errors.append("{} {}: repo {} not allowlisted for scope {}!".format(
                    chain.name, chain.task_id, my_repo, scope
                ))
    # verify all tasks w/ same decision_task_id have the same source repo.
    if len(set(repos.values())) > 1:
        for obj, repo in repos.items():
            if obj.decision_task_id == chain.decision_task_id:
                if repo != my_repo:
                    errors.append("{} {} repo {} doesn't match my repo {}!".format(
                        obj.name, obj.task_id, repo, my_repo
                    ))
            # if we have restricted privs, the non-sibling tasks must at least be in
            # a known repo.
            # (Not currently requiring that all tasks have the same privilege level,
            #  in case a docker-image build is run on mozilla-central and that image
            #  is used for a release-priv task, for example.)
            elif restricted_privs and repo is None:
                errors.append("{} {} has no privileged repo on an restricted privilege scope!".format(
                    obj.name, obj.task_id
                ))
    # Disallow restricted privs on is_try.  This may be a redundant check.
    if restricted_privs and chain.is_try():
        errors.append("{} {} has restricted privilege scope, and is_try()!".format(chain.name, chain.task_id))
    raise_on_errors(errors)


# verify_chain_of_trust {{{1
async def verify_chain_of_trust(chain):
    """Build and verify the chain of trust.

    Args:
        chain (ChainOfTrust): the chain we're operating on

    Raises:
        CoTError: on failure
    """
    with audit_log_handler(chain.context):
        try:
            # build LinkOfTrust objects
            await build_task_dependencies(chain, chain.task, chain.name, chain.task_id)
            # download the signed chain of trust artifacts
            await download_cot(chain)
            # verify the signatures and populate the `link.cot`s
            verify_cot_signatures(chain)
            # download all other artifacts needed to verify chain of trust
            await download_firefox_cot_artifacts(chain)
            # verify the task types, e.g. decision
            task_count = await verify_task_types(chain)
            check_num_tasks(chain, task_count)
            # verify the worker_impls, e.g. docker-worker
            await verify_worker_impls(chain)
            await trace_back_to_firefox_tree(chain)
        except (DownloadError, KeyError, AttributeError) as exc:
            log.critical("Chain of Trust verification error!", exc_info=True)
            if isinstance(exc, CoTError):
                raise
            else:
                raise CoTError(str(exc))
        log.info("Good.")
