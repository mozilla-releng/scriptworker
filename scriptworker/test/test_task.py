#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.task
"""
import aiohttp
import asyncio
import glob
import json
import mock
import os
import pprint
import pytest
import scriptworker.task as swtask
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
    assert swtask.worst_level(one, two) == expected


# get_action_name {{{1
@pytest.mark.parametrize("name", ("foo", "bar"))
def test_get_action_name(name):
    assert swtask.get_action_name({
        "extra": {
            "action": {
                "name": name
            }
        }
    }) == name


# get_commit_message {{{1
@pytest.mark.parametrize("message,expected", ((
    None, ' '
), (
    "foo bar", "foo bar"
)))
def test_get_commit_message(message, expected):
    task = {'payload': {'env': {}}}
    if message is not None:
        task['payload']['env']['GECKO_COMMIT_MSG'] = message
    assert swtask.get_commit_message(task) == expected


# get_decision_task_id {{{1
@pytest.mark.parametrize("task,result", (({"taskGroupId": "one"}, "one"), ({"taskGroupId": "two"}, "two")))
def test_get_decision_task_id(task, result):
    assert swtask.get_decision_task_id(task) == result


# get_parent_task_id {{{1
@pytest.mark.parametrize("set_parent", (True, False))
def test_get_parent_task_id(set_parent):
    task = {'taskGroupId': 'parent_task_id', 'extra': {}}
    if set_parent:
        task['extra']['parent'] = 'parent_task_id'
    assert swtask.get_parent_task_id(task) == 'parent_task_id'


# get_repo {{{1
@pytest.mark.parametrize("repo", (
    None,
    "https://hg.mozilla.org/mozilla-central",
    "https://hg.mozilla.org/mozilla-central/",
))
def test_get_repo(repo):
    task = {'payload': {'env': {}}}
    if repo:
        task['payload']['env']['GECKO_HEAD_REPOSITORY'] = repo
        assert swtask.get_repo(task, 'GECKO') == 'https://hg.mozilla.org/mozilla-central'
    else:
        assert swtask.get_repo(task, 'GECKO') is None


# get_revision {{{1
@pytest.mark.parametrize("rev", (None, "revision!"))
def test_get_revision(rev):
    task = {'payload': {'env': {}}}
    if rev:
        task['payload']['env']['GECKO_HEAD_REV'] = rev
    assert swtask.get_revision(task, 'GECKO') == rev


# get_worker_type {{{1
@pytest.mark.parametrize("task,result", (({"workerType": "one"}, "one"), ({"workerType": "two"}, "two")))
def test_get_worker_type(task, result):
    assert swtask.get_worker_type(task) == result


# is_try {{{1
@pytest.mark.parametrize("task,source_env_prefix", (
    ({'payload': {'env': {'GECKO_HEAD_REPOSITORY': "https://hg.mozilla.org/try/blahblah"}}, 'metadata': {}, 'schedulerId': "x"}, 'GECKO'),
    ({'payload': {'env': {'GECKO_HEAD_REPOSITORY': "https://hg.mozilla.org/mozilla-central", "MH_BRANCH": "try"}}, 'metadata': {}, "schedulerId": "x"}, 'GECKO'),
    ({'payload': {}, 'metadata': {'source': 'http://hg.mozilla.org/try'}, 'schedulerId': "x"}, 'GECKO'),
    ({'payload': {}, 'metadata': {}, 'schedulerId': "gecko-level-1"}, 'GECKO'),
    ({'payload': {'env': {'GECKO_HEAD_REPOSITORY': "https://hg.mozilla.org/mozilla-central", 'COMM_HEAD_REPOSITORY': "https://hg.mozilla.org/try-comm-central/blahblah"}}, 'metadata': {}, 'schedulerId': "x"}, 'COMM'),
))
def test_is_try(task,source_env_prefix):
    assert swtask.is_try(task, source_env_prefix=source_env_prefix)


# is_action {{{1
@pytest.mark.parametrize("task,expected", ((
    {
        'payload': {
            'env': {
                'ACTION_CALLBACK': 'foo'
            }
        },
        'extra': {
            'action': {
            }
        },
    },
    True
), (
    {
        'payload': {
        },
        'extra': {
            'action': {
            }
        },
    },
    True
), (
    {
        'payload': {
            'env': {
                'ACTION_CALLBACK': 'foo'
            }
        },
    },
    True
), (
    {
        'payload': {
            'env': {
                'GECKO_HEAD_REPOSITORY': "https://hg.mozilla.org/try/blahblah"
            }
        },
        'metadata': {},
        'schedulerId': "x"
    },
    False
)))
def test_is_action(task, expected):
    assert swtask.is_action(task) == expected


# prepare_to_run_task {{{1
def test_prepare_to_run_task(context):
    claim_task = context.claim_task
    context.claim_task = None
    expected = {'taskId': 'taskId', 'runId': 'runId'}
    path = os.path.join(context.config['work_dir'], 'current_task_info.json')
    assert swtask.prepare_to_run_task(context, claim_task) == expected
    assert os.path.exists(path)
    with open(path) as fh:
        contents = json.load(fh)
    assert contents == expected


# run_task {{{1
@pytest.mark.asyncio
async def test_run_task(context):
    status = await swtask.run_task(context)
    log_file = log.get_log_filename(context)
    assert read(log_file) in ("bar\nfoo\nexit code: 1\n", "foo\nbar\nexit code: 1\n")
    assert status == 1


@pytest.mark.asyncio
async def test_run_task_negative_11(context, mocker):
    async def fake_wait():
        return -11

    fake_proc = mock.MagicMock()
    fake_proc.wait = fake_wait

    async def fake_exec(*args, **kwargs):
        return fake_proc

    mocker.patch.object(asyncio, 'create_subprocess_exec', new=fake_exec)

    status = await swtask.run_task(context)
    log_file = log.get_log_filename(context)
    contents = read(log_file)
    assert contents == "Automation Error: python exited with signal -11\n"


# report* {{{1
def test_reportCompleted(context, successful_queue, event_loop):
    context.temp_queue = successful_queue
    event_loop.run_until_complete(
        swtask.complete_task(context, 0)
    )
    assert successful_queue.info == ["reportCompleted", ('taskId', 'runId'), {}]


def test_reportFailed(context, successful_queue, event_loop):
    context.temp_queue = successful_queue
    event_loop.run_until_complete(
        swtask.complete_task(context, 1)
    )
    assert successful_queue.info == ["reportFailed", ('taskId', 'runId'), {}]


def test_reportException(context, successful_queue, event_loop):
    context.temp_queue = successful_queue
    event_loop.run_until_complete(
        swtask.complete_task(context, 2)
    )
    assert successful_queue.info == ["reportException", ('taskId', 'runId', {'reason': 'worker-shutdown'}), {}]


# complete_task {{{1
def test_complete_task_409(context, unsuccessful_queue, event_loop):
    context.temp_queue = unsuccessful_queue
    event_loop.run_until_complete(
        swtask.complete_task(context, 0)
    )


def test_complete_task_non_409(context, unsuccessful_queue, event_loop):
    unsuccessful_queue.status = 500
    context.temp_queue = unsuccessful_queue
    with pytest.raises(taskcluster.exceptions.TaskclusterRestFailure):
        event_loop.run_until_complete(
            swtask.complete_task(context, 0)
        )


# reclaim_task {{{1
def test_reclaim_task(context, successful_queue, event_loop):
    context.temp_queue = successful_queue
    event_loop.run_until_complete(
        swtask.reclaim_task(context, context.task)
    )


def test_skip_reclaim_task(context, successful_queue, event_loop):
    context.temp_queue = successful_queue
    event_loop.run_until_complete(
        swtask.reclaim_task(context, {"unrelated": "task"})
    )


def test_reclaim_task_non_409(context, successful_queue, event_loop):
    successful_queue.status = 500
    context.temp_queue = successful_queue
    with pytest.raises(taskcluster.exceptions.TaskclusterRestFailure):
        event_loop.run_until_complete(
            swtask.reclaim_task(context, context.task)
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
    await swtask.reclaim_task(context, context.task)


# max_timeout {{{1
def test_max_timeout_noop(context):
    with mock.patch.object(swtask.log, 'debug') as p:
        swtask.max_timeout(context, "invalid_proc", 0)
        assert not p.called


def test_max_timeout(context, event_loop):
    temp_dir = os.path.join(context.config['work_dir'], "timeout")
    context.config['task_script'] = (
        sys.executable, TIMEOUT_SCRIPT, temp_dir
    )
    context.config['task_max_timeout'] = 3
    event_loop.run_until_complete(swtask.run_task(context))
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
    assert await swtask.claim_work(context) is None
