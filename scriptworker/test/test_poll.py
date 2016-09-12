#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.poll
"""
import arrow
from copy import deepcopy
import os
import pytest
from scriptworker.context import Context
import scriptworker.poll as poll
from . import event_loop, successful_queue, unsuccessful_queue

assert event_loop  # silence flake8
assert successful_queue, unsuccessful_queue  # silence flake8


# constants helpers and fixtures {{{1
async def fake_response(*args, **kwargs):
    return (args, kwargs)


async def fake_request(*args, **kwargs):
    with open(os.path.join(os.path.dirname(__file__), "data", "azure.xml"), "r") as fh:
        return fh.read()


@pytest.fixture(scope='function')
def context():
    context = Context()
    context.config = {
        'worker_group': 'worker_group',
        'worker_id': 'worker_id',
    }
    context.poll_task_urls = {
        'queues': [{
            "signedPollUrl": "poll0",
            "signedDeleteUrl": "delete0",
        }, {
            "signedPollUrl": "poll1",
            "signedDeleteUrl": "delete1",
        }],
    }
    return context


@pytest.fixture(scope='function')
def azure_xml():
    with open(os.path.join(os.path.dirname(__file__), "data", "azure.xml"), "r") as fh:
        xml = fh.read()
    return xml


# tests {{{1
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


def test_successful_claim_task(context, successful_queue, event_loop):
    context.queue = successful_queue
    result = event_loop.run_until_complete(
        poll.claim_task(context, 1, 2)
    )
    assert result == successful_queue.result


def test_unsuccessful_claim_task(context, unsuccessful_queue, event_loop):
    context.queue = unsuccessful_queue
    result = event_loop.run_until_complete(
        poll.claim_task(context, 1, 2)
    )
    assert result is None


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


def test_get_azure_urls(context):
    count = 0
    for poll_url, delete_url in poll.get_azure_urls(context):
        assert poll_url == "poll{}".format(count)
        assert delete_url == "delete{}".format(count)
        count += 1


def test_successful_find_task(context, successful_queue, event_loop):
    context.queue = successful_queue
    result = event_loop.run_until_complete(
        poll.find_task(context, "poll", "delete", fake_request)
    )
    assert result == "yay"


def test_unsuccessful_find_task(context, unsuccessful_queue, event_loop):
    context.queue = unsuccessful_queue
    result = event_loop.run_until_complete(
        poll.find_task(context, "poll", "delete", fake_request)
    )
    assert result is None
