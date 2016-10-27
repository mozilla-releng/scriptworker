#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.client
"""
import arrow
from copy import deepcopy
import json
import os
import pytest
from shutil import copyfile
import scriptworker.client as client
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.exceptions import ScriptWorkerTaskException
from . import tmpdir

assert tmpdir  # silence pyflakes

TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PARTIAL_CREDS = os.path.join(TEST_DATA_DIR, "partial_credentials.json")
CLIENT_CREDS = os.path.join(TEST_DATA_DIR, "client_credentials.json")
SCHEMA = os.path.join(TEST_DATA_DIR, "basic_schema.json")
BASIC_TASK = os.path.join(TEST_DATA_DIR, "basic_task.json")


# constants helpers and fixtures {{{1
# LEGAL_URLS format:
#  1. valid_artifact_rules: tuple-of-dicts with `schemes`, `netlocs`, and `path_regexes`
#  2. valid_artifact_task_ids: list
#  3. url to test
#  4. expected `filepath` return value from `validate_artifact_url()`
LEGAL_URLS = ((
    deepcopy(DEFAULT_CONFIG['valid_artifact_rules']),
    ["VALID_TASK_ID1", "VALID_TASK_ID2"],
    "https://queue.taskcluster.net/v1/task/VALID_TASK_ID2/artifacts/FILE_PATH",
    "FILE_PATH",
), (
    ({
        'schemes': ("ftp", "http"),
        'netlocs': ("example.com", "localhost"),
        'path_regexes': ('(?P<filepath>.*.baz)', ),
    }, ),
    [],
    "http://localhost/FILE/PATH.baz",
    "FILE/PATH.baz",
))

# ILLEGAL_URLS format:
#  1. valid_artifact_rules: dict with `schemes`, `netlocs`, and `path_regexes`
#  2. valid_artifact_task_ids: list
#  3. url to test
ILLEGAL_URLS = ((
    deepcopy(DEFAULT_CONFIG['valid_artifact_rules']),
    ["VALID_TASK_ID1", "VALID_TASK_ID2"],
    "https://queue.taskcluster.net/v1/task/INVALID_TASK_ID/artifacts/FILE_PATH"
), (
    deepcopy(DEFAULT_CONFIG['valid_artifact_rules']),
    ["VALID_TASK_ID1", "VALID_TASK_ID2"],
    "https://queue.taskcluster.net/v1/task/VALID_TASK_ID1/BAD_FILE_PATH"
), (
    deepcopy(DEFAULT_CONFIG['valid_artifact_rules']),
    ["VALID_TASK_ID1", "VALID_TASK_ID2"],
    "BAD_SCHEME://queue.taskcluster.net/v1/task/VALID_TASK_ID1/artifacts/FILE_PATH"
), (
    deepcopy(DEFAULT_CONFIG['valid_artifact_rules']),
    ["VALID_TASK_ID1", "VALID_TASK_ID2"],
    "https://BAD_NETLOC/v1/task/VALID_TASK_ID1/artifacts/FILE_PATH"
), (
    ({'schemes': ['https'], 'netlocs': ['example.com'],
      # missing filepath
      'path_regexes': ['.*BAD_REGEX.*']}, ),
    [],
    "https://example.com/BAD_REGEX",
))


@pytest.fixture(scope='function')
def config(tmpdir):
    work_dir = os.path.join(tmpdir, "work")
    os.makedirs(work_dir)
    return {
        'work_dir': work_dir,
        'log_dir': os.path.join(tmpdir, "log"),
        'artifact_dir': os.path.join(tmpdir, "artifact"),
        'task_log_dir': os.path.join(tmpdir, "artifact", "public", "logs"),
        'provisioner_id': 'provisioner_id',
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


# tests {{{1
def test_get_missing_task(config):
    with pytest.raises(ScriptWorkerTaskException):
        client.get_task(config)


def test_get_task(config):
    copyfile(BASIC_TASK, os.path.join(config['work_dir'], "task.json"))
    assert client.get_task(config)["this_is_a_task"] is True


def test_validate_task(schema):
    with open(BASIC_TASK, "r") as fh:
        task = json.load(fh)
    client.validate_json_schema(task, schema)


def test_invalid_task(schema):
    with open(BASIC_TASK, "r") as fh:
        task = json.load(fh)
    with pytest.raises(ScriptWorkerTaskException):
        client.validate_json_schema({'foo': task}, schema)


@pytest.mark.parametrize("valid_artifact_rules,valid_artifact_task_ids,url,expected", LEGAL_URLS)
def test_artifact_url(valid_artifact_rules, valid_artifact_task_ids, url, expected):
    value = client.validate_artifact_url(valid_artifact_rules, valid_artifact_task_ids, url)
    assert value == expected


@pytest.mark.parametrize("valid_artifact_rules,valid_artifact_task_ids,url", ILLEGAL_URLS)
def test_bad_artifact_url(valid_artifact_rules, valid_artifact_task_ids, url):
    with pytest.raises(ScriptWorkerTaskException):
        client.validate_artifact_url(valid_artifact_rules, valid_artifact_task_ids, url)
