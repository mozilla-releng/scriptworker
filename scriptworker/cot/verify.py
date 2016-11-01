#!/usr/bin/env python
"""Chain of Trust artifact validation.

Attributes:
    log (logging.Logger): the log object for this module.
"""
from contextlib import contextmanager
from frozendict import frozendict
import logging
import os
import re
from urllib.parse import unquote, urljoin, urlparse
from scriptworker.config import freeze_values
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.exceptions import CoTError, ScriptWorkerGPGException
from scriptworker.gpg import get_body, GPG
from scriptworker.task import download_artifacts, get_decision_task_id, get_task_id
from scriptworker.utils import get_hash, makedirs, raise_future_exceptions
from taskcluster.exceptions import TaskclusterFailure

log = logging.getLogger(__name__)


# ChainOfTrust {{{1
class ChainOfTrust(object):
    """The master Chain of Trust, tracking all the various `LinkOfTrust`s.

    Attributes:
        name (str): the name of the current task, e.g. signing
        task_id (str): the taskcluster task id of the current task
        task (dict): the current task's task definition
        decision_task_id (str): the current task's decision task id
        context (scriptworker.context.Context): the scriptworker context
        links (list): the list of `LinkOfTrust`s
    """
    def __init__(self, context, name, task_id=None):
        self.name = name
        self.task_id = task_id or get_task_id(context.claim_task)
        self.task = context.task
        self.decision_task_id = get_decision_task_id(self.task)
        self.context = context
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
        task_type (str): the task type (e.g., build)
        worker_class (str): the taskcluster worker class (e.g., docker-worker) of the task
    """
    _task = None
    _cot = None
    decision_task_id = None
    task_type = None
    worker_class = None
    # status = None  # TODO automate status going to False or True?
    # messages = []
    # errors = []
    # tests_to_run = []
    # tests_completed = []

    def __init__(self, context, name, task_id):
        self.name = name
        self.context = context
        self.task_type = guess_task_type(self.name)
        self.task_id = task_id
        self.cot_dir = os.path.join(
            context.config['artifact_dir'], 'cot', self.task_id
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
        `self.decision_task_id`, `self.worker_class`, and `self.is_try` based
        on the task definition.
        """
        return self._task

    @task.setter
    def task(self, task):
        freeze_values(task)
        self._set('_task', frozendict(task))
        self.decision_task_id = get_decision_task_id(self.task)
        self.worker_class = guess_worker_class(self.task, self.name)
        self.is_try = is_try(self.task)
        # TODO add tests to run

    @property
    def cot(self):
        """frozendict: the chain of trust json body.

        When set, the chain of trust dict is converted to a frozendict.
        """
        return self._cot

    @cot.setter
    def cot(self, cot):
        freeze_values(cot)
        self._set('_cot', frozendict(cot))
        # TODO add tests to run


# audit_log_handler {{{1
@contextmanager
def audit_log_handler(context):
    """Add an audit.log for `scriptworker.cot.verify` with a contextmanager for cleanup.

    Args:
        context (scriptworker.context.Context): the scriptworker context

    Yields:
        None: but cleans up the handler afterwards.
    """
    parent_path = os.path.join(context.config['artifact_dir'], 'cot')
    makedirs(parent_path)
    log_path = os.path.join(parent_path, 'audit.log')
    audit_handler = logging.FileHandler(log_path)
    audit_handler.setLevel(logging.DEBUG)
    audit_handler.setFormatter(
        logging.Formatter('%(asctime)s %levelname)8s - %(message)s', '%H:%M:%s')
    )
    log.addHandler(audit_handler)
    yield
    log.removeHandler(audit_handler)


