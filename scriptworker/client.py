#!/usr/bin/env python
"""Jobs running in scriptworker will use functions in this file.
"""
import arrow
import asyncio
import glob
import json
import jsonschema
import os
from scriptworker.exceptions import ScriptWorkerTaskException
from scriptworker.task import STATUSES
from scriptworker.utils import retry_async


def get_task(config):
    """The worker writes a task.json to the work_dir; the task needs to be
    able to retrieve it.
    """
    try:
        path = os.path.join(config['work_dir'], "task.json")
        with open(path, "r") as fh:
            contents = json.load(fh)
            return contents['task']
    except (OSError, ValueError) as exc:
        raise ScriptWorkerTaskException(
            "Can't read task from {}!\n{}".format(path, str(exc)),
            exit_code=STATUSES['internal-error']
        )


async def _get_temp_creds_from_file(config, num_files=2):
    """The worker writes a credentials.TIMESTAMP.json with temp creds to
    the work_dir every time claimTask or reclaimTask is run.

    We should get our temp creds from the latest credentials file, but let's
    look at the latest 2 files just in case we try to read the credentials file
    while the next one is being written to.

    There isn't a strong reason for this function to be async, other than
    the existence of scriptworker.utils.retry_async.
    """
    match = os.path.join(config['work_dir'], "credentials.*.json")
    all_files = sorted(glob.glob(match), reverse=True)  # start with the latest file
    if len(all_files) > num_files:
        all_files = all_files[:num_files]
    while all_files:
        path = all_files.pop(0)
        try:
            with open(path, "r") as fh:
                return json.load(fh)
        except (OSError, ValueError) as exc:
            if not all_files:
                raise ScriptWorkerTaskException(
                    "Can't load credentials from latest {} {}!\n{}".format(num_files, match, str(exc)),
                    exit_code=STATUSES['internal-error']
                )
    raise ScriptWorkerTaskException(
        "No credentials files found that match {}!".format(match),
        exit_code=STATUSES['internal-error']
    )


def get_temp_creds_from_file(config):
    """Retry _get_temp_creds_from_file
    """
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(retry_async(
        _get_temp_creds_from_file, retry_exceptions=(ScriptWorkerTaskException,),
        args=(config, ),
    ))


def validate_task_schema(task, schema):
    """Given task json and a jsonschema, let's validate the task.
    Most likely this will operate on the task_json['task'] rather than
    the entire response from claimTask.
    """
    try:
        jsonschema.validate(task, schema)
    except jsonschema.exceptions.ValidationError as exc:
        raise ScriptWorkerTaskException(
            "Can't validate task schema!\n{}".format(str(exc)),
            exit_code=STATUSES['malformed-payload']
        )


def integration_create_task_payload(config, task_group_id, scopes=None,
                                    task_payload=None, task_extra=None):
    """For various integration tests, we need to call createTask for test tasks.

    This function creates a dummy payload for those createTask calls.
    """
    now = arrow.utcnow()
    deadline = now.replace(hours=1)
    expires = now.replace(days=3)
    scopes = scopes or []
    task_payload = task_payload or {}
    task_extra = task_extra or {}
    return {
        'provisionerId': config['provisioner_id'],
        'schedulerId': config['scheduler_id'],
        'workerType': config['worker_type'],
        'taskGroupId': task_group_id,
        'dependencies': [],
        'requires': 'all-completed',
        'routes': [],
        'priority': 'normal',
        'retries': 5,
        'created': now.isoformat(),
        'deadline': deadline.isoformat(),
        'expires': expires.isoformat(),
        'scopes': scopes,
        'payload': task_payload,
        'metadata': {
            'name': 'ScriptWorker Integration Test',
            'description': 'ScriptWorker Integration Test',
            'owner': 'release+python@mozilla.com',
            'source': 'https://github.com/escapewindow/scriptworker/'
        },
        'tags': {},
        'extra': task_extra,
    }
