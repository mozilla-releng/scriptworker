#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.poll
"""
from copy import deepcopy
import datetime
import os
import pytest
from scriptworker.context import Context
import scriptworker.poll as poll
from . import successful_queue, unsuccessful_queue
assert (successful_queue, unsuccessful_queue)  # silence flake8


@pytest.mark.asyncio
async def fake_response(*args, **kwargs):
    return (args, kwargs)


@pytest.mark.asyncio
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


class TestPoll(object):
    def test_parse_azure_xml(self, azure_xml):
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
            "messageText": "eyJmb28iOiAiYmFyIn0K",
            "task_info": {
                "foo": "bar",
            },
        }]
        count = -1
        for message in poll.parse_azure_xml(azure_xml):
            count += 1
            assert message == results[count]

    @pytest.mark.asyncio
    async def test_successful_claim_task(self, context, successful_queue):
        context.queue = successful_queue
        result = await poll.claim_task(context, 1, 2)
        assert result == successful_queue.result

    @pytest.mark.asyncio
    async def test_unsuccessful_claim_task(self, context, unsuccessful_queue):
        context.queue = unsuccessful_queue
        result = await poll.claim_task(context, 1, 2)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_expired_poll_task_urls(self, context):
        context.poll_task_urls['expires'] = "2016-04-16T03:46:24.958Z"
        await poll.update_poll_task_urls(context, fake_response)
        assert context.poll_task_urls == ((), {})

    @pytest.mark.asyncio
    async def test_update_unexpired_poll_task_urls(self, context):
        context.poll_task_urls['expires'] = datetime.datetime.strftime(
            datetime.datetime.utcnow() + datetime.timedelta(hours=10),
            "%Y-%m-%dT%H:%M:%S.123Z"
        )
        good = deepcopy(context.poll_task_urls)
        await poll.update_poll_task_urls(context, fake_response)
        assert context.poll_task_urls == good

    def test_get_azure_urls(self, context):
        count = 0
        for poll_url, delete_url in poll.get_azure_urls(context):
            assert poll_url == "poll{}".format(count)
            assert delete_url == "delete{}".format(count)
            count += 1

    @pytest.mark.asyncio
    async def test_successful_find_task(self, context, successful_queue):
        context.queue = successful_queue
        result = await poll.find_task(context, "poll", "delete", fake_request)
        assert result == "yay"
