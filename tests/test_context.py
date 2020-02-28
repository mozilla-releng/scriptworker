#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.context
"""
import asyncio
import json
import os
from copy import deepcopy

import mock
import pytest
import scriptworker.context as swcontext
import taskcluster
from scriptworker.exceptions import CoTError


# constants helpers and fixtures {{{1
@pytest.fixture(scope="function")
def claim_task():
    return {"credentials": {"task_credentials": True}, "task": {"task_defn": True}}


@pytest.fixture(scope="function")
def reclaim_task():
    return {"credentials": {"reclaim_task_credentials": True}}


def get_task_file(rw_context):
    temp_dir = rw_context.config["work_dir"]
    path = os.path.join(temp_dir, "task.json")
    return path


def get_json(path):
    with open(path, "r") as fh:
        return json.load(fh)


# tests {{{1
def test_empty_context(rw_context):
    assert rw_context.task is None
    assert rw_context.claim_task is None
    assert rw_context.reclaim_task is None
    assert rw_context.temp_credentials is None


@pytest.mark.asyncio
async def test_set_task(rw_context, claim_task):
    rw_context.claim_task = claim_task
    assert rw_context.claim_task == claim_task
    assert rw_context.reclaim_task is None
    assert rw_context.temp_credentials == claim_task["credentials"]
    assert get_json(get_task_file(rw_context)) == claim_task["task"]


@pytest.mark.asyncio
async def test_set_reclaim_task(rw_context, claim_task, reclaim_task):
    rw_context.claim_task = claim_task
    rw_context.reclaim_task = reclaim_task
    assert rw_context.claim_task == claim_task
    assert rw_context.task == claim_task["task"]
    assert rw_context.reclaim_task == reclaim_task
    assert rw_context.temp_credentials == reclaim_task["credentials"]
    assert get_json(get_task_file(rw_context)) == claim_task["task"]


@pytest.mark.asyncio
async def test_set_reset_task(rw_context, claim_task, reclaim_task):
    rw_context.claim_task = claim_task
    rw_context.reclaim_task = reclaim_task
    rw_context.claim_task = None
    assert rw_context.claim_task is None
    assert rw_context.task is None
    assert rw_context.reclaim_task is None
    assert rw_context.proc is None
    assert rw_context.temp_credentials is None
    assert rw_context.temp_queue is None


def test_temp_queue(rw_context, mocker):
    mocker.patch("taskcluster.aio.Queue")
    rw_context.session = {"c": "d"}
    rw_context.temp_credentials = {"a": "b"}
    assert taskcluster.aio.Queue.called_once_with(
        options={"rootUrl": rw_context.config["taskcluster_root_url"], "credentials": rw_context.temp_credentials}, session=rw_context.session
    )


@pytest.mark.asyncio
async def test_projects(rw_context, mocker):
    fake_projects = {"mozilla-central": "blah", "count": 0}

    async def fake_load(*args):
        fake_projects["count"] += 1
        return deepcopy(fake_projects)

    mocker.patch.object(swcontext, "load_json_or_yaml_from_url", new=fake_load)
    assert rw_context.projects is None
    await rw_context.populate_projects()
    assert rw_context.projects == fake_projects
    assert fake_projects["count"] == 1

    await rw_context.populate_projects(force=True)
    assert rw_context.projects == fake_projects
    assert fake_projects["count"] == 2

    await rw_context.populate_projects()
    assert rw_context.projects == fake_projects
    assert fake_projects["count"] == 2


def test_get_credentials(rw_context):
    expected = {"asdf": "foobar"}
    rw_context._credentials = expected
    assert rw_context.credentials == expected


def test_new_event_loop(mocker):
    """The default rw_context.event_loop is from `asyncio.get_event_loop`"""
    fake_loop = mock.MagicMock()
    mocker.patch.object(asyncio, "get_event_loop", return_value=fake_loop)
    rw_context = swcontext.Context()
    assert rw_context.event_loop is fake_loop


def test_set_event_loop(mocker):
    """`rw_context.event_loop` returns the same value once set.

    (This may seem obvious, but this tests the correctness of the property.)

    """
    fake_loop = mock.MagicMock()
    rw_context = swcontext.Context()
    rw_context.event_loop = fake_loop
    assert rw_context.event_loop is fake_loop


def test_verify_task(claim_task):
    rw_context = swcontext.Context()
    rw_context.task = {"payload": {"upstreamArtifacts": [{"taskId": "foo", "paths": ["bar"]}]}}
    # should not throw
    rw_context.verify_task()


@pytest.mark.parametrize("bad_path", ("/abspath/foo", "public/../../../blah"))
def test_bad_verify_task(claim_task, bad_path):
    context = swcontext.Context()
    context.task = {"payload": {"upstreamArtifacts": [{"taskId": "bar", "paths": ["baz", bad_path]}]}}
    with pytest.raises(CoTError):
        context.verify_task()
