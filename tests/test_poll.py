#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.utils
"""
import os
import pytest
from scriptworker.context import Context
import scriptworker.poll as poll


@pytest.fixture(scope='function')
def context(tmpdir_factory):
    context = Context()
    # TODO fake context.queue
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
