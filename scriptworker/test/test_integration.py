#!/usr/bin/env python
# coding=utf-8
"""Scriptworker integration tests.
"""
import aiohttp
import arrow
from contextlib import contextmanager
import json
import os
import pytest
import slugid
import tempfile
from scriptworker.config import CREDS_FILES, read_worker_creds, get_unfrozen_copy
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.context import Context
import scriptworker.log as swlog
import scriptworker.worker as worker
import scriptworker.utils as utils
from . import event_loop, integration_create_task_payload

assert event_loop  # silence pyflakes

# constants helpers and fixtures {{{1
TIMEOUT_SCRIPT = os.path.join(os.path.dirname(__file__), "data", "long_running.py")
SKIP_REASON = "NO_TESTS_OVER_WIRE: skipping integration test"


def read_integration_creds():
    creds = read_worker_creds(key="integration_credentials")
    if creds:
        return creds
    raise Exception(
        """To run integration tests, put your worker-test clientId creds, in json format,
in one of these files:

    {files}

with the format

    {{"integration_credentials": {{"accessToken": "...", "clientId": "...", "certificate": "..."}}}}

(only specify "certificate" if using temporary credentials)

This clientId will need the scope assume:project:taskcluster:worker-test-scopes

To skip integration tests, set the environment variable NO_TESTS_OVER_WIRE""".format(files=CREDS_FILES)
    )


def build_config(override, basedir):
    randstring = slugid.nice()[0:6].decode('utf-8')
    config = get_unfrozen_copy(DEFAULT_CONFIG)
    GPG_HOME = os.path.join(os.path.basename(__file__), "data", "gpg")
    config.update({
        'log_dir': os.path.join(basedir, "log"),
        'artifact_dir': os.path.join(basedir, "artifact"),
        'task_log_dir': os.path.join(basedir, "artifact", "public", "logs"),
        'work_dir': os.path.join(basedir, "work"),
        "worker_type": "dummy-worker-{}".format(randstring),
        "worker_id": "dummy-worker-{}".format(randstring),
        'artifact_upload_timeout': 60 * 2,
        'artifact_expiration_hours': 1,
        'gpg_home': GPG_HOME,
        "gpg_encoding": 'utf-8',
        "gpg_options": None,
        "gpg_path": os.environ.get("GPG_PATH", None),
        "gpg_public_keyring": os.path.join(GPG_HOME, "pubring.gpg"),
        "gpg_secret_keyring": os.path.join(GPG_HOME, "secring.gpg"),
        "gpg_use_agent": None,
        'reclaim_interval': 5,
        'task_script': ('bash', '-c', '>&2 echo bar && echo foo && sleep 9 && exit 1'),
        'task_max_timeout': 60,
    })
    creds = read_integration_creds()
    del(config['credentials'])
    if isinstance(override, dict):
        config.update(override)
    with open(os.path.join(basedir, "config.json"), "w") as fh:
        json.dump(config, fh, indent=2, sort_keys=True)
    return config, creds


@contextmanager
def get_context(config_override):
    context = Context()
    with tempfile.TemporaryDirectory() as tmp:
        context.config, credentials = build_config(config_override, basedir=tmp)
        swlog.update_logging_config(context)
        utils.cleanup(context)
        with aiohttp.ClientSession() as session:
            context.session = session
            context.credentials = credentials
            yield context


def get_temp_creds(context):
    if 'certificate' in context.credentials:
        return
    temp_creds = utils.create_temp_creds(
        context.credentials['clientId'],
        context.credentials['accessToken'],
        expires=arrow.utcnow().replace(minutes=10).datetime,
    )
    if temp_creds:
        context.credentials = temp_creds
        print("Using temp creds!")
    else:
        raise Exception("Can't get temp_creds!")


@contextmanager
def get_temp_creds_context(config_override):
    with get_context(config_override) as context:
        get_temp_creds(context)
        yield context


async def create_task(context, task_id, task_group_id):
    payload = integration_create_task_payload(context.config, task_group_id)
    return await context.queue.createTask(task_id, payload)


async def task_status(context, task_id):
    return await context.queue.status(task_id)


@contextmanager
def remember_cwd():
    """http://stackoverflow.com/a/170174
    """
    curdir = os.getcwd()
    try:
        yield
    finally:
        os.chdir(curdir)


# run_successful_task {{{1
@pytest.mark.skipif(os.environ.get("NO_TESTS_OVER_WIRE"), reason=SKIP_REASON)
@pytest.mark.parametrize("context_function", [get_context, get_temp_creds_context])
def test_run_successful_task(event_loop, context_function):
    task_id = slugid.nice().decode('utf-8')
    task_group_id = slugid.nice().decode('utf-8')
    with context_function(None) as context:
        result = event_loop.run_until_complete(
            create_task(context, task_id, task_group_id)
        )
        assert result['status']['state'] == 'pending'
        with remember_cwd():
            os.chdir(os.path.dirname(context.config['work_dir']))
            status = event_loop.run_until_complete(
                worker.run_loop(context, creds_key="integration_credentials")
            )
        assert status == 1
        result = event_loop.run_until_complete(
            task_status(context, task_id)
        )
        assert result['status']['state'] == 'failed'


# run_maxtimeout {{{1
@pytest.mark.skipif(os.environ.get("NO_TESTS_OVER_WIRE"), reason=SKIP_REASON)
@pytest.mark.parametrize("context_function", [get_context, get_temp_creds_context])
def test_run_maxtimeout(event_loop, context_function):
    task_id = slugid.nice().decode('utf-8')
    task_group_id = slugid.nice().decode('utf-8')
    partial_config = {
        'task_max_timeout': 2,
    }
    with context_function(partial_config) as context:
        result = event_loop.run_until_complete(
            create_task(context, task_id, task_group_id)
        )
        assert result['status']['state'] == 'pending'
        with remember_cwd():
            os.chdir(os.path.dirname(context.config['work_dir']))
            with pytest.raises(RuntimeError):
                event_loop.run_until_complete(
                    worker.run_loop(context, creds_key="integration_credentials")
                )
                # Because we're using asyncio to kill tasks in the loop,
                # we're going to hit a RuntimeError
        result = event_loop.run_until_complete(task_status(context, task_id))
        # TODO We need to be able to ensure this is 'failed'.
        assert result['status']['state'] in ('failed', 'running')


# empty_queue {{{1
@pytest.mark.skipif(os.environ.get("NO_TESTS_OVER_WIRE"), reason=SKIP_REASON)
@pytest.mark.parametrize("context_function", [get_context, get_temp_creds_context])
def test_empty_queue(event_loop, context_function):
    with context_function(None) as context:
        with remember_cwd():
            os.chdir(os.path.dirname(context.config['work_dir']))
            status = event_loop.run_until_complete(
                worker.run_loop(context, creds_key="integration_credentials")
            )
        assert status is None


# temp_creds {{{1
@pytest.mark.skipif(os.environ.get("NO_TESTS_OVER_WIRE"), reason=SKIP_REASON)
@pytest.mark.parametrize("context_function", [get_context, get_temp_creds_context])
def test_temp_creds(event_loop, context_function):
    with context_function(None) as context:
        with remember_cwd():
            os.chdir(os.path.dirname(context.config['work_dir']))
            context.temp_credentials = utils.create_temp_creds(
                context.credentials['clientId'], context.credentials['accessToken'],
                expires=arrow.utcnow().replace(minutes=10).datetime
            )
            result = event_loop.run_until_complete(context.temp_queue.ping())
            assert result['alive']
