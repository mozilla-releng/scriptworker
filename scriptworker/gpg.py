#!/usr/bin/env python
"""GPG functions
"""
import gnupg
import logging

from scriptworker.exceptions import ScriptWorkerTaskException

log = logging.getLogger(__name__)

# map the context.config keys to gnupg.GPG kwarg keys
GPG_CONFIG_MAPPING = {
    'gpg_home': 'gnupghome',
    'gpg_options': 'options',
    'gpg_path': 'gpgbinary',
    'gpg_public_keyring': 'keyring',
    'gpg_secret_keyring': 'secret_keyring',
    'gpg_use_agent': 'use_agent',
}


def GPG(context):
    """Return a python-gnupg GPG instance
    """
    kwargs = {}
    for config_key, gnupg_key in GPG_CONFIG_MAPPING.items():
        if context.config[config_key] is not None:
            kwargs[gnupg_key] = context.config[config_key]
    gpg = gnupg.GPG(**kwargs)
    gpg.encoding = context.config['gpg_encoding'] or gpg.encoding
    return gpg


def sign(context, data, **kwargs):
    """Sign `data` with the key `kwargs['keyid']`, or the default key if not specified
    """
    gpg = GPG(context)
    return str(gpg.sign(data, **kwargs))


def verify_signature(context, signed_data, **kwargs):
    """Verify `signed_data` with the key `kwargs['keyid']`, or the default key if not specified
    """
    log.info("Verifying signature...")
    gpg = GPG(context)
    verified = gpg.verify(signed_data, **kwargs)
    if verified.trust_level is not None and verified.trust_level >= verified.TRUST_FULLY:
        log.info("Fully trusted signature from {}, {}".format(verified.username, verified.key_id))
    else:
        raise ScriptWorkerTaskException("Signature could not be verified!")
    return verified


def get_body(context, signed_data, **kwargs):
    """Returned the unsigned data from `signed_data`.
    """
    gpg = GPG(context)
    verify_signature(context, signed_data)
    body = gpg.decrypt(signed_data, **kwargs)
    return str(body)
