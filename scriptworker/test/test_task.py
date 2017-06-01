#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.task
"""
import aiohttp
import asyncio
import glob
import mock
import os
import pprint
import pytest
import scriptworker.task as task
import scriptworker.log as log
import sys
import taskcluster.exceptions
import taskcluster.async
import time
from . import event_loop, fake_session, fake_session_500, noop_async, rw_context, \
    successful_queue, unsuccessful_queue, read

assert event_loop, rw_context  # silence flake8
assert fake_session, fake_session_500  # silence flake8
assert successful_queue, unsuccessful_queue  # silence flake8

# constants helpers and fixtures {{{1
TIMEOUT_SCRIPT = os.path.join(os.path.dirname(__file__), "data", "long_running.py")


@pytest.yield_fixture(scope='function')
def context(rw_context):
    rw_context.config['artifact_expiration_hours'] = 1
    rw_context.config['reclaim_interval'] = 0.001
    rw_context.config['task_max_timeout'] = .1
    rw_context.config['task_script'] = ('bash', '-c', '>&2 echo bar && echo foo && exit 1')
    rw_context.claim_task = {
        'credentials': {'a': 'b'},
        'status': {'taskId': 'taskId'},
        'task': {'dependencies': ['dependency1', 'dependency2'], 'taskGroupId': 'dependency0'},
        'runId': 'runId',
    }
    yield rw_context


# worst_level {{{1
@pytest.mark.parametrize("one,two,expected", ((1, 2, 2), (4, 2, 4)))
def test_worst_level(one, two, expected):
    assert task.worst_level(one, two) == expected


# get_decision_task_id {{{1
@pytest.mark.parametrize("defn,result", (({"taskGroupId": "one"}, "one"), ({"taskGroupId": "two"}, "two")))
def test_get_decision_task_id(defn, result):
    assert task.get_decision_task_id(defn) == result


# get_worker_type {{{1
@pytest.mark.parametrize("defn,result", (({"workerType": "one"}, "one"), ({"workerType": "two"}, "two")))
def test_get_worker_type(defn, result):
    assert task.get_worker_type(defn) == result


# run_task {{{1
def test_run_task(context, event_loop):
    status = event_loop.run_until_complete(
        task.run_task(context)
    )
    log_file = log.get_log_filename(context)
    assert read(log_file) in ("bar\nfoo\nexit code: 1\n", "foo\nbar\nexit code: 1\n")
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


@pytest.mark.asyncio
async def test_reclaim_task_mock(context, mocker, event_loop):

    async def fake_reclaim(*args, **kwargs):
        return {'credentials': context.credentials}

    def die(*args):
        raise taskcluster.exceptions.TaskclusterRestFailure("foo", None, status_code=409)

    context.temp_queue = mock.MagicMock()
    context.temp_queue.reclaimTask = fake_reclaim
    mocker.patch.object(pprint, 'pformat', new=die)
    await task.reclaim_task(context, context.task)


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


# claim_work {{{1
@pytest.mark.asyncio
@pytest.mark.parametrize("raises", (True, False))
async def test_claim_work(event_loop, raises, context):
    context.queue = mock.MagicMock()
    if raises:
        async def foo(*args):
            raise taskcluster.exceptions.TaskclusterRestFailure("foo", None, status_code=4)

        context.queue.claimWork = foo
    else:
        context.queue.claimWork = noop_async
    assert await task.claim_work(context) is None
