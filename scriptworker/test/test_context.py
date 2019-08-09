#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.context
"""
import asyncio
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
