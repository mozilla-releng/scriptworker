#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.gpg
"""
import arrow
import asyncio
from contextlib import contextmanager
from copy import deepcopy
import glob
import json
import mock
import os
import pexpect
import pytest
import shutil
import subprocess
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerGPGException, ScriptWorkerRetryException
import scriptworker.gpg as sgpg
from . import GOOD_GPG_KEYS, BAD_GPG_KEYS, event_loop, noop_async, noop_sync, tmpdir, tmpdir2, touch

assert event_loop, tmpdir  # silence pyflakes
assert tmpdir2  # silence pyflakes


# constants helpers and fixtures {{{1
GPG_HOME = os.path.join(os.path.dirname(__file__), "data", "gpg")
PUBKEY_DIR = os.path.join(os.path.dirname(__file__), "data", "pubkeys")

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
GPG_CONF_KEYSERVERS = "keyserver key1\nkeyserver-options auto-key-retrieve\n"
GPG_CONF_FINGERPRINT = "default-key MY_FINGERPRINT\n"
GPG_CONF_PARAMS = ((
    None, None, GPG_CONF_BASE
), (
    "key1", None, GPG_CONF_BASE + GPG_CONF_KEYSERVERS
), (
    None, "MY_FINGERPRINT", GPG_CONF_BASE + GPG_CONF_FINGERPRINT
), (
    "key1", "MY_FINGERPRINT", GPG_CONF_BASE + GPG_CONF_KEYSERVERS + GPG_CONF_FINGERPRINT
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

KEYS_AND_FINGERPRINTS = ((
    "D9DC50F64C7D44CF", "FB7765CD0FC616FF7AC961A1D9DC50F64C7D44CF",
    os.path.join(GPG_HOME, "keys", "scriptworker@example.com"),
), (
    "9DA033D5FFFABCCF", "BFCEA6E98A1C2EC4918CBDEE9DA033D5FFFABCCF",
    os.path.join(GPG_HOME, "keys", "docker.root@example.com"),
), (
    "CD3C13EFBEAB7ED4", "F612354DFAF46BAADAE23801CD3C13EFBEAB7ED4",
    os.path.join(GPG_HOME, "keys", "docker@example.com"),
), (
    "4ACA2B25224905DA", "B45FE2F4035C3786120998174ACA2B25224905DA",
    os.path.join(GPG_HOME, "keys", "unknown@example.com"),
))

VERIFY_GIT_OUTPUT_BAD_PARAMS = (
    "Author: Aki Sasaki <aki@escapewindow.com>\nDate:   Mon Sep 19 21:50:35 2016 -0700\n\n    add another check + small fixes + comments",

    """commit 6efb4ebe8900ad1920f6eaaf64b615fe6e6e839a
gpg: Signature made Mon Sep 19 21:50:53 2016 PDT
gpg:                using RSA key FC829B7FFAA9AC38
gpg: Good signature from "Aki Sasaki (2016.09.16) <aki@escapewindow.com>" [unknown]
gpg:                 aka "Aki Sasaki (2016.09.16) <aki@mozilla.com>" [unknown]
gpg:                 aka "Aki Sasaki (2016.09.16) <asasaki@mozilla.com>" [unknown]
gpg:                 aka "[jpeg image of size 5283]" [unknown]
gpg: WARNING: This key is not certified with a trusted signature!
gpg:          There is no indication that the signature belongs to the owner.
Primary key fingerprint: 83A4 B550 BC68 2F0B 0601  57B0 4654 904B B484 B6B2
     Subkey fingerprint: CC62 C097 98FD EFBB 4CC9  4D9C FC82 9B7F FAA9 AC38
Author: Aki Sasaki <aki@escapewindow.com>
Date:   Mon Sep 19 21:50:35 2016 -0700

    add another check + small fixes + comments
""",

    """commit 6efb4ebe8900ad1920f6eaaf64b615fe6e6e839a
gpg: directory `/Users/asasaki/.gnupg' created
gpg: new configuration file `/Users/asasaki/.gnupg/gpg.conf' created
gpg: WARNING: options in `/Users/asasaki/.gnupg/gpg.conf' are not yet active during this run
gpg: keyring `/Users/asasaki/.gnupg/pubring.gpg' created
gpg: Signature made Mon Sep 19 21:50:53 2016 PDT
gpg:                using RSA key FC829B7FFAA9AC38
gpg: Can't check signature: No public key
Author: Aki Sasaki <aki@escapewindow.com>
Date:   Mon Sep 19 21:50:35 2016 -0700

    add another check + small fixes + comments
""",
)

VERIFY_GIT_OUTPUT_GOOD_PARAMS = (
    """commit 6efb4ebe8900ad1920f6eaaf64b615fe6e6e839a
