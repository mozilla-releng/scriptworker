#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.log
"""
import asyncio
from asyncio.subprocess import PIPE
import logging
import os
import pytest
import scriptworker.log as swlog
from . import event_loop, read
from . import rw_context as context

assert event_loop, context  # silence pyflakes


# constants helpers and fixtures {{{1
@pytest.fixture(scope='function')
def text():
    return u"""This
is a bunch
of text
💩
"""


def close_handlers(log_name=None):
    log_name = log_name or __name__.split('.')[0]
    log = logging.getLogger(log_name)
    handlers = log.handlers[:]
    for handler in handlers:
        handler.close()
        log.removeHandler(handler)
    log.addHandler(logging.NullHandler())


# tests {{{1
def test_get_log_filename(context):
    log_file = swlog.get_log_filename(context)
    assert log_file == os.path.join(context.config['task_log_dir'], 'live_backing.log')


def test_get_log_filehandle(context, text):
    log_file = swlog.get_log_filename(context)
    with swlog.get_log_filehandle(context) as log_fh:
        log_fh.write(text)
        log_fh.write(text)
    assert read(log_file) == text + text


def test_pipe_to_log(context, event_loop):
    cmd = r""">&2 echo "foo" && echo "bar" && exit 0"""
    proc = event_loop.run_until_complete(
        asyncio.create_subprocess_exec(
            "bash", "-c", cmd,
            stdout=PIPE, stderr=PIPE, stdin=None
        )
    )
    tasks = []
    with swlog.get_log_filehandle(context) as log_fh:
        tasks.append(swlog.pipe_to_log(proc.stderr, filehandles=[log_fh]))
        tasks.append(swlog.pipe_to_log(proc.stdout, filehandles=[log_fh]))
        event_loop.run_until_complete(asyncio.wait(tasks))
        event_loop.run_until_complete(proc.wait())
    log_file = swlog.get_log_filename(context)
    assert read(log_file) in ("foo\nbar\n", "bar\nfoo\n")


def test_update_logging_config_verbose(context):
    swlog.update_logging_config(context, log_name=context.config['log_dir'])
    log = logging.getLogger(context.config['log_dir'])
    assert log.level == logging.DEBUG
    assert len(log.handlers) == 3
    close_handlers(log_name=context.config['log_dir'])


def test_update_logging_config_verbose_existing_handler(context):
    log = logging.getLogger(context.config['log_dir'])
    log.addHandler(logging.NullHandler())
    log.addHandler(logging.NullHandler())
    swlog.update_logging_config(context, log_name=context.config['log_dir'])
    assert log.level == logging.DEBUG
    assert len(log.handlers) == 4
    close_handlers(log_name=context.config['log_dir'])


def test_update_logging_config_not_verbose(context):
    context.config['verbose'] = False
    swlog.update_logging_config(context, log_name=context.config['log_dir'])
    log = logging.getLogger(context.config['log_dir'])
    assert log.level == logging.INFO
    assert len(log.handlers) == 2
    close_handlers(log_name=context.config['log_dir'])


def test_contextual_log_handler(context, mocker):
    contextual_path = os.path.join(context.config['artifact_dir'], "test.log")
    swlog.log.setLevel(logging.DEBUG)
    with swlog.contextual_log_handler(context, path=contextual_path):
        swlog.log.info("foo")
    swlog.log.info("bar")
    with open(contextual_path, "r") as fh:
        contents = fh.read().splitlines()
    assert len(contents) == 1
    assert contents[0].endswith("foo")


def test_watched_log_file(context):
    context.config['watch_log_file'] = True
    context.config["log_fmt"] = "%(levelname)s - %(message)s"
    swlog.update_logging_config(context, log_name=context.config['log_dir'])
    path = os.path.join(context.config['log_dir'], 'worker.log')
    log = logging.getLogger(context.config['log_dir'])
    log.info("foo")
    os.rename(path, "{}.1".format(path))
    log.info("bar")
    with open(path, "r") as fh:
        assert fh.read().rstrip() == "INFO - bar"
    close_handlers(log_name=context.config['log_dir'])
