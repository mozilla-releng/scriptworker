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
from . import event_loop, fake_session, fake_session_500, successful_queue, \
    tmpdir, touch, unsuccessful_queue, read

assert event_loop, tmpdir  # silence flake8
assert fake_session, fake_session_500  # silence flake8
assert successful_queue, unsuccessful_queue  # silence flake8

# constants helpers and fixtures {{{1
TIMEOUT_SCRIPT = os.path.join(os.path.dirname(__file__), "data", "long_running.py")


@pytest.fixture(scope='function')
def context(tmpdir):
    context = Context()
    context.config = {
        'log_dir': os.path.join(tmpdir, "log"),
        'artifact_dir': os.path.join(tmpdir, "artifact"),
        'task_log_dir': os.path.join(tmpdir, "artifact", "public", "logs"),
        'work_dir': os.path.join(tmpdir, "work"),
        'artifact_upload_timeout': 200,
        'artifact_expiration_hours': 1,
        'reclaim_interval': 0.001,
        'task_script': ('bash', '-c', '>&2 echo bar && echo foo && exit 1'),
        'task_max_timeout': .1,
    }
    context.claim_task = {
        'credentials': {'a': 'b'},
        'status': {'taskId': 'taskId'},
        'task': {'dependencies': ['dependency1', 'dependency2'], 'taskGroupId': 'dependency0'},
        'runId': 'runId',
    }
    return context

mimetypes = {
    "/foo/bar/test.txt": "text/plain",
    "/tmp/blah.tgz": "application/x-tar",
    "~/Firefox.dmg": "application/x-apple-diskimage",
    "/foo/bar/blah.log": "text/plain",
    "/totally/unknown": "application/binary",
}


# worst_level {{{1
@pytest.mark.parametrize("one,two,expected", ((1, 2, 2), (4, 2, 4)))
def test_worst_level(one, two, expected):
    assert task.worst_level(one, two) == expected


# get_expiration_arrow {{{1
def test_expiration_arrow(context):
    now = arrow.utcnow()

    # make sure time differences don't screw up the test
    with mock.patch.object(arrow, 'utcnow') as p:
        p.return_value = now
        expiration = task.get_expiration_arrow(context)
        diff = expiration.timestamp - now.timestamp
        assert diff == 3600


# guess_content_type {{{1
@pytest.mark.parametrize("mimetypes", [(k, v) for k, v in sorted(mimetypes.items())])
def test_guess_content_type(mimetypes):
    path, mimetype = mimetypes
    assert task.guess_content_type(path) == mimetype


# run_task {{{1
def test_run_task(context, event_loop):
    status = event_loop.run_until_complete(
        task.run_task(context)
    )
    log_file, error_file = log.get_log_filenames(context)
    assert read(log_file) in ("bar\nfoo\nexit code: 1\n", "foo\nbar\nexit code: 1\n")
    assert read(error_file) == "bar\n"
    assert status == 1


# report* {{{1
def test_reportCompleted(context, successful_queue, event_loop):
    context.temp_queue = successful_queue
    event_loop.run_until_complete(
        task.complete_task(context, 0)
    )
    assert successful_queue.info == ["reportCompleted", ('taskId', 'runId'), {}]


def test_reportFailed(context, successful_queue, event_loop):
    context.temp_queue = successful_queue
    event_loop.run_until_complete(
        task.complete_task(context, 1)
    )
    assert successful_queue.info == ["reportFailed", ('taskId', 'runId'), {}]


def test_reportException(context, successful_queue, event_loop):
    context.temp_queue = successful_queue
    event_loop.run_until_complete(
        task.complete_task(context, 2)
    )
    assert successful_queue.info == ["reportException", ('taskId', 'runId', {'reason': 'worker-shutdown'}), {}]


# complete_task {{{1
def test_complete_task_409(context, unsuccessful_queue, event_loop):
    context.temp_queue = unsuccessful_queue
    event_loop.run_until_complete(
        task.complete_task(context, 0)
    )


