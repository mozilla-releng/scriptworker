#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.worker
"""
from copy import deepcopy
import datetime
import mock
import os
import pytest
from scriptworker.config import DEFAULT_CONFIG, create_config
from scriptworker.context import Context
import scriptworker.worker as worker
import sys


@pytest.fixture(scope='function')
def context(tmpdir_factory):
    temp_dir = tmpdir_factory.mktemp("context", numbered=True)
    context = Context()
    context.config = deepcopy(DEFAULT_CONFIG)
    context.config['log_dir'] = os.path.join(str(temp_dir), "log")
    context.config['work_dir'] = os.path.join(str(temp_dir), "work")
    context.config['artifact_dir'] = os.path.join(str(temp_dir), "artifact")
    context.poll_task_urls = {
        'queues': [{
            "signedPollUrl": "poll0",
            "signedDeleteUrl": "delete0",
        }, {
            "signedPollUrl": "poll1",
            "signedDeleteUrl": "delete1",
        }],
        'expires': datetime.datetime.strftime(
            datetime.datetime.utcnow() + datetime.timedelta(hours=10),
            "%Y-%m-%dT%H:%M:%S.123Z"
        ),
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
        config = create_config(path)

        def foo(arg):
            assert arg.config == config
        mocker.patch('sys.argv', new=[__file__, path])
        mocker.patch('asyncio.get_event_loop')
        mocker.patch('scriptworker.worker.async_main', new=foo)
        worker.main()

    @pytest.mark.asyncio
    async def test_async_main(self, context):

        async def exit(*args, **kwargs):
            sys.exit()

        with mock.patch('scriptworker.worker.run_loop', new=exit):
            with pytest.raises(SystemExit):
                await worker.async_main(context)
