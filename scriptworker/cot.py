#!/usr/bin/env python
"""Chain of Trust artifact validation and creation.
"""

import gnupg
import hashlib
import json
from scriptworker.client import validate_json_schema
from scriptworker.exceptions import ScriptWorkerTaskException

# XXX Temporarily silence flake8
assert (gnupg, hashlib, json, ScriptWorkerTaskException) is not None


def validate_cot_schema(cot, schema):
    """Simple wrapper function, probably overkill.
    """
    return validate_json_schema(cot, schema, name="chain of trust")


def generate_cot(context):
    """Generate the chain of trust dictionary
    """
    cot = {
        'workerGroup': context.config['worker_group'],
        'workerId': context.config['worker_id'],
        'workerType': context.config['worker_type'],
    }
    # "artifacts", "extra", "runId", "task", "taskId",

    return cot
