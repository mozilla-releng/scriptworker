#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.task
"""
import aiohttp
import arrow
import asyncio
import glob
import json
import mock
import os
import pprint
import pytest
from scriptworker.exceptions import ScriptWorkerTaskException
import scriptworker.task as swtask
import scriptworker.log as log
import sys
import taskcluster.exceptions
import time
from . import fake_session, fake_session_500, noop_async, rw_context, \
    successful_queue, unsuccessful_queue, read, TIMEOUT_SCRIPT

assert rw_context  # silence flake8
assert fake_session, fake_session_500  # silence flake8
assert successful_queue, unsuccessful_queue  # silence flake8


# constants helpers and fixtures {{{1
@pytest.yield_fixture(scope='function')
def context(rw_context):
    rw_context.config['reclaim_interval'] = 0.001
    rw_context.config['task_max_timeout'] = 1
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
    task = {
        'payload': {'env': {}}
    }
    if message is not None:
        task['payload']['env']['GECKO_COMMIT_MSG'] = message
    assert swtask.get_commit_message(task) == expected


# get_decision_task_id {{{1
@pytest.mark.parametrize("task,result", ((
    {"taskGroupId": "one", "payload": {}}, "one"
), (
    {"taskGroupId": "two", "payload": {}}, "two"
), (
    {
        "taskGroupId": "three",
        "payload": {},
        "extra": {
            "action": {},
            "parent": "two"
        }
    },
    "three"
)))
def test_get_decision_task_id(task, result):
    assert swtask.get_decision_task_id(task) == result


# get_parent_task_id {{{1
@pytest.mark.parametrize("set_parent", (True, False))
def test_get_parent_task_id(set_parent):
    task = {'taskGroupId': 'parent_task_id', 'extra': {}, 'payload': {}}
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
    task = {
        'payload': {'env': {}}
    }
    if repo:
        task['payload']['env']['GECKO_HEAD_REPOSITORY'] = repo
        assert swtask.get_repo(task, 'GECKO') == 'https://hg.mozilla.org/mozilla-central'
    else:
        assert swtask.get_repo(task, 'GECKO') is None


# get_revision {{{1
@pytest.mark.parametrize("rev", (None, "revision!"))
def test_get_revision(rev):
    task = {
        'payload': {'env': {}}
    }
    if rev:
        task['payload']['env']['GECKO_HEAD_REV'] = rev
    assert swtask.get_revision(task, 'GECKO') == rev


# get_worker_type {{{1
@pytest.mark.parametrize("task,result", (({"workerType": "one"}, "one"), ({"workerType": "two"}, "two")))
def test_get_worker_type(task, result):
    assert swtask.get_worker_type(task) == result


# get_and_check_project {{{1
@pytest.mark.parametrize("source_url,expected,raises", ((
    "https://hg.mozilla.org/mozilla-central", "mozilla-central", False
), (
    "ssh://hg.mozilla.org/projects/foo", "foo", False
), (
    "ssh://hg.mozilla.org/releases/mozilla-esr60", "mozilla-esr60", False
), (
    "https://hg.mozilla.org/try", "try", False
), (
    "https://hg.mozilla.org/releases/unknown", "", True
)))
def test_get_and_check_project(context, source_url, expected, raises):
    if raises:
        with pytest.raises(ValueError):
            swtask.get_and_check_project(context.config['valid_vcs_rules'], source_url)
    else:
        assert expected == \
            swtask.get_and_check_project(context.config['valid_vcs_rules'], source_url)


# get_and_check_tasks_for {{{1
@pytest.mark.parametrize("tasks_for,raises", ((
    "hg-push", False,
), (
    "cron", False,
), (
    "action", False,
), (
    "foobar", True,
)))
def test_get_and_check_tasks_for(tasks_for, raises):
    task = {
        "extra": {
            "tasks_for": tasks_for
        },
    }
    if raises:
        with pytest.raises(ValueError):
            swtask.get_and_check_tasks_for(task)
    else:
        assert swtask.get_and_check_tasks_for(task) == tasks_for


# get_repo_scope {{{1
@pytest.mark.parametrize("scopes,expected,raises", ((
    [], None, False
), (
    ['assume:repo:foo:action:bar'], 'assume:repo:foo:action:bar', False
), (
    ['foo', 'assume:repo:foo:action:bar'], 'assume:repo:foo:action:bar', False
), (
    ['assume:repo:bar:action:baz', 'assume:repo:foo:action:bar'], None, True
)))
def test_get_repo_scope(scopes, expected, raises):
    task = {"scopes": scopes}
    if raises:
        with pytest.raises(ValueError):
            swtask.get_repo_scope(task, "x")
    else:
        if expected is None:
            assert swtask.get_repo_scope(task, "x") is None
        else:
            assert swtask.get_repo_scope(task, "x") == expected


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


@pytest.mark.asyncio
async def test_run_task_timeout(context):
    """`run_task` raises `ScriptWorkerTaskException` and kills the process
    after exceeding `task_max_timeout`.
    """
    temp_dir = os.path.join(context.config['work_dir'], "timeout")
    context.config['task_script'] = (
        sys.executable, TIMEOUT_SCRIPT, temp_dir
    )
    # With shorter timeouts we hit issues with the script not managing to
    # create all 6 files
    context.config['task_max_timeout'] = 5

    pre = arrow.utcnow().timestamp
    with pytest.raises(ScriptWorkerTaskException):
        await swtask.run_task(context)
    post = arrow.utcnow().timestamp
    # I don't love these checks, because timing issues may cause this test
    # to be flaky. However, I don't want a non- or long- running test to pass.
    # Did this run at all?
    assert post - pre >= 5
    # Did this run too long? e.g. did it exit on its own rather than killed
    # If this is set too low (too close to the timeout), it may not be enough
    # time for kill_proc, kill_pid, and the `finally` block to run
    assert post - pre < 10
    # Did the script generate the expected output?
    files = {}
    for path in glob.glob(os.path.join(temp_dir, '*')):
        files[path] = (time.ctime(os.path.getmtime(path)), os.stat(path).st_size)
        print("{} {}".format(path, files[path]))
    for path in glob.glob(os.path.join(temp_dir, '*')):
        print("Checking {}...".format(path))
        assert files[path] == (time.ctime(os.path.getmtime(path)), os.stat(path).st_size)
    assert len(list(files.keys())) == 6
    # Did we clean up?
    assert context.proc is None


# report* {{{1
@pytest.mark.asyncio
async def test_reportCompleted(context, successful_queue):
    context.temp_queue = successful_queue
    await swtask.complete_task(context, 0)
    assert successful_queue.info == ["reportCompleted", ('taskId', 'runId'), {}]


@pytest.mark.asyncio
async def test_reportFailed(context, successful_queue):
    context.temp_queue = successful_queue
    await swtask.complete_task(context, 1)
    assert successful_queue.info == ["reportFailed", ('taskId', 'runId'), {}]


@pytest.mark.asyncio
async def test_reportException(context, successful_queue):
    context.temp_queue = successful_queue
    await swtask.complete_task(context, 2)
    assert successful_queue.info == ["reportException", ('taskId', 'runId', {'reason': 'worker-shutdown'}), {}]


# complete_task {{{1
@pytest.mark.asyncio
async def test_complete_task_409(context, unsuccessful_queue):
    context.temp_queue = unsuccessful_queue
    await swtask.complete_task(context, 0)


@pytest.mark.asyncio
async def test_complete_task_non_409(context, unsuccessful_queue):
    unsuccessful_queue.status = 500
    context.temp_queue = unsuccessful_queue
    with pytest.raises(taskcluster.exceptions.TaskclusterRestFailure):
        await swtask.complete_task(context, 0)


# reclaim_task {{{1
@pytest.mark.asyncio
async def test_reclaim_task(context, successful_queue):
    context.temp_queue = successful_queue
    await swtask.reclaim_task(context, context.task)


@pytest.mark.asyncio
async def test_skip_reclaim_task(context, successful_queue):
    context.temp_queue = successful_queue
    await swtask.reclaim_task(context, {"unrelated": "task"})


@pytest.mark.asyncio
async def test_reclaim_task_non_409(context, successful_queue):
    successful_queue.status = 500
    context.temp_queue = successful_queue
    with pytest.raises(taskcluster.exceptions.TaskclusterRestFailure):
        await swtask.reclaim_task(context, context.task)


@pytest.mark.parametrize("proc", (None, 1))
@pytest.mark.asyncio
async def test_reclaim_task_mock(context, mocker, proc):
    """When `queue.reclaim_task` raises an error with status 409, `reclaim_task`
    returns. If there is a running process, `reclaim_task` tries to kill it
    before returning.

    Run a good queue.reclaim_task first, so we get full test coverage.

    """
    kill_count = []
    reclaim_count = []
    temp_queue = mock.MagicMock()

    def die(*args):
        raise taskcluster.exceptions.TaskclusterRestFailure("foo", None, status_code=409)

    async def fake_reclaim(*args, **kwargs):
        if reclaim_count:
            die()
        reclaim_count.append([args, kwargs])
        return {'credentials': {'foo': 'bar'}}

    async def fake_kill_proc(*args):
        kill_count.append(args)

    def fake_create_queue(*args):
        return temp_queue

    context.proc = proc
    context.create_queue = fake_create_queue
    temp_queue.reclaimTask = fake_reclaim
    context.temp_queue = temp_queue
    mocker.patch.object(swtask, 'kill_proc', new=fake_kill_proc)
    await swtask.reclaim_task(context, context.task)
    if proc:
        assert len(kill_count) == 1
    else:
        assert len(kill_count) == 0


# kill_proc {{{1
@pytest.mark.asyncio
async def test_kill_proc_no_pid(mocker):
    """If the pid doesn't exist, `kill_proc` returns."""

    async def die_async(*args):
        assert -1, "We haven't returned due to ProcessLookupError!"

    def fake_terminate():
        raise ProcessLookupError("Fake pid doesn't exist")

    mocker.patch.object(swtask, 'kill_pid', new=die_async)
    proc = mock.MagicMock()
    proc.terminate = fake_terminate
    await swtask.kill_proc(proc, "testing", -1)


# claim_work {{{1
@pytest.mark.asyncio
@pytest.mark.parametrize("raises", (True, False))
async def test_claim_work(raises, context):
    context.queue = mock.MagicMock()
    if raises:
        async def foo(*args):
            raise taskcluster.exceptions.TaskclusterRestFailure("foo", None, status_code=4)

        context.queue.claimWork = foo
    else:
        context.queue.claimWork = noop_async
    assert await swtask.claim_work(context) is None