gpg: Signature made Mon Sep 19 21:50:53 2016 PDT
gpg:                using RSA key FC829B7FFAA9AC38
gpg: checking the trustdb
gpg: 3 marginal(s) needed, 1 complete(s) needed, PGP trust model
gpg: depth: 0  valid:   1  signed:   0  trust: 0-, 0q, 0n, 0m, 0f, 1u
gpg: next trustdb check due at 2018-09-17
gpg: Good signature from "Aki Sasaki (2016.09.16) <aki@escapewindow.com>" [ultimate]
gpg:                 aka "Aki Sasaki (2016.09.16) <aki@mozilla.com>" [ultimate]
gpg:                 aka "Aki Sasaki (2016.09.16) <asasaki@mozilla.com>" [ultimate]
gpg:                 aka "[jpeg image of size 5283]" [ultimate]
Author: Aki Sasaki <aki@escapewindow.com>
Date:   Mon Sep 19 21:50:35 2016 -0700

    add another check + small fixes + comments
""",
    """commit 6efb4ebe8900ad1920f6eaaf64b615fe6e6e839a
gpg: Signature made Mon Sep 19 21:50:53 2016 PDT
gpg:                using RSA key FC829B7FFAA9AC38
gpg: checking the trustdb
gpg: 3 marginal(s) needed, 1 complete(s) needed, PGP trust model
gpg: depth: 0  valid:   1  signed:   0  trust: 0-, 0q, 0n, 0m, 0f, 1u
gpg: next trustdb check due at 2018-09-17
gpg: Good signature from "Aki Sasaki (2016.09.16) <aki@escapewindow.com>" [trusted]
gpg:                 aka "Aki Sasaki (2016.09.16) <aki@mozilla.com>" [trusted]
gpg:                 aka "Aki Sasaki (2016.09.16) <asasaki@mozilla.com>" [trusted]
gpg:                 aka "[jpeg image of size 5283]" [trusted]
Author: Aki Sasaki <aki@escapewindow.com>
Date:   Mon Sep 19 21:50:35 2016 -0700

    add another check + small fixes + comments
""",
    """commit 02dc29251021519ebac4508545477a7b23efea49
gpg: Signature made Tue Sep 20 04:22:57 2016 UTC
gpg:                using RSA key 0xFC829B7FFAA9AC38
gpg: Good signature from "Aki Sasaki (2016.09.16) <aki@escapewindow.com>"
gpg:                 aka "Aki Sasaki (2016.09.16) <aki@mozilla.com>"
gpg:                 aka "Aki Sasaki (2016.09.16) <asasaki@mozilla.com>"
gpg:                 aka "[jpeg image of size 5283]"
Author: Aki Sasaki <aki@escapewindow.com>
Date:   Mon Sep 19 21:22:40 2016 -0700

    add travis tests for commit signatures.
