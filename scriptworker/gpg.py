#!/usr/bin/env python
"""GPG functions.  These currently assume gpg 2.0.x
"""
import arrow
import gnupg
import logging
import os

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


def create_gpg_conf(homedir, my_fingerprint):
    """ Set infosec guidelines; use my_fingerprint by default
    """
    gpg_conf = os.path.join(homedir, "gpg.conf")
    if os.path.exists(gpg_conf):
        os.rename(gpg_conf, "{}.{}".format(gpg_conf, arrow.utcnow().timestamp))
    with open(gpg_conf, "w") as fh:
        # https://wiki.mozilla.org/Security/Guidelines/Key_Management#GnuPG_settings
        print("personal-digest-preferences SHA512 SHA384\n"
              "cert-digest-algo SHA256\n"
              "default-preference-list SHA512 SHA384 AES256 ZLIB BZIP2 ZIP Uncompressed\n"
              "keyid-format 0xlong\n", file=fh)

        # XXX If we want keyservers, we can specify, ideally configurable:
        # print("keyserver gpg.mozilla.org\n"
        #       "keyserver hkp://keys.gnupg.net\n"
        #       "keyserver-options auto-key-retrieve\n", file=fh)

        # default key
        print("default-key {}".format(my_fingerprint), file=fh)


def GPG(context, gpg_home=None):
    """Return a python-gnupg GPG instance
    """
    kwargs = {}
    for config_key, gnupg_key in GPG_CONFIG_MAPPING.items():
        if context.config[config_key] is not None:
            kwargs[gnupg_key] = context.config[config_key]
    if gpg_home is not None:
        kwargs['gnupghome'] = gpg_home
    gpg = gnupg.GPG(**kwargs)
    gpg.encoding = context.config['gpg_encoding'] or gpg.encoding
    return gpg


def sign(gpg, data, **kwargs):
    """Sign `data` with the key `kwargs['keyid']`, or the default key if not specified
    """
    return str(gpg.sign(data, **kwargs))


def verify_signature(gpg, signed_data, **kwargs):
    """Verify `signed_data` with the key `kwargs['keyid']`, or the default key if not specified
    """
    log.info("Verifying signature...")
    verified = gpg.verify(signed_data, **kwargs)
    if verified.trust_level is not None and verified.trust_level >= verified.TRUST_FULLY:
        log.info("Fully trusted signature from {}, {}".format(verified.username, verified.key_id))
    else:
        raise ScriptWorkerTaskException("Signature could not be verified!")
    return verified


def get_body(gpg, signed_data, gpg_home=None, **kwargs):
    """Returned the unsigned data from `signed_data`.
    """
    verify_signature(gpg, signed_data)
    body = gpg.decrypt(signed_data, **kwargs)
    return str(body)
