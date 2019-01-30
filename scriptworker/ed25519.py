#!/usr/bin/env python
"""ed25519 support for scriptworker.

Attributes:
    log (logging.Logger): the log object for the module

"""
import functools
import logging
from nacl.encoding import Base64Encoder
from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey
from scriptworker.exceptions import ScriptWorkerEd25519Error, ScriptWorkerException
from scriptworker.utils import read_from_file

log = logging.getLogger(__name__)


def _ed25519_key_from_string(obj, string):
    """Create an ed25519 key from ``string``, which is a seed.

    Args:
        obj (nacl.signing.SigningKey or nacl.signing.VerifyKey): the object to instantiate.
        string (str): the string to use as a seed.

    Returns:
        obj: the appropriate key type from ``path``

    """
    try:
        return obj(string, encoder=Base64Encoder)
    except (TypeError, ValueError) as exc:
        raise ScriptWorkerEd25519Error("Can't create {}: {}!".format(obj, str(exc)))


def _ed25519_key_from_file(obj, path):
    """Create an ed25519 key from the contents of ``path``.

    ``path`` is a filepath containing a base64-encoded ed25519 key seed.

    Args:
        obj (nacl.signing.SigningKey or nacl.signing.VerifyKey): the object to instantiate.
        path (str): the file path to the base64-encoded key seed.

    Returns:
        obj: the appropriate key type from ``path``

    Raises:
        ScriptWorkerEd25519Error

    """
    try:
        return _ed25519_key_from_string(obj, read_from_file(path, exception=ScriptWorkerEd25519Error))
    except ScriptWorkerException as exc:
        raise ScriptWorkerEd25519Error("Can't create {} from {}: {}!".format(obj, path, str(exc)))


def ed25519_key_to_string(key):
    """Convert an ed25519 key to a base64-encoded string.

    Args:
        key (nacl.signing.SigningKey or nacl.signing.VerifyKey): the key to write to the file.

    Returns:
        str: the key representation as a str

    """
    return key.encode(encoder=Base64Encoder).decode('utf-8')


ed25519_signing_key_from_string = functools.partial(_ed25519_key_from_string, SigningKey)
ed25519_verify_key_from_string = functools.partial(_ed25519_key_from_string, VerifyKey)
ed25519_signing_key_from_file = functools.partial(_ed25519_key_from_file, SigningKey)
ed25519_verify_key_from_file = functools.partial(_ed25519_key_from_file, VerifyKey)


def verify_ed25519_signature(verify_key, contents, signature, message):
    """Verify that ``signature`` comes from ``verify_key`` and ``contents``.

    Args:
        verify_key (nacl.signing.VerifyKey): the key to verify the signature
        contents (bytes): the contents that was signed
        signature (bytes): the signature to verify
        message (str): the error message to raise.

    Raises:
        ScriptWorkerEd25519Error: on failure

    """
    try:
        verify_key.verify(contents, signature=signature)
    except BadSignatureError as exc:
        raise ScriptWorkerEd25519Error(message % {'exc': str(exc)})


def ed25519_sign(signing_key, contents, signature_type='detached'):
    """Create a signature of ``contents`` using ``signing_key``.

    This can be a ``detached`` or ``attached`` signature.

    Args:
        verify_key (nacl.signing.VerifyKey): the key to verify the signature
        contents (bytes): the contents to sign
        signature_type (str, optional): Either ``detached`` or ``attached``.
            Defaults to ``detached``.

    Raises:
        ScriptWorkerEd25519Error: on unknown ``signature_type``

    Returns:
        bytes: the signature.

    """
    full_sig = signing_key.sign(contents)
    if signature_type == 'detached':
        return full_sig.signature
    elif signature_type == 'attached':
        return full_sig
    else:
        raise ScriptWorkerEd25519Error("Unknown signature type {}!".format(signature_type))