""",
)


def versionless(ascii_key):
    """Strip the gpg version out of a key, to aid in comparison
    """
    new = []
    for line in ascii_key.split('\n'):
        if line and not line.startswith("Version: "):
            new.append("{}\n".format(line))
    return ''.join(new)


def die_sync(*args, **kwargs):
    raise ScriptWorkerGPGException("foo")


async def die_async(*args, **kwargs):
    raise ScriptWorkerGPGException("foo")


def check_sigs(context, manifest, pubkey_dir, trusted_emails=None):
    messages = []
    gpg = sgpg.GPG(context)
    for fingerprint, info in manifest.items():
        try:
            with open(os.path.join(pubkey_dir, "data", "{}.asc".format(fingerprint))) as fh:
                message = sgpg.get_body(gpg, fh.read())
            if message != info['message'] + '\n':
                messages.append(
                    "Unexpected message '{}', expected '{}'".format(message, info['message'])
                )
        except ScriptWorkerGPGException as exc:
            if trusted_emails and info['signing_email'] not in trusted_emails:
                pass
            else:
                messages.append("{} {} error: {}".format(fingerprint, info['signing_email'], str(exc)))
    return messages


@pytest.yield_fixture(scope='function')
def context(tmpdir2):
    """Use this function to get a context obj pointing at any directory as
    gnupghome.
    """
    context_ = Context()
    context_.config = dict(deepcopy(DEFAULT_CONFIG))
    cot_config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "cot_config_example.json"
    )
    for key, value in context_.config.items():
        if key.endswith("_dir") or key in ("gpg_home", ):
            context_.config[key] = os.path.join(tmpdir2, key)
    context_.config['sign_key_timeout'] = 5 * 60
    with open(cot_config_path) as fh:
        context_.cot_config = json.load(fh)
    yield context_


class PexpectChild():
    """Pretend to be a pexpect child proc for sign_key failures
    """
    def __init__(self, exitstatus=1, expect_status=1, signalstatus=None, exc=False):
        self.exitstatus = exitstatus
        self.expect_status = expect_status
        self.signalstatus = signalstatus
        self.exc = exc

    @asyncio.coroutine
    def expect(self, _, **kwargs):
        if self.exc:
            raise pexpect.exceptions.TIMEOUT("")
        return 0

    def sendline(*_):
        pass

    def close(*_):
        pass


class FakeProc():
    """Pretend to be a subprocess proc
    """
    def __init__(self, returncode=1, args=(), output=b''):
        self.returncode = returncode
        self.args = args
        self.output = output

    def communicate(self, *args, **kwargs):
        return (self.output, b'')

    def poll(self, *args, **kwargs):
        return self.returncode


@pytest.yield_fixture(scope='function')
def base_context(context):
    """Use this fixture to use the existing gpg homedir in the data/ directory
    (treat this as read-only)
    """
    context.config['gpg_home'] = GPG_HOME
    yield context


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
def test_guess_gpg_home(base_context, gpg_home, expected):
    assert sgpg.guess_gpg_home(base_context, gpg_home=gpg_home) == expected


@pytest.mark.parametrize("gpg_home,expected", (("foo", "foo"), (None, "bar")))
def test_guess_gpg_home_GPG(base_context, gpg_home, expected):
    gpg = sgpg.GPG(base_context, "bar")
    assert sgpg.guess_gpg_home(gpg, gpg_home) == expected


def test_guess_gpg_home_exception(base_context, mocker):
    env = {}
    base_context.config['gpg_home'] = None
    mocker.patch.object(os, "environ", new=env)
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.guess_gpg_home(base_context)


@pytest.mark.parametrize("gpg_path, expected", (("path/to/gpg", "path/to/gpg"), (None, "gpg")))
def test_guess_gpg_path(base_context, gpg_path, expected):
    base_context.config['gpg_path'] = gpg_path
    assert sgpg.guess_gpg_path(base_context) == expected


# keyid / fingerprint conversion {{{1
@pytest.mark.parametrize("keyid,fingerprint,path", KEYS_AND_FINGERPRINTS)
def test_keyid_fingerprint_conversion(base_context, keyid, fingerprint, path):
    gpg = sgpg.GPG(base_context)
    assert path
    assert sgpg.keyid_to_fingerprint(gpg, keyid) == fingerprint
    assert sgpg.fingerprint_to_keyid(gpg, fingerprint) == keyid


@pytest.mark.parametrize("keyid,fingerprint,path", KEYS_AND_FINGERPRINTS)
def test_keyid_fingerprint_exception(base_context, keyid, fingerprint, path):
    gpg = sgpg.GPG(base_context)
    assert path
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.keyid_to_fingerprint(gpg, keyid.replace('C', '1').replace('F', 'C'))
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.fingerprint_to_keyid(gpg, fingerprint.replace('C', '1').replace('F', 'C'))


# signatures {{{1
@pytest.mark.parametrize("params", GOOD_GPG_KEYS.items())
def test_verify_good_signatures(base_context, params):
    gpg = sgpg.GPG(base_context)
    data = sgpg.sign(gpg, "foo", keyid=params[1]["fingerprint"])
    sgpg.verify_signature(gpg, data)


@pytest.mark.parametrize("params", BAD_GPG_KEYS.items())
def test_verify_bad_signatures(base_context, params):
    gpg = sgpg.GPG(base_context)
    data = sgpg.sign(gpg, "foo", keyid=params[1]["fingerprint"])
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.verify_signature(gpg, data)


@pytest.mark.parametrize("text", [v for _, v in sorted(TEXT.items())])
@pytest.mark.parametrize("params", GOOD_GPG_KEYS.items())
def test_get_body(base_context, text, params):
    gpg = sgpg.GPG(base_context)
    data = sgpg.sign(gpg, text, keyid=params[1]["fingerprint"])
    if not text.endswith('\n'):
        text = "{}\n".format(text)
    assert sgpg.get_body(gpg, data) == text


# create_gpg_conf {{{1
@pytest.mark.parametrize("keyserver,fingerprint,expected", GPG_CONF_PARAMS)
def test_create_gpg_conf(keyserver, fingerprint, expected, tmpdir):
    sgpg.create_gpg_conf(tmpdir, keyserver=keyserver, my_fingerprint=fingerprint)
    with open(os.path.join(tmpdir, "gpg.conf"), "r") as fh:
        assert fh.read() == expected


def test_create_second_gpg_conf(mocker, tmpdir):
    now = arrow.utcnow()
    with mock.patch.object(arrow, 'utcnow') as p:
        p.return_value = now
        sgpg.create_gpg_conf(
            tmpdir, keyserver=GPG_CONF_PARAMS[0][0], my_fingerprint=GPG_CONF_PARAMS[0][1]
        )
        sgpg.create_gpg_conf(
            tmpdir, keyserver=GPG_CONF_PARAMS[1][0], my_fingerprint=GPG_CONF_PARAMS[1][1]
        )
        with open(os.path.join(tmpdir, "gpg.conf"), "r") as fh:
            assert fh.read() == GPG_CONF_PARAMS[1][2]
        with open(os.path.join(tmpdir, "gpg.conf.{}".format(now.timestamp)), "r") as fh:
            assert fh.read() == GPG_CONF_PARAMS[0][2]


# generate_key {{{1
@pytest.mark.parametrize("expires,expected", GENERATE_KEY_EXPIRATION)
def test_generate_key(context, expires, expected, tmpdir):
    gpg = sgpg.GPG(context)
    fingerprint = sgpg.generate_key(gpg, "foo", "bar", "baz", expiration=expires)
    for key in gpg.list_keys():
        if key['fingerprint'] == fingerprint:
            assert key['uids'] == ['foo (bar) <baz>']
            assert key['expires'] == expected
            assert key['trust'] == 'u'
            assert key['length'] == '4096'


# import / export keys {{{1
@pytest.mark.parametrize("suffix", (".pub", ".sec"))
@pytest.mark.parametrize("return_type", ("fingerprints", "result"))
def test_import_single_key(context, suffix, return_type):
    gpg = sgpg.GPG(context)
    with open("{}{}".format(KEYS_AND_FINGERPRINTS[0][2], suffix), "r") as fh:
        contents = fh.read()
    result = sgpg.import_key(gpg, contents, return_type=return_type)
    if return_type == 'result':
        fingerprints = []
        for entry in result:
            fingerprints.append(entry['fingerprint'])
    else:
        fingerprints = result
    # the .sec fingerprints are doubled; use set() for unsorted & uniq
    assert set(fingerprints) == set([KEYS_AND_FINGERPRINTS[0][1]])


@pytest.mark.parametrize("fingerprint,private,expected", EXPORT_KEY_PARAMS)
def test_export_key(base_context, fingerprint, private, expected):
    gpg = sgpg.GPG(base_context)
    key = sgpg.export_key(gpg, fingerprint, private=private) + "\n"
    with open(expected, "r") as fh:
        contents = fh.read()
        assert contents == key + "\n" or versionless(contents) == versionless(key)


def test_export_unknown_key(base_context):
    gpg = sgpg.GPG(base_context)
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.export_key(gpg, "illegal_fingerprint_lksjdflsjdkls")


# sign_key {{{1
@pytest.mark.asyncio
async def test_sign_key(context, event_loop):
    """This test calls get_list_sigs_output in several different ways.  Each
    is valid; the main thing is more code coverage.

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
    gpg = sgpg.GPG(context)
    # create my key, get fingerprint + keyid
    my_fingerprint = sgpg.generate_key(gpg, "one", "one", "one")
    my_keyid = sgpg.fingerprint_to_keyid(gpg, my_fingerprint)
    # create signed key, get fingerprint + keyid
    signed_fingerprint = sgpg.generate_key(gpg, "two", "two", "two")
    signed_keyid = sgpg.fingerprint_to_keyid(gpg, signed_fingerprint)
    # create unsigned key, get fingerprint + keyid
    unsigned_fingerprint = sgpg.generate_key(gpg, "three", "three", "three")
    unsigned_keyid = sgpg.fingerprint_to_keyid(gpg, unsigned_fingerprint)
    # update gpg configs, sign signed key
    sgpg.create_gpg_conf(context.config['gpg_home'], my_fingerprint=my_fingerprint)
    sgpg.check_ownertrust(context)
    await sgpg.sign_key(context, signed_fingerprint)
    # signed key get_list_sigs_output
    signed_output = sgpg.get_list_sigs_output(context, signed_fingerprint)
    # unsigned key get_list_sigs_output
    # Call get_list_sigs_output with validate=False, then parse it, for more code coverage
    unsigned_output1 = sgpg.get_list_sigs_output(context, unsigned_fingerprint, validate=False)
    unsigned_output = sgpg.parse_list_sigs_output(unsigned_output1, "unsigned")
    # signed key has my signature + self-signed
    assert sorted([signed_keyid, my_keyid]) == sorted(signed_output['sig_keyids'])
    assert ["one (one) <one>", "two (two) <two>"] == sorted(signed_output['sig_uids'])
    # unsigned key is only self-signed
    assert [unsigned_keyid] == unsigned_output['sig_keyids']
    assert ["three (three) <three>"] == unsigned_output['sig_uids']
    # sign the unsigned key and test
    await sgpg.sign_key(context, unsigned_fingerprint, signing_key=signed_fingerprint)
    # Call get_list_sigs_output with expected, for more code coverage
    new_output = sgpg.get_list_sigs_output(
        context, unsigned_fingerprint, expected={
            "keyid": unsigned_keyid,
            "fingerprint": unsigned_fingerprint,
            "uid": "three (three) <three>",
            "sig_keyids": [signed_keyid, unsigned_keyid],
            "sig_uids": ["three (three) <three>", "two (two) <two>"]
        }
    )
    # sig_uids goes unchecked; sig_keyids only checks that it's a subset.
    # let's do another check.
    assert ["three (three) <three>", "two (two) <two>"] == sorted(new_output['sig_uids'])


