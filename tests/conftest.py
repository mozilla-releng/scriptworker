import asyncio
import functools
import os.path
import tempfile

import aiohttp
import pytest
import taskcluster.exceptions
from scriptworker.config import apply_product_config, get_unfrozen_copy
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.context import Context
from scriptworker.utils import makedirs

from . import VERBOSE, FakeResponse


class SuccessfulQueue(object):
    result = "yay"
    info = None
    status = 409
    task = {}
    reclaim_task = {"credentials": {"a": "b"}}

    async def claimTask(self, *args, **kwargs):
        return self.result

    async def reclaimTask(self, *args, **kwargs):
        self.info = ["reclaimTask", args, kwargs]
        raise taskcluster.exceptions.TaskclusterRestFailure("foo", None, status_code=self.status)

    async def reportCompleted(self, *args, **kwargs):
        self.info = ["reportCompleted", args, kwargs]

    async def reportFailed(self, *args, **kwargs):
        self.info = ["reportFailed", args, kwargs]

    async def reportException(self, *args, **kwargs):
        self.info = ["reportException", args, kwargs]

    async def createArtifact(self, *args, **kwargs):
        self.info = ["createArtifact", args, kwargs]
        return {"contentType": "text/plain", "putUrl": "url"}

    async def claimWork(self, *args, **kwargs):
        self.info = ["claimWork", args, kwargs]
        return {"tasks": [self.task]}


class UnsuccessfulQueue(object):
    status = 409

    async def claimTask(self, *args, **kwargs):
        raise taskcluster.exceptions.TaskclusterRestFailure("foo", None, status_code=self.status)

    async def reportCompleted(self, *args, **kwargs):
        raise taskcluster.exceptions.TaskclusterRestFailure("foo", None, status_code=self.status)

    async def reportFailed(self, *args, **kwargs):
        raise taskcluster.exceptions.TaskclusterRestFailure("foo", None, status_code=self.status)


@pytest.fixture(scope="function")
def successful_queue():
    return SuccessfulQueue()


@pytest.fixture(scope="function")
def unsuccessful_queue():
    return UnsuccessfulQueue()


@asyncio.coroutine
def _fake_request(resp_status, method, url, *args, **kwargs):
    resp = FakeResponse(method, url, status=resp_status)
    resp._history = (FakeResponse(method, url, status=302),)
    return resp


@pytest.mark.asyncio
@pytest.fixture(scope="function")
async def fake_session():
    session = aiohttp.ClientSession()
    session._request = functools.partial(_fake_request, 200)
    yield session
    await session.close()


@pytest.mark.asyncio
@pytest.fixture(scope="function")
async def fake_session_500():
    session = aiohttp.ClientSession()
    session._request = functools.partial(_fake_request, 500)
    yield session
    await session.close()


@pytest.mark.asyncio
@pytest.fixture(scope="function")
async def fake_session_404():
    session = aiohttp.ClientSession()
    session._request = functools.partial(_fake_request, 404)
    yield session
    await session.close()


@pytest.yield_fixture(scope="function")
def tmpdir():
    """Yield a tmpdir that gets cleaned up afterwards.

    This is because various pytest tmpdir implementations either don't return
    a string, or don't clean up properly.
    """
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


@pytest.yield_fixture(scope="function")
def tmpdir2():
    """Yield a tmpdir that gets cleaned up afterwards.

    Sometimes I need 2 tmpdirs in a test.
    a string, or don't clean up properly.
    """
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


async def _close_session(obj):
    """Get rid of all the unclosed session warnings.

    """
    if not hasattr(obj, "session"):
        return
    if isinstance(obj.session, aiohttp.ClientSession):
        await obj.session.close()


@pytest.mark.asyncio
@pytest.yield_fixture(scope="function")
async def rw_context(event_loop):
    async with aiohttp.ClientSession() as session:
        with tempfile.TemporaryDirectory() as tmp:
            context = _craft_rw_context(tmp, event_loop, cot_product="firefox", session=session)
            yield context


@pytest.mark.asyncio
@pytest.yield_fixture(scope="function")
async def mobile_rw_context(event_loop):
    async with aiohttp.ClientSession() as session:
        with tempfile.TemporaryDirectory() as tmp:
            context = _craft_rw_context(tmp, event_loop, cot_product="mobile", session=session)
            yield context


@pytest.mark.asyncio
@pytest.yield_fixture(scope="function")
async def mpd_private_rw_context(event_loop):
    async with aiohttp.ClientSession() as session:
        with tempfile.TemporaryDirectory() as tmp:
            context = _craft_rw_context(tmp, event_loop, cot_product="mpd001", session=session, private=True)
            yield context


def _craft_rw_context(tmp, event_loop, cot_product, session, private=False):
    config = get_unfrozen_copy(DEFAULT_CONFIG)
    config["cot_product"] = cot_product
    context = Context()
    context.session = session
    context.config = apply_product_config(config)
    context.config["cot_job_type"] = "scriptworker"
    for key, value in context.config.items():
        if key.endswith("_dir"):
            context.config[key] = os.path.join(tmp, key)
            makedirs(context.config[key])
        if key.endswith("key_path"):
            context.config[key] = os.path.join(tmp, key)
    if private:
        for rule in context.config["trusted_vcs_rules"]:
            rule["require_secret"] = True
    context.config["verbose"] = VERBOSE
    context.event_loop = event_loop
    return context
