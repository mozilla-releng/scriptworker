import base64
import json
import os
import pytest

import scriptworker.ed25519 as swed25519
from scriptworker.exceptions import ScriptWorkerEd25519Error
from scriptworker.utils import load_json_or_yaml, read_from_file

from . import touch, rw_context, fake_session, fake_session_500, successful_queue

ED25519_DIR = os.path.join(os.path.dirname(__file__), 'data', 'ed25519')


def test_from_file():
    privkey_path = os.path.join(ED25519_DIR, 'scriptworker_private_key')
    privkey_string = read_from_file(privkey_path)
    privkey = swed25519.ed25519_private_key_from_file(privkey_path)
    pubkey_path = os.path.join(ED25519_DIR, 'scriptworker_public_key')
    pubkey_string = read_from_file(pubkey_path)
    pubkey = swed25519.ed25519_public_key_from_file(pubkey_path)
    assert swed25519.ed25519_public_key_to_string(privkey.public_key()) == pubkey_string
    assert swed25519.ed25519_private_key_to_string(privkey) == privkey_string
    assert swed25519.ed25519_public_key_to_string(pubkey) == pubkey_string


def test_bad_file():
    with pytest.raises(ScriptWorkerEd25519Error):
        swed25519.ed25519_private_key_from_file(
            os.path.join(ED25519_DIR, 'foo.json')
        )


def test_sign():
    privkey_path = os.path.join(ED25519_DIR, 'scriptworker_private_key')
    privkey = swed25519.ed25519_private_key_from_file(privkey_path)
    pubkey_path = os.path.join(ED25519_DIR, 'scriptworker_public_key')
    pubkey = swed25519.ed25519_public_key_from_file(pubkey_path)
    binary_contents = read_from_file(os.path.join(ED25519_DIR, 'foo.json'), file_type='binary')
    detached_sig = read_from_file(os.path.join(ED25519_DIR, 'foo.json.scriptworker.sig'), file_type='binary')
    assert privkey.sign(binary_contents) == detached_sig


@pytest.mark.parametrize('unsigned_path, signature_path, public_key_path, raises', ((
    # Good
    os.path.join(ED25519_DIR, 'foo.json'),
    os.path.join(ED25519_DIR, 'foo.json.scriptworker.sig'),
    os.path.join(ED25519_DIR, 'scriptworker_public_key'),
    False,
), (
    # Bad verify key
    os.path.join(ED25519_DIR, 'foo.json'),
    os.path.join(ED25519_DIR, 'foo.json.scriptworker.sig'),
    os.path.join(ED25519_DIR, 'docker-worker_public_key'),
    True,
)))
def test_verify_ed25519_signature(unsigned_path, signature_path, public_key_path, raises):
    pubkey = swed25519.ed25519_public_key_from_file(public_key_path)
    contents = read_from_file(unsigned_path, file_type='binary')
    sig = read_from_file(signature_path, file_type='binary')
    if raises:
        with pytest.raises(ScriptWorkerEd25519Error):
            swed25519.verify_ed25519_signature(pubkey, contents, sig, "foo")
    else:
        swed25519.verify_ed25519_signature(pubkey, contents, sig, "foo")


def test_bad_ed25519_public_key_from_string():
    with pytest.raises(ScriptWorkerEd25519Error):
        swed25519.ed25519_public_key_from_string('bad_base64_string')


@pytest.mark.parametrize('pubkey_path, file_path, sig_path, exception', ((
    os.path.join(ED25519_DIR, 'scriptworker_public_key'),
    os.path.join(ED25519_DIR, 'foo.json'),
    os.path.join(ED25519_DIR, 'foo.json.scriptworker.sig'),
    SystemExit
), (
    None,
    os.path.join(ED25519_DIR, 'foo.json'),
    os.path.join(ED25519_DIR, 'foo.json.scriptworker.sig'),
    ScriptWorkerEd25519Error
)))
def test_ed25519_cmdln(pubkey_path, file_path, sig_path, exception):
    args = []
    if pubkey_path is not None:
        args.extend(['--pubkey', pubkey_path])
    args.extend([file_path, sig_path])
    with pytest.raises(exception):
        swed25519.verify_ed25519_signature_cmdln(args=args, exception=ScriptWorkerEd25519Error)