@pytest.mark.asyncio
async def test_sign_key_twice(context):
    gpg = sgpg.GPG(context)
    for suffix in (".sec", ".pub"):
        with open("{}{}".format(KEYS_AND_FINGERPRINTS[0][2], suffix), "r") as fh:
            contents = fh.read()
        fingerprint = sgpg.import_key(gpg, contents)[0]
    # keys already sign themselves, so this is a second signature that should
    # be noop.
    await sgpg.sign_key(context, fingerprint, signing_key=fingerprint)


@pytest.mark.asyncio
@pytest.mark.parametrize("exportable", (True, False))
async def test_sign_key_exportable(context, exportable, event_loop):
    gpg_home2 = os.path.join(context.config['gpg_home'], "two")
    context.config['gpg_home'] = os.path.join(context.config['gpg_home'], "one")
    gpg = sgpg.GPG(context)
    gpg2 = sgpg.GPG(context, gpg_home=gpg_home2)
    my_fingerprint = KEYS_AND_FINGERPRINTS[0][1]
    my_keyid = KEYS_AND_FINGERPRINTS[0][0]
    # import my keys
    for suffix in (".sec", ".pub"):
        with open("{}{}".format(KEYS_AND_FINGERPRINTS[0][2], suffix), "r") as fh:
            contents = fh.read()
            sgpg.import_key(gpg, contents)
    # create gpg.conf's
    sgpg.create_gpg_conf(context.config['gpg_home'], my_fingerprint=my_fingerprint)
    sgpg.create_gpg_conf(gpg_home2, my_fingerprint=my_fingerprint)
    sgpg.check_ownertrust(context)
    sgpg.check_ownertrust(context, gpg_home=gpg_home2)
    # generate a new key
    fingerprint = sgpg.generate_key(gpg, "one", "one", "one")
    # sign it, exportable signature is `exportable`
    await sgpg.sign_key(context, fingerprint, signing_key=my_fingerprint, exportable=exportable)
    # export my privkey and import it in gpg_home2
    priv_key = sgpg.export_key(gpg, my_fingerprint, private=True)
    sgpg.import_key(gpg2, priv_key)
    # export both pubkeys and import in gpg_home2
    for fp in (my_fingerprint, fingerprint):
        pub_key = sgpg.export_key(gpg, fp)
        sgpg.import_key(gpg2, pub_key)
    # check sigs on `fingerprint` key.  If exportable, we're good.  If not exportable,
    # it'll throw
    expected = {'sig_keyids': [my_keyid]}
    if exportable:
        sgpg.get_list_sigs_output(context, fingerprint, gpg_home=gpg_home2, expected=expected)
    else:
        with pytest.raises(ScriptWorkerGPGException):
            sgpg.get_list_sigs_output(context, fingerprint, gpg_home=gpg_home2, expected=expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("expect_status", (0, 1))
@pytest.mark.parametrize("exc_bool", (False, True))
async def test_sign_key_failure(context, mocker, expect_status, exc_bool):

    def child(*args, **kwargs):
        return PexpectChild(expect_status=expect_status, exc=exc_bool)

    mocker.patch.object(pexpect, 'spawn', new=child)
    mocker.patch.object(pexpect, 'spawn', new=child)
    with pytest.raises(ScriptWorkerGPGException):
        await sgpg.sign_key(context, "foo")


# list sigs and parsing {{{1
def test_get_list_sigs_output_failure(base_context, mocker):

    # check_call needs popen to be a decorator
    @contextmanager
    def popen(*args, **kwargs):
        yield FakeProc(output=b'No public key', returncode=0)

    mocker.patch.object(subprocess, "Popen", new=popen)
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.get_list_sigs_output(base_context, "nonexistent_fingerprint")


def test_parse_trust_line_failure():
    line = 'tru:t:::::::::'
    with pytest.raises(ScriptWorkerGPGException):
        sgpg._parse_trust_line(line, "foo")


def test_parse_pub_line_failure():
    line = 'pub:i::::::::::D:'
    with pytest.raises(ScriptWorkerGPGException):
        sgpg._parse_pub_line(line, "foo")


def test_parse_list_sigs_failure():
    output = """tru::1:1472242430:0:3:1:5
pub:f:2048:1:CD3C13EFBEAB7ED4:1472242430:::-:::escaESCA:
fpr:::::::::F612354DFAF46BAADAE23801CD3C13EFBEAB7ED4:
uid:f::::1472242430::F7EC4B43E7A20A1ED5D875D9FC1EF955269EBC54::Docker Embedded (embedded key for the docker ami) <docker@example.com>:
sig:::1:CD3C13EFBEAB7ED4:1472242430::::Docker Embedded (embedded key for the docker ami) <docker@example.com>:13x:::::8:
sig:::1:9DA033D5FFFABCCF:1472242430::::Docker Root (root key for the docker task keys) <docker.root@example.com>:10l:::::8:
rvk:
"""
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.parse_list_sigs_output(
            output, "foo", expected={
                "keyid": "bad_keyid",
                "fingerprint": "bad_fingerprint",
                "uid": "bad uid",
                "sig_keyids": ["bad sig keyid"],
            }
        )


# ownertrust {{{1
@pytest.mark.parametrize("trusted_names", ((), ("two", "three")))
def test_ownertrust(context, trusted_names):
    """This is a fairly complex test.

    Create a new gnupg_home, update ownertrust with just my fingerprint.
    The original update will run its own verify; we then make sure to get full
    code coverage by testing that extra and missing fingerprints raise a
    ScriptWorkerGPGException.
    """
    gpg = sgpg.GPG(context)
    my_fingerprint = sgpg.generate_key(gpg, "one", "one", "one")
    sgpg.create_gpg_conf(context.config['gpg_home'], my_fingerprint=my_fingerprint)
    trusted_fingerprints = []
    for name in trusted_names:
        trusted_fingerprints.append(sgpg.generate_key(gpg, name, name, name))
    # append my fingerprint to get more coverage
    if trusted_fingerprints:
        trusted_fingerprints.append(my_fingerprint)
    unsigned_fingerprint = sgpg.generate_key(gpg, "four", "four", "four")
    sgpg.update_ownertrust(context, my_fingerprint, trusted_fingerprints=trusted_fingerprints)
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.verify_ownertrust(context, my_fingerprint, trusted_fingerprints + [unsigned_fingerprint])
    if trusted_fingerprints:
        with pytest.raises(ScriptWorkerGPGException):
            sgpg.verify_ownertrust(context, my_fingerprint, [trusted_fingerprints[0]])


def test_update_ownertrust_failure(context, mocker):

    def popen(*args, **kwargs):
        return FakeProc(returncode=1)

    mocker.patch.object(subprocess, 'Popen', new=popen)
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.update_ownertrust(context, "foo")


# consume {{{1
@pytest.mark.parametrize("path,suffixes,expected", ((
    "foo/bar/baz.blah", [".zip", ".bz2"], False
), (
    "/foo/bar/baz.blah", [".blah", ".bz2"], True
)))
def test_has_suffix(path, suffixes, expected):
    assert sgpg.has_suffix(path, suffixes) == expected


@pytest.mark.parametrize("keydir", (__file__, os.path.join(os.path.dirname(__file__), "data", "artifacts")))
def test_consume_valid_keys_exception(context, keydir):
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.consume_valid_keys(context, keydir)


def test_consume_valid_keys_suffixes(context):
    # this shouldn't raise if ignore_suffixes works properly
    sgpg.consume_valid_keys(context, PUBKEY_DIR, ignore_suffixes=('.json', '.asc', '.unsigned.pub'))


def test_rebuild_gpg_home_flat(context, event_loop):
    event_loop.run_until_complete(
        sgpg.rebuild_gpg_home_flat(
            context,
            context.config['gpg_home'],
            "{}{}".format(KEYS_AND_FINGERPRINTS[0][2], ".pub"),
            "{}{}".format(KEYS_AND_FINGERPRINTS[0][2], ".sec"),
            os.path.join(PUBKEY_DIR, "unsigned")
        )
    )
    with open(os.path.join(PUBKEY_DIR, "manifest.json")) as fh:
        manifest = json.load(fh)
    messages = check_sigs(context, manifest, PUBKEY_DIR)
    assert messages == []


@pytest.mark.parametrize("trusted_email", ("docker@example.com", "docker.root@example.com"))
def test_rebuild_gpg_home_signed(context, trusted_email, tmpdir, event_loop):

    gpg = sgpg.GPG(context)
    for path in glob.glob(os.path.join(GPG_HOME, "keys", "{}.*".format(trusted_email))):
        shutil.copyfile(path, os.path.join(tmpdir, os.path.basename(path)))
    event_loop.run_until_complete(
        sgpg.rebuild_gpg_home_signed(
            context,
            context.config['gpg_home'],
            "{}{}".format(KEYS_AND_FINGERPRINTS[0][2], ".pub"),
            "{}{}".format(KEYS_AND_FINGERPRINTS[0][2], ".sec"),
            tmpdir,
        )
    )
    with open(os.path.join(PUBKEY_DIR, "manifest.json")) as fh:
        manifest = json.load(fh)
    for fingerprint, info in manifest.items():
        with open(os.path.join(PUBKEY_DIR, info['signed_path'])) as fh:
            sgpg.import_key(gpg, fh.read())
        if info['signing_email'] == trusted_email:
            sgpg.get_list_sigs_output(
                context, fingerprint, expected={'sig_keyids': [info['signing_keyid']]}
            )
    messages = check_sigs(context, manifest, PUBKEY_DIR, trusted_emails=[trusted_email])
    assert messages == []


# verify_signed_git_commit_output {{{1
@pytest.mark.parametrize("output", VERIFY_GIT_OUTPUT_GOOD_PARAMS)
def test_verify_signed_git_commit_output(output):
    sgpg.verify_signed_git_commit_output(output)


@pytest.mark.parametrize("output", VERIFY_GIT_OUTPUT_BAD_PARAMS)
def test_verify_signed_git_commit_output_exception(output):
    with pytest.raises(ScriptWorkerGPGException):
        sgpg.verify_signed_git_commit_output(output)


# get_git_revision {{{1
@pytest.mark.asyncio
async def test_get_git_revision():
    parent_dir = os.path.dirname(__file__)
    expected = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=parent_dir)
    assert await sgpg.get_git_revision(parent_dir) == expected.decode('utf-8').rstrip()


