#!/usr/bin/env python
# coding=utf-8
"""Test base files
"""
import pytest
import taskcluster.exceptions


class SuccessfulQueue(object):
    result = "yay"

    @pytest.mark.asyncio
    async def claimTask(self, *args, **kwargs):
        return self.result


class UnsuccessfulQueue(object):
    @pytest.mark.asyncio
    async def claimTask(self, *args, **kwargs):
        raise taskcluster.exceptions.TaskclusterFailure("foo")


@pytest.fixture(scope='function')
def successful_queue():
    return SuccessfulQueue()


@pytest.fixture(scope='function')
def unsuccessful_queue():
    return UnsuccessfulQueue()
