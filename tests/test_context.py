#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.context
"""
import asyncio
import json
import mock
import os
import pytest
import taskcluster
from scriptworker.exceptions import CoTError
import scriptworker.context as swcontext
from copy import deepcopy
from . import tmpdir
from . import rw_context as context

assert tmpdir, context  # silence pyflakes


# constants helpers and fixtures {{{1
@pytest.fixture(scope='function')
def claim_task():
    return {
        "credentials": {
            "task_credentials": True,
        },
        "task": {
            "task_defn": True,
        }
    }


@pytest.fixture(scope='function')
def reclaim_task():
    return {
        "credentials": {
            "reclaim_task_credentials": True,
        }
    }


def get_task_file(context):
    temp_dir = context.config['work_dir']
    path = os.path.join(temp_dir, "task.json")
    return path


def get_json(path):
    with open(path, "r") as fh:
        return json.load(fh)


# tests {{{1
def test_empty_context(context):
    assert context.task is None
    assert context.claim_task is None
    assert context.reclaim_task is None
    assert context.temp_credentials is None


@pytest.mark.asyncio
async def test_set_task(context, claim_task):
    context.claim_task = claim_task
    assert context.claim_task == claim_task
    assert context.reclaim_task is None
    assert context.temp_credentials == claim_task['credentials']
    assert get_json(get_task_file(context)) == claim_task['task']


@pytest.mark.asyncio
async def test_set_reclaim_task(context, claim_task, reclaim_task):
    context.claim_task = claim_task
    context.reclaim_task = reclaim_task
    assert context.claim_task == claim_task
    assert context.task == claim_task['task']
    assert context.reclaim_task == reclaim_task
    assert context.temp_credentials == reclaim_task['credentials']
    assert get_json(get_task_file(context)) == claim_task['task']


@pytest.mark.asyncio
async def test_set_reset_task(context, claim_task, reclaim_task):
    context.claim_task = claim_task
    context.reclaim_task = reclaim_task
    context.claim_task = None
    assert context.claim_task is None
    assert context.task is None
    assert context.reclaim_task is None
    assert context.proc is None
    assert context.temp_credentials is None
    assert context.temp_queue is None


def test_temp_queue(context, mocker):
    mocker.patch('taskcluster.aio.Queue')
    context.session = {'c': 'd'}
    context.temp_credentials = {'a': 'b'}
    assert taskcluster.aio.Queue.called_once_with(
        options={
            'rootUrl': context.config['taskcluster_root_url'],
            'credentials': context.temp_credentials,
        },
        session=context.session
    )


@pytest.mark.asyncio
async def test_projects(context, mocker):
    fake_projects = {"mozilla-central": "blah", "count": 0}

    async def fake_load(*args):
        fake_projects['count'] += 1
        return deepcopy(fake_projects)

    mocker.patch.object(swcontext, "load_json_or_yaml_from_url", new=fake_load)
    assert context.projects is None
    await context.populate_projects()
    assert context.projects == fake_projects
    assert fake_projects['count'] == 1

    await context.populate_projects(force=True)
    assert context.projects == fake_projects
    assert fake_projects['count'] == 2

    await context.populate_projects()
    assert context.projects == fake_projects
    assert fake_projects['count'] == 2


def test_get_credentials(context):
    expected = {'asdf': 'foobar'}
    context._credentials = expected
    assert context.credentials == expected


def test_new_event_loop(mocker):
    """The default context.event_loop is from `asyncio.get_event_loop`"""
    fake_loop = mock.MagicMock()
    mocker.patch.object(asyncio, 'get_event_loop', return_value=fake_loop)
    context = swcontext.Context()
    assert context.event_loop is fake_loop


def test_set_event_loop(mocker):
    """`context.event_loop` returns the same value once set.

    (This may seem obvious, but this tests the correctness of the property.)

    """
    fake_loop = mock.MagicMock()
    context = swcontext.Context()
    context.event_loop = fake_loop
    assert context.event_loop is fake_loop


def test_verify_task(claim_task):
    context = swcontext.Context()
    context.task = {
        "payload": {
            "upstreamArtifacts": [{
                "taskId": "foo",
                "paths": ["bar"],
            }],
        },
    }
    # should not throw
    context.verify_task()


@pytest.mark.parametrize("bad_path", ("/abspath/foo", "public/../../../blah"))
def test_bad_verify_task(claim_task, bad_path):
    context = swcontext.Context()
    context.task = {
        "payload": {
            "upstreamArtifacts": [{
                "taskId": "bar",
                "paths": ["baz", bad_path],
            }],
        },
    }
    with pytest.raises(CoTError):
        context.verify_task()