# guess_worker_class {{{1
def guess_worker_class(task, name):
    """Given a task, determine which worker class it was run on.

    Currently there are no task markers for generic-worker and
    taskcluster-worker hasn't been rolled out.  Those need to be populated here
    once they're ready.

    * docker-worker: `task.payload.image` is not None
    * check for scopes beginning with the worker type name.

    Args:
        task (dict): the task definition to check.
        name (str): the name of the task, used for error message strings.

    Returns:
        str: the worker type.

    Raises:
        CoTError: on inability to determine the worker type
    """
    worker_type = {'worker_type': None}

    def _set_worker_type(wt):
        if worker_type['worker_type'] is not None and worker_type['worker_type'] != wt:
            raise CoTError("guess_worker_class: {} was {} and now looks like {}!\n{}".format(name, worker_type['worker_type'], wt, task))
        worker_type['worker_type'] = wt

    if task['payload'].get("image"):
        _set_worker_type("docker-worker")
    if task['provisionerId'] in task.context.config['scriptworker_provisioners']:
        _set_worker_type("scriptworker")
    if task['workerType'] in task.context.config['scriptworker_worker_types']:
        _set_worker_type("scriptworker")

    for scope in task['scopes']:
        if scope.startswith("docker-worker:"):
            _set_worker_type("docker-worker")

    if worker_type['worker_type'] is None:
        raise CoTError("guess_worker_class: can't find a type for {}!\n{}".format(name, task))
    return worker_type['worker_type']


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
        'build': verify_build_tasks,
        'decision': verify_decision_tasks,
        'docker-image': verify_docker_image_tasks,
        'signing': verify_signing_tasks,
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
        list: the list of error messages.  Success is an empty list.
    """
    messages = []
    try:
        if task['payload']['features'].get('interactive'):
            messages.append("{} is interactive: task.payload.features.interactive!".format(name))
        if task['payload']['env'].get('TASKCLUSTER_INTERACTIVE'):
            messages.append("{} is interactive: task.payload.env.TASKCLUSTER_INTERACTIVE!".format(name))
    except KeyError:
        messages.append("check_interactive_docker_worker: {} task definition is malformed!".format(name))
    return messages


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
        for count, build_id in enumerate(build_ids):
            dep_dict['{}:build{}'.format(name, count)] = build_id
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
        context.queue.makeRoute('getLatestArtifact', replDict={
            'taskId': task_id,
            'name': 'public/chainOfTrust.json.asc'
        })
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
        async_tasks.append(
            download_artifacts(
                chain.context, [url], parent_dir=parent_dir,
                valid_artifact_task_ids=[task_id]
            )
        )
    # XXX catch DownloadError and raise CoTError?
    await raise_future_exceptions(async_tasks)


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
        if path not in link.cot['artifacts']:
            raise CoTError("path {} not in {} chain of trust artifacts!".format(path, link.name))
        url = get_artifact_url(chain.context, task_id, path)
        urls.append(url)
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
                chain.context.config['base_gpg_home_dir'], link.worker_class
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
        link.cot = body


# verify_*_tasks {{{1
def verify_decision_tasks(chain, num=None):
    """
    """
    # TODO docstring
    # TODO num of decision tasks per chain
    # VALID_DECISION_WORKER_TYPES
    num = num or range(1, 3)
    # TODO download_cot_artifacts full task graph
    # TODO add tests for docker image -- here or in docker_worker tests?


def verify_build_tasks(chain):
    """
    """
    pass


def verify_docker_image_tasks(chain):
    """
    """
    pass


def verify_signing_tasks(chain):
    """
    """
    pass


def verify_task_types(chain):
    """
    """


# build_chain_of_trust {{{1
async def build_chain_of_trust(chain):
    """
    """
    # TODO
    # build LinkOfTrust objects
    build_task_dependencies(chain, chain.task, chain.name, chain.task_id)
    # download the signed chain of trust artifacts
    await download_cot(chain)
    # verify the signatures and populate the `link.cot`s
    verify_cot_signatures(chain)
    # TODO find decision tasks; add tests
    # TODO verify build tasks
    # verify_task_types(chain)
    #  - decision
    #    - download full task graph
    #    - verify all child tasks are part of that graph
    #  - build
    #  - docker-image
    #  - signing
    # TODO verify worker types
    # verify_worker_types(chain)
    # TODO trace back to tree
    # - allowlisted repo/branch/revision
