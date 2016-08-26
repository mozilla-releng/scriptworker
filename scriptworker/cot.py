#!/usr/bin/env python
"""Chain of Trust artifact validation and creation.
"""

import json
import logging
import os
from scriptworker.client import validate_json_schema
from scriptworker.exceptions import ScriptWorkerException
from scriptworker.gpg import sign
from scriptworker.utils import filepaths_in_dir, format_json, get_hash

log = logging.getLogger(__name__)


def get_cot_artifacts(context):
    """Generate the artifact relative paths and shas for the chain of trust
    """
    artifacts = []
    filepaths = filepaths_in_dir(context.config['artifact_dir'])
    hash_alg = context.config['chain_of_trust_hash_algorithm']
    for filepath in sorted(filepaths):
        path = os.path.join(context.config['artifact_dir'], filepath)
        sha = get_hash(path, hash_type=hash_alg)
        artifacts.append({
            "name": filepath,
            "hash": "{}:{}".format(hash_alg, sha),
        })
    return artifacts


def generate_cot_body(context):
    """Generate the chain of trust dictionary
    """
    try:
        cot = {
            'artifacts': get_cot_artifacts(context),
            'runId': context.claim_task['runId'],
            'task': context.task,
            'taskId': context.claim_task['status']['taskId'],
            'workerGroup': context.claim_task['workerGroup'],
            'workerId': context.config['worker_id'],
            'workerType': context.config['worker_type'],
            'extra': {},  # TODO
        }
    except (KeyError, ) as e:
        raise ScriptWorkerException("Can't generate chain of trust! {}".format(str(e)))

    return cot


def generate_cot(context, path=None):
    """Format and sign the cot body, and write to disk
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
    formatted_body = format_json(body)
    path = path or os.path.join(context.config['artifact_dir'], "public", "certificate.json.gpg")
    signed_body = sign(context, formatted_body)
    with open(path, "w") as fh:
        print(signed_body, file=fh, end="")
    return signed_body
