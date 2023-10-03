#!/usr/bin/env python
# coding=utf-8
"""Test base files
"""
import asyncio
import json
import os
import sys

import aiohttp
import arrow
import mock

try:
    import yarl

    YARL = True
except ImportError:
    YARL = False


VERBOSE = os.environ.get("SCRIPTWORKER_VERBOSE_TESTS", False)

ARTIFACT_SHAS = {
    "public/foo": "b5bb9d8014a0f9b1d61e21e796d78dccdf1352f23cd32812f4850b878ae4944c",
    "public/baz": "bf07a7fbb825fc0aae7bf4a1177b2b31fcf8a3feeaf7092761e18c859ee52a9c",
    "public/logs/bar": "7d865e959b2466918c9863afca942d0fb89d7c9ac0c99bafc3749504ded97730",
}

TIMEOUT_SCRIPT = os.path.join(os.path.dirname(__file__), "data", "long_running.py")
AT_LEAST_PY38 = sys.version_info >= (3, 8)


def read(path):
    """Return the contents of a file."""
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def touch(path):
    """Create an empty file.  Different from the system 'touch' in that it
    will overwrite an existing file.
    """
    with open(path, "w") as fh:
        print(path, file=fh, end="")


class FakeResponse(aiohttp.client_reqrep.ClientResponse):
    """Integration tests allow us to test everything's hooked up to aiohttp
    correctly.  When we don't want to actually hit an external url, have
    the aiohttp session's _request method return a FakeResponse.
    """

    def __init__(self, *args, status=200, payload=None, **kwargs):
        self._connection = mock.MagicMock()
        self._payload = payload or {}
        self.status = status
        self._headers = {"content-type": "application/json"}
        self._cache = {}
        self._loop = mock.MagicMock()
        self.content = self
        self.resp = [b"asdf", b"asdf"]
        self._url = args[1]
        self._history = ()
        if YARL:
            # fix aiohttp 1.1.0
            self._url_obj = yarl.URL(args[1])

    async def text(self, *args, **kwargs):
        return json.dumps(self._payload)

    async def json(self, *args, **kwargs):
        return self._payload

    async def release(self):
        return

    async def read(self, *args):
        if self.resp:
            return self.resp.pop(0)


def integration_create_task_payload(config, task_group_id, scopes=None, task_payload=None, task_extra=None):
    """For various integration tests, we need to call createTask for test tasks.

    This function creates a dummy payload for those createTask calls.
    """
    now = arrow.utcnow()
    deadline = now.shift(hours=1)
    expires = now.shift(days=3)
    scopes = scopes or []
    task_payload = task_payload or {}
    task_extra = task_extra or {}
    return {
        "provisionerId": config["provisioner_id"],
        "schedulerId": "test-dummy-scheduler",
        "workerType": config["worker_type"],
        "taskGroupId": task_group_id,
        "dependencies": [],
        "requires": "all-completed",
        "routes": [],
        "priority": "normal",
        "retries": 5,
        "created": now.isoformat(),
        "deadline": deadline.isoformat(),
        "expires": expires.isoformat(),
        "scopes": scopes,
        "payload": task_payload,
        "metadata": {
            "name": "ScriptWorker Integration Test",
            "description": "ScriptWorker Integration Test",
            "owner": "release+python@mozilla.com",
            "source": "https://github.com/mozilla-releng/scriptworker/",
        },
        "tags": {},
        "extra": task_extra,
    }


async def noop_async(*args, **kwargs):
    pass


def noop_sync(*args, **kwargs):
    pass


def create_finished_future(result=None):
    # XXX deprecated; remove after we drop py37 support
    assert not AT_LEAST_PY38, "Use AsyncMock!"
    future = asyncio.Future()
    future.set_result(result)
    return future


def create_rejected_future(exception=BaseException):
    # XXX deprecated; remove after we drop py37 support
    assert not AT_LEAST_PY38, "Use AsyncMock!"
    future = asyncio.Future()
    future.set_exception(exception)
    return future


def create_slow_async(result=None):
    future = asyncio.Future()

    async def slow_function(*args, **kwargs):
        future.set_result(None)
        await asyncio.Future()
        return result

    return future, slow_function


def create_sync(result=None):
    def fn(*args, **kwargs):
        return result

    return fn


def create_async(result=None):
    async def fn(*args, **kwargs):
        return result

    return fn
