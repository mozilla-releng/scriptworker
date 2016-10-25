#!/usr/bin/env python
"""Chain of Trust artifact validation and creation.

Attributes:
    log (logging.Logger): the log object for this module.
"""

import json
import logging
import os
from urllib.parse import unquote, urlparse
from scriptworker.client import validate_json_schema
from scriptworker.exceptions import CoTError, ScriptWorkerException
from scriptworker.gpg import GPG, sign
from scriptworker.task import get_decision_task_id, get_task_id
from scriptworker.utils import filepaths_in_dir, format_json, get_hash
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
            `context.cot_config['docker_image_allowlists']`.

    Raises:
        CoTError: on failure.
        KeyError: on malformed config / cot
    """
    # XXX we will need some way to allow trusted developers to update these
    # allowlists
    if cot['environment']['imageHash'] not in context.cot_config['docker_image_allowlists'][name]:
        raise CoTError("{} docker imageHash {} not in the allowlist!\n{}".format(name, cot['environment']['imageHash'], cot))


# build_cot_task_dict {{{2
def find_task_dependencies(task, name, task_id):
    """ TODO FILL ME OUT
    """
    decision_task_id = get_decision_task_id(task)
    decision_key = '{}:decision'.format(name)
    dep_dict = {decision_key: decision_task_id}
    for key, val in task['extra'].get('chainOfTrust', {}).get('inputs', {}).items():
        dep_dict['{}:{}'.format(name, key)] = val
    if dep_dict[decision_key] != decision_task_id:
        raise CoTError(
            "{}:{} : task.extra.chainOfTrust.inputs.decision != get_decision_task_id!\n{}".format(name, task_id, task)
        )
    return dep_dict


async def build_task_dependencies(context, task_dict, task, name, my_task_id):
    """ TODO
    """
    deps = find_task_dependencies(task, name, my_task_id)
    for task_name, task_id in deps.items():
        task_dict['dependencies'][task_name] = task_id
        if task_id not in task_dict['tasks']:
            try:
                task_defn = await context.queue.task(task_id)
                task_dict[task_id] = task_defn
                await build_task_dependencies(
                    context, task_dict, task_defn,
                    "{}:{}".format(name, task_name), task_id
                )
            except TaskclusterFailure as exc:
                raise CoTError(str(exc))


async def build_cot_task_dict(context, name):
    """ TODO FILL ME OUT

    {
      "tasks": {
        "taskId1": { # task defn },
        "taskId2": { # task defn },
        "taskId3": { # task defn },
      },
      "dependencies": {
        "signing:decision": "taskId",
        "signing:build": "taskId",
        "signing:build:decision": "taskId",
        "signing:build:docker-image": "taskId",
      },
    }
    """
    my_task_id = get_task_id(context.claim_task)
    task_dict = {
        "tasks": {
            my_task_id: context.task
        },
        "dependencies": {},
    }
    await build_task_dependencies(context, task_dict, context.task, name, my_task_id)
    return task_dict
