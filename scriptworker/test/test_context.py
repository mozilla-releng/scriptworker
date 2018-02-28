#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.context
"""
import json
import os
import pytest
import taskcluster
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


def test_set_task(context, claim_task):
    context.claim_task = claim_task
    assert context.claim_task == claim_task
    assert context.reclaim_task is None
    assert context.temp_credentials == claim_task['credentials']
    assert get_json(get_task_file(context)) == claim_task['task']


def test_set_reclaim_task(context, claim_task, reclaim_task):
    context.claim_task = claim_task
    context.reclaim_task = reclaim_task
    assert context.claim_task == claim_task
    assert context.task == claim_task['task']
    assert context.reclaim_task == reclaim_task
    assert context.temp_credentials == reclaim_task['credentials']
    assert get_json(get_task_file(context)) == claim_task['task']


def test_set_reset_task(context, claim_task, reclaim_task):
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
    mocker.patch('taskcluster.async.Queue')
    context.session = {'c': 'd'}
    context.temp_credentials = {'a': 'b'}
    assert taskcluster.async.Queue.called_once_with({
        'credentials': context.temp_credentials,
    }, session=context.session)


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
