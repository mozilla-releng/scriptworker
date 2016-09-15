#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.client
"""
import arrow
import json
import os
import pytest
from shutil import copyfile
from scriptworker.exceptions import ScriptWorkerTaskException
import scriptworker.client as client
from . import tmpdir

assert tmpdir  # silence pyflakes

TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PARTIAL_CREDS = os.path.join(TEST_DATA_DIR, "partial_credentials.json")
CLIENT_CREDS = os.path.join(TEST_DATA_DIR, "client_credentials.json")
SCHEMA = os.path.join(TEST_DATA_DIR, "basic_schema.json")
BASIC_TASK = os.path.join(TEST_DATA_DIR, "basic_task.json")


# constants helpers and fixtures {{{1
# LEGAL_URLS format:
#  1. config dictionary that can define `valid_artifact_schemes`,
#     `valid_artifact_netlocs`, `valid_artifact_path_regexes`,
#     `valid_artifact_task_ids`
#  2. url to test
#  3. expected `filepath` return value from `validate_artifact_url()`
LEGAL_URLS = ((
    {'valid_artifact_task_ids': ("9999999", "VALID_TASK_ID", )},
    "https://queue.taskcluster.net/v1/task/VALID_TASK_ID/artifacts/FILE_PATH",
    "FILE_PATH",
), (
    {'valid_artifact_path_regexes': ()},
    "https://queue.taskcluster.net/FILE_PATH",
    "FILE_PATH",
), (
    {
        'valid_artifact_netlocs': ("example.com", "localhost"),
        'valid_artifact_path_regexes': (),
    },
    "https://localhost/FILE/PATH.baz",
    "FILE/PATH.baz",
), (
    {
        'valid_artifact_schemes': ("https", "file"),
        'valid_artifact_netlocs': ("example.com", "localhost"),
        'valid_artifact_path_regexes': ("^/foo/(?P<filepath>.*)$", "^/bar/(?P<filepath>.*)$"),
    },
    "file://localhost/bar/FILE/PATH.baz",
    "FILE/PATH.baz",
), (
    {
        'valid_artifact_schemes': None,
        'valid_artifact_netlocs': None,
        'valid_artifact_path_regexes': None,
    },
    "anyscheme://anyhost/FILE/PATH.baz",
    "FILE/PATH.baz",
))

# ILLEGAL_URLS format:
#  1. config dictionary that can define `valid_artifact_schemes`,
#     `valid_artifact_netlocs`, `valid_artifact_path_regexes`,
#     `valid_artifact_task_ids`
#  2. url to test
ILLEGAL_URLS = ((
    {}, "https://queue.taskcluster.net/v1/task/INVALID_TASK_ID/artifacts/FILE_PATH"
), (
    {},
    "https://queue.taskcluster.net/BAD_FILE_PATH"
), (
    {
        'valid_artifact_path_regexes': ('BAD_FILE_PATH', )
    },
    "https://queue.taskcluster.net/BAD_FILE_PATH"
), (
    {
        'valid_artifact_path_regexes': (),
    },
    "BAD_SCHEME://queue.taskcluster.net/FILE_PATH"
), (
    {
        'valid_artifact_path_regexes': (),
    },
    "https://BAD_NETLOC/FILE_PATH"
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


@pytest.mark.parametrize("params", LEGAL_URLS)
def test_artifact_url(params):
    value = client.validate_artifact_url(params[0], params[1])
    assert value == params[2]


@pytest.mark.parametrize("params", ILLEGAL_URLS)
def test_bad_artifact_url(params):
    with pytest.raises(ScriptWorkerTaskException):
        client.validate_artifact_url(params[0], params[1])
