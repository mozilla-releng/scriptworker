#!/usr/bin/env python
"""Chain of Trust artifact validation and creation.

Attributes:
    log (logging.Logger): the log object for this module.
"""

import json
import logging
import os
import re
from urllib.parse import unquote, urljoin, urlparse
from scriptworker.client import validate_json_schema
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.exceptions import CoTError, ScriptWorkerException, ScriptWorkerGPGException
from scriptworker.gpg import get_body, GPG, sign
from scriptworker.task import download_artifacts, get_decision_task_id, get_task_id
from scriptworker.utils import filepaths_in_dir, format_json, get_hash, raise_future_exceptions
from taskcluster.exceptions import TaskclusterFailure

log = logging.getLogger(__name__)


# cot generation {{{1
# get_cot_artifacts {{{2
def get_cot_artifacts(context):
    """Generate the artifact relative paths and shas for the chain of trust

    Args:
        context (scriptworker.context.Context): the scriptworker context.

    Returns:
        dict: a dictionary of {"path/to/artifact": {"hash_alg": "..."}, ...}
    """
    artifacts = {}
    filepaths = filepaths_in_dir(context.config['artifact_dir'])
    hash_alg = context.config['chain_of_trust_hash_algorithm']
    for filepath in sorted(filepaths):
        path = os.path.join(context.config['artifact_dir'], filepath)
        sha = get_hash(path, hash_alg=hash_alg)
        artifacts[filepath] = {hash_alg: sha}
    return artifacts


# get_cot_environment {{{2
def get_cot_environment(context):
    """Get environment information for the chain of trust artifact.

    Args:
        context (scriptworker.context.Context): the scriptworker context.

    Returns:
        dict: the environment info.
    """
    env = {}
    # TODO
    return env


# generate_cot_body {{{2
def generate_cot_body(context):
    """Generate the chain of trust dictionary.

    This is the unsigned and unformatted chain of trust artifact contents.

    Args:
        context (scriptworker.context.Context): the scriptworker context.

    Returns:
        dict: the unsignd and unformatted chain of trust artifact contents.

    Raises:
        ScriptWorkerException: on error.
    """
    try:
        cot = {
            'artifacts': get_cot_artifacts(context),
            'chainOfTrustVersion': 1,
            'runId': context.claim_task['runId'],
            'task': context.task,
            'taskId': context.claim_task['status']['taskId'],
            'workerGroup': context.claim_task['workerGroup'],
            'workerId': context.config['worker_id'],
            'workerType': context.config['worker_type'],
            'environment': get_cot_environment(context),
        }
    except (KeyError, ) as exc:
        raise ScriptWorkerException("Can't generate chain of trust! {}".format(str(exc)))

    return cot


# generate_cot {{{2
def generate_cot(context, path=None):
    """Format and sign the cot body, and write to disk

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        path (str, optional): The path to write the chain of trust artifact to.
            If None, this is artifact_dir/public/chainOfTrust.json.asc.
            Defaults to None.

    Returns:
        str: the contents of the chain of trust artifact.

    Raises:
        ScriptWorkerException: on schema error.
    """
    body = generate_cot_body(context)
    try:
        with open(context.config['cot_schema_path'], "r") as fh:
            schema = json.load(fh)
    except (IOError, ValueError) as e:
        raise ScriptWorkerException(
            "Can't read schema file {}: {}".format(context.config['cot_schema_path'], str(e))
        )
    validate_json_schema(body, schema, name="chain of trust")
    body = format_json(body)
    path = path or os.path.join(context.config['artifact_dir'], "public", "chainOfTrust.json.asc")
    if context.config['sign_chain_of_trust']:
        body = sign(GPG(context), body)
    with open(path, "w") as fh:
        print(body, file=fh, end="")
    return body