@pytest.mark.asyncio
async def test_get_git_revision_exception(mocker):
    x = mock.MagicMock()

    async def fake(*args, **kwargs):
        return x

    async def return_1(*args, **kwargs):
        return 1

    async def fake_communicate(*args, **kwargs):
        return ("x", "y")

    x.communicate = fake_communicate
    x.wait = return_1

    parent_dir = os.path.dirname(__file__)
    with pytest.raises(ScriptWorkerRetryException):
        await sgpg.get_git_revision(parent_dir, exec_function=fake)


# update_signed_git_repo {{{1
@pytest.mark.asyncio
@pytest.mark.parametrize("result1,result2,expected,return_value", ((
    "one", "one", False, 0
), (
    "one", "two", True, 0
), (
    "one", "two", True, 1
)))
async def test_update_signed_git_repo(context, mocker, result1, result2, expected,
                                      return_value):
    results = [result1, result2]

    async def fake_revision(*args, **kwargs):
        return results.pop(0)

    async def wait(*args, **kwargs):
        return return_value

    async def fake_exec(*args, **kwargs):
        value = mock.MagicMock()
        value.wait = wait
        return value

    mocker.patch.object(sgpg, "get_git_revision", new=fake_revision)
    if return_value:
        with pytest.raises(ScriptWorkerRetryException):
            await sgpg.update_signed_git_repo(
                context, exec_function=fake_exec, log_function=noop_async)
    else:
        result = await sgpg.update_signed_git_repo(
            context, exec_function=fake_exec, log_function=noop_async)
        assert result == expected


