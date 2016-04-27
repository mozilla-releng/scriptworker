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


@pytest.fixture(scope='function')
def context(tmpdir_factory):
    temp_dir = tmpdir_factory.mktemp("context", numbered=True)
    context = Context()
    context.config = {
        "log_fmt": "%(message)s",
        "log_datefmt": "%H:%M:%S",
        "log_dir": str(temp_dir),
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


def read(path):
    with open(path, "r") as fh:
        return fh.read()


class TestLog(object):
    def test_get_log_filenames(self, context):
        log_file, error_file = swlog.get_log_filenames(context)
        assert log_file == os.path.join(context.config['log_dir'], 'task_output.log')
        assert error_file == os.path.join(context.config['log_dir'], 'task_error.log')

    def test_get_log_fhs(self, context, text):
        log_file, error_file = swlog.get_log_filenames(context)
        with swlog.get_log_fhs(context) as (log_fh, error_fh):
            print(text, file=log_fh, end="")
            print(text, file=error_fh, end="")
            print(text, file=error_fh, end="")
        assert read(log_file) == text
        assert read(error_file) == text + text

    @pytest.mark.asyncio
    async def test_read_stdout(self, context):
        cmd = r""">&2 echo "foo" && echo "bar" && exit 0"""
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c", cmd,
            stdout=PIPE, stderr=PIPE, stdin=None
        )
        tasks = []
        with swlog.get_log_fhs(context) as (log_fh, error_fh):
            tasks.append(swlog.log_errors(proc.stderr, log_fh, error_fh))
            tasks.append(swlog.read_stdout(proc.stdout, log_fh))
            await asyncio.wait(tasks)
            await proc.wait()
        log_file, error_file = swlog.get_log_filenames(context)
        assert read(log_file) in ("ERROR foo\nbar\n", "bar\nERROR foo\n")
        assert read(error_file) == "foo\n"

    def test_update_logging_config_verbose(self, context):
        swlog.update_logging_config(context, context.config['log_dir'])
        log = logging.getLogger(context.config['log_dir'])
        assert log.level == logging.DEBUG
        assert len(log.handlers) == 3

    def test_update_logging_config_not_verbose(self, context):
        context.config['verbose'] = False
        swlog.update_logging_config(context, context.config['log_dir'])
        log = logging.getLogger(context.config['log_dir'])
        assert log.level == logging.INFO
        assert len(log.handlers) == 2
