#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.task
"""
import arrow
import asyncio
import glob
import mock
import os
import pytest
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerRetryException
import scriptworker.task as task
import scriptworker.log as log
import sys
import taskcluster.exceptions
import taskcluster.async
import time
from . import fake_session, fake_session_500, successful_queue, unsuccessful_queue, read

assert fake_session, fake_session_500  # silence flake8
assert successful_queue, unsuccessful_queue  # silence flake8

# constants helpers and fixtures {{{1
TIMEOUT_SCRIPT = os.path.join(os.path.dirname(__file__), "data", "long_running.py")


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
        'reclaim_interval': 0.001,
        'task_script': ('bash', '-c', '>&2 echo bar && echo foo && exit 1'),
        'task_max_timeout': .1,
    }
    context.claim_task = {
        'credentials': {'a': 'b'},
        'status': {'taskId': 'taskId'},
        'task': {'task_defn': True},
        'runId': 'runId',
    }
    return context

mimetypes = {
    "/foo/bar/test.txt": "text/plain",
    "/tmp/blah.tgz": "application/x-tar",
    "~/Firefox.dmg": "application/x-apple-diskimage",
}


# tests {{{1
def test_temp_queue(context, mocker):
    context.temp_credentials = {'a': 'b'}
    context.session = {'c': 'd'}
    mocker.patch('taskcluster.async.Queue')
    task.get_temp_queue(context)
    assert taskcluster.async.Queue.called_once_with({
        'credentials': context.temp_credentials,
    }, session=context.session)


def test_expiration_arrow(context):
    now = arrow.utcnow()

    # make sure time differences don't screw up the test
    with mock.patch.object(arrow, 'utcnow') as p:
        p.return_value = now
        expiration = task.get_expiration_arrow(context)
        diff = expiration.timestamp - now.timestamp
        assert diff == 3600


@pytest.mark.parametrize("mimetypes", [(k, v) for k, v in sorted(mimetypes.items())])
def test_guess_content_type(mimetypes):
    path, mimetype = mimetypes
    assert task.guess_content_type(path) == mimetype


@pytest.mark.asyncio
async def test_run_task(context):
    status = await task.run_task(context)
    log_file, error_file = log.get_log_filenames(context)
    assert read(log_file) in ("bar\nfoo\nexit code: 1\n", "foo\nbar\nexit code: 1\n")
    assert read(error_file) == "bar\n"
    assert status == 1


@pytest.mark.asyncio
async def test_reportCompleted(context, successful_queue):
    with mock.patch('scriptworker.task.get_temp_queue') as p:
        p.return_value = successful_queue
        await task.complete_task(context, 0)
    assert successful_queue.info == ["reportCompleted", ('taskId', 'runId'), {}]


@pytest.mark.asyncio
async def test_reportFailed(context, successful_queue):
    with mock.patch('scriptworker.task.get_temp_queue') as p:
        p.return_value = successful_queue
        await task.complete_task(context, 1)
    assert successful_queue.info == ["reportFailed", ('taskId', 'runId'), {}]


@pytest.mark.asyncio
async def test_reportException(context, successful_queue):
    with mock.patch('scriptworker.task.get_temp_queue') as p:
        p.return_value = successful_queue
        await task.complete_task(context, 2)
    assert successful_queue.info == ["reportException", ('taskId', 'runId', {'reason': 'worker-shutdown'}), {}]


@pytest.mark.asyncio
async def test_complete_task_409(context, unsuccessful_queue):
    with mock.patch('scriptworker.task.get_temp_queue') as p:
        p.return_value = unsuccessful_queue
        await task.complete_task(context, 0)


@pytest.mark.asyncio
async def test_complete_task_non_409(context, unsuccessful_queue):
    unsuccessful_queue.status = 500
    with pytest.raises(taskcluster.exceptions.TaskclusterRestFailure):
        with mock.patch('scriptworker.task.get_temp_queue') as p:
            p.return_value = unsuccessful_queue
            await task.complete_task(context, 0)


@pytest.mark.asyncio
async def test_reclaim_task(context, successful_queue):
    with mock.patch('scriptworker.task.get_temp_queue') as p:
        p.return_value = successful_queue
        await task.reclaim_task(context)


@pytest.mark.asyncio
async def test_reclaim_task_non_409(context, successful_queue):
    successful_queue.status = 500
    with pytest.raises(taskcluster.exceptions.TaskclusterRestFailure):
        with mock.patch('scriptworker.task.get_temp_queue') as p:
            p.return_value = successful_queue
            await task.reclaim_task(context)


@pytest.mark.asyncio
async def test_upload_artifacts(context):
    args = []
    os.makedirs(context.config['artifact_dir'])
    os.makedirs(context.config['log_dir'])
    paths = list(log.get_log_filenames(context)) + [
        os.path.join(context.config['artifact_dir'], 'one'),
        os.path.join(context.config['artifact_dir'], 'two'),
    ]
    for path in paths:
        touch(path)

    async def foo(_, path, **kwargs):
        args.append(path)

    with mock.patch('scriptworker.task.create_artifact', new=foo):
        await task.upload_artifacts(context)

    assert sorted(args) == sorted(paths)


@pytest.mark.asyncio
async def test_create_artifact(context, fake_session, successful_queue):
    path = os.path.join(context.config['artifact_dir'], "one.txt")
    os.makedirs(context.config['artifact_dir'])
    touch(path)
    context.session = fake_session
    expires = arrow.utcnow().isoformat()
    with mock.patch('scriptworker.task.get_temp_queue') as p:
        p.return_value = successful_queue
        await task.create_artifact(context, path, expires=expires)
    assert successful_queue.info == [
        "createArtifact", ('taskId', 'runId', "public/env/one.txt", {
            "storageType": "s3",
            "expires": expires,
            "contentType": "text/plain",
        }), {}
    ]
    context.session.close()


@pytest.mark.asyncio
async def test_create_artifact_retry(context, fake_session_500, successful_queue):
    path = os.path.join(context.config['artifact_dir'], "one.log")
    os.makedirs(context.config['artifact_dir'])
    touch(path)
    context.session = fake_session_500
    expires = arrow.utcnow().isoformat()
    with pytest.raises(ScriptWorkerRetryException):
        with mock.patch('scriptworker.task.get_temp_queue') as p:
            p.return_value = successful_queue
            await task.create_artifact(context, path, expires=expires)
    context.session.close()


def test_max_timeout_noop(context):
    with mock.patch.object(task.log, 'debug') as p:
        task.max_timeout(context, "invalid_proc", 0)
        assert not p.called


def test_max_timeout(context, event_loop):
    temp_dir = os.path.join(context.config['work_dir'], "timeout")
    context.config['task_script'] = (
        sys.executable, TIMEOUT_SCRIPT, temp_dir
    )
    context.config['task_max_timeout'] = 3
    event_loop.run_until_complete(task.run_task(context))
    try:
        event_loop.run_until_complete(asyncio.sleep(10))  # Let kill() calls run
    except RuntimeError:
        pass
    files = {}
    for path in glob.glob(os.path.join(temp_dir, '*')):
        files[path] = (time.ctime(os.path.getmtime(path)), os.stat(path).st_size)
        print("{} {}".format(path, files[path]))
    for path in glob.glob(os.path.join(temp_dir, '*')):
        print("Checking {}...".format(path))
        assert files[path] == (time.ctime(os.path.getmtime(path)), os.stat(path).st_size)
    assert len(files.keys()) == 6