# verify_signed_git_commit {{{1
@pytest.mark.asyncio
async def test_verify_signed_git_commit(context, mocker):
    output = [b'onetwothree', b'onetwothree']

    async def fake_readline():
        if output:
            return output.pop(0)

    stdout = mock.MagicMock()
    stdout.readline = fake_readline

    async def fake_exec(*args, **kwargs):
        m = mock.MagicMock()
        m.stdout = stdout
        return m

    mocker.patch.object(sgpg, "verify_signed_git_commit_output", new=noop_sync)
    await sgpg.verify_signed_git_commit(context, exec_function=fake_exec)


# build_gpg_homedirs_from_repo {{{1
@pytest.mark.asyncio
async def test_build_gpg_homedirs_from_repo(context, mocker):
    homedirs = {'flat': [], 'signed': []}
    expected = {
        'flat': ['docker-worker', 'generic-worker'],
        'signed': ['scriptworker'],
    }

    async def counter(_, path, *args, **kwargs):
        worker_dir = os.path.basename(path)
        key = 'flat'
        if 'untrusted_path' in kwargs:
            key = 'signed'
        homedirs[key].append(worker_dir)
        homedirs[key] = sorted(homedirs[key])

    await sgpg.build_gpg_homedirs_from_repo(
        context, verify_function=noop_async, flat_function=counter, signed_function=counter
    )
    assert homedirs == expected


