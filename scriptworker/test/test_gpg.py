#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.gpg
"""
import os
import pytest
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerTaskException
import scriptworker.gpg as gpg
from . import GOOD_GPG_KEYS, BAD_GPG_KEYS


# constants helpers and fixtures {{{1
@pytest.fixture(scope='function')
def context():
    GPG_HOME = os.path.join(os.path.dirname(__file__), "data", "gpg")
    context = Context()
    context.config = {
        "gpg_home": GPG_HOME,
        "gpg_encoding": None,
        "gpg_options": None,
        "gpg_path": os.environ.get("GPG_PATH", None),
        "gpg_public_keyring": os.path.join(GPG_HOME, "pubring.gpg"),
        "gpg_secret_keyring": os.path.join(GPG_HOME, "secring.gpg"),
        "gpg_use_agent": None,
    }
    return context


# tests {{{1
@pytest.mark.parametrize("params", GOOD_GPG_KEYS.items())
def test_verify_good_signatures(context, params):
    data = gpg.sign(context, "foo", keyid=params[1]["fingerprint"])
    gpg.verify_signature(context, data)


@pytest.mark.parametrize("params", BAD_GPG_KEYS.items())
def test_verify_bad_signatures(context, params):
    data = gpg.sign(context, "foo", keyid=params[1]["fingerprint"])
    with pytest.raises(ScriptWorkerTaskException):
        gpg.verify_signature(context, data)
