#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.task
"""
import datetime
import mock
import os
import pytest
from scriptworker.context import Context
import scriptworker.task as task
# from . import successful_queue, unsuccessful_queue
import taskcluster.async


@pytest.fixture(scope='function')
def context(tmpdir_factory):
    temp_dir = tmpdir_factory.mktemp("context", numbered=True)
    context = Context()
    context.config = {
        'log_dir': os.path.join(str(temp_dir), "log"),
        'artifact_dir': os.path.join(str(temp_dir), "artifact"),
        'work_dir': os.path.join(str(temp_dir), "work"),
        'artifact_upload_timeout': 200,
        'artifact_expiration_hours': 1,
        'reclaim_interval': .1,
        'task_script': ('bash', '-c', 'echo foo && 2>& echo bar && exit 2'),
    }
    return context


class TestTask(object):
    def test_temp_queue(self, context, mocker):
        context.temp_credentials = {'a': 'b'}
        context.session = {'c': 'd'}
        mocker.patch('taskcluster.async.Queue')
        task.get_temp_queue(context)
        assert taskcluster.async.Queue.called_once_with({
            'credentials': context.temp_credentials,
        }, session=context.session)

    def test_expiration_datetime(self, context):
        now = datetime.datetime.utcnow()

        def utcnow():
            return now

        # make sure time differences don't screw up the test
        # for some reason pytest-mock isn't working for me here
        with mock.patch.object(datetime, 'datetime') as p:
            p.utcnow = utcnow
            expiration = task.get_expiration_datetime(context)
            diff = expiration.timestamp() - now.timestamp()
            assert diff == 3600
