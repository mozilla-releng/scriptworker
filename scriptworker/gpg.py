#!/usr/bin/env python
"""GPG functions.  These currently assume gpg 2.0.x
"""
import arrow
import gnupg
import logging
import os
import pexpect
import pprint
import subprocess

from scriptworker.exceptions import ScriptWorkerGPGException

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


# helper functions {{{1
def gpg_default_args(gpg_home):
    """ For commandline gpg calls, use these args by default
    """
    return [
        "--homedir", gpg_home,
        "--no-default-keyring",
        "--secret-keyring", os.path.join(gpg_home, "secring.gpg"),
        "--keyring", os.path.join(gpg_home, "pubring.gpg"),
    ]


def guess_gpg_home(obj, gpg_home=None):
    """Guess gpg_home.  If `gpg_home` is specified, return that.
    If `obj` is a context object and `context.config['gpg_home']` is not None,
    return that.
    If `obj` is a GPG object and `obj.gnupghome` is not None, return that.
    Otherwise look in `~/.gnupg`.  If os.environ['HOME'] isn't set, raise
    a ScriptWorkerGPGException.
    """
    try:
        if hasattr(obj, 'config'):
            gpg_home = gpg_home or obj.config['gpg_home']
        elif hasattr(obj, 'gnupghome'):
            gpg_home = gpg_home or obj.gnupghome
        gpg_home = gpg_home or os.path.join(os.environ['HOME'], '.gnupg')
    except KeyError:
        raise ScriptWorkerGPGException("Can't guess_gpg_home: $HOME not set!")
    return gpg_home


# create_gpg_conf {{{1
def create_gpg_conf(homedir, keyservers=None, my_fingerprint=None):
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

        if keyservers:
            for keyserver in keyservers:
                print("keyserver {}".format(keyserver), file=fh)
            print("keyserver-options auto-key-retrieve\n", file=fh)

        if my_fingerprint is not None:
            # default key
            print("default-key {}".format(my_fingerprint), file=fh)


# GPG {{{1
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


# key generation and export{{{1
def generate_key(gpg, name, comment, email, key_length=4096, expiration=None):
    """Generate a gpg keypair.
    """
    log.info("Generating key for {}...".format(email))
    kwargs = {
        "name_real": name,
        "name_comment": comment,
        "name_email": email,
        "key_length": key_length,
    }
    if expiration:
        kwargs['expire_date'] = expiration
    key = gpg.gen_key(gpg.gen_key_input(**kwargs))
    log.info("Fingerprint {}".format(key.fingerprint))
    return key.fingerprint


def export_key(gpg, fingerprint, private=False):
    """Return the ascii armored key identified by `fingerprint`.

    Raises ScriptworkerGPGException if the key isn't there.
    """
    message = "Exporting key {} from gnupghome {}".format(fingerprint, guess_gpg_home(gpg))
    log.info(message)
    key = gpg.export_keys(fingerprint)
    if not key:
        raise ScriptWorkerGPGException("Can't find key with fingerprint {}!".format(fingerprint))
    return key


def sign_key(context, target_fingerprint, signing_key=None, gpg_home=None):
    """Sign the `target_fingerprint` key with the `signing_key` or default key
    """
    args = []
    gpg_path = context.config['gpg_path'] or 'gpg'
    gpg_home = guess_gpg_home(context, gpg_home)
    message = "Signing key {} in {}".format(target_fingerprint, gpg_home)
    if signing_key:
        args.extend(['-u', signing_key])
        message += " with {}...".format(signing_key)
    log.info(message)
    # local, non-exportable signature
    args.append("--lsign-key")
    args.append(target_fingerprint)
    cmd_args = gpg_default_args(context.config['gpg_home']) + args
    child = pexpect.spawn(gpg_path, cmd_args)
    child.expect(b".*Really sign\? \(y/N\) ")
    child.sendline(b'y')
    index = child.expect([pexpect.EOF, pexpect.TIMEOUT])
    if index != 0:
        raise ScriptWorkerGPGException("Failed signing {}! Timeout".format(target_fingerprint))
    else:
        child.close()
        if child.exitstatus != 0 or child.signalstatus is not None:
            raise ScriptWorkerGPGException(
                "Failed signing {}! exit {} signal {}".format(
                    target_fingerprint, child.exitstatus, child.signalstatus
                )
            )


def update_trust(context, my_fingerprint, trusted_fingerprints=None, gpg_home=None):
    """ Trust my key ultimately; trusted_fingerprints fully
    """
    gpg_home = guess_gpg_home(context, gpg_home)
    log.info("Updating ownertrust in {}...".format(gpg_home))
    ownertrust = []
    trusted_fingerprints = trusted_fingerprints or []
    gpg_path = context.config['gpg_path'] or 'gpg'
    trustdb = os.path.join(gpg_home, "trustdb.gpg")
    if os.path.exists(trustdb):
        os.remove(trustdb)
    # trust my_fingerprint ultimately
    ownertrust.append("{}:6\n".format(my_fingerprint))
    # Trust trusted_fingerprints fully.  Once they are signed by my key, any
    # key they sign will be valid.  Only do this for root/intermediate keys
    # that are intended to sign other keys.
    for fingerprint in trusted_fingerprints:
        ownertrust.append("{}:5\n".format(fingerprint))
    log.debug(pprint.pformat(ownertrust))
    ownertrust = ''.join(ownertrust).encode('utf-8')
    cmd = [gpg_path] + gpg_default_args(gpg_home) + ["--import-ownertrust"]
    # TODO asyncio?
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdout = p.communicate(input=ownertrust)[0]
    if p.returncode:
        message = "gpg update_trust error!"
        if stdout:
            message += "\n{}".format(stdout.decode('utf-8'))
        raise ScriptWorkerGPGException(message)
    log.debug(subprocess.check_output(
        [gpg_path] + gpg_default_args(gpg_home) + ["--export-ownertrust"]).decode('utf-8')
    )


# data signatures and verification {{{1
def sign(gpg, data, **kwargs):
    """Sign `data` with the key `kwargs['keyid']`, or the default key if not specified
    """
    return str(gpg.sign(data, **kwargs))


def verify_signature(gpg, signed_data, **kwargs):
    """Verify `signed_data` with the key `kwargs['keyid']`, or the default key
    if not specified.

    Raises ScriptWorkerGPGException on failure.
    """
    log.info("Verifying signature (gnupghome {})".format(guess_gpg_home(gpg)))
    verified = gpg.verify(signed_data, **kwargs)
    if verified.trust_level is not None and verified.trust_level >= verified.TRUST_FULLY:
        log.info("Fully trusted signature from {}, {}".format(verified.username, verified.key_id))
    else:
        raise ScriptWorkerGPGException("Signature could not be verified!")
    return verified


def get_body(gpg, signed_data, gpg_home=None, **kwargs):
    """Returned the unsigned data from `signed_data`.
    """
    verify_signature(gpg, signed_data)
    body = gpg.decrypt(signed_data, **kwargs)
    return str(body)
