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

from unittest.mock import MagicMock

from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerException
from scriptworker.script import sync_main, _init_context, _usage, _init_logging, _handle_asyncio_loop

from . import event_loop


@pytest.mark.parametrize('name', (__name__, 'random-name'))
def test_sync_main_early_returns(event_loop, name):
    generator = (n for n in range(0, 2))

    async def async_main(_):
        next(generator)

    sync_main(async_main, name=__name__, config_path=None)

    assert next(generator) == 0 # async_main was never called


@pytest.mark.parametrize('name', (None, '__main__'))
def test_sync_main_runs_fully(event_loop, name):
    generator = (n for n in range(0, 2))

    async def async_main(_):
        next(generator)

    with tempfile.NamedTemporaryFile('w+') as f:
        json.dump({'some': 'json_config'}, f)
        f.seek(0)

        sync_main(async_main, name=name, config_path=f.name)

    assert next(generator) == 1 # async_main was called once


@pytest.mark.parametrize('does_use_argv', (True, False))
def test_init_context(monkeypatch, does_use_argv):
    with tempfile.NamedTemporaryFile('w+') as f:
        json.dump({'some': 'json_config'}, f)
        f.seek(0)

        if does_use_argv:
            monkeypatch.setattr(sys, 'argv', ['some_binary_name', f.name])
            context = _init_context()
        else:
            context = _init_context(config_path=f.name)

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
            context = _init_context()

        # XXX This prevents usage from being printed out when the test is passing. Assertions are
        # done in test_usage
        capsys.readouterr()


def test_usage(capsys, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['my_binary'])
    with pytest.raises(SystemExit):
        _usage()

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
    _init_logging(context)

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

    _handle_asyncio_loop(async_main, context)

    assert isinstance(context.session, aiohttp.ClientSession)
    assert context.was_async_main_called is True


def test_fail_handle_asyncio_loop(event_loop, capsys):
    context = MagicMock()

    async def async_error(context):
        exception = ScriptWorkerException('async_error!')
        exception.exit_code = 42
        raise exception

    with pytest.raises(SystemExit) as excinfo:
        _handle_asyncio_loop(async_error, context)

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

    _handle_asyncio_loop(dummy_main, context)
    event_loop.close.assert_called_once_with()
