#!/usr/bin/env python
"""GPG functions
"""

import gnupg

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
    return gpg.sign(data, **kwargs)
