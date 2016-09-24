#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.log
"""
import asyncio
from asyncio.subprocess import PIPE
import logging
import os
import pytest
from scriptworker.context import Context
import scriptworker.log as swlog
from . import event_loop, read, tmpdir

assert event_loop, tmpdir  # silence pyflakes


# constants helpers and fixtures {{{1
@pytest.fixture(scope='function')
def context(tmpdir):
    context = Context()
    context.config = {
        "log_fmt": "%(message)s",
        "log_datefmt": "%H:%M:%S",
        "log_dir": tmpdir,
        "task_log_dir": os.path.join(tmpdir, "public", "logs"),
        "log_max_bytes": 100,
        "log_num_backups": 1,
        "verbose": True,
    }
    return context


@pytest.fixture(scope='function')
def text():
    return u"""This
is a bunch
of text
💩
"""


# tests {{{1
def test_get_log_filenames(context):
    log_file, error_file = swlog.get_log_filenames(context)
    assert log_file == os.path.join(context.config['task_log_dir'], 'task_output.log')
    assert error_file == os.path.join(context.config['task_log_dir'], 'task_error.log')


def test_get_log_fhs(context, text):
    log_file, error_file = swlog.get_log_filenames(context)
    with swlog.get_log_fhs(context) as (log_fh, error_fh):
        print(text, file=log_fh, end="")
        print(text, file=error_fh, end="")
        print(text, file=error_fh, end="")
    assert read(log_file) == text
    assert read(error_file) == text + text


def test_pipe_to_log(context, event_loop):
    cmd = r""">&2 echo "foo" && echo "bar" && exit 0"""
    proc = event_loop.run_until_complete(
        asyncio.create_subprocess_exec(
            "bash", "-c", cmd,
            stdout=PIPE, stderr=PIPE, stdin=None
        )
    )
    tasks = []
    with swlog.get_log_fhs(context) as (log_fh, error_fh):
        tasks.append(swlog.pipe_to_log(proc.stderr, filehandles=[log_fh, error_fh]))
        tasks.append(swlog.pipe_to_log(proc.stdout, filehandles=[log_fh]))
        event_loop.run_until_complete(asyncio.wait(tasks))
        event_loop.run_until_complete(proc.wait())
    log_file, error_file = swlog.get_log_filenames(context)
    assert read(log_file) in ("foo\nbar\n", "bar\nfoo\n")
    assert read(error_file) == "foo\n"


def test_update_logging_config_verbose(context):
    swlog.update_logging_config(context, log_name=context.config['log_dir'])
    log = logging.getLogger(context.config['log_dir'])
    assert log.level == logging.DEBUG
    assert len(log.handlers) == 3


def test_update_logging_config_verbose_existing_handler(context):
    log = logging.getLogger(context.config['log_dir'])
    log.addHandler(logging.NullHandler())
    log.addHandler(logging.NullHandler())
    swlog.update_logging_config(context, log_name=context.config['log_dir'])
    assert log.level == logging.DEBUG
    assert len(log.handlers) == 4


def test_update_logging_config_not_verbose(context):
    context.config['verbose'] = False
    swlog.update_logging_config(context, log_name=context.config['log_dir'])
    log = logging.getLogger(context.config['log_dir'])
    assert log.level == logging.INFO
    assert len(log.handlers) == 2
