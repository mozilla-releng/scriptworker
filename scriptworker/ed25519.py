#!/usr/bin/env python
"""ed25519 support for scriptworker.

Attributes:
    log (logging.Logger): the log object for the module

"""
import argparse
import base64
from binascii import Error as Base64Error
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
import functools
import logging
import sys
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.exceptions import ScriptWorkerEd25519Error, ScriptWorkerException
from scriptworker.utils import read_from_file

log = logging.getLogger(__name__)


def ed25519_private_key_from_string(string):
    """Create an ed25519 private key from ``string``, which is a seed.

    Args:
        string (str): the string to use as a seed.

    Returns:
        Ed25519PrivateKey: the private key

    """
    try:
        return Ed25519PrivateKey.from_private_bytes(
            base64.b64decode(string)
        )
    except (UnsupportedAlgorithm, Base64Error) as exc:
        raise ScriptWorkerEd25519Error("Can't create Ed25519PrivateKey: {}!".format(str(exc)))


def ed25519_public_key_from_string(string):
    """Create an ed25519 public key from ``string``, which is a seed.

    Args:
        string (str): the string to use as a seed.

    Returns:
        Ed25519PublicKey: the public key

    """
    try:
        return Ed25519PublicKey.from_public_bytes(
            base64.b64decode(string)
        )
    except (UnsupportedAlgorithm, Base64Error) as exc:
        raise ScriptWorkerEd25519Error("Can't create Ed25519PublicKey: {}!".format(str(exc)))


def _ed25519_key_from_file(fn, path):
    """Create an ed25519 key from the contents of ``path``.

    ``path`` is a filepath containing a base64-encoded ed25519 key seed.

    Args:
        fn (callable): the function to call with the contents from ``path``
        path (str): the file path to the base64-encoded key seed.

    Returns:
        obj: the appropriate key type from ``path``

    Raises:
        ScriptWorkerEd25519Error

    """
    try:
        return fn(read_from_file(path, exception=ScriptWorkerEd25519Error))
    except ScriptWorkerException as exc:
        raise ScriptWorkerEd25519Error("Failed calling {} for {}: {}!".format(fn, path, str(exc)))


ed25519_private_key_from_file = functools.partial(_ed25519_key_from_file, ed25519_private_key_from_string)
ed25519_public_key_from_file = functools.partial(_ed25519_key_from_file, ed25519_public_key_from_string)


def ed25519_private_key_to_string(key):
    """Convert an ed25519 private key to a base64-encoded string.

    Args:
        key (Ed25519PrivateKey): the key to write to the file.

    Returns:
        str: the key representation as a str

    """
    return base64.b64encode(key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    ), None).decode('utf-8')


def ed25519_public_key_to_string(key):
    """Convert an ed25519 public key to a base64-encoded string.

    Args:
        key (Ed25519PublicKey): the key to write to the file.

    Returns:
        str: the key representation as a str

    """
    return base64.b64encode(key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ), None).decode('utf-8')


def verify_ed25519_signature(public_key, contents, signature, message):
    """Verify that ``signature`` comes from ``public_key`` and ``contents``.

    Args:
        public_key (Ed25519PublicKey): the key to verify the signature
        contents (bytes): the contents that was signed
        signature (bytes): the signature to verify
        message (str): the error message to raise.

    Raises:
        ScriptWorkerEd25519Error: on failure

    """
    try:
        public_key.verify(signature, contents)
    except InvalidSignature as exc:
        raise ScriptWorkerEd25519Error(message % {'exc': str(exc)})


# verify_ed25519_signature_cmdln {{{1
def verify_ed25519_signature_cmdln(args=None, exception=SystemExit):
    """Verify an ed25519 signature from the command line.

    Args:
        args (list, optional): the commandline args to parse. If ``None``, use
            ``sys.argv[1:]``. Defaults to ``None``.
        exception (Exception, optional): the exception to raise on failure.
            Defaults to ``SystemExit``.

    """
    args = args or sys.argv[1:]
    parser = argparse.ArgumentParser(
        description="""Verify an ed25519 signature from the command line.

Given a file and its detached signature, verify that it has been signed with
a valid key. This key can be specified on the command line; otherwise we'll
default to ``config['ed25519_public_keys']``.""")
    parser.add_argument('--pubkey', help='path to a base64-encoded ed25519 pubkey, optional')
    parser.add_argument('file_path')
    parser.add_argument('sig_path')
    opts = parser.parse_args(args)
    log = logging.getLogger('scriptworker')
    log.setLevel(logging.DEBUG)
    logging.basicConfig()
    pubkeys = {}
    if opts.pubkey:
        pubkeys['cmdln'] = [read_from_file(opts.pubkey)]
    pubkeys.update(dict(DEFAULT_CONFIG['ed25519_public_keys']))
    contents = read_from_file(opts.file_path, file_type='binary')
    signature = read_from_file(opts.sig_path, file_type='binary')
    for key_type, seeds in pubkeys.items():
        for seed in seeds:
            try:
                verify_ed25519_signature(
                    ed25519_public_key_from_string(seed), contents, signature,
                    "didn't work with {}".format(seed)
                )
                log.info("Verified good with {} seed {} !".format(
                    key_type, seed
                ))
                sys.exit(0)
            except ScriptWorkerEd25519Error:
                pass
    raise exception("This is not a valid signature!")
