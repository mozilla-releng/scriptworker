#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.worker
"""
from copy import deepcopy
import mock
import os
import pytest
from scriptworker.config import DEFAULT_CONFIG, create_config
from scriptworker.context import Context
import scriptworker.worker as worker
from . import fake_session, successful_queue, unsuccessful_queue

assert (fake_session, successful_queue, unsuccessful_queue)  # silence flake8


@pytest.fixture(scope='function')
def context(tmpdir_factory):
    temp_dir = tmpdir_factory.mktemp("context", numbered=True)
    context = Context()
    context.config = deepcopy(DEFAULT_CONFIG)
    context.config['log_dir'] = os.path.join(str(temp_dir), "log")
    context.config['work_dir'] = os.path.join(str(temp_dir), "work")
    context.config['artifact_dir'] = os.path.join(str(temp_dir), "artifact")
    return context


class TestWorker(object):
    def test_too_many_args(self):
        with pytest.raises(SystemExit):
            with mock.patch('sys.argv', new=[1, 2, 3, 4]):
                worker.main()

    def test_bad_json(self):
        path = os.path.join(os.path.dirname(__file__), "data", "bad.json")
        with pytest.raises(SystemExit):
            with mock.patch('sys.argv', new=[__file__, path]):
                worker.main()

    def test_main(self, mocker):
        path = os.path.join(os.path.dirname(__file__), "data", "good.json")
        config = create_config(path)

        def foo(arg):
            assert arg.config == config
        mocker.patch('sys.argv', new=[__file__, path])
        mocker.patch('asyncio.get_event_loop')
        mocker.patch('scriptworker.worker.async_main', new=foo)
        worker.main()
