#!/usr/bin/env python
# coding=utf-8
"""Scriptworker integration tests.
"""
import aiohttp
from contextlib import contextmanager
from copy import deepcopy
import datetime
import json
import os
import pytest
import slugid
from scriptworker.config import DEFAULT_CONFIG
from scriptworker.context import Context
import scriptworker.log as swlog
import scriptworker.worker as worker
import scriptworker.utils as utils
from taskcluster.async import Queue

TIMEOUT_SCRIPT = os.path.join(os.path.dirname(__file__), "data", "long_running.py")
SKIP_REASON = "NO_TESTS_OVER_WIRE: skipping integration test"


def read_worker_creds():
    """
    """
    files = (
        os.path.join(os.getcwd(), 'secrets.json'),
        os.path.join(os.environ['HOME'], '.scriptworker'),
    )
    for path in files:
        if not os.path.exists(path):
            continue
        with open(path, "r") as fh:
            try:
                contents = json.load(fh)
                creds = {}
                for key in ("taskcluster_client_id", "taskcluster_access_token"):
                    creds[key] = contents[key]
                return creds
            except (json.decoder.JSONDecodeError, KeyError):
                pass
    raise Exception(
        """To run integration tests, put your worker-test clientId creds, in json format,
in one of these files:

    {files}

with the format

    {{"taskcluster_client_id": "...", "taskcluster_access_token": "..."}}

This clientId will need the scope assume:project:taskcluster:worker-test-scopes

To skip integration tests, set the environment variable NO_TESTS_OVER_WIRE""".format(files=files)
    )


def build_config(override):
    cwd = os.getcwd()
    basedir = os.path.join(cwd, "integration")
    if not os.path.exists(basedir):
        os.makedirs(basedir)
    randstring = slugid.nice()[0:6].decode('utf-8')
    config = deepcopy(DEFAULT_CONFIG)
    config.update({
        'log_dir': os.path.join(basedir, "log"),
        'artifact_dir': os.path.join(basedir, "artifact"),
        'work_dir': os.path.join(basedir, "work"),
        "worker_type": "dummy-worker-{}".format(randstring),
        "worker_id": "dummy-worker-{}".format(randstring),
        'artifact_upload_timeout': 60 * 2,
        'artifact_expiration_hours': 1,
        'reclaim_interval': 5,
        'task_script': ('bash', '-c', '>&2 echo bar && echo foo && sleep 9 && exit 2'),
        'task_max_timeout': 60,
    })
    config.update(read_worker_creds())
    # TODO add read_worker_creds() into the main config, so we don't have to
    # include creds in the config json?
    # Might want to be able to specify "integration" as the prefix, so look
    # for integration_taskcluster_client_id etc
    if isinstance(override, dict):
        config.update(override)
    with open(os.path.join(basedir, "secrets.json"), "w") as fh:
        json.dump(config, fh, indent=2, sort_keys=True)
    return config


@contextmanager
def get_context(config_override):
    context = Context()
    context.config = build_config(config_override)
    swlog.update_logging_config(context)
    utils.cleanup(context)
    with aiohttp.ClientSession() as session:
        context.session = session
        context.queue = Queue({
            "credentials": {
                "clientId": context.config['taskcluster_client_id'],
                "accessToken": context.config['taskcluster_access_token'],
            },
        }, session=session)
        yield context


async def create_task(context, task_id, task_group_id):
    task_group_id = task_group_id or slugid.nice().decode('utf-8')
    now = datetime.datetime.utcnow()
    deadline = now + datetime.timedelta(hours=1)
    expires = now + datetime.timedelta(days=3)
    payload = {
        'provisionerId': context.config['provisioner_id'],
        'schedulerId': context.config['scheduler_id'],
        'workerType': context.config['worker_type'],
        'taskGroupId': task_group_id,
        'dependencies': [],
        'requires': 'all-completed',
        'routes': [],
        'priority': 'normal',
        'retries': 5,
        'created': now.isoformat() + "Z",
        'deadline': deadline.isoformat() + "Z",
        'expires': expires.isoformat() + "Z",
        'scopes': [],
        'payload': {
        },
        'metadata': {
            'name': 'ScriptWorker Integration Test',
            'description': 'ScriptWorker Integration Test',
            'owner': 'release+python@mozilla.com',
            'source': 'https://github.com/escapewindow/scriptworker/'
        },
        'tags': {},
        'extra': {
            'test_extra': 1,
        }
    }
    return await context.queue.createTask(task_id, payload)


@contextmanager
def remember_cwd():
    """http://stackoverflow.com/a/170174
    """
    curdir = os.getcwd()
    try:
        yield
    finally:
        os.chdir(curdir)


class TestIntegration(object):
    @pytest.mark.skipif(os.environ.get("NO_TESTS_OVER_WIRE"), reason=SKIP_REASON)
    @pytest.mark.asyncio
    async def test_run_successful_task(self, event_loop):
        task_id = slugid.nice().decode('utf-8')
        task_group_id = slugid.nice().decode('utf-8')
        with get_context(None) as context:
            result = await create_task(context, task_id, task_group_id)
            assert result['status']['state'] == 'pending'
            with remember_cwd():
                os.chdir("integration")
                status = await worker.run_loop(context)
            assert status == 2

    @pytest.mark.skipif(os.environ.get("NO_TESTS_OVER_WIRE"), reason=SKIP_REASON)
    def test_run_maxtimeout(self, event_loop):
        task_id = slugid.nice().decode('utf-8')
        task_group_id = slugid.nice().decode('utf-8')
        partial_config = {
            'task_max_timeout': 2,
        }
        with get_context(partial_config) as context:
            result = event_loop.run_until_complete(
                create_task(context, task_id, task_group_id)
            )
            assert result['status']['state'] == 'pending'
            with remember_cwd():
                os.chdir("integration")
                with pytest.raises(RuntimeError):
                    event_loop.run_until_complete(
                        worker.run_loop(context)
                    )
                    # Because we're using asyncio to kill tasks in the loop,
                    # we're going to hit a RuntimeError

    @pytest.mark.skipif(os.environ.get("NO_TESTS_OVER_WIRE"), reason=SKIP_REASON)
    @pytest.mark.asyncio
    async def test_empty_queue(self, event_loop):
        with get_context(None) as context:
            with remember_cwd():
                os.chdir("integration")
                status = await worker.run_loop(context)
            assert status is None
