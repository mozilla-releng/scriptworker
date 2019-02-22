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
from scriptworker.exceptions import ScriptWorkerTaskException, WorkerShutdownDuringTask
import scriptworker.task as swtask
import scriptworker.log as log
import sys
import taskcluster.exceptions
import time
from unittest.mock import MagicMock

from scriptworker.task_process import TaskProcess
from . import fake_session, fake_session_500, noop_async, rw_context, mobile_rw_context, \
    successful_queue, unsuccessful_queue, read, TIMEOUT_SCRIPT

assert rw_context  # silence flake8
assert fake_session, fake_session_500  # silence flake8
assert successful_queue, unsuccessful_queue  # silence flake8


async def noop_to_cancellable_process(process):
    return process


# constants helpers and fixtures {{{1
@pytest.yield_fixture(scope='function')
def context(rw_context):
    yield _craft_context(rw_context)


@pytest.yield_fixture(scope='function')
def mobile_context(mobile_rw_context):
    yield _craft_context(mobile_rw_context)


def _craft_context(rw_context):
    rw_context.config['reclaim_interval'] = 0.001
    rw_context.config['task_max_timeout'] = 1
    rw_context.config['task_script'] = ('bash', '-c', '>&2 echo bar && echo foo && exit 1')
    rw_context.claim_task = {
        'credentials': {'a': 'b'},
        'status': {'taskId': 'taskId'},
        'task': {'dependencies': ['dependency1', 'dependency2'], 'taskGroupId': 'dependency0'},
        'runId': 'runId',
    }
    return rw_context


# worst_level {{{1
@pytest.mark.parametrize("one,two,expected", ((1, 2, 2), (4, 2, 4)))
def test_worst_level(one, two, expected):
    assert swtask.worst_level(one, two) == expected


