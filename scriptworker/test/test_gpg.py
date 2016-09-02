#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.gpg
"""
import arrow
import mock
import os
import pytest
import tempfile
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerGPGException
import scriptworker.gpg as sgpg
from . import GOOD_GPG_KEYS, BAD_GPG_KEYS


# constants helpers and fixtures {{{1
GPG_HOME = os.path.join(os.path.dirname(__file__), "data", "gpg")

TEXT = {
    # from https://github.com/SecurityInnovation/PGPy/blob/develop/tests/test_01_types.py
    'english': 'The quick brown fox jumped over the lazy dog',
    # this hiragana pangram comes from http://www.columbia.edu/~fdc/utf8/
    'hiragana': 'いろはにほへど　ちりぬるを\n'
                'わがよたれぞ　つねならむ\n'
                'うゐのおくやま　けふこえて\n'
                'あさきゆめみじ　ゑひもせず',

    'poo': 'Hello, \U0001F4A9!\n\n',
}

GPG_CONF_BASE = "personal-digest-preferences SHA512 SHA384\n" + \
                "cert-digest-algo SHA256\n" + \
                "default-preference-list SHA512 SHA384 AES256 ZLIB BZIP2 ZIP Uncompressed\n" + \
                "keyid-format 0xlong\n"
GPG_CONF_KEYSERVERS = "keyserver key1\nkeyserver key2\nkeyserver-options auto-key-retrieve\n"
GPG_CONF_FINGERPRINT = "default-key MY_FINGERPRINT\n"
GPG_CONF_PARAMS = ((
    [], None, GPG_CONF_BASE
), (
    ["key1", "key2"], None, GPG_CONF_BASE + GPG_CONF_KEYSERVERS
), (
    [], "MY_FINGERPRINT", GPG_CONF_BASE + GPG_CONF_FINGERPRINT
), (
    ["key1", "key2"], "MY_FINGERPRINT", GPG_CONF_BASE + GPG_CONF_KEYSERVERS + GPG_CONF_FINGERPRINT
))

GENERATE_KEY_EXPIRATION = ((
    None, ''
), (
    "2017-10-1", "2017-10-1"
))


def get_context(homedir):
    context = Context()
    context.config = {
        "gpg_home": homedir,
        "gpg_encoding": None,
        "gpg_options": None,
        "gpg_path": os.environ.get("GPG_PATH", None),
        "gpg_public_keyring": os.path.join(homedir, "pubring.gpg"),
        "gpg_secret_keyring": os.path.join(homedir, "secring.gpg"),
        "gpg_use_agent": None,
    }
    return context


@pytest.fixture(scope='function')
def context():
    return get_context(GPG_HOME)


# gpg_default_args {{{1
def test_gpg_default_args():
    expected = [
        "--homedir", GPG_HOME,
        "--no-default-keyring",
        "--secret-keyring", os.path.join(GPG_HOME, "secring.gpg"),
        "--keyring", os.path.join(GPG_HOME, "pubring.gpg"),
    ]
    assert sgpg.gpg_default_args(GPG_HOME) == expected


# guess_gpg_home {{{1
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


# signatures {{{1
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


@pytest.mark.parametrize("text", [v for _, v in sorted(TEXT.items())])
@pytest.mark.parametrize("params", GOOD_GPG_KEYS.items())
def test_get_body(context, text, params):
    gpg = sgpg.GPG(context)
    data = sgpg.sign(gpg, text, keyid=params[1]["fingerprint"])
    if not text.endswith('\n'):
        text = "{}\n".format(text)
    assert sgpg.get_body(gpg, data) == text


# create_gpg_conf {{{1
@pytest.mark.parametrize("keyservers,fingerprint,expected", GPG_CONF_PARAMS)
def test_create_gpg_conf(keyservers, fingerprint, expected):
    with tempfile.TemporaryDirectory() as tmp:
        sgpg.create_gpg_conf(tmp, keyservers=keyservers, my_fingerprint=fingerprint)
        with open(os.path.join(tmp, "gpg.conf"), "r") as fh:
            assert fh.read() == expected


def test_create_second_gpg_conf(mocker):
    now = arrow.utcnow()
    with mock.patch.object(arrow, 'utcnow') as p:
        p.return_value = now
        with tempfile.TemporaryDirectory() as tmp:
            sgpg.create_gpg_conf(
                tmp, keyservers=GPG_CONF_PARAMS[0][0], my_fingerprint=GPG_CONF_PARAMS[0][1]
            )
            sgpg.create_gpg_conf(
                tmp, keyservers=GPG_CONF_PARAMS[1][0], my_fingerprint=GPG_CONF_PARAMS[1][1]
            )
            with open(os.path.join(tmp, "gpg.conf"), "r") as fh:
                assert fh.read() == GPG_CONF_PARAMS[1][2]
            with open(os.path.join(tmp, "gpg.conf.{}".format(now.timestamp)), "r") as fh:
                assert fh.read() == GPG_CONF_PARAMS[0][2]


# generate_key {{{1
@pytest.mark.parametrize("expires,expected", GENERATE_KEY_EXPIRATION)
def test_generate_key(expires, expected):
    with tempfile.TemporaryDirectory() as tmp:
        context = get_context(tmp)
        gpg = sgpg.GPG(context)
        fingerprint = sgpg.generate_key(gpg, "foo", "bar", "baz", expiration=expires)
        for key in gpg.list_keys():
            if key['fingerprint'] == fingerprint:
                assert key['uids'] == ['foo (bar) <baz>']
                assert key['expires'] == expected
                assert key['trust'] == 'u'
                assert key['length'] == '4096'
