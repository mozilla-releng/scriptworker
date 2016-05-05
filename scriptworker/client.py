#!/usr/bin/env python
"""Jobs running in scriptworker will use functions in this file.
"""
import json
import jsonschema
import os
from scriptworker.exceptions import ScriptWorkerTaskException


def get_task(config):
    try:
        path = os.path.join(config['work_dir'], "task.json")
        with open(path, "r") as fh:
            contents = json.load(fh)
            return contents['task']
    except (OSError, ValueError) as exc:
        raise ScriptWorkerTaskException(
            "Can't read task from {}!".format(path),
            super_exc=exc
        )


def validate_task_schema(task, schema):
    try:
        jsonschema.validate(task, schema)
    except jsonschema.exceptions.ValidationError as exc:
        raise ScriptWorkerTaskException(
            "Can't validate task schema!",
            super_exc=exc
        )
