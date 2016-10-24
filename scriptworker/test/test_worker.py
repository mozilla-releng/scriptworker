#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.worker
"""
import arrow
import asyncio
from copy import deepcopy
import mock
import os
import pytest
from scriptworker.config import create_config
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerException
import scriptworker.worker as worker
import sys
from . import event_loop, successful_queue, tmpdir

assert tmpdir  # silence flake8
assert successful_queue, event_loop  # silence flake8


# constants helpers and fixtures {{{1
@pytest.fixture(scope='function')
def context(tmpdir):
    context = Context()
    context.config = dict(deepcopy(DEFAULT_CONFIG))
    context.config['log_dir'] = os.path.join(tmpdir, "log")
    context.config['work_dir'] = os.path.join(tmpdir, "work")
    context.config['artifact_dir'] = os.path.join(tmpdir, "artifact")
    context.config['poll_interval'] = .1
    context.config['credential_update_interval'] = .1
    context.credentials_timestamp = arrow.utcnow().replace(minutes=-10).timestamp
    context.poll_task_urls = {
        'queues': [{
            "signedPollUrl": "poll0",
            "signedDeleteUrl": "delete0",
        }, {
            "signedPollUrl": "poll1",
            "signedDeleteUrl": "delete1",
        }],
        'expires': arrow.utcnow().replace(hours=10).isoformat(),
    }
    return context


def die_sync(*args, **kwargs):
    raise ScriptWorkerException("foo")


async def die_async(*args, **kwargs):
    raise ScriptWorkerException("foo")


# tests {{{1
def test_main_too_many_args(mocker, event_loop):
    mocker.patch.object(worker, 'async_main', new=die_async)
    with pytest.raises(SystemExit):
        with mock.patch('sys.argv', new=[1, 2, 3, 4]):
            worker.main()


def test_main_bad_json(mocker, event_loop):
    path = os.path.join(os.path.dirname(__file__), "data", "bad.json")
    mocker.patch.object(worker, 'async_main', new=die_async)
    with pytest.raises(SystemExit):
        with mock.patch('sys.argv', new=[__file__, path]):
            worker.main()


def test_main(mocker, event_loop):
    path = os.path.join(os.path.dirname(__file__), "data", "good.json")
    config, creds = create_config(path)
    loop = mock.MagicMock()

    def run_until_complete(*args):
        raise ScriptWorkerException("foo")

    def foo(arg):
        assert arg.config == config
        assert arg.credentials == creds

    loop.run_until_complete = run_until_complete

    mocker.patch.object(sys, 'argv', new=[__file__, path])
    mocker.patch.object(worker, 'async_main', new=foo)
    with mock.patch.object(asyncio, 'get_event_loop') as p:
        p.return_value = loop
        with pytest.raises(ScriptWorkerException):
            worker.main()


def test_async_main(context, event_loop):

    async def exit(*args, **kwargs):
        sys.exit()

    with mock.patch('scriptworker.worker.run_loop', new=exit):
        with pytest.raises(SystemExit):
            event_loop.run_until_complete(
                worker.async_main(context)
            )


def test_run_loop_exception(context, successful_queue, event_loop):
    context.queue = successful_queue

    async def raise_swe(*args, **kwargs):
        raise ScriptWorkerException("foo")

    with mock.patch.object(worker, 'find_task', new=raise_swe):
        status = event_loop.run_until_complete(worker.run_loop(context))

    assert status is None


def test_mocker_run_loop(context, successful_queue, event_loop, mocker):
    task = {"foo": "bar", "credentials": {"a": "b"}, "task": {'task_defn': True}}

    async def find_task(*args, **kwargs):
        return deepcopy(task)

    async def noop(*args, **kwargs):
        return

    context.queue = successful_queue
    mocker.patch.object(worker, "find_task", new=find_task)
    mocker.patch.object(worker, "reclaim_task", new=noop)
    mocker.patch.object(worker, "run_task", new=find_task)
    mocker.patch.object(worker, "generate_cot", new=noop)
    mocker.patch.object(worker, "upload_artifacts", new=noop)
    mocker.patch.object(worker, "complete_task", new=noop)
    status = event_loop.run_until_complete(worker.run_loop(context))
    assert status == task


def test_mocker_run_loop_noop(context, successful_queue, event_loop, mocker):
    async def find_task(*args, **kwargs):
        return None

    async def noop(*args, **kwargs):
        return

    def noop_sync(*args, **kwargs):
        return

    context.queue = successful_queue
    mocker.patch.object(worker, "find_task", new=find_task)
    mocker.patch.object(worker, "reclaim_task", new=noop)
    mocker.patch.object(worker, "run_task", new=find_task)
    mocker.patch.object(worker, "generate_cot", new=noop_sync)
    mocker.patch.object(worker, "upload_artifacts", new=noop)
    mocker.patch.object(worker, "complete_task", new=noop)
    mocker.patch.object(worker, "read_worker_creds", new=noop_sync)
    status = event_loop.run_until_complete(worker.run_loop(context))
    assert context.credentials is None
    assert status is None


def test_mocker_run_loop_noop_update_creds(context, successful_queue,
                                           event_loop, mocker):
    new_creds = {"new_creds": "true"}

    async def find_task(*args, **kwargs):
        return None

    async def noop(*args, **kwargs):
        return

    def noop_sync(*args, **kwargs):
        return

    def get_creds(*args, **kwargs):
        return deepcopy(new_creds)

    context.queue = successful_queue
    mocker.patch.object(worker, "find_task", new=find_task)
    mocker.patch.object(worker, "reclaim_task", new=noop)
    mocker.patch.object(worker, "run_task", new=find_task)
    mocker.patch.object(worker, "generate_cot", new=noop_sync)
    mocker.patch.object(worker, "upload_artifacts", new=noop)
    mocker.patch.object(worker, "complete_task", new=noop)
    mocker.patch.object(worker, "read_worker_creds", new=get_creds)
    status = event_loop.run_until_complete(worker.run_loop(context))
    assert context.credentials == new_creds
    assert status is None


@pytest.mark.parametrize("func_to_raise", ['run_task', 'upload_artifacts'])
def test_mocker_run_loop_exception(context, successful_queue,
                                   event_loop, mocker, func_to_raise):
    """Raise an exception within the run_loop try/excepts and make sure the
    status is changed
    """
    task = {"foo": "bar", "credentials": {"a": "b"}, "task": {'task_defn': True}}

    async def find_task(*args, **kwargs):
        return task

    async def noop(*args, **kwargs):
        return 0

    def noop_sync(*args, **kwargs):
        return 0

    async def exc(*args, **kwargs):
        raise ScriptWorkerException("foo")

    context.queue = successful_queue
    mocker.patch.object(worker, "find_task", new=find_task)
    mocker.patch.object(worker, "reclaim_task", new=noop)
    if func_to_raise == "run_task":
        mocker.patch.object(worker, "run_task", new=exc)
    else:
        mocker.patch.object(worker, "run_task", new=noop)
    mocker.patch.object(worker, "generate_cot", new=noop_sync)
    if func_to_raise == "upload_artifacts":
        mocker.patch.object(worker, "upload_artifacts", new=exc)
    else:
        mocker.patch.object(worker, "upload_artifacts", new=noop)
    mocker.patch.object(worker, "complete_task", new=noop)
    mocker.patch.object(worker, "read_worker_creds", new=noop_sync)
    status = event_loop.run_until_complete(worker.run_loop(context))
    assert status == ScriptWorkerException.exit_code
