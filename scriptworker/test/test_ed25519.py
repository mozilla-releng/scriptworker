import base64
import json
from nacl.signing import SigningKey
import os
import pytest

import scriptworker.ed25519 as swed25519
from scriptworker.exceptions import ScriptWorkerEd25519Error
from scriptworker.utils import load_json_or_yaml, read_from_file

from . import touch, rw_context, fake_session, fake_session_500, successful_queue

ED25519_DIR = os.path.join(os.path.dirname(__file__), 'data', 'ed25519')


def test_from_file():
    sk_path = os.path.join(ED25519_DIR, 'scriptworker_private_key')
    sk_string = read_from_file(sk_path)
    sk = swed25519.ed25519_signing_key_from_file(sk_path)
    vk_path = os.path.join(ED25519_DIR, 'scriptworker_public_key')
    vk_string = read_from_file(vk_path)
    vk = swed25519.ed25519_verify_key_from_file(vk_path)
    assert vk == sk.verify_key
    assert swed25519.ed25519_key_to_string(sk) == sk_string
    assert swed25519.ed25519_key_to_string(vk) == vk_string


def test_bad_file():
    with pytest.raises(ScriptWorkerEd25519Error):
        swed25519.ed25519_signing_key_from_file(
            os.path.join(ED25519_DIR, 'foo.json')
        )


def test_sign():
    sk_path = os.path.join(ED25519_DIR, 'scriptworker_private_key')
    sk = swed25519.ed25519_signing_key_from_file(sk_path)
    vk_path = os.path.join(ED25519_DIR, 'scriptworker_public_key')
    vk = swed25519.ed25519_verify_key_from_file(vk_path)
    binary_contents = read_from_file(os.path.join(ED25519_DIR, 'foo.json'), file_type='binary')
    detached_sig = read_from_file(os.path.join(ED25519_DIR, 'foo.json.scriptworker.sig'), file_type='binary')
    assert swed25519.ed25519_sign(sk, binary_contents) == detached_sig
    full_sig = swed25519.ed25519_sign(sk, binary_contents, signature_type='attached')
    assert vk.verify(full_sig) == binary_contents


def test_sign_exception():
    sk_path = os.path.join(ED25519_DIR, 'scriptworker_private_key')
    sk = swed25519.ed25519_signing_key_from_file(sk_path)
    with pytest.raises(ScriptWorkerEd25519Error):
        swed25519.ed25519_sign(sk, b'asdf', signature_type='illegal signature type')


@pytest.mark.parametrize('unsigned_path, signature_path, verify_key_path, raises', ((
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
def test_verify_ed25519_signature(unsigned_path, signature_path, verify_key_path, raises):
    vk = swed25519.ed25519_verify_key_from_file(verify_key_path)
    contents = read_from_file(unsigned_path, file_type='binary')
    sig = read_from_file(signature_path, file_type='binary')
    if raises:
        with pytest.raises(ScriptWorkerEd25519Error):
            swed25519.verify_ed25519_signature(vk, contents, sig, "foo")
    else:
        swed25519.verify_ed25519_signature(vk, contents, sig, "foo")