def test_complete_task_non_409(context, unsuccessful_queue, event_loop):
    unsuccessful_queue.status = 500
    context.temp_queue = unsuccessful_queue
    with pytest.raises(taskcluster.exceptions.TaskclusterRestFailure):
        event_loop.run_until_complete(
            task.complete_task(context, 0)
        )


# reclaim_task {{{1
def test_reclaim_task(context, successful_queue, event_loop):
    context.temp_queue = successful_queue
    event_loop.run_until_complete(
        task.reclaim_task(context, context.task)
    )


def test_skip_reclaim_task(context, successful_queue, event_loop):
    context.temp_queue = successful_queue
    event_loop.run_until_complete(
        task.reclaim_task(context, {"unrelated": "task"})
    )


def test_reclaim_task_non_409(context, successful_queue, event_loop):
    successful_queue.status = 500
    context.temp_queue = successful_queue
    with pytest.raises(taskcluster.exceptions.TaskclusterRestFailure):
        event_loop.run_until_complete(
            task.reclaim_task(context, context.task)
        )


# upload_artifacts {{{1
def test_upload_artifacts(context, event_loop):
    args = []
    os.makedirs(os.path.join(context.config['artifact_dir'], 'public'))
    paths = [
        os.path.join(context.config['artifact_dir'], 'one'),
        os.path.join(context.config['artifact_dir'], 'public/two'),
    ]
    for path in paths:
        touch(path)

    async def foo(_, path, **kwargs):
        args.append(path)

    with mock.patch('scriptworker.task.create_artifact', new=foo):
        event_loop.run_until_complete(
            task.upload_artifacts(context)
        )

    assert sorted(args) == sorted(paths)


# create_artifact {{{1
def test_create_artifact(context, fake_session, successful_queue, event_loop):
    path = os.path.join(context.config['artifact_dir'], "one.txt")
    os.makedirs(context.config['artifact_dir'])
    touch(path)
    context.session = fake_session
    expires = arrow.utcnow().isoformat()
    context.temp_queue = successful_queue
    event_loop.run_until_complete(
        task.create_artifact(context, path, "public/env/one.txt", expires=expires)
    )
    assert successful_queue.info == [
        "createArtifact", ('taskId', 'runId', "public/env/one.txt", {
            "storageType": "s3",
            "expires": expires,
            "contentType": "text/plain",
        }), {}
    ]
    context.session.close()


def test_create_artifact_retry(context, fake_session_500, successful_queue,
                               event_loop):
    path = os.path.join(context.config['artifact_dir'], "one.log")
    os.makedirs(context.config['artifact_dir'])
    touch(path)
    context.session = fake_session_500
    expires = arrow.utcnow().isoformat()
    with pytest.raises(ScriptWorkerRetryException):
        context.temp_queue = successful_queue
        event_loop.run_until_complete(
            task.create_artifact(context, path, "public/env/one.log", expires=expires)
        )
    context.session.close()


# max_timeout {{{1
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


# download_artifacts {{{1
def test_download_artifacts(context, event_loop):
    urls = []
    paths = []

    expected_urls = [
        "https://queue.taskcluster.net/v1/task/dependency1/artifacts/foo/bar",
        "https://queue.taskcluster.net/v1/task/dependency2/artifacts/baz",
    ]
    expected_paths = [
        os.path.join(context.config['work_dir'], "foo", "bar"),
        os.path.join(context.config['work_dir'], "baz"),
    ]
    expected_result = [
        "foo/bar", "baz"
    ]

    async def foo(_, url, path, **kwargs):
        urls.append(url)
        paths.append(path)

    result = event_loop.run_until_complete(
        task.download_artifacts(context, expected_urls, download_func=foo)
    )

    assert sorted(result) == sorted(expected_result)
    assert sorted(paths) == sorted(expected_paths)
    assert sorted(urls) == sorted(expected_urls)
