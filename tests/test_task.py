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
import scriptworker.log as log
import taskcluster.exceptions
import taskcluster.async
from . import fake_session, successful_queue, unsuccessful_queue, read

assert (fake_session, successful_queue, unsuccessful_queue)  # silence flake8


def touch(path):
    with open(path, "w") as fh:
        print(path, file=fh, end="")


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
        'task_script': ('bash', '-c', '>&2 echo bar && echo foo && exit 2'),
    }
    context.task = {
        'credentials': {'a': 'b'},
        'status': {'taskId': 'taskId'},
        'runId': 'runId',
    }
    return context

mimetypes = {
    "/foo/bar/test.log": "text/plain",
    "/tmp/blah.tgz": "application/x-tar",
    "~/Firefox.dmg": "application/x-apple-diskimage",
}


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
        with mock.patch.object(datetime, 'datetime') as p:
            p.utcnow = utcnow
            expiration = task.get_expiration_datetime(context)
            diff = expiration.timestamp() - now.timestamp()
            assert diff == 3600

    @pytest.mark.parametrize("mimetypes", [(k, v) for k, v in sorted(mimetypes.items())])
    def test_guess_content_type(self, mimetypes):
        path, mimetype = mimetypes
        assert task.guess_content_type(path) == mimetype

    @pytest.mark.asyncio
    async def test_run_task(self, context):
        status = await task.run_task(context)
        log_file, error_file = log.get_log_filenames(context)
        assert read(log_file) in ("ERROR bar\nfoo\nexit code: 2\n", "foo\nERROR bar\nexit code: 2\n")
        assert read(error_file) == "bar\n"
        assert status == 2

    def test_schedule_reclaim_task(self, event_loop):
        task.schedule_reclaim_task(None)

    @pytest.mark.asyncio
    async def test_reportCompleted(self, context, successful_queue):
        with mock.patch('scriptworker.task.get_temp_queue') as p:
            p.return_value = successful_queue
            await task.complete_task(context, 0)
        assert successful_queue.info == ["reportCompleted", ('taskId', 'runId'), {}]

    @pytest.mark.asyncio
    async def test_reportFailed(self, context, successful_queue):
        with mock.patch('scriptworker.task.get_temp_queue') as p:
            p.return_value = successful_queue
            await task.complete_task(context, 1)
        assert successful_queue.info == ["reportFailed", ('taskId', 'runId'), {}]

    @pytest.mark.asyncio
    async def test_complete_task_409(self, context, unsuccessful_queue):
        with mock.patch('scriptworker.task.get_temp_queue') as p:
            p.return_value = unsuccessful_queue
            await task.complete_task(context, 0)

    @pytest.mark.asyncio
    async def test_complete_task_non_409(self, context, unsuccessful_queue):
        unsuccessful_queue.status = 500
        with pytest.raises(taskcluster.exceptions.TaskclusterRestFailure):
            with mock.patch('scriptworker.task.get_temp_queue') as p:
                p.return_value = unsuccessful_queue
                await task.complete_task(context, 0)

    @pytest.mark.asyncio
    async def test_reclaim_task(self, context, successful_queue):
        with mock.patch('scriptworker.task.get_temp_queue') as p:
            p.return_value = successful_queue
            await task.reclaim_task(context)

    @pytest.mark.asyncio
    async def test_reclaim_task_non_409(self, context, successful_queue):
        successful_queue.status = 500
        with pytest.raises(taskcluster.exceptions.TaskclusterRestFailure):
            with mock.patch('scriptworker.task.get_temp_queue') as p:
                p.return_value = successful_queue
                await task.reclaim_task(context)

    @pytest.mark.asyncio
    async def test_upload_artifacts(self, context):
        args = []
        os.makedirs(context.config['artifact_dir'])
        os.makedirs(context.config['log_dir'])
        paths = list(log.get_log_filenames(context)) + [
            os.path.join(context.config['artifact_dir'], 'one'),
            os.path.join(context.config['artifact_dir'], 'two'),
        ]
        for path in paths:
            touch(path)

        async def foo(_, path):
            args.append(path)

        with mock.patch('scriptworker.task.create_artifact', new=foo):
            await task.upload_artifacts(context)

        assert sorted(args) == sorted(paths)

    @pytest.mark.asyncio
    async def test_create_artifact(self, context, fake_session, successful_queue):
        path = os.path.join(context.config['artifact_dir'], "one.log")
        os.makedirs(context.config['artifact_dir'])
        touch(path)
        context.session = fake_session
        expires = datetime.datetime.utcnow()
        with mock.patch('scriptworker.task.get_temp_queue') as p:
            p.return_value = successful_queue
            await task.create_artifact(context, path, expires=expires)
        assert successful_queue.info == [
            "createArtifact", ('taskId', 'runId', "one.log", {
                "storageType": "s3",
                "expires": expires,
                "contentType": "text/plain",
            }), {}
        ]
