#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.worker
"""
import aiohttp
import arrow
import asyncio
from copy import deepcopy
import json
import mock
import os
import pytest
import tempfile
import shutil
import sys
import signal

from scriptworker.constants import STATUSES
from scriptworker.exceptions import ScriptWorkerException
import scriptworker.worker as worker
from . import noop_async, noop_sync, rw_context, successful_queue, \
    tmpdir, TIMEOUT_SCRIPT

assert rw_context, tmpdir  # silence flake8
assert successful_queue  # silence flake8


# constants helpers and fixtures {{{1
@pytest.yield_fixture(scope='function')
def context(rw_context):
    rw_context.credentials_timestamp = arrow.utcnow().replace(minutes=-10).timestamp
    yield rw_context


# main {{{1
def test_main(mocker, context, event_loop):
    config = dict(context.config)
    config['poll_interval'] = 1
    creds = {'fake_creds': True}
    config['credentials'] = deepcopy(creds)

    async def foo(arg, credentials):
        # arg.credentials will be a dict copy of a frozendict.
        assert credentials == dict(creds)
        raise ScriptWorkerException("foo")

    try:
        _, tmp = tempfile.mkstemp()
        with open(tmp, "w") as fh:
            json.dump(config, fh)
        del(config['credentials'])
        mocker.patch.object(worker, 'async_main', new=foo)
        mocker.patch.object(sys, 'argv', new=['x', tmp])
        with pytest.raises(ScriptWorkerException):
            worker.main(event_loop=event_loop)
    finally:
        os.remove(tmp)


def test_main_sigterm(mocker, context, event_loop):
    """Test that sending SIGTERM causes the main loop to stop after the next
    call to async_main."""
    config = dict(context.config)
    config['poll_interval'] = 1
    creds = {'fake_creds': True}
    config['credentials'] = deepcopy(creds)

    async def async_main(*args):
        # Send SIGTERM to ourselves so that we stop
        os.kill(os.getpid(), signal.SIGTERM)
        return True

    try:
        _, tmp = tempfile.mkstemp()
        with open(tmp, "w") as fh:
            json.dump(config, fh)
        del(config['credentials'])
        mocker.patch.object(worker, 'async_main', new=async_main)
        mocker.patch.object(sys, 'argv', new=['x', tmp])
        worker.main(event_loop=event_loop)
    finally:
        os.remove(tmp)


# async_main {{{1
@pytest.mark.asyncio
async def test_async_main(context, mocker, tmpdir):
    path = "{}.tmp".format(context.config['base_gpg_home_dir'])

    async def tweak_lockfile(_):
        path = "{}.tmp".format(context.config['base_gpg_home_dir'])
        try:
            os.makedirs(path)
        except FileExistsError:
            pass
        lockfile = context.config['gpg_lockfile']
        if os.path.exists(lockfile):
            with open(lockfile, "w") as fh:
                print("ready:", file=fh)
        else:
            with open(lockfile, "w") as fh:
                print("locked:", file=fh)

    def exit(*args, **kwargs):
        sys.exit()

    try:
        mocker.patch.object(worker, 'run_tasks', new=tweak_lockfile)
        mocker.patch.object(asyncio, 'sleep', new=noop_async)
        mocker.patch.object(worker, 'rm', new=noop_sync)
        mocker.patch.object(os, 'rename', new=noop_sync)
        mocker.patch.object(worker, 'rm_lockfile', new=exit)
        await worker.async_main(context, {})
        await worker.async_main(context, {})
        with pytest.raises(SystemExit):
            await worker.async_main(context, {})
    finally:
        if os.path.exists(path):
            shutil.rmtree(path)


# run_tasks {{{1
@pytest.mark.asyncio
@pytest.mark.parametrize("verify_cot", (True, False))
async def test_mocker_run_tasks(context, successful_queue, verify_cot, mocker):
    task = {"foo": "bar", "credentials": {"a": "b"}, "task": {'task_defn': True}}

    successful_queue.task = task
    async def claim_work(*args, **kwargs):
        return {'tasks': [deepcopy(task)]}

    async def run_task(*args, **kwargs):
        return 19

    fake_cot = mock.MagicMock

    context.config['verify_chain_of_trust'] = verify_cot

    context.queue = successful_queue
    mocker.patch.object(worker, "claim_work", new=claim_work)
    mocker.patch.object(worker, "reclaim_task", new=noop_async)
    mocker.patch.object(worker, "prepare_to_run_task", new=noop_sync)
    mocker.patch.object(worker, "run_task", new=run_task)
    mocker.patch.object(worker, "ChainOfTrust", new=fake_cot)
    mocker.patch.object(worker, "verify_chain_of_trust", new=noop_async)
    mocker.patch.object(worker, "generate_cot", new=noop_sync)
    mocker.patch.object(worker, "upload_artifacts", new=noop_async)
    mocker.patch.object(worker, "complete_task", new=noop_async)
    status = await worker.run_tasks(context)
    assert status == 19


@pytest.mark.asyncio
async def test_mocker_run_tasks_noop(context, successful_queue, mocker):
    context.queue = successful_queue
    mocker.patch.object(worker, "claim_work", new=noop_async)
    mocker.patch.object(worker, "reclaim_task", new=noop_async)
    mocker.patch.object(worker, "prepare_to_run_task", new=noop_sync)
    mocker.patch.object(worker, "run_task", new=noop_async)
    mocker.patch.object(worker, "generate_cot", new=noop_sync)
    mocker.patch.object(worker, "upload_artifacts", new=noop_async)
    mocker.patch.object(worker, "complete_task", new=noop_async)
    status = await worker.run_tasks(context)
    assert context.credentials is None
    assert status is None


def _mocker_run_tasks_helper(mocker, exc, func_to_raise):
    """Mock run_tasks for the test_mocker_run_tasks_* tests.

    """
    task = {"foo": "bar", "credentials": {"a": "b"}, "task": {'task_defn': True}}

    async def claim_work(*args, **kwargs):
        return {'tasks': [task]}

    async def fail(*args, **kwargs):
        raise exc("foo")

    async def run_task(*args, **kwargs):
        return 0

    mocker.patch.object(worker, "claim_work", new=claim_work)
    mocker.patch.object(worker, "reclaim_task", new=noop_async)
    mocker.patch.object(worker, "prepare_to_run_task", new=noop_sync)
    if func_to_raise == "run_task":
        mocker.patch.object(worker, "run_task", new=fail)
    else:
        mocker.patch.object(worker, "run_task", new=run_task)
    mocker.patch.object(worker, "generate_cot", new=noop_sync)
    if func_to_raise == "upload_artifacts":
        mocker.patch.object(worker, "upload_artifacts", new=fail)
    else:
        mocker.patch.object(worker, "upload_artifacts", new=noop_async)
    mocker.patch.object(worker, "complete_task", new=noop_async)


@pytest.mark.parametrize("func_to_raise,exc,expected", ((
    'run_task', ScriptWorkerException, ScriptWorkerException.exit_code
), (
    'upload_artifacts', ScriptWorkerException, ScriptWorkerException.exit_code
), (
    'upload_artifacts', aiohttp.ClientError, STATUSES['intermittent-task']
)))
@pytest.mark.asyncio
async def test_mocker_run_tasks_caught_exception(context, successful_queue, mocker,
                                                 func_to_raise, exc, expected):
    """Raise an exception within the run_tasks try/excepts and return status.

    """
    _mocker_run_tasks_helper(mocker, exc, func_to_raise)

    context.queue = successful_queue
    status = await worker.run_tasks(context)
    assert status == expected


@pytest.mark.parametrize("func_to_raise,exc", ((
    'run_task', ValueError
), (
    'upload_artifacts', OSError
)))
@pytest.mark.asyncio
async def test_mocker_run_tasks_uncaught_exception(context, successful_queue, mocker,
                                                 func_to_raise, exc):
    """Raise an uncaught exception within the run_tasks try/excepts.

    """
    _mocker_run_tasks_helper(mocker, exc, func_to_raise)

    context.queue = successful_queue
    with pytest.raises(exc):
        await worker.run_tasks(context)


@pytest.mark.asyncio
async def test_run_tasks_timeout(context, successful_queue, mocker):
    temp_dir = os.path.join(context.config['work_dir'], "timeout")
    task = {"foo": "bar", "credentials": {"a": "b"}, "task": {'task_defn': True}}
    context.config['task_script'] = (
        sys.executable, TIMEOUT_SCRIPT, temp_dir
    )
    context.config['task_max_timeout'] = 1
    context.queue = successful_queue

    async def claim_work(*args, **kwargs):
        return {'tasks': [task]}

    mocker.patch.object(worker, "claim_work", new=claim_work)
    mocker.patch.object(worker, "reclaim_task", new=noop_async)
    mocker.patch.object(worker, "generate_cot", new=noop_sync)
    mocker.patch.object(worker, "prepare_to_run_task", new=noop_sync)
    mocker.patch.object(worker, "upload_artifacts", new=noop_async)
    mocker.patch.object(worker, "complete_task", new=noop_async)
    status = await worker.run_tasks(context)
    assert status == context.config['task_max_timeout_status']
