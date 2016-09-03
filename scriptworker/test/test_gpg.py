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

EXPORT_KEY_PARAMS = ((
    "4ACA2B25224905DA", False, os.path.join(GPG_HOME, "keys", "unknown@example.com.pub")
), (
    "4ACA2B25224905DA", True, os.path.join(GPG_HOME, "keys", "unknown@example.com.sec")
))


def versionless(ascii_key):
    """Strip the gpg version out of a key, to aid in comparison
    """
    new = []
    for line in ascii_key.split('\n'):
        if line and not line.startswith("Version: "):
            new.append("{}\n".format(line))
    return ''.join(new)


def get_context(homedir):
    """Use this function to get a context obj pointing at any directory as
    gnupghome.
    """
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
    """Use this fixture to use the existing gpg homedir in the data/ directory
    (treat this as read-only)
    """
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


# guess_gpg_* {{{1
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


@pytest.mark.parametrize("gpg_path, expected", (("path/to/gpg", "path/to/gpg"), (None, "gpg")))
def test_guess_gpg_path(context, gpg_path, expected):
    context.config['gpg_path'] = gpg_path
    assert sgpg.guess_gpg_path(context) == expected


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


# export_key {{{1
@pytest.mark.parametrize("fingerprint,private,expected", EXPORT_KEY_PARAMS)
def test_export_key(context, fingerprint, private, expected):
    gpg = sgpg.GPG(context)
    key = sgpg.export_key(gpg, fingerprint, private=private) + "\n"
    with open(expected, "r") as fh:
        contents = fh.read()
        assert contents == key + "\n" or versionless(contents) == versionless(key)


def test_export_unknown_key(context):
    gpg = sgpg.GPG(context)
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.export_key(gpg, "illegal_fingerprint_lksjdflsjdkls")


# sign_key {{{1
def test_sign_key():
    """
tru:o:1:1472876459:1:3:1:5
pub:u:4096:1:EA608995918B2DF9:1472876455:::u:::escaESCA:
fpr:::::::::A9F598A3179551CC664C15DEEA608995918B2DF9:
uid:u::::1472876455::6477C0BAC30FB3E244C8F1907D78C6B243AFD516::two (two) <two>:
sig:::1:EA608995918B2DF9:1472876455::::two (two) <two>:13x:::::8:
sig:::1:9633F5F38B9BD3C5:1472876459::::one (one) <one>:10l:::::8:


tru::1:1472876460:0:3:1:5
pub:u:4096:1:BC76BF8F77D1B3F5:1472876457:::u:::escaESCA:
fpr:::::::::7CFAD9E699D8559F1D3A50CCBC76BF8F77D1B3F5:
uid:u::::1472876457::91AC286E48FDA7378B86F63FA6DDC2A46B54808F::three (three) <three>:
sig:::1:BC76BF8F77D1B3F5:1472876457::::three (three) <three>:13x:::::8:
    """
    with tempfile.TemporaryDirectory() as tmp:
        context = get_context(tmp)
        gpg = sgpg.GPG(context)
        my_fingerprint = sgpg.generate_key(gpg, "one", "one", "one")
        signed_fingerprint = sgpg.generate_key(gpg, "two", "two", "two")
        unsigned_fingerprint = sgpg.generate_key(gpg, "three", "three", "three")
        sgpg.create_gpg_conf(tmp, my_fingerprint=my_fingerprint)
        sgpg.sign_key(context, signed_fingerprint)
        signed_output = sgpg.list_key_signatures(context, signed_fingerprint)
        unsigned_output = sgpg.list_key_signatures(context, unsigned_fingerprint)
        # TODO we need a function in sgpg
        assert "two (two) <two>" in signed_output
        assert "one (one) <one>" in signed_output
        assert "three (three) <three>" in unsigned_output
        assert "one (one) <one>" not in unsigned_output
