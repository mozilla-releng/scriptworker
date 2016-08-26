#!/usr/bin/env python
"""Chain of Trust artifact validation and creation.
"""

import gnupg
import json
import os
from scriptworker.client import validate_json_schema
from scriptworker.exceptions import ScriptWorkerException
from scriptworker.utils import filepaths_in_dir, get_hash

# XXX Temporarily silence flake8
assert gnupg


def validate_cot_schema(cot, schema):
    """Simple wrapper function, probably overkill.
    """
    return validate_json_schema(cot, schema, name="chain of trust")


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
        # TODO checks to make sure the below aren't empty?  maybe jsonschema?
        cot = {
            'artifacts': get_cot_artifacts(context),
            'runId': context.claim_task['runId'],
            'task': context.task,
            'taskId': context.claim_task['taskId'],
            'workerGroup': context.config['worker_group'],
            'workerId': context.config['worker_id'],
            'workerType': context.config['worker_type'],
            'extra': {},  # TODO
        }
    except (KeyError, ) as e:
        raise ScriptWorkerException("Can't generate chain of trust!")

    return cot


def generate_cot(context, path=None):
    """Format and sign the cot body, and write to disk
    """
    body = json.dumps(generate_cot_body(context), indent=2, sort_keys=True)
    path = path or os.path.join(context.config['artifact_dir'], "public", "certificate.json.gpg")
    # TODO sign
    with open(path, "w") as fh:
        print(body, file=fh, end="")
    return body