@pytest.mark.asyncio
async def test_build_gpg_homedirs_from_repo_lockfile(context, mocker):

    os.makedirs(context.config['base_gpg_home_dir'])
    touch(os.path.join(context.config['base_gpg_home_dir'], '.lock'))
    await sgpg.build_gpg_homedirs_from_repo(
        context, verify_function=die_async, flat_function=die_async, signed_function=die_async
    )


# create_initial_gpg_homedirs {{{1
def test_create_initial_gpg_homedirs(context, mocker, event_loop):

    def fake_context(*args):
        return (context, None)

    mocker.patch.object(sgpg, "get_context_from_cmdln", new=fake_context)
    mocker.patch.object(sgpg, "rebuild_gpg_home_signed", new=noop_async)
    mocker.patch.object(sgpg, "retry_async", new=noop_async)
    mocker.patch.object(sgpg, "update_ownertrust", new=noop_sync)
    mocker.patch.object(sgpg, "check_ownertrust", new=noop_sync)
    mocker.patch.object(sgpg, "verify_signed_git_commit", new=noop_async)
    mocker.patch.object(sgpg, "overwrite_gpg_home", new=noop_sync)
    mocker.patch.object(sgpg, "update_signed_git_repo", new=noop_async)
    mocker.patch.object(sgpg, "build_gpg_homedirs_from_repo", new=noop_async)

    sgpg.create_initial_gpg_homedirs()


