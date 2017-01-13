#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.poll
"""
import arrow
from copy import deepcopy
import os
import pytest
from scriptworker.exceptions import ScriptWorkerRetryException
import scriptworker.poll as poll
from . import rw_context, event_loop, successful_queue, unsuccessful_queue

assert rw_context, event_loop  # silence flake8
assert successful_queue, unsuccessful_queue  # silence flake8


# constants helpers and fixtures {{{1
async def fake_response(*args, **kwargs):
    return (args, kwargs)


async def fake_request(*args, **kwargs):
    with open(os.path.join(os.path.dirname(__file__), "data", "azure.xml"), "r") as fh:
        return fh.read()


@pytest.yield_fixture(scope='function')
def context(rw_context):
    rw_context.poll_task_urls = {
        'queues': [{
            "signedPollUrl": "poll0",
            "signedDeleteUrl": "delete0",
        }, {
            "signedPollUrl": "poll1",
            "signedDeleteUrl": "delete1",
        }],
    }
    yield rw_context


@pytest.fixture(scope='function')
def azure_xml():
    with open(os.path.join(os.path.dirname(__file__), "data", "azure.xml"), "r") as fh:
        xml = fh.read()
    return xml


# parse_azure_xml {{{1
def test_parse_azure_xml(azure_xml):
    results = [{
        "messageId": "fdfc7989-b048-4ea8-bd33-69f63b83ba54",
        "popReceipt": "AgAAAAMAAAAAAAAAMApAvp2X0QE%3D",
        "messageText": "eyJ0YXNrSWQiOiJHVmkydlR3OFJZcWRnYTZwRTA4QWl3IiwicnVuSWQiOjB9",
        "task_info": {
            "runId": 0,
            "taskId": "GVi2vTw8RYqdga6pE08Aiw",
        },
    }, {
        "messageId": "two_id",
        "popReceipt": "two_pop%3D",
        "messageText": "eyJydW5JZCI6IDAsICJ0YXNrSWQiOiAiYXNkZiJ9Cg==",
        "task_info": {
            "runId": 0,
            "taskId": 'asdf',
        },
    }]
    count = -1
    for message in poll.parse_azure_xml(azure_xml):
        count += 1
        assert message == results[count]


# claim_task {{{1
def test_successful_claim_task(context, successful_queue, event_loop):
    context.queue = successful_queue
    result = event_loop.run_until_complete(
        poll.claim_task(context, 1, 2)
    )
    assert result == successful_queue.result


@pytest.mark.parametrize("error_code,raises", ((409, False), (500, True)))
def test_unsuccessful_claim_task(context, unsuccessful_queue, event_loop,
                                 error_code, raises):
    """claim_task with a non-successful result.

    On 409, the task has already been claimed or cancelled, but we should
    delete it from the Azure queue.  We should get None.

    On other errors, ``claim_task`` should raise ScriptWorkerRetryException
    so we can retry.
    """
    unsuccessful_queue.status = error_code
    context.queue = unsuccessful_queue
    if raises:
        with pytest.raises(ScriptWorkerRetryException):
            event_loop.run_until_complete(poll.claim_task(context, 1, 2))
    else:
        result = event_loop.run_until_complete(poll.claim_task(context, 1, 2))
        assert result is None


# update_poll_task_urls {{{1
def test_update_expired_poll_task_urls(context, event_loop):
    context.poll_task_urls['expires'] = "2016-04-16T03:46:24.958Z"
    event_loop.run_until_complete(
        poll.update_poll_task_urls(context, fake_response)
    )
    assert context.poll_task_urls == ((), {})


def test_update_unexpired_poll_task_urls(context, event_loop):
    expires = arrow.utcnow().replace(hours=10)
    context.poll_task_urls['expires'] = expires.isoformat()
    good = deepcopy(context.poll_task_urls)
    event_loop.run_until_complete(
        poll.update_poll_task_urls(context, fake_response)
    )
    assert context.poll_task_urls == good


def test_update_empty_poll_task_urls(context, event_loop):
    context.poll_task_urls = None
    event_loop.run_until_complete(
        poll.update_poll_task_urls(context, fake_response)
    )
    assert context.poll_task_urls == ((), {})


# get_azure_urls {{{1
def test_get_azure_urls(context):
    count = 0
    for poll_url, delete_url in poll.get_azure_urls(context):
        assert poll_url == "poll{}".format(count)
        assert delete_url == "delete{}".format(count)
        count += 1


# find_task {{{1
def test_successful_find_task(context, successful_queue, event_loop):
    context.queue = successful_queue
    result = event_loop.run_until_complete(
        poll.find_task(context, "poll", "delete", fake_request)
    )
    assert result == "yay"


@pytest.mark.parametrize("raises", (True, False))
def test_unsuccessful_find_task(context, unsuccessful_queue, event_loop, mocker, raises):
    counters = {
        "claim_task": 0,
    }

    # Raise the first time; return None the second
    async def claim(*args, **kwargs):
        if counters['claim_task']:
            return None
        counters['claim_task'] = counters['claim_task'] + 1
        raise ScriptWorkerRetryException("died in claim")

    async def req(_, url, **kwargs):
        if url == "poll":
            return await fake_request()
        if raises:
            raise ScriptWorkerRetryException("died in req")

    mocker.patch.object(poll, 'retry_async', new=claim)
    context.queue = unsuccessful_queue
    result = event_loop.run_until_complete(
        poll.find_task(context, "poll", "delete", req)
    )
    assert result is None
