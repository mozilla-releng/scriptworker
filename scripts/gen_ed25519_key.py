#!/usr/bin/env python
"""Generate an ed25519 keypair, and store as base64-encoded text files.

This script doesn't currently reuse the functions in `scriptworker.ed25519`, for
easier standalone use. It could easily be a `console_script` though.

"""
from __future__ import print_function
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
import sys


def private_key_from_string(key_str):
    """Create an Ed25519PrivateKey from a base64-encoded string."""
    return Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(key_str)
    )


def public_key_from_string(key_str):
    """Create an Ed25519PublicKey from a base64-encoded string."""
    return Ed25519PublicKey.from_public_bytes(
        base64.b64decode(key_str)
    )


def b64_from_private_key(key):
    """Get the base64 string from an Ed25519PrivateKey."""
    return base64.b64encode(key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    )).decode('utf-8')


def b64_from_public_key(key):
    """Get the base64 string from an Ed25519PublicKey."""
    return base64.b64encode(key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )).decode('utf-8')


prefix = ""
if len(sys.argv) > 1:
    prefix = "{}_".format(sys.argv[1])

privkey = Ed25519PrivateKey.generate()
pubkey = privkey.public_key()
privkey_str = b64_from_private_key(privkey)
pubkey_str = b64_from_public_key(pubkey)

# test
privkey2 = private_key_from_string(privkey_str)
pubkey2 = public_key_from_string(pubkey_str)
assert b64_from_private_key(privkey2) == privkey_str
assert b64_from_public_key(pubkey2) == pubkey_str

with open("{}private_key".format(prefix), "w") as fh:
    fh.write(privkey_str)
with open("{}public_key".format(prefix), "w") as fh:
    fh.write(pubkey_str)