# cot verification {{{1
# classify_worker_type {{{2
def classify_worker_type(task, name):
    """Given a task, determine which worker type it was run on.

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
            raise CoTError("classify_worker_type: {} was {} and now looks like {}!\n{}".format(name, worker_type['worker_type'], wt, task))
        worker_type['worker_type'] = wt

    if task['payload'].get("image"):
        _set_worker_type("docker-worker")
    # TODO config for these scriptworker checks?
    if task['provisionerId'] in ("scriptworker-prov-v1", ):
        _set_worker_type("scriptworker")
    if task['workerType'] in ("signing-linux-v1", ):
        _set_worker_type("scriptworker")

    for scope in task['scopes']:
        if scope.startswith("docker-worker:"):
            _set_worker_type("docker-worker")

    if worker_type['worker_type'] is None:
        raise CoTError("classify_worker_type: can't find a type for {}!\n{}".format(name, task))
    return worker_type['worker_type']


# is_try {{{2
def _is_try_url(url):
    parsed = urlparse(url)
    path = unquote(parsed.path).lstrip('/')
    parts = path.split('/')
    if parts[0] == "try":
        return True
    return False


def is_try(task, name):
    """Determine if a task is a 'try' task (restricted privs).

    XXX do we want this, or just do this behavior for any non-allowlisted repo?

    This checks for the following things::

        * `task.payload.env.GECKO_HEAD_REPOSITORY` == "https://hg.mozilla.org/try/"
        * `task.payload.env.MH_BRANCH` == "try"
        * `task.metadata.source` == "https://hg.mozilla.org/try/..."
        * `task.schedulerId` in ("gecko-level-1", )

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


# check_interactive_docker_worker {{{2
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


# check_docker_image_sha {{{2
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


