#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.cot.verify
"""
import logging
import mock
import os
import pytest
from scriptworker.exceptions import CoTError
import scriptworker.cot.verify as cotverify
from . import rw_context

assert rw_context  # silence pyflakes

log = logging.getLogger(__name__)


# constants helpers and fixtures {{{1
@pytest.yield_fixture(scope='function')
def chain(rw_context):
    rw_context.config['scriptworker_provisioners'] = [rw_context.config['provisioner_id']]
    rw_context.config['scriptworker_worker_types'] = [rw_context.config['worker_type']]
    rw_context.task = {
        'scopes': [],
        'provisionerId': rw_context.config['provisioner_id'],
        'schedulerId': 'schedulerId',
        'workerType': rw_context.config['worker_type'],
        'taskGroupId': 'groupid',
        'payload': {
            'image': None,
        },
        'metadata': {},
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
        l = cotverify.LinkOfTrust(chain.context, 'build', i)
        chain.links.append(l)
    assert sorted(chain.dependent_task_ids()) == sorted(ids)


# is_try {{{1
@pytest.mark.parametrize("bools,result", (([False, False], False), ([False, True], True)))
def test_chain_is_try(chain, bools, result):
    for b in bools:
        m = mock.MagicMock()
        m.is_try = b
        chain.links.append(m)
    assert chain.is_try() == result


@pytest.mark.parametrize("task", (
    {'payload': {'env': {'GECKO_HEAD_REPOSITORY': "https://hg.mozilla.org/try/sdfsd"}}, 'metadata': {}, 'schedulerId': "x"},
    {'payload': {'env': {'GECKO_HEAD_REPOSITORY': "https://hg.mozilla.org/mozilla-central", "MH_BRANCH": "try"}}, 'metadata': {}, "schedulerId": "x"},
    {'payload': {}, 'metadata': {'source': 'http://hg.mozilla.org/try'}, 'schedulerId': "x"},
    {'payload': {}, 'metadata': {}, 'schedulerId': "gecko-level-1"},
))
def test_is_try(task):
    assert cotverify.is_try(task)


# get_link {{{1
@pytest.mark.parametrize("ids,req,raises", ((
    ("one", "two", "three"), "one", False
), (
    ("one", "one", "two"), "one", True
), (
    ("one", "two"), "three", True
)))
def test_get_link(chain, ids, req, raises):
    for i in ids:
        l = cotverify.LinkOfTrust(chain.context, 'build', i)
        chain.links.append(l)
    if raises:
        with pytest.raises(CoTError):
            chain.get_link(req)
    else:
        chain.get_link(req)


# link.task {{{1
def test_link_task(chain):
    link = cotverify.LinkOfTrust(chain.context, 'build', "one")
    link.task = chain.task
    assert not link.is_try
    assert link.worker_impl == 'scriptworker'
    with pytest.raises(CoTError):
        link.task = {}


# raise_on_errors {{{1
@pytest.mark.parametrize("errors,raises", (([], False,), (["foo"], True)))
def test_raise_on_errors(errors, raises):
    if raises:
        with pytest.raises(CoTError):
            cotverify.raise_on_errors(errors)
    else:
        cotverify.raise_on_errors(errors)


# audit_log_handler {{{1
def test_audit_log_handler(rw_context, mocker):
    cotverify.log.setLevel(logging.DEBUG)
    with cotverify.audit_log_handler(rw_context):
        cotverify.log.info("foo")
    cotverify.log.info("bar")
    audit_path = os.path.join(rw_context.config['artifact_dir'], 'public', 'cot', "audit.log")
    with open(audit_path, "r") as fh:
        contents = fh.read().splitlines()
    assert len(contents) == 1
    assert contents[0].endswith("foo")
