#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.log
"""
import asyncio
import logging
import os
from asyncio.subprocess import PIPE

import pytest

import scriptworker.log as swlog

from . import read


# constants helpers and fixtures {{{1
@pytest.fixture(scope="function")
def text():
    return """This
is a bunch
of text
💩
"""


def close_handlers(log_name=None):
    log_name = log_name or __name__.split(".")[0]
    log = logging.getLogger(log_name)
    handlers = log.handlers[:]
    for handler in handlers:
        handler.close()
        log.removeHandler(handler)
    log.addHandler(logging.NullHandler())


# tests {{{1
def test_get_log_filename(rw_context):
    log_file = swlog.get_log_filename(rw_context)
    assert log_file == os.path.join(rw_context.config["task_log_dir"], "live_backing.log")


def test_get_log_filehandle(rw_context, text):
    log_file = swlog.get_log_filename(rw_context)
    with swlog.get_log_filehandle(rw_context) as log_fh:
        log_fh.write(text)
        log_fh.write(text)
    assert read(log_file) == text + text


@pytest.mark.asyncio
async def test_pipe_to_log(rw_context):
    cmd = r""">&2 echo "foo" && echo "bar" && exit 0"""
    proc = await asyncio.create_subprocess_exec("bash", "-c", cmd, stdout=PIPE, stderr=PIPE, stdin=None)
    tasks = []
    with swlog.get_log_filehandle(rw_context) as log_fh:
        tasks.append(swlog.pipe_to_log(proc.stderr, filehandles=[log_fh]))
        tasks.append(swlog.pipe_to_log(proc.stdout, filehandles=[log_fh]))
        await asyncio.wait(tasks)
        await proc.wait()
    log_file = swlog.get_log_filename(rw_context)
    assert read(log_file) in ("foo\nbar\n", "bar\nfoo\n")


def test_update_logging_config_verbose(rw_context):
    rw_context.config["verbose"] = True
    swlog.update_logging_config(rw_context, log_name=rw_context.config["log_dir"])
    log = logging.getLogger(rw_context.config["log_dir"])
    assert log.level == logging.DEBUG
    assert len(log.handlers) == 3
    close_handlers(log_name=rw_context.config["log_dir"])


def test_update_logging_config_verbose_existing_handler(rw_context):
    log = logging.getLogger(rw_context.config["log_dir"])
    log.addHandler(logging.NullHandler())
    log.addHandler(logging.NullHandler())
    rw_context.config["verbose"] = True
    swlog.update_logging_config(rw_context, log_name=rw_context.config["log_dir"])
    assert log.level == logging.DEBUG
    assert len(log.handlers) == 4
    close_handlers(log_name=rw_context.config["log_dir"])


def test_update_logging_config_not_verbose(rw_context):
    rw_context.config["verbose"] = False
    swlog.update_logging_config(rw_context, log_name=rw_context.config["log_dir"])
    log = logging.getLogger(rw_context.config["log_dir"])
    assert log.level == logging.INFO
    assert len(log.handlers) == 2
    close_handlers(log_name=rw_context.config["log_dir"])


def test_contextual_log_handler(rw_context, mocker):
    contextual_path = os.path.join(rw_context.config["artifact_dir"], "test.log")
    swlog.log.setLevel(logging.DEBUG)
    with swlog.contextual_log_handler(rw_context, path=contextual_path):
        swlog.log.info("foo")
    swlog.log.info("bar")
    with open(contextual_path, "r") as fh:
        contents = fh.read().splitlines()
    assert len(contents) == 1
    assert contents[0].endswith("foo")


def test_watched_log_file(rw_context):
    rw_context.config["watch_log_file"] = True
    rw_context.config["log_fmt"] = "%(levelname)s - %(message)s"
    swlog.update_logging_config(rw_context, log_name=rw_context.config["log_dir"])
    path = os.path.join(rw_context.config["log_dir"], "worker.log")
    log = logging.getLogger(rw_context.config["log_dir"])
    log.info("foo")
    os.rename(path, "{}.1".format(path))
    log.info("bar")
    with open(path, "r") as fh:
        assert fh.read().rstrip() == "INFO - bar"
    close_handlers(log_name=rw_context.config["log_dir"])
