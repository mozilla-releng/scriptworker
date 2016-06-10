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
from scriptworker.config import DEFAULT_CONFIG, create_config
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerException
import scriptworker.worker as worker
import sys
from . import successful_queue

assert successful_queue  # silence flake8


@pytest.fixture(scope='function')
def context(tmpdir_factory):
    temp_dir = tmpdir_factory.mktemp("context", numbered=True)
    context = Context()
    context.config = deepcopy(DEFAULT_CONFIG)
    context.config['log_dir'] = os.path.join(str(temp_dir), "log")
    context.config['work_dir'] = os.path.join(str(temp_dir), "work")
    context.config['artifact_dir'] = os.path.join(str(temp_dir), "artifact")
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


class TestWorker(object):
    def test_main_too_many_args(self, event_loop):
        with pytest.raises(SystemExit):
            with mock.patch('sys.argv', new=[1, 2, 3, 4]):
                worker.main()

    def test_main_bad_json(self, event_loop):
        path = os.path.join(os.path.dirname(__file__), "data", "bad.json")
        with pytest.raises(SystemExit):
            with mock.patch('sys.argv', new=[__file__, path]):
                worker.main()

    def test_main(self, mocker, event_loop):
        path = os.path.join(os.path.dirname(__file__), "data", "good.json")
        config, creds = create_config(path)
        loop = mock.MagicMock()
        exceptions = [RuntimeError, ScriptWorkerException]

        def run_forever():
            exc = exceptions.pop(0)
            raise exc("foo")

        def foo(arg):
            assert arg.config == config
            assert arg.credentials == creds

        loop.run_forever = run_forever

        mocker.patch.object(sys, 'argv', new=[__file__, path])
        mocker.patch.object(worker, 'async_main', new=foo)
        with mock.patch.object(asyncio, 'get_event_loop') as p:
            p.return_value = loop
            with pytest.raises(ScriptWorkerException):
                worker.main()

    @pytest.mark.asyncio
    async def test_async_main(self, context):

        async def exit(*args, **kwargs):
            sys.exit()

        with mock.patch('scriptworker.worker.run_loop', new=exit):
            with pytest.raises(SystemExit):
                await worker.async_main(context)

    def test_run_loop_exception(self, context, successful_queue, event_loop):
        context.queue = successful_queue

        async def raise_swe(*args, **kwargs):
            raise ScriptWorkerException("foo")

        with mock.patch.object(worker, 'find_task', new=raise_swe):
            status = event_loop.run_until_complete(worker.run_loop(context))

        assert status is None

    def test_mocker_run_loop(self, context, successful_queue, event_loop, mocker):
        task = {"foo": "bar", "credentials": {"a": "b"}, "task": {'task_defn': True}}

        async def find_task(*args, **kwargs):
            return deepcopy(task)

        async def noop(*args, **kwargs):
            return

        context.queue = successful_queue
        mocker.patch.object(worker, "find_task", new=find_task)
        mocker.patch.object(worker, "reclaim_task", new=noop)
        mocker.patch.object(worker, "run_task", new=find_task)
        mocker.patch.object(worker, "upload_artifacts", new=noop)
        mocker.patch.object(worker, "complete_task", new=noop)
        status = event_loop.run_until_complete(worker.run_loop(context))
        assert status == task

    def test_mocker_run_loop_noop(self, context, successful_queue, event_loop, mocker):
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
        mocker.patch.object(worker, "upload_artifacts", new=noop)
        mocker.patch.object(worker, "complete_task", new=noop)
        mocker.patch.object(worker, "read_worker_creds", new=noop_sync)
        status = event_loop.run_until_complete(worker.run_loop(context))
        assert context.credentials is None
        assert status is None

    def test_mocker_run_loop_noop_update_creds(self, context, successful_queue,
                                               event_loop, mocker):
        new_creds = {"new_creds": "true"}

        async def find_task(*args, **kwargs):
            return None

        async def noop(*args, **kwargs):
            return

        def get_creds(*args, **kwargs):
            return deepcopy(new_creds)

        context.queue = successful_queue
        mocker.patch.object(worker, "find_task", new=find_task)
        mocker.patch.object(worker, "reclaim_task", new=noop)
        mocker.patch.object(worker, "run_task", new=find_task)
        mocker.patch.object(worker, "upload_artifacts", new=noop)
        mocker.patch.object(worker, "complete_task", new=noop)
        mocker.patch.object(worker, "read_worker_creds", new=get_creds)
        status = event_loop.run_until_complete(worker.run_loop(context))
        assert context.credentials == new_creds
        assert status is None