def test_create_initial_gpg_homedirs_exception(context, mocker, event_loop):

    def fake_context(*args):
        return (context, None)

    mocker.patch.object(sgpg, "get_context_from_cmdln", new=fake_context)
    mocker.patch.object(sgpg, "rebuild_gpg_home_signed", new=die_async)
    mocker.patch.object(sgpg, "retry_async", new=noop_async)
    mocker.patch.object(sgpg, "update_ownertrust", new=noop_sync)
    mocker.patch.object(sgpg, "verify_signed_git_commit", new=noop_async)
    mocker.patch.object(sgpg, "overwrite_gpg_home", new=noop_sync)
    mocker.patch.object(sgpg, "update_signed_git_repo", new=noop_async)
    mocker.patch.object(sgpg, "build_gpg_homedirs_from_repo", new=noop_async)

    with pytest.raises(SystemExit):
        sgpg.create_initial_gpg_homedirs()


# rebuild_gpg_homedirs_loop {{{1
@pytest.mark.asyncio
async def test_rebuild_gpg_homedirs_loop(context, mocker):
    """Try to hit all the parts of the actual loop
    """
    counts = {
        "rm_basedir": 0,
        "return_none": 0,
        "raise": 0
    }
    basedir = context.config['base_gpg_home_dir']

    async def rm_basedir_2nd_pass(*args, **kwargs):
        counts['rm_basedir'] += 1
        if counts['rm_basedir'] > 1 and os.path.exists(basedir):
            shutil.rmtree(basedir)

    async def return_none_1st_pass(*args, **kwargs):
        counts['return_none'] += 1
        if counts['return_none'] > 1:
            return True

    def raise_1st_die_2nd(*args, **kwargs):
        counts['raise'] += 1
        if counts['raise'] == 1:
            raise ScriptWorkerGPGException("foo")
        else:
            raise SystemExit()

    context.config['sign_chain_of_trust'] = True
    context.config['verify_chain_of_trust'] = True
    os.makedirs(basedir)
    mocker.patch.object(sgpg, "rm", new=noop_sync)
    mocker.patch.object(asyncio, "sleep", new=rm_basedir_2nd_pass)
    mocker.patch.object(sgpg, "retry_async", new=return_none_1st_pass)
    mocker.patch.object(sgpg, "build_gpg_homedirs_from_repo", new=raise_1st_die_2nd)

    with pytest.raises(SystemExit):
        await sgpg.rebuild_gpg_homedirs_loop(context, basedir)


@pytest.mark.asyncio
async def test_rebuild_gpg_homedirs_loop_skip(context, tmpdir, mocker):
    path = os.path.join(tmpdir, "foo")
    context.config['sign_chain_of_trust'] = False
    context.config['verify_chain_of_trust'] = False
    mocker.patch.object(asyncio, "sleep", new=die_sync)
    mocker.patch.object(sgpg, "retry_async", new=die_async)
    await sgpg.rebuild_gpg_homedirs_loop(context, path)
