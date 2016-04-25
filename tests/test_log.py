#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.log
"""
import asyncio
from asyncio.subprocess import PIPE
import os
import pytest
import tempfile
from scriptworker.context import Context
import scriptworker.log as swlog


@pytest.fixture(scope='function')
def context(tmpdir_factory):
    temp_dir = tmpdir_factory.mktemp("context", numbered=True)
    context = Context()
    context.config = {
        "log_fmt": "%(message)s",
        "log_dir": str(temp_dir),
    }
    return context


@pytest.fixture(scope='function')
def text():
    return u"""This
is a bunch
of text
💩
"""


@pytest.fixture(scope='function')
def temp_textfile(request, text):
    path = tempfile.TemporaryFile()
    request.addfinalizer(lambda: path.remove())
    with open(str(path), "w") as fh:
        print(text, file=fh, end="")
    return str(path)


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
        assert read(log_file) == "ERROR foo\nbar\n"
        assert read(error_file) == "foo\n"
