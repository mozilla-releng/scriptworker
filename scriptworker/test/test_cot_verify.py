#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.cot.verify
"""
import logging
import mock
import pytest
from scriptworker.exceptions import CoTError
import scriptworker.cot.verify as cotverify
from . import rw_context

assert rw_context  # silence pyflakes

# TODO remove once we use
assert CoTError

log = logging.getLogger(__name__)


# constants helpers and fixtures {{{1
@pytest.yield_fixture(scope='function')
def chain(rw_context):
    rw_context.config['scriptworker_provisioners'] = [rw_context.config['provisioner_id']]
    rw_context.config['scriptworker_worker_types'] = [rw_context.config['worker_type']]
    rw_context.task = {
        'scopes': [],
        'provisionerId': rw_context.config['provisioner_id'],
        'workerType': rw_context.config['worker_type'],
        'taskGroupId': 'groupid',
        'payload': {
            'image': None,
        },
    }
    # decision_task_id
    chain_ = cotverify.ChainOfTrust(
        rw_context, 'signing', task_id='taskid'
    )
    yield chain_


# dependent_task_ids {{{1
def test_dependent_task_ids(chain):
    ids = ["one", "TWO", "thr33", "vier"]
    for i in ids:
        m = mock.MagicMock()
        m.task_id = i
        chain.links.append(m)
    assert sorted(chain.dependent_task_ids()) == sorted(ids)
