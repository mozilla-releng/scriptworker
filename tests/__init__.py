#!/usr/bin/env python
# coding=utf-8
"""Test base files
"""
import pytest
import taskcluster.exceptions


def read(path):
    with open(path, "r") as fh:
        return fh.read()


class SuccessfulQueue(object):
    result = "yay"
    info = None

    @pytest.mark.asyncio
    async def claimTask(self, *args, **kwargs):
        return self.result

    @pytest.mark.asyncio
    async def reportCompleted(self, *args, **kwargs):
        self.info = ['reportCompleted', args, kwargs]

    @pytest.mark.asyncio
    async def reportFailed(self, *args, **kwargs):
        self.info = ['reportFailed', args, kwargs]


class UnsuccessfulQueue(object):
    status = 409

    @pytest.mark.asyncio
    async def claimTask(self, *args, **kwargs):
        raise taskcluster.exceptions.TaskclusterFailure("foo")

    @pytest.mark.asyncio
    async def reportCompleted(self, *args, **kwargs):
        raise taskcluster.exceptions.TaskclusterRestFailure("foo", None, status_code=self.status)

    @pytest.mark.asyncio
    async def reportFailed(self, *args, **kwargs):
        raise taskcluster.exceptions.TaskclusterRestFailure("foo", None, status_code=self.status)


@pytest.fixture(scope='function')
def successful_queue():
    return SuccessfulQueue()


@pytest.fixture(scope='function')
def unsuccessful_queue():
    return UnsuccessfulQueue()