# get_action_callback_name {{{1
@pytest.mark.parametrize("name", ("foo", "bar"))
def test_get_action_callback_name(name):
    assert swtask.get_action_callback_name({
        "payload": {
            "env": {
                "ACTION_CALLBACK": name
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


@pytest.mark.parametrize("branch", (None, "some-git-branch"))
def test_get_branch(branch):
    task = {
        'payload': {'env': {}}
    }
    if branch:
        task['payload']['env']['MOBILE_HEAD_BRANCH'] = branch
    assert swtask.get_branch(task, 'MOBILE') == branch


@pytest.mark.parametrize("user", (None, "some-user"))
def test_get_triggered_by(user):
    task = {
        'payload': {'env': {}}
    }
    if user:
        task['payload']['env']['MOBILE_TRIGGERED_BY'] = user
    assert swtask.get_triggered_by(task, 'MOBILE') == user


@pytest.mark.parametrize("pull_request_number", (None, 1))
def test_get_pull_request_number(pull_request_number):
    task = {
        'payload': {'env': {}}
    }
    if pull_request_number:
        task['payload']['env']['MOBILE_PULL_REQUEST_NUMBER'] = str(pull_request_number)
    assert swtask.get_pull_request_number(task, 'MOBILE') == pull_request_number


@pytest.mark.parametrize("push_date_time", (None, '2019-02-01T12:00:00.000Z'))
def test_get_push_date_time(push_date_time):
    task = {
        'payload': {'env': {}}
    }
    if push_date_time:
        task['payload']['env']['MOBILE_PUSH_DATE_TIME'] = push_date_time
    assert swtask.get_push_date_time(task, 'MOBILE') == push_date_time


# get_worker_type {{{1
@pytest.mark.parametrize("task,result", (({"workerType": "one"}, "one"), ({"workerType": "two"}, "two")))
def test_get_worker_type(task, result):
    assert swtask.get_worker_type(task) == result


# get_and_check_project {{{1
@pytest.mark.parametrize("source_url, expected, raises, context_type", ((
    "https://hg.mozilla.org/mozilla-central", "mozilla-central", False, "firefox"
), (
    "ssh://hg.mozilla.org/projects/foo", "foo", False, "firefox"
), (
    "ssh://hg.mozilla.org/releases/mozilla-esr60", "mozilla-esr60", False, "firefox"
), (
    "https://hg.mozilla.org/try", "try", False, "firefox"
), (
    "https://hg.mozilla.org/releases/unknown", "", True, "firefox"
# Mobile
), (
    "https://github.com/mozilla-mobile/android-components", "android-components", False, "mobile",
), (
    "https://github.com/mozilla-mobile/focus-android", "focus-android", False, "mobile",
), (
    "https://github.com/mozilla-mobile/reference-browser", "reference-browser", False, "mobile",
), (
    "https://github.com/mozilla-mobile/unknown-repo", "", True, "mobile",
), (
    "https://github.com/mozilla-mobile/android-components.git", "android-components", False, "mobile",
), (
    "ssh://github.com/mozilla-mobile/android-components", "android-components", False, "mobile",
), (
    "ssh://github.com/mozilla-mobile/android-components.git", "android-components", False, "mobile",
# Allowed staging users
), (
    "https://github.com/JohanLorenzo/reference-browser", "reference-browser", False, "mobile",
), (
    "https://github.com/mitchhentges/reference-browser", "reference-browser", False, "mobile",
), (
    "https://github.com/MihaiTabara/reference-browser", "reference-browser", False, "mobile",
), (
    "https://github.com/UnknownUser/reference-browser", "", True, "mobile",
)))
def test_get_and_check_project(context, mobile_context, source_url, expected, raises, context_type):
    context_ = mobile_context if context_type == 'mobile' else context

    if raises:
        with pytest.raises(ValueError):
            swtask.get_and_check_project(context_.config['valid_vcs_rules'], source_url)
    else:
        assert expected == \
            swtask.get_and_check_project(context_.config['valid_vcs_rules'], source_url)


# get_and_check_tasks_for {{{1
@pytest.mark.parametrize('context_type, tasks_for, raises', ((
    'firefox', 'hg-push', False,
), (
    'firefox', 'cron', False,
), (
    'firefox', 'action', False,
), (
    'mobile', 'hg-push', True,
), (
    'mobile', 'cron', False,    # Mobile does accept cron tasks
), (
    'mobile', 'action', True,
), (
    'firefox', 'github-pull-request', True,
), (
    'firefox', 'github-push', True,
), (
    'firefox', 'github-release', True,
), (
    'mobile', 'github-pull-request', False,
), (
    'mobile', 'github-push', False,
), (
    'mobile', 'github-release', False,
), (
    'firefox', 'foobar', True,
), (
    'mobile', 'foobar', True,
)))
def test_get_and_check_tasks_for(context, mobile_context, context_type, tasks_for, raises):
    context_ = mobile_context if context_type == 'mobile' else context
    task = {
        "extra": {
            "tasks_for": tasks_for
        },
    }
    if raises:
        with pytest.raises(ValueError):
            swtask.get_and_check_tasks_for(context_, task)
    else:
        assert swtask.get_and_check_tasks_for(context_, task) == tasks_for


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


@pytest.mark.parametrize('task, has_commit_landed, raises, expected', ((
    {
        'payload': {},
        'extra': {'env': {'tasks_for': 'github-pull-request'}},
        'metadata': {'source': 'https://github.com/some-user/some-repo/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml'},
    },
    True, False, True,
), (
    {
        'payload': {
            'env': {'MOBILE_HEAD_REPOSITORY': 'https://github.com/some-user/some-repo'}
        },
        'extra': {'env': {'tasks_for': 'github-push'}},
        'metadata': {'source': 'https://github.com/some-user/some-repo/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml'},
    },
    True, False, True,
), (
    {
        'payload': {'env': {'MOBILE_HEAD_REPOSITORY': 'https://github.com/some-user/some-repo.git'}},
        'extra': {'env': {'tasks_for': 'github-release'}},
        'metadata': {'source': 'https://github.com/some-user/some-repo/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml'},
    },
    True, False, True,
), (
    {
        'payload': {},
        'metadata': {'source': 'https://github.com/some-user/some-repo/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml'},
    },
    True, False, True,
), (
    {
        'extra': {
            'env': {
                'tasks_for': 'cron',
            },
        },
        'metadata': {
            'source': 'https://github.com/mozilla-mobile/some-repo/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml',
        },
        'payload': {
            'env': {
                'MOBILE_HEAD_REPOSITORY': 'https://github.com/mozilla-mobile/some-repo',
            },
        },
    },
    True, False, False,
), (
    {'payload': {'env': {'MOBILE_HEAD_REPOSITORY': 'https://github.com/some-user/some-repo.git'}}, 'metadata': {}},
    True, True, None,
), (
    {'extra': {}, 'metadata': {'source': 'https://some-non-github-url.tld',}, 'payload': {},},
    True, True, None,
), (
    {'payload': {}, 'metadata': {'source': 'https://github.com/some-user/some-repo'}},
    True, True, None,
)))
@pytest.mark.asyncio
async def test_is_pull_request(mocker, mobile_context, task, has_commit_landed, raises, expected):
    async def has_commit_landed_on_repository(*args):
        return has_commit_landed

    github_repository_instance_mock = MagicMock()
    github_repository_instance_mock.has_commit_landed_on_repository = has_commit_landed_on_repository
    GitHubRepositoryClassMock = MagicMock()
    GitHubRepositoryClassMock.return_value = github_repository_instance_mock
    mocker.patch.object(swtask, 'GitHubRepository', GitHubRepositoryClassMock)

    if raises:
        with pytest.raises(ValueError):
            await swtask.is_pull_request(mobile_context, task)
    else:
        assert await swtask.is_pull_request(mobile_context, task) == expected


@pytest.mark.parametrize('context_type, is_github_task, is_try, is_pr, expected', (
    ('firefox', True, True, False, False,),
    ('firefox', True, False, False, False,),
    ('firefox', False, False, False, False,),
    ('firefox', False, True, False, True,),

    ('mobile', True, False, True, True,),
    ('mobile', True, False, False, False,),
    ('mobile', False, False, False, False,),
    ('mobile', False, False, True, False,),
))
@pytest.mark.asyncio
async def test_is_try_or_pull_request(mocker, context, mobile_context, context_type, is_github_task, is_try, is_pr, expected):
    context_ = mobile_context if context_type == 'mobile' else context

    async def is_pull_request(*args):
        return is_pr

    mocker.patch.object(swtask, 'is_github_task', lambda *args: is_github_task)
    mocker.patch.object(swtask, 'is_pull_request', is_pull_request)
    mocker.patch.object(swtask, 'is_try', lambda *args: is_try)

    assert await swtask.is_try_or_pull_request(context_, {}) == expected


@pytest.mark.parametrize('task, expected', ((
    {'schedulerId': 'taskcluster-github'}, True,
), (
    {'extra': {'tasks_for': 'github-pull-request'}}, True,
), (
    {'extra': {'tasks_for': 'github-push'}}, True,
), (
    {'extra': {'tasks_for': 'github-release'}}, True,
), (
    {'metadata': {'source': 'https://github.com/some-owner/some-repo'}}, True,
), (
    {'extra': {'tasks_for': 'cron'}, 'metadata': {'source': 'https://github.com/some-owner/some-repo'}}, True,
), (
    {'schedulerId': 'gecko-level-1', 'extra': {'tasks_for': 'hg-push'}, 'metadata': {'source': 'https://hg.mozilla.org/try'}}, False,
), (
    {'schedulerId': 'gecko-level-3', 'extra': {'tasks_for': 'action'}, 'metadata': {'source': 'https://hg.mozilla.org/mozilla-central'}}, False,
)))
def test_is_github_task(task, expected):
    assert swtask.is_github_task(task) == expected


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
    status = await swtask.run_task(context, noop_to_cancellable_process)
    log_file = log.get_log_filename(context)
    assert read(log_file) in ("bar\nfoo\nexit code: 1\n", "foo\nbar\nexit code: 1\n")
    assert status == 1


@pytest.mark.asyncio
async def test_run_task_shutdown(context):
    async def stop_task_process(task_process: TaskProcess):
        await task_process.worker_shutdown_stop()
        return task_process

    with pytest.raises(WorkerShutdownDuringTask):
        await swtask.run_task(context, stop_task_process)


@pytest.mark.asyncio
async def test_run_task_negative_11(context, mocker):
    async def fake_wait():
        return -11

    fake_proc = mock.MagicMock()
    fake_proc.wait = fake_wait

    async def fake_exec(*args, **kwargs):
        return fake_proc

    mocker.patch.object(asyncio, 'create_subprocess_exec', new=fake_exec)

    status = await swtask.run_task(context, noop_to_cancellable_process)
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
        await swtask.run_task(context, noop_to_cancellable_process)
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


@pytest.mark.parametrize("no_proc", (True, False))
@pytest.mark.asyncio
async def test_reclaim_task_mock(context, mocker, no_proc):
    """When `queue.reclaim_task` raises an error with status 409, `reclaim_task`
    returns. If there is a running process, `reclaim_task` tries to kill it
    before returning.

    Run a good queue.reclaim_task first, so we get full test coverage.

    """

    kill_count = 0
    reclaim_count = []
    temp_queue = mock.MagicMock()

    def die(*args):
        raise taskcluster.exceptions.TaskclusterRestFailure("foo", None, status_code=409)

    async def fake_reclaim(*args, **kwargs):
        if reclaim_count:
            die()
        reclaim_count.append([args, kwargs])
        return {'credentials': {'foo': 'bar'}}

    class MockTaskProcess:
        async def stop(self):
            nonlocal kill_count
            kill_count += 1

    def fake_create_queue(*args):
        return temp_queue

    context.proc = None if no_proc else MockTaskProcess()
    context.create_queue = fake_create_queue
    temp_queue.reclaimTask = fake_reclaim
    context.temp_queue = temp_queue
    try:
        await swtask.reclaim_task(context, context.task)
    except ScriptWorkerTaskException:
        pass
    if no_proc:
        assert kill_count == 0
    else:
        assert kill_count == 1


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
