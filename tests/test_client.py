#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.client
"""
import arrow
import json
import mock
import os
import pytest
from shutil import copyfile
from scriptworker.exceptions import ScriptWorkerTaskException
import scriptworker.client as client
import scriptworker.utils as utils

TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PARTIAL_CREDS = os.path.join(TEST_DATA_DIR, "partial_credentials.json")
CLIENT_CREDS = os.path.join(TEST_DATA_DIR, "client_credentials.json")
SCHEMA = os.path.join(TEST_DATA_DIR, "basic_schema.json")
BASIC_TASK = os.path.join(TEST_DATA_DIR, "basic_task.json")


@pytest.fixture(scope='function')
def config(tmpdir_factory):
    temp_dir = tmpdir_factory.mktemp("work_dir", numbered=True)
    work_dir = os.path.join(str(temp_dir), "work")
    os.makedirs(work_dir)
    return {
        'work_dir': work_dir,
        'log_dir': os.path.join(str(temp_dir), "log"),
        'artifact_dir': os.path.join(str(temp_dir), "artifact"),
        'provisioner_id': 'provisioner_id',
        'scheduler_id': 'scheduler_id',
        'worker_type': 'worker_type',
    }


@pytest.fixture(scope='function')
def schema():
    with open(SCHEMA, "r") as fh:
        return json.load(fh)


def populate_credentials(config, sources, start=None):
    start = start or arrow.utcnow().replace(minutes=-20)
    for count, path in enumerate(sources):
        new_time = start.replace(minutes=count)
        copyfile(path, os.path.join(config['work_dir'], "credentials.{}.json".format(new_time.timestamp)))


def no_sleep(*args, **kwargs):
    return 0


class TestClient(object):
    def test_get_missing_task(self, config):
        with pytest.raises(ScriptWorkerTaskException):
            client.get_task(config)

    def test_get_task(self, config):
        copyfile(BASIC_TASK, os.path.join(config['work_dir'], "task.json"))
        assert client.get_task(config)["this_is_a_task"] is True

    def test_retry_fail_creds(self, config):
        populate_credentials(config, [CLIENT_CREDS, PARTIAL_CREDS, PARTIAL_CREDS])
        with mock.patch.object(utils, "calculateSleepTime", new=no_sleep):
            with pytest.raises(ScriptWorkerTaskException):
                client.get_temp_creds_from_file(config)

    def test_get_missing_creds(self, config, event_loop):
        with pytest.raises(ScriptWorkerTaskException):
            event_loop.run_until_complete(client._get_temp_creds_from_file(config))

    def test_validate_task(self, schema):
        with open(BASIC_TASK, "r") as fh:
            task = json.load(fh)
        client.validate_task_schema(task['task'], schema)

    def test_invalid_task(self, schema):
        with open(BASIC_TASK, "r") as fh:
            task = json.load(fh)
        with pytest.raises(ScriptWorkerTaskException):
            client.validate_task_schema(task, schema)
