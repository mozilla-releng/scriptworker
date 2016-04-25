#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.log
"""
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
        assert read(log_file) == text
        assert read(error_file) == text
