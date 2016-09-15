#!/usr/bin/env python
"""Chain of Trust artifact validation and creation.

Attributes:
    log (logging.Logger): the log object for this module.
"""

import json
import logging
import os
from scriptworker.client import validate_json_schema
from scriptworker.exceptions import ScriptWorkerException
from scriptworker.gpg import GPG, sign
from scriptworker.utils import filepaths_in_dir, format_json, get_hash

log = logging.getLogger(__name__)


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


def get_environment(context):
    """Get environment information for the chain of trust artifact.

    Args:
        context (scriptworker.context.Context): the scriptworker context.

    Returns:
        dict: the environment info.
    """
    env = {}
    # TODO
    return env


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
            'environment': get_environment(context),
        }
    except (KeyError, ) as exc:
        raise ScriptWorkerException("Can't generate chain of trust! {}".format(str(exc)))

    return cot


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
