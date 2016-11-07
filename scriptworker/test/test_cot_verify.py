#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.cot.verify
"""
import logging
import pytest
from scriptworker.exceptions import CoTError
import scriptworker.cot.verify as verify
from . import rw_context

assert rw_context  # silence pyflakes

# TODO remove once we use
assert CoTError, verify
assert pytest

log = logging.getLogger(__name__)


# constants helpers and fixtures {{{1
@pytest.yield_fixture(scope='function')
def chain_of_trust(rw_context):
    pass
