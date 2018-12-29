#!/usr/bin/env python
"""Generate an ed25519 keypair, and store as base64-encoded text files.

This script doesn't currently reuse the functions in `scriptworker.ed25519`, for
easier standalone use. It could easily be a `console_script` though.

"""
from __future__ import print_function
from nacl.encoding import Base64Encoder
from nacl.signing import SigningKey, VerifyKey
import sys


def signing_key_from_string(key_str):
    """Create a SigningKey from a base64-encoded string."""
    return SigningKey(key_str, encoder=Base64Encoder)


def verify_key_from_string(key_str):
    """Create a VerifyKey from a base64-encoded string."""
    return VerifyKey(key_str, encoder=Base64Encoder)


prefix = ""
if len(sys.argv) > 1:
    prefix = "{}_".format(sys.argv[1])

sk = SigningKey.generate()
vk = sk.verify_key
sk_str = sk.encode(encoder=Base64Encoder).decode('utf-8')
vk_str = vk.encode(encoder=Base64Encoder).decode('utf-8')

# test
sk2 = signing_key_from_string(sk_str)
vk2 = verify_key_from_string(vk_str)
assert sk == sk2
assert vk == vk2

open("{}private_key".format(prefix), "w").write(sk_str)
open("{}public_key".format(prefix), "w").write(vk_str)
