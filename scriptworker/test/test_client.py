#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.client
"""

import aiohttp
import asyncio
import json
import logging
import os
import pytest
import random
import string
import sys
import tempfile
import arrow

from copy import deepcopy
from shutil import copyfile
from unittest.mock import MagicMock

import scriptworker.client as client
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerException, ScriptWorkerTaskException

from . import tmpdir, event_loop

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
    "https://queue.taskcluster.net/v1/task/VALID_TASK_ID2/artifacts/FILE_DIR%2FFILE_PATH",
    "FILE_DIR/FILE_PATH",
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


def test_sync_main_runs_fully(event_loop):
    generator = (n for n in range(0, 2))

    async def async_main(_):
        next(generator)

    with tempfile.NamedTemporaryFile('w+') as f:
        json.dump({'some': 'json_config'}, f)
        f.seek(0)

        client.sync_main(async_main, config_path=f.name)

    assert next(generator) == 1 # async_main was called once


@pytest.mark.parametrize('does_use_argv', (True, False))
def test_init_context(monkeypatch, does_use_argv):
    with tempfile.NamedTemporaryFile('w+') as f:
        json.dump({'some': 'json_config'}, f)
        f.seek(0)

        if does_use_argv:
            monkeypatch.setattr(sys, 'argv', ['some_binary_name', f.name])
            context = client._init_context()
        else:
            context = client._init_context(config_path=f.name)

    assert isinstance(context, Context)
    assert context.config == {'some': 'json_config'}


def test_fail_init_context(capsys, monkeypatch):
    for i in range(1, 10):
        if i == 2:
            # expected working case
            continue

        argv = ['argv{}'.format(j) for j in range(i)]
        monkeypatch.setattr(sys, 'argv', argv)
        with pytest.raises(SystemExit):
            context = client._init_context()

        # XXX This prevents usage from being printed out when the test is passing. Assertions are
        # done in test_usage
        capsys.readouterr()


def test_usage(capsys, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['my_binary'])
    with pytest.raises(SystemExit):
        client._usage()

    captured = capsys.readouterr()
    assert captured.out == ''
    assert captured.err == 'Usage: my_binary CONFIG_FILE\n'


@pytest.mark.parametrize('is_verbose, log_level', (
    (True, logging.DEBUG),
    (False, logging.INFO),
))
def test_init_logging(monkeypatch, is_verbose, log_level):
    context = MagicMock()
    context.config = {'verbose': is_verbose}

    basic_config_mock = MagicMock()

    monkeypatch.setattr(logging, 'basicConfig', basic_config_mock)
    client._init_logging(context)

    basic_config_mock.assert_called_once_with(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=log_level,
    )
    assert logging.getLogger('taskcluster').level == logging.WARNING


def test_handle_asyncio_loop(event_loop):
    context = MagicMock()
    context.was_async_main_called = False

    async def async_main(context):
        context.was_async_main_called = True

    client._handle_asyncio_loop(async_main, context)

    assert isinstance(context.session, aiohttp.ClientSession)
    assert context.was_async_main_called is True


def test_fail_handle_asyncio_loop(event_loop, capsys):
    context = MagicMock()

    async def async_error(context):
        exception = ScriptWorkerException('async_error!')
        exception.exit_code = 42
        raise exception

    with pytest.raises(SystemExit) as excinfo:
        client._handle_asyncio_loop(async_error, context)

    assert excinfo.value.code == 42

    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'Traceback' in captured.err
    assert 'ScriptWorkerException: async_error!' in captured.err


def test_handle_asyncio_loop_closes_loop(event_loop):
    context = MagicMock()
    event_loop.close = MagicMock()

    async def dummy_main(_):
        pass

    client._handle_asyncio_loop(dummy_main, context)
    event_loop.close.assert_called_once_with()
