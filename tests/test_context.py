#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.context
"""
import glob
import json
import os
import pytest
from scriptworker.context import Context


@pytest.fixture(scope='function')
def context(tmpdir_factory):
    temp_dir = tmpdir_factory.mktemp("context", numbered=True)
    print(temp_dir)
    context = Context()
    context.config = {
        "work_dir": str(temp_dir),
    }
    return context


@pytest.fixture(scope='function')
def task():
    return {
        "credentials": {
            "task_credentials": True,
        }
    }


@pytest.fixture(scope='function')
def reclaim_task():
    return {
        "credentials": {
            "reclaim_task_credentials": True,
        }
    }


def get_credentials_files(context):
    temp_dir = context.config['work_dir']
    files = sorted(glob.glob(os.path.join(temp_dir, "credentials.*.json")))
    return files


def get_reclaim_task_files(context):
    temp_dir = context.config['work_dir']
    files = sorted(glob.glob(os.path.join(temp_dir, "reclaim_task.*.json")))
    return files


def get_task_file(context):
    temp_dir = context.config['work_dir']
    path = os.path.join(temp_dir, "task.json")
    return path


def get_json(path):
    with open(path, "r") as fh:
        return json.load(fh)


class TestContext(object):
    def test_empty_context(self, context):
        assert context.task is None
        assert context.reclaim_task is None
        assert context.temp_credentials is None

    def test_set_task(self, context, task):
        context.task = task
        assert context.task == task
        assert context.reclaim_task is None
        assert context.temp_credentials == task['credentials']
        assert get_reclaim_task_files(context) == []
        assert get_json(get_task_file(context)) == task
        files = get_credentials_files(context)
        assert len(files) == 1, "Invalid number of credentials files!"
        assert get_json(files[0]) == task['credentials']

    def test_set_reclaim_task(self, context, task, reclaim_task):
        context.task = task
        context.reclaim_task = reclaim_task
        assert context.task == task
        assert context.reclaim_task == reclaim_task
        assert context.temp_credentials == reclaim_task['credentials']
        assert get_json(get_task_file(context)) == task
        files = get_reclaim_task_files(context)
        assert len(files) == 1, "Invalid number of reclaim_task files!"
        assert get_json(files[0]) == reclaim_task
        files = get_credentials_files(context)
        assert len(files) == 2, "Invalid number of credentials files!"
        assert get_json(files[0]) == task['credentials']
        assert get_json(files[1]) == reclaim_task['credentials']
