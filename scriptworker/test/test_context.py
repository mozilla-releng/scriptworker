#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.context
"""
import asyncio
from copy import deepcopy
import json
import mock
from mock import MagicMock, call
import os
import pytest
import signal
import taskcluster
import scriptworker.context as swcontext
from copy import deepcopy
from . import task_context as context

assert context  # silence pyflakes


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


# tests {{{1
def test_empty_context(context):
    assert context.task is None
    assert context.claim_task is None
    assert context.reclaim_task is None
    assert context.credentials is None


@pytest.mark.asyncio
async def test_set_reclaim_task(context, claim_task, reclaim_task):
    context.claim_task = claim_task
    context.reclaim_task = reclaim_task
    assert context.claim_task == claim_task
    assert context.task == claim_task['task']
    assert context.reclaim_task == reclaim_task
    assert context.credentials == reclaim_task['credentials']


def test_temp_queue(context, mocker):
    mocker.patch('taskcluster.aio.Queue')
    context.session = {'c': 'd'}
    context.credentials = {'a': 'b'}
    assert taskcluster.aio.Queue.called_once_with(
        options={
            'rootUrl': context.config['taskcluster_root_url'],
            'credentials': context.credentials,
        },
        session=context.session
    )


@pytest.mark.asyncio
async def test_projects(context, mocker):
    fake_projects = {"mozilla-central": "blah", "count": 0}

    async def fake_load(*args):
        fake_projects['count'] += 1
        return deepcopy(fake_projects)

    worker_context = swcontext.WorkerContext()
    worker_context.config = context.config

    mocker.patch.object(swcontext, "load_json_or_yaml_from_url", new=fake_load)
    assert worker_context.projects is None
    await worker_context.populate_projects()
    assert worker_context.projects == fake_projects
    assert fake_projects['count'] == 1

    await worker_context.populate_projects(force=True)
    assert worker_context.projects == fake_projects
    assert fake_projects['count'] == 2

    await worker_context.populate_projects()
    assert worker_context.projects == fake_projects
    assert fake_projects['count'] == 2


def test_get_credentials(context):
    expected = {'asdf': 'foobar'}
    context._credentials = expected
    assert context.credentials == expected


def test_create_queue_no_creds():
    """`BaseWorkerContext` doesn't create a queue with no creds"""

    t = swcontext.BaseWorkerContext()
    assert t.create_queue(None) is None


def test_new_event_loop(mocker):
    """The default context.event_loop is from `asyncio.get_event_loop`"""
    fake_loop = mock.MagicMock()
    mocker.patch.object(asyncio, 'get_event_loop', return_value=fake_loop)
    context = swcontext.WorkerContext()
    assert context.event_loop is fake_loop


def test_set_event_loop(mocker):
    """`context.event_loop` returns the same value once set.

    (This may seem obvious, but this tests the correctness of the property.)

    """
    fake_loop = mock.MagicMock()
    context = swcontext.WorkerContext()
    context.event_loop = fake_loop
    assert context.event_loop is fake_loop


def test_empty_task_run_id():
    """If `claim_task` isn't set, `run_id` and `task_id` should return `None`."""
    t = swcontext.TaskContext()
    assert t.run_id is None
    assert t.task_id is None


def test_task_run_id():
    t = swcontext.TaskContext()
    t._claim_task = {
        "status": {
            "taskId": "task_id",
        },
        "runId": "run_id"
    }
    assert t.run_id == "run_id"
    assert t.task_id == "task_id"


def test_set_paths():
    """If we specify `task_num` with `num_concurrent_tasks > 1`, `set_paths`
    will append `task_num` to the `work_dir` and `artifact_dir`."""
    config = {
        "base_work_dir": "work",
        "base_artifact_dir": "artifact",
        "task_log_dir_template": "%(artifact_dir)s/public/logs",
        "num_concurrent_tasks": 1,
    }
    t = swcontext.TaskContext()
    t.config = deepcopy(config)
    t.set_paths(task_num=1)
    assert t.work_dir == "work"
    assert t.artifact_dir == "artifact"
    assert t.task_log_dir == "artifact/public/logs"

    config["num_concurrent_tasks"] = 3
    t = swcontext.TaskContext()
    t.config = deepcopy(config)
    t.set_paths(task_num=2)
    assert t.work_dir == "work/2"
    assert t.artifact_dir == "artifact/2"
    assert t.task_log_dir == "artifact/2/public/logs"


def test_create_task_context(context, claim_task):
    """`create_task_context sets config, paths, loop, session, projects,
    and claim_task."""

    context2 = swcontext.create_task_context(
        context.config,
        task_num=1,
        event_loop=context.event_loop,
        session=context.session,
        projects=context.projects,
        claim_task=claim_task,
    )
    assert context2.config == context.config
    assert context2.work_dir == context.work_dir
    assert context2.artifact_dir == context.artifact_dir
    assert context2.event_loop == context.event_loop
    assert context2.session == context.session
    assert context2.projects == context.projects
    assert context2.claim_task == claim_task
