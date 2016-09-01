#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.gpg
"""
import os
import pytest
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerGPGException
import scriptworker.gpg as sgpg
from . import GOOD_GPG_KEYS, BAD_GPG_KEYS


# constants helpers and fixtures {{{1
GPG_HOME = os.path.join(os.path.dirname(__file__), "data", "gpg")


@pytest.fixture(scope='function')
def context():
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
def test_gpg_default_args():
    expected = [
        "--homedir", GPG_HOME,
        "--no-default-keyring",
        "--secret-keyring", os.path.join(GPG_HOME, "secring.gpg"),
        "--keyring", os.path.join(GPG_HOME, "pubring.gpg"),
    ]
    assert sgpg.gpg_default_args(GPG_HOME) == expected


@pytest.mark.parametrize("gpg_home,expected", (("foo", "foo"), (None, GPG_HOME)))
def test_guess_gpg_home(context, gpg_home, expected):
    assert sgpg.guess_gpg_home(context, gpg_home=gpg_home) == expected


@pytest.mark.parametrize("gpg_home,expected", (("foo", "foo"), (None, "bar")))
def test_guess_gpg_home_GPG(context, gpg_home, expected):
    gpg = sgpg.GPG(context, "bar")
    assert sgpg.guess_gpg_home(gpg, gpg_home) == expected


def test_guess_gpg_home_exception(context, mocker):
    env = {}
    context.config['gpg_home'] = None
    mocker.patch.object(os, "environ", new=env)
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.guess_gpg_home(context)


@pytest.mark.parametrize("params", GOOD_GPG_KEYS.items())
def test_verify_good_signatures(context, params):
    gpg = sgpg.GPG(context)
    data = sgpg.sign(gpg, "foo", keyid=params[1]["fingerprint"])
    sgpg.verify_signature(gpg, data)


@pytest.mark.parametrize("params", BAD_GPG_KEYS.items())
def test_verify_bad_signatures(context, params):
    gpg = sgpg.GPG(context)
    data = sgpg.sign(gpg, "foo", keyid=params[1]["fingerprint"])
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.verify_signature(gpg, data)