# find_task_dependencies {{{2
def find_task_dependencies(task, name, task_id):
    """Find the taskIds of the chain of trust dependencies of a given task.

    Args:
        task (dict): the task definition to inspect.
        name (str): the name of the task, for logging and naming children.
        task_id (str): the taskId of the task.

    Returns:
        tuple (str, dict): decision task id, mapping dependent task `name` to
            dependent task `taskId`.
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
            m = re.search(DEFAULT_CONFIG['valid_artifact_path_regexes'][0], path)
            path_info = m.groupdict()
            if path_info['taskId'] not in build_ids:
                build_ids.append(path_info['taskId'])
        for count, build_id in enumerate(build_ids):
            dep_dict['{}:build{}'.format(name, count)] = build_id
    # XXX end hack
    if decision_task_id != task_id:
        dep_dict[decision_key] = decision_task_id
    log.info(dep_dict)
    return decision_task_id, dep_dict


# build_task_dependencies {{{2
async def build_task_dependencies(context, task_dict, task, name, my_task_id):
    """Recursively build the task dependencies of a task.

    This is a helper function for `build_cot_task_dict`.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        task_dict (dict): the task dict to modify.
        task (dict): the task definition to operate on.
        name (str): the name of the task to operate on.
        my_task_id (str): the taskId of the task to operate on.

    Raises:
        KeyError: on failure.
    """
    log.info("build_task_dependencies {}".format(name))
    if name.count(':') > 5:
        raise CoTError("Too deep recursion!\n{}".format(task_dict))
    decision_task_id, deps = find_task_dependencies(task, name, my_task_id)
    log.info("{} decision is {}".format(name, decision_task_id))
    task_dict['dependencies'][name]['decision'] = decision_task_id
    task_dict['dependencies'][name]['cot_dir'] = os.path.join(
        context.config['artifact_dir'], 'cot', my_task_id
    )
    task_names = sorted(deps.keys())
    # make sure we deal with the decision task first, or we may populate
    # signing:build0:decision before signing:decision
    decision_key = "{}:decision".format(name)
    if decision_key in task_names:
        task_names = [decision_key] + sorted([x for x in task_names if x != decision_key])
    for task_name in task_names:
        task_id = deps[task_name]
        if task_id not in task_dict['tasks']:
            task_dict['dependencies'][task_name] = {
                'taskId': task_id,
            }
            try:
                task_defn = await context.queue.task(task_id)
                task_dict['tasks'][task_id] = task_defn
                await build_task_dependencies(
                    context, task_dict, task_defn,
                    task_name, task_id
                )
            except TaskclusterFailure as exc:
                raise CoTError(str(exc))


# build_cot_task_dict {{{2
async def build_cot_task_dict(context, name, my_task_id=None):
    """Build the chain of trust task dict, following dependencies.

    The task_dict looks like::

        {
          "tasks": {
            "taskId0": { # task defn },
            "taskId1": { # task defn },
            "taskId2": { # task defn },
            "taskId3": { # task defn },
            "taskId4": { # task defn },
          },
          "dependencies": {
            "signing": {
                'taskId': "taskId0",
                'decision': "taskId1",
            },
            "signing:decision": {
                'taskId': "taskId1",
                'decision': "taskId1",
            }
            "signing:build": {
                'taskId': "taskId2",
                'decision': "taskId1",
            }
            "signing:build:docker-image": {
                'taskId': "taskId3",
                'decision': "taskId4",
            },
            "signing:build:docker-image:decision": {
                'taskId': "taskId4",
                'decision': "taskId4",
            },
          },
        }

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        name (str): the name of the top level task, e.g. 'signing'.
        my_task_id (str, optional): Use this `taskId`.  If `None`, use
            `get_task_id(context.claim_task)`.  Defaults to None.

    Returns:
        dict: the task_dict as shown above.

    Raises:
        KeyError: on failure.
    """
    my_task_id = my_task_id or get_task_id(context.claim_task)
    task_dict = {
        "tasks": {
            my_task_id: context.task
        },
        "dependencies": {
            name: {
                'taskId': my_task_id
            },
        },
    }
    await build_task_dependencies(context, task_dict, context.task, name, my_task_id)
    return task_dict


# download_cot {{{1
async def download_cot(context, task_dict, name):
    """Download the signed chain of trust artifacts.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        task_dict (dict): the task_dict from `build_cot_task_dict`
        name (str): the name of the current task; used to skip downloading
            the currently nonexistent chain of trust artifact for the
            current task.

    Raises:
        DownloadError: on failure.
    """
    tasks = []
    for task_name, task_info in task_dict['dependencies'].items():
        # don't try to download the current task's chain of trust artifact,
        # which hasn't been created / uploaded yet
        if task_name == name:
            continue
        task_id = task_info['taskId']
        url = urljoin(
            context.queue.options['baseUrl'],
            context.queue.makeRoute('getLatestArtifact', replDict={
                'taskId': task_id,
                'name': 'public/chainOfTrust.json.asc'
            })
        )
        parent_dir = task_info['cot_dir']
        tasks.append(
            download_artifacts(
                context, [url], parent_dir=parent_dir, valid_artifact_task_ids=[task_id]
            )
        )
    # XXX catch DownloadError and raise CoTError?
    await raise_future_exceptions(tasks)


# download_cot_artifacts {{{1
async def download_cot_artifacts(context, task_dict, task_id, paths):
    """ TODO
    """
    pass


# verify_cot_signatures {{{1
def verify_cot_signatures(context, task_dict, name):
    """Verify the signatures of the chain of trust artifacts populated in `download_cot`.

    Populate `task_dict['dependencies'][task_name]['cot']` with the json body.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        task_dict (dict): the task_dict from `build_cot_task_dict`
        name (str): the name of the current task; used to skip parsing
            the currently nonexistent chain of trust artifact for the
            current task.

    Raises:
        CoTError: on failure.
    """
    for task_name, task_info in task_dict['dependencies'].items():
        if task_name == name:
            continue
        path = os.path.join(task_info['cot_dir'], 'public/chainOfTrust.json.asc')
        task_id = task_info['taskId']
        worker_type = classify_worker_type(task_dict['tasks'][task_id])
        gpg = GPG(context, gpg_home=os.path.join(context.config['base_gpg_home_dir'], worker_type))
        try:
            with open(path, "r") as fh:
                contents = fh.read()
        except OSError as exc:
            raise CoTError("Can't read {}: {}!".format(path, str(exc)))
        try:
            # XXX remove verify_sig pref and kwarg when pubkeys are in git repo
            body = get_body(gpg, contents, verify_sig=context.config['verify_cot_signature'])
        except ScriptWorkerGPGException as exc:
            raise CoTError("GPG Error verifying chain of trust for {}: {}!".format(path, str(exc)))
        task_dict['dependencies'][task_name]['cot'] = body
