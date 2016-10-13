#!/usr/bin/env python
"""GPG functions.  These currently assume gpg 2.0.x

These GPG functions expose considerable functionality over gpg key management,
data signatures, and validation, but by no means are they intended to cover all
gnupg functionality.  They are intended for automated key management and
validation for scriptworker.

Attributes:
    log (logging.Logger): the log object for this module.
    GPG_CONFIG_MAPPING (dict): This maps the scriptworker config key names to
        the python-gnupg names.
"""
import arrow
import asyncio
from asyncio.subprocess import DEVNULL, PIPE, STDOUT
import gnupg
import logging
import os
import pexpect
import pprint
import re
import subprocess
import sys
import tempfile
import traceback

from scriptworker.config import get_context_from_cmdln
from scriptworker.exceptions import ScriptWorkerException, ScriptWorkerGPGException, \
    ScriptWorkerRetryException
from scriptworker.log import pipe_to_log
from scriptworker.utils import filepaths_in_dir, makedirs, raise_future_exceptions, retry_async, rm

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
    """For commandline gpg calls, use these args by default.

    Args:
        gpg_home (str): The path to the gpg homedir.  gpg will look for
            the gpg.conf, trustdb.gpg, and keyring files in here.

    Returns:
        list: the list of default commandline arguments to add to the gpg call.
    """
    return [
        "--homedir", gpg_home,
        "--no-default-keyring",
        "--secret-keyring", os.path.join(gpg_home, "secring.gpg"),
        "--keyring", os.path.join(gpg_home, "pubring.gpg"),
    ]


def guess_gpg_home(obj, gpg_home=None):
    """Guess gpg_home.  If `gpg_home` is specified, return that.

    Args:
        obj (object): If gpg_home is set, return that. Otherwise, if `obj` is a
            context object and `context.config['gpg_home']` is not None, return
            that. If `obj` is a GPG object and `obj.gnupghome` is not None,
            return that.  Otherwise look in `~/.gnupg`.
        gpg_home (str, optional): The path to the gpg homedir.  gpg will look for
            the gpg.conf, trustdb.gpg, and keyring files in here.  Defaults to None.

    Returns:
        str: the path to the guessed gpg homedir.

    Raises:
        ScriptWorkerGPGException: if obj doesn't contain the gpg home info and
            os.environ['HOME'] isn't set.
    """
    try:
        if hasattr(obj, 'config'):
            gpg_home = gpg_home or obj.config['gpg_home']
        if hasattr(obj, 'gnupghome'):
            gpg_home = gpg_home or obj.gnupghome
        gpg_home = gpg_home or os.path.join(os.environ['HOME'], '.gnupg')
    except KeyError:
        raise ScriptWorkerGPGException("Can't guess_gpg_home: $HOME not set!")
    return gpg_home


def guess_gpg_path(context):
    """Simple gpg_path guessing function.

    Args:
        context (scriptworker.context.Context): the scriptworker context.

    Returns:
        str: either `context.config['gpg_path']` or 'gpg' if that's not defined.
    """
    return context.config['gpg_path'] or 'gpg'


def keyid_to_fingerprint(gpg, keyid, private=False):
    """Return the fingerprint of the key that corresponds to `keyid`.

    Keyids should default to long keyids; this will happen once
    `create_gpg_conf()` is called.

    Args:
        gpg (gnupg.GPG): gpg object for the appropriate gpg_home / keyring
        keyid (str): the long keyid that represents the key we're searching
            for.
        private (bool, optional): If True, search the private keyring instead
            of the public keyring.  Defaults to False.

    Returns:
        fingerprint (str): the fingerprint of the key with keyid `keyid`

    Raises:
        ScriptworkerGPGException: if we can't find `keyid` in this keyring.
    """
    for key in gpg.list_keys(private):
        if key['keyid'] == keyid:
            return key['fingerprint']
    else:
        raise ScriptWorkerGPGException(
            "Can't find keyid {} for {}!".format(
                keyid, guess_gpg_home(gpg)
            )
        )


def fingerprint_to_keyid(gpg, fingerprint, private=False):
    """Return the keyid of the key that corresponds to `fingerprint`.

    Keyids should default to long keyids; this will happen once
    `create_gpg_conf()` is called.

    Args:
        gpg (gnupg.GPG): gpg object for the appropriate gpg_home / keyring
        fingerpint (str): the fingerprint of the key we're searching for.
        private (bool, optional): If True, search the private keyring instead
            of the public keyring.  Defaults to False.

    Returns:
        keyid (str): the keyid of the key with fingerprint `fingerprint`

    Raises:
        ScriptworkerGPGException: if we can't find `fingerprint` in this keyring.
    """
    for key in gpg.list_keys(private):
        if key['fingerprint'] == fingerprint:
            return key['keyid']
    else:
        raise ScriptWorkerGPGException(
            "Can't find fingerprint {} for {}!".format(
                fingerprint, guess_gpg_home(gpg)
            )
        )


# create_gpg_conf {{{1
def create_gpg_conf(gpg_home, keyserver=None, my_fingerprint=None):
    """Create a gpg.conf with Mozilla infosec guidelines.

    Args:
        gpg_home (str): the homedir for this keyring.
        keyserver (str, optional): The gpg keyserver to specify, e.g.
            `hkp://gpg.mozilla.org` or `hkp://keys.gnupg.net`.  If set, we also
            enable `auto-key-retrieve`.  Defaults to None.
        my_fingerprint (str, optional): the fingerprint of the default key.
            Once set, gpg will use it by default, unless a different key is
            specified.  Defaults to None.
    """
    gpg_conf = os.path.join(gpg_home, "gpg.conf")
    if os.path.exists(gpg_conf):
        os.rename(gpg_conf, "{}.{}".format(gpg_conf, arrow.utcnow().timestamp))
    with open(gpg_conf, "w") as fh:
        # https://wiki.mozilla.org/Security/Guidelines/Key_Management#GnuPG_settings
        print("personal-digest-preferences SHA512 SHA384\n"
              "cert-digest-algo SHA256\n"
              "default-preference-list SHA512 SHA384 AES256 ZLIB BZIP2 ZIP Uncompressed\n"
              "keyid-format 0xlong", file=fh)

        if keyserver:
            print("keyserver {}".format(keyserver), file=fh)
            print("keyserver-options auto-key-retrieve", file=fh)

        if my_fingerprint is not None:
            # default key
            print("default-key {}".format(my_fingerprint), file=fh)


# GPG {{{1
def GPG(context, gpg_home=None):
    """Get a python-gnupg GPG instance based on the settings in `context`.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        gpg_home (str, optional): override `context.config['gpg_home']` if
            desired.  Defaults to None.

    Returns:
        gnupg.GPG: the GPG instance with the appropriate configs.
    """
    kwargs = {}
    gpg_home = guess_gpg_home(context, gpg_home=gpg_home)
    for config_key, gnupg_key in GPG_CONFIG_MAPPING.items():
        if isinstance(context.config[config_key], str):
            # allow for the keyring paths to contain %(gpg_home)s (recommended)
            kwargs[gnupg_key] = context.config[config_key] % {'gpg_home': gpg_home}
    kwargs['gnupghome'] = gpg_home
    gpg = gnupg.GPG(**kwargs)
    # gpg.encoding defaults to latin-1, but python3 defaults to utf-8 for
    # everything else
    gpg.encoding = context.config['gpg_encoding']
    return gpg


# key generation, import, and export{{{1
def generate_key(gpg, name, comment, email, key_length=4096, expiration=None):
    """Generate a gpg keypair.

    Args:
        gpg (gnupg.GPG): the GPG instance.
        name (str): the name attached to the key.  1/3 of the key user id.
        comment (str): the comment attached to the key.  1/3 of the key user id.
        email (str): the email attached to the key.  1/3 of the key user id.
        key_length (int, optional): the key length in bits.  Defaults to 4096.
        expiration (str, optional):  The expiration of the key.  This can take
            the forms “2009-12-31”, “365d”, “3m”, “6w”, “5y”, “seconds=<epoch>”,
            or 0 for no expiry.  Defaults to None.

    Returns:
        fingerprint (str): the fingerprint of the key just generated.
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


def import_key(gpg, key_data, return_type='fingerprints'):
    """Import ascii key_data.

    In theory this can be multiple keys.  However, jenkins is barfing on
    multiple key import tests, although multiple key import tests are working
    locally.  Until we identify what the problem is (likely gpg version?)
    we should only import 1 key at a time.

    Args:
        gpg (gnupg.GPG): the GPG instance.
        key_data (str): ascii armored key data
        return_type (str, optional): if 'fingerprints', return the fingerprints
            only.  Otherwise return the result list.

    Returns:
        list: if return_type is 'fingerprints', return the fingerprints of the
            imported keys.  Otherwise return the results list.
            https://pythonhosted.org/python-gnupg/#importing-and-receiving-keys
    """
    import_result = gpg.import_keys(key_data)
    if return_type == 'fingerprints':
        return import_result.fingerprints
    return import_result.results


def export_key(gpg, fingerprint, private=False):
    """Return the ascii armored key identified by `fingerprint`.

    Args:
        gpg (gnupg.GPG): the GPG instance.
        fingerprint (str): the fingerprint of the key to export.
        private (bool, optional): If True, return the private key instead
            of the public key.  Defaults to False.

    Returns:
        str: the ascii armored key identified by `fingerprint`.

    Raises:
        ScriptworkerGPGException: if the key isn't found.
    """
    message = "Exporting key {} from gnupghome {}".format(fingerprint, guess_gpg_home(gpg))
    log.info(message)
    key = gpg.export_keys(fingerprint, private)
    if not key:
        raise ScriptWorkerGPGException("Can't find key with fingerprint {}!".format(fingerprint))
    return key


@asyncio.coroutine
def sign_key(context, target_fingerprint, signing_key=None,
             exportable=False, gpg_home=None):
    """Sign the `target_fingerprint` key with the `signing_key` or default key

    This signs the target key with the signing key, which adds to the web of trust.

    This function is async, but should not be used in parallel in the same
    gpg homedir.  GPG keysigning requires a lock on the keyring, so any
    parallelization in the same homedir will result in failures and unhappiness.
    This function is meant to be used async to parallelize multiple GPG
    homedir operations.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        target_fingerprint (str): the fingerprint of the key to sign.
        signing_key (str, optional): the fingerprint of the signing key to sign
            with.  If not set, this defaults to the default-key in the gpg.conf.
            Defaults to None.
        exportable (bool, optional): whether the signature should be exportable.
            Defaults to False.
        gpg_home (str, optional): override the gpg_home with a different
            gnupg home directory here.  Defaults to None.

    Raises:
        ScriptWorkerGPGException: on a failed signature.
    """
    args = []
    gpg_path = guess_gpg_path(context)
    gpg_home = guess_gpg_home(context, gpg_home=gpg_home)
    message = "Signing key {} in {}".format(target_fingerprint, gpg_home)
    if signing_key:
        args.extend(['-u', signing_key])
        message += " with {}...".format(signing_key)
    log.info(message)
    if exportable:
        args.append("--sign-key")
    else:
        args.append("--lsign-key")
    args.append(target_fingerprint)
    cmd_args = gpg_default_args(gpg_home) + args
    log.debug(subprocess.list2cmdline([gpg_path] + cmd_args))
    child = pexpect.spawn(gpg_path, cmd_args, timeout=context.config['sign_key_timeout'])
    try:
        while True:
            index = yield from child.expect([pexpect.EOF, b".*Really sign\? \(y/N\) ", b".*Really sign all user IDs\? \(y/N\) "], async=True)
            if index == 0:
                break
            child.sendline(b'y')
    except (pexpect.exceptions.TIMEOUT):
        raise ScriptWorkerGPGException(
            "Failed signing {}! Timeout".format(target_fingerprint)
        )
    child.close()
    if child.exitstatus != 0 or child.signalstatus is not None:
        raise ScriptWorkerGPGException(
            "Failed signing {}! exit {} signal {}".format(
                target_fingerprint, child.exitstatus, child.signalstatus
            )
        )


# ownertrust {{{1
def check_ownertrust(context, gpg_home=None):
    """In theory, this will repair a broken trustdb.

    Rebuild the trustdb via --import-ownertrust if not.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        gpg_home (str, optional): override the gpg_home with a different
            gnupg home directory here.  Defaults to None.
    """
    gpg_home = guess_gpg_home(context, gpg_home=gpg_home)
    gpg_path = guess_gpg_path(context)
    subprocess.check_call([gpg_path] + gpg_default_args(gpg_home) + ["--check-trustdb"])


def update_ownertrust(context, my_fingerprint, trusted_fingerprints=None, gpg_home=None):
    """ Trust my key ultimately; trusted_fingerprints fully

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        my_fingerprint (str): the fingerprint of the key we want to specify
            as ultimately trusted.
        trusted_fingerprints (list, optional): the list of fingerprints that
            we want to mark as fully trusted.  These need to be signed by
            the my_fingerprint key before they are trusted.
        gpg_home (str, optional): override the gpg_home with a different
            gnupg home directory here.  Defaults to None.

    Raises:
        ScriptWorkerGPGException: if there is an error.
    """
    gpg_home = guess_gpg_home(context, gpg_home=gpg_home)
    log.info("Updating ownertrust in {}...".format(gpg_home))
    ownertrust = []
    trusted_fingerprints = list(set(trusted_fingerprints or []))
    gpg_path = guess_gpg_path(context)
    trustdb = os.path.join(gpg_home, "trustdb.gpg")
    rm(trustdb)
    # trust my_fingerprint ultimately
    ownertrust.append("{}:6\n".format(my_fingerprint))
    # Trust trusted_fingerprints fully.  Once they are signed by my key, any
    # key they sign will be valid.  Only do this for root/intermediate keys
    # that are intended to sign other keys.
    for fingerprint in trusted_fingerprints:
        if fingerprint != my_fingerprint:
            ownertrust.append("{}:5\n".format(fingerprint))
    log.debug(pprint.pformat(ownertrust))
    ownertrust = ''.join(ownertrust).encode('utf-8')
    cmd = [gpg_path] + gpg_default_args(gpg_home) + ["--import-ownertrust"]
    # TODO asyncio?
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdout = p.communicate(input=ownertrust)[0] or b''
    if p.returncode:
        raise ScriptWorkerGPGException("gpg update_ownertrust error!\n{}".format(stdout.decode('utf-8')))
    verify_ownertrust(
        context, my_fingerprint, trusted_fingerprints=trusted_fingerprints,
        gpg_home=gpg_home
    )


def verify_ownertrust(context, my_fingerprint, trusted_fingerprints=None, gpg_home=None):
    """Verify the ownertrust is exactly as expected.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        my_fingerprint (str): the fingerprint of the key we specified
            as ultimately trusted.
        trusted_fingerprints (list, optional): the list of fingerprints that
            we marked as fully trusted.
        gpg_home (str, optional): override the gpg_home with a different
            gnupg home directory here.  Defaults to None.

    Raises:
        ScriptWorkerGPGException: if there is an error.
    """
    gpg_home = guess_gpg_home(context, gpg_home=gpg_home)
    gpg_path = guess_gpg_path(context)
    expected = ['{}:6:'.format(my_fingerprint)]
    for fp in trusted_fingerprints:
        if fp != my_fingerprint:
            expected.append('{}:5:'.format(fp))
    expected = set(expected)
    real = []
    output = subprocess.check_output(
        [gpg_path] + gpg_default_args(gpg_home) + ["--export-ownertrust"],
        stderr=subprocess.STDOUT
    ).decode('utf-8')
    for line in output.split('\n'):
        if line and not line.startswith('#'):
            real.append(line)
    real = set(real)
    messages = []
    extra = real.difference(expected)
    missing = expected.difference(real)
    if extra:
        messages.append("Extra trust lines!\n{}".format(extra))
    if missing:
        messages.append("Missing trust lines!\n{}".format(missing))
    if messages:
        raise ScriptWorkerGPGException(
            "{}\n{}".format('\n'.join(messages), output)
        )


# data signatures and verification {{{1
def sign(gpg, data, **kwargs):
    """Sign `data` with the key `kwargs['keyid']`, or the default key if not specified

    Args:
        gpg (gnupg.GPG): the GPG instance.
        data (str): The contents to sign with the key.
        kwargs (dict, optional): These are passed directly to gpg.sign().
            Defaults to {}.
            https://pythonhosted.org/python-gnupg/#signing

    Returns:
        str: the ascii armored signed data.
    """
    return str(gpg.sign(data, **kwargs))


def verify_signature(gpg, signed_data, **kwargs):
    """Verify `signed_data` with the key `kwargs['keyid']`, or the default key
    if not specified.

    Args:
        gpg (gnupg.GPG): the GPG instance.
        signed_data (str): The ascii armored signed data.
        kwargs (dict, optional): These are passed directly to gpg.verify().
            Defaults to {}.
            https://pythonhosted.org/python-gnupg/#verification

    Returns:
        gnupg.Verify: on success.

    Raises:
        ScriptWorkerGPGException: on failure.
    """
    log.info("Verifying signature (gnupghome {})".format(guess_gpg_home(gpg)))
    verified = gpg.verify(signed_data, **kwargs)
    if verified.trust_level is not None and verified.trust_level >= verified.TRUST_FULLY:
        log.info("Fully trusted signature from {}, {}".format(verified.username, verified.key_id))
    else:
        raise ScriptWorkerGPGException("Signature could not be verified!")
    return verified


def get_body(gpg, signed_data, gpg_home=None, **kwargs):
    """Verifies the signature, then returns the unsigned data from `signed_data`.

    Args:
        gpg (gnupg.GPG): the GPG instance.
        signed_data (str): The ascii armored signed data.
        gpg_home (str, optional): override the gpg_home with a different
            gnupg home directory here.  Defaults to None.
        kwargs (dict, optional): These are passed directly to gpg.decrypt().
            Defaults to {}.
            https://pythonhosted.org/python-gnupg/#decryption

    Returns:
        str: unsigned contents on success.

    Raises:
        ScriptWorkerGPGException: on signature verification failure.
    """
    verify_signature(gpg, signed_data)
    body = gpg.decrypt(signed_data, **kwargs)
    return str(body)


# key signature verification {{{1
def _parse_trust_line(trust_line, desc):
    """parse `gpg --list-sigs --with-colons` `tru` line

       https://git.gnupg.org/cgi-bin/gitweb.cgi?p=gnupg.git;a=blob;f=doc/DETAILS;h=645814a4c1fa8e8e735850f0f93b17617f60d4c8;hb=refs/heads/STABLE-BRANCH-2-0

       Example for a "tru" trust base record:

          tru:o:0:1166697654:1:3:1:5

        The fields are:

        2: Reason for staleness of trust.  If this field is empty, then the
           trustdb is not stale.  This field may have multiple flags in it:

           o: Trustdb is old
           t: Trustdb was built with a different trust model than the one we
              are using now.

        3: Trust model:
           0: Classic trust model, as used in PGP 2.x.
           1: PGP trust model, as used in PGP 6 and later.  This is the same
              as the classic trust model, except for the addition of trust
              signatures.

           GnuPG before version 1.4 used the classic trust model by default.
           GnuPG 1.4 and later uses the PGP trust model by default.

        4: Date trustdb was created in seconds since 1970-01-01.
        5: Date trustdb will expire in seconds since 1970-01-01.
        6: Number of marginally trusted users to introduce a new key signer
           (gpg's option --marginals-needed)
        7: Number of completely trusted users to introduce a new key signer.
           (gpg's option --completes-needed)
        8: Maximum depth of a certification chain.
           *gpg's option --max-cert-depth)
    """
    parts = trust_line.split(':')
    messages = []
    # check for staleness
    if 't' in parts[1]:
        messages.append(
            "{} trustdb was built with a different trust model than the one we\n"
            "are using now.\n{}".format(desc, trust_line)
        )
    # XXX I'm creating an expired trustdb for some reason.  Until I figure it out,
    # I can't raise on old/expired trustdb
    elif parts[1] == 'o':
        log.warning("{} trustdb is old.  Ignoring for now.\n {}".format(desc, trust_line))
    # check for expiration; assuming 0 is no expiration
    if parts[4] and int(parts[4]) < arrow.utcnow().timestamp:
        log.warning(
            "{} trustdb is expired, as of {}Z!".format(
                desc, arrow.get(int(parts[4])).format("YYYY-MM-DDTHH:mm:ssZZ")
            )
        )
    if messages:
        raise ScriptWorkerGPGException('\n'.join(messages))


def _parse_pub_line(pub_line, desc):
    """parse `gpg --list-sigs --with-colons` `pub` line
    https://git.gnupg.org/cgi-bin/gitweb.cgi?p=gnupg.git;a=blob;f=doc/DETAILS;h=645814a4c1fa8e8e735850f0f93b17617f60d4c8;hb=refs/heads/STABLE-BRANCH-2-0
     2. Field:  A letter describing the calculated validity. This is a single
                letter, but be prepared that additional information may follow
                in some future versions. (not used for secret keys)
                    o = Unknown (this key is new to the system)
                    i = The key is invalid (e.g. due to a missing self-signature)
                    d = The key has been disabled
                        (deprecated - use the 'D' in field 12 instead)
                    r = The key has been revoked
                    e = The key has expired
                    - = Unknown validity (i.e. no value assigned)
                    q = Undefined validity
                        '-' and 'q' may safely be treated as the same
                        value for most purposes
                    n = The key is valid
                    m = The key is marginal valid.
                    f = The key is fully valid
                    u = The key is ultimately valid.  This often means
                        that the secret key is available, but any key may
                        be marked as ultimately valid.

                If the validity information is given for a UID or UAT
                record, it describes the validity calculated based on this
                user ID.  If given for a key record it describes the best
                validity taken from the best rated user ID.

                For X.509 certificates a 'u' is used for a trusted root
                certificate (i.e. for the trust anchor) and an 'f' for all
                other valid certificates.

     3. Field:  length of key in bits.

     4. Field:  Algorithm:  1 = RSA
                           16 = Elgamal (encrypt only)
                           17 = DSA (sometimes called DH, sign only)
                           20 = Elgamal (sign and encrypt - don't use them!)
                (for other id's see include/cipher.h)

     5. Field:  KeyID

     6. Field:  Creation Date (in UTC).  For UID and UAT records, this is
                the self-signature date.  Note that the date is usally
                printed in seconds since epoch, however, we are migrating
                to an ISO 8601 format (e.g. "19660205T091500").  This is
                currently only relevant for X.509.  A simple way to detect
                the new format is to scan for the 'T'.

     7. Field:  Key or user ID/user attribute expiration date or empty if none.

     8. Field:  Used for serial number in crt records (used to be the Local-ID).
                For UID and UAT records, this is a hash of the user ID contents
                used to represent that exact user ID.  For trust signatures,
                this is the trust depth seperated by the trust value by a
                space.

     9. Field:  Ownertrust (primary public keys only)
                This is a single letter, but be prepared that additional
                information may follow in some future versions.  For trust
                signatures with a regular expression, this is the regular
                expression value, quoted as in field 10.

    10. Field:  User-ID.  The value is quoted like a C string to avoid
                control characters (the colon is quoted "\x3a").
                For a "pub" record this field is not used on --fixed-list-mode.
                A UAT record puts the attribute subpacket count here, a
                space, and then the total attribute subpacket size.
                In gpgsm the issuer name comes here
                An FPR record stores the fingerprint here.
                The fingerprint of an revocation key is stored here.

    11. Field:  Signature class as per RFC-4880.  This is a 2 digit
                hexnumber followed by either the letter 'x' for an
                exportable signature or the letter 'l' for a local-only
                signature.  The class byte of an revocation key is also
                given here, 'x' and 'l' is used the same way.  IT is not
                used for X.509.

    12. Field:  Key capabilities:
                    e = encrypt
                    s = sign
                    c = certify
                    a = authentication
                A key may have any combination of them in any order.  In
                addition to these letters, the primary key has uppercase
                versions of the letters to denote the _usable_
                capabilities of the entire key, and a potential letter 'D'
                to indicate a disabled key.

    13. Field:  Used in FPR records for S/MIME keys to store the
                fingerprint of the issuer certificate.  This is useful to
                build the certificate path based on certificates stored in
                the local keyDB; it is only filled if the issuer
                certificate is available. The root has been reached if
                this is the same string as the fingerprint. The advantage
                of using this value is that it is guaranteed to have been
                been build by the same lookup algorithm as gpgsm uses.
                For "uid" records this lists the preferences in the same
                way the gpg's --edit-key menu does.
                For "sig" records, this is the fingerprint of the key that
                issued the signature.  Note that this is only filled in if
                the signature verified correctly.  Note also that for
                various technical reasons, this fingerprint is only
                available if --no-sig-cache is used.

    14. Field   Flag field used in the --edit menu output:

    15. Field   Used in sec/sbb to print the serial number of a token
                (internal protect mode 1002) or a '#' if that key is a
                simple stub (internal protect mode 1001)
    16. Field:  For sig records, this is the used hash algorithm:
                    2 = SHA-1
                    8 = SHA-256
                (for other id's see include/cipher.h)
    """
    parts = pub_line.split(':')
    messages = []
    VALIDITY = {
        "o": "The key validity is unknown (this key is new to the system)",
        "i": "The key is invalid (e.g. due to a missing self-signature)",
        "d": "The key has been disabled",
        "r": "The key has been revoked",
        "e": "The key has expired",
        "-": "The key is of unknown validity (i.e. no value assigned)",
        "q": "The key is of undefined validity",
        "n": "The key is valid",
        "m": "The key is marginal valid.",
        "f": "The key is fully valid",
        "u": "The key is ultimately valid.",
    }
    if parts[1] in ('i', 'd', 'r', 'e'):
        messages.append("{}: {}".format(desc, VALIDITY[parts[1]]))
    if 'D' in parts[11]:
        messages.append("{}: The key has been disabled (field 12)".format(desc))
    if messages:
        raise ScriptWorkerGPGException('\n'.join(messages))
    keyid = parts[4]
    return keyid


def _parse_fpr_line(fpr_line, desc, expected=None):
    """
     10. Field:  User-ID.  The value is quoted like a C string to avoid
                 control characters (the colon is quoted "\x3a").
                 For a "pub" record this field is not used on --fixed-list-mode.
                 A UAT record puts the attribute subpacket count here, a
                 space, and then the total attribute subpacket size.
                 In gpgsm the issuer name comes here
                 An FPR record stores the fingerprint here.
                 The fingerprint of an revocation key is stored here.
    """
    parts = fpr_line.split(':')
    fingerprint = parts[9]
    return fingerprint


def _parse_sig_line(sig_line, desc):
    """
sig:::1:D9DC50F64C7D44CF:1472242430::::Scriptworker Test (test key for scriptworker) <scriptworker@example.com>:13x:::::8:
    """
    parts = sig_line.split(':')
    keyid = parts[4]
    uid = parts[9]
    return keyid, uid


def _parse_uid_line(uid_line, desc):
    """
sig:::1:D9DC50F64C7D44CF:1472242430::::Scriptworker Test (test key for scriptworker) <scriptworker@example.com>:13x:::::8:
    """
    parts = uid_line.split(':')
    uid = parts[9]
    return uid


def parse_list_sigs_output(output, desc, expected=None):
    """Parse the output from --list-sigs; validate.

    NOTE: This doesn't work with complex key/subkeys; this is only written for
    the keys generated through the functions in this module.

    1. Field:  Type of record
               pub = public key
               crt = X.509 certificate
               crs = X.509 certificate and private key available
               sub = subkey (secondary key)
               sec = secret key
               ssb = secret subkey (secondary key)
               uid = user id (only field 10 is used).
               uat = user attribute (same as user id except for field 10).
               sig = signature
               rev = revocation signature
               fpr = fingerprint: (fingerprint is in field 10)
               pkd = public key data (special field format, see below)
               grp = keygrip
               rvk = revocation key
               tru = trust database information
               spk = signature subpacket

    There are also 'gpg' lines like

        gpg: checking the trustdb
        gpg: 3 marginal(s) needed, 1 complete(s) needed, PGP trust model
        gpg: depth: 0  valid:   3  signed:   0  trust: 0-, 0q, 0n, 0m, 0f, 3u

    This is a description of the web of trust.  I'm currently not parsing
    these; per [1] and [2] I would need to read the source for full parsing.

    [1] http://security.stackexchange.com/a/41209

    [2] http://gnupg.10057.n7.nabble.com/placing-trust-in-imported-keys-td30124.html#a30125

    Args:
        output (str): the output from get_list_sigs_output()
        desc (str): a description of the key being tested, for exception
            message purposes.
        expected (dict, optional): expected outputs.  If specified and
            the expected doesn't match the real, raise an exception.
            Expected takes `keyid`, `fingerprint`, `uid`, `sig_keyids` (list),
            and `sig_uids` (list), all optional.  Defaults to None.

    Returns:
        real (dict): the real values from the key.  This specifies
            `keyid`, `fingerprint`, `uid`, `sig_keyids`, and `sig_uids`.

    Raises:
        ScriptWorkerGPGException: on mismatched expectations, or if we found
            revocation markers or the like that make for a bad key.
    """
    expected = expected or {}
    real = {
        'sig_keyids': [],
        'sig_uids': [],
    }
    messages = []
    for line in output.split('\n'):
        if not line:
            continue
        parts = line.split(':')
        if parts[0] == "tru":
            _parse_trust_line(line, desc)
        elif parts[0] == "pub":
            real['keyid'] = _parse_pub_line(line, desc)
            if expected.get('keyid', real['keyid']) != real['keyid']:
                messages.append(
                    "keyid {} differs from expected {}!".format(
                        real['keyid'], expected['keyid']
                    )
                )
        elif parts[0] == "fpr":
            real['fingerprint'] = _parse_fpr_line(line, desc)
            if expected.get('fingerprint', real['fingerprint']) != real['fingerprint']:
                messages.append(
                    "fingerprint {} differs from expected {}!".format(
                        real['fingerprint'], expected['fingerprint']
                    )
                )
        elif parts[0] == "uid":
            real['uid'] = _parse_uid_line(line, desc)
            if expected.get('uid', real['uid']) != real['uid']:
                messages.append(
                    "uid {} differs from expected {}!".format(
                        real['uid'], expected['uid']
                    )
                )
        elif parts[0] == "sig":
            sig_keyid, sig_uid = _parse_sig_line(line, desc)
            real['sig_keyids'].append(sig_keyid)
            real['sig_uids'].append(sig_uid)
        elif parts[0] in ("rev", "rvk"):
            messages.append(
                "Found a revocation marker {} in {}!\nRevocation parsing is incomplete; assuming this key is bad.".format(parts[0], desc)
            )
        else:
            log.warning("Signature parsing doesn't yet support {} lines (in {})...\n {}".format(parts[0], desc, line))
    expected_sigs = set(expected.get('sig_keyids', real['sig_keyids']))
    real_sigs = set(real['sig_keyids'])
    if not expected_sigs.issubset(real_sigs):
        messages.append("Missing expected signatures on {}!\n{}".format(desc, expected_sigs.difference(real_sigs)))
    if messages:
        raise ScriptWorkerGPGException("\n".join(messages))
    return real


def get_list_sigs_output(context, key_fingerprint, gpg_home=None, validate=True, expected=None):
    """gpg --list-sigs, with machine parsable output, for gpg 2.0.x

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        key_fingerprint (str): the fingerprint of the key we want to get
            signature information about.
        gpg_home (str, optional): override the gpg_home with a different
            gnupg home directory here.  Defaults to None.
        validate (bool, optional): Validate the output via parse_list_sigs_output()
            Defaults to True.
        expected (dict, optional): This is passed on to parse_list_sigs_output()
            if validate is True.  Defaults to None.

    Returns:
        str: the output from gpg --list-sigs, if validate is False
        dict: the output from parse_list_sigs_output, if validate is True

    Raises:
        ScriptWorkerGPGException: if there is an issue with the key.
    """
    gpg_home = guess_gpg_home(context, gpg_home=gpg_home)
    gpg_path = guess_gpg_path(context)
    log.info("Getting --list-sigs output for {} in {}...".format(key_fingerprint, gpg_home))
    sig_output = subprocess.check_output(
        [gpg_path] + gpg_default_args(gpg_home) +
        ["--with-colons", "--list-sigs", "--with-fingerprint", "--with-fingerprint",
         key_fingerprint],
        stderr=subprocess.STDOUT
    ).decode('utf-8')
    if "No public key" in sig_output:
        raise ScriptWorkerGPGException("No gpg key {} in {}!".format(key_fingerprint, gpg_home))
    if validate:
        return parse_list_sigs_output(sig_output, key_fingerprint, expected=expected)
    return sig_output


# consume pubkey libraries {{{1
def has_suffix(path, suffixes):
    """Given a list of suffixes, return True if path ends with one of them.

    Args:
        path (str): the file path to check
        suffixes (list): the suffixes to check for
    """
    for suffix in suffixes:
        if path.endswith(suffix):
            return True
    return False


def consume_valid_keys(context, keydir=None, ignore_suffixes=(), gpg_home=None):
    """Given a keydir, traverse the keydir, and import all gpg public keys.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        keydir (str, optional): the path of the directory to traverse.  If None,
            this function is noop.  Default is None.
        ignore_suffixes (list, optional): file suffixes to ignore.  Default is ().
        gpg_home (str, optional): override the gpg_home dir.  Default is None.

    Returns:
        list: fingerprints

    Raises:
        ScriptworkerGPGException: on error.
    """
    if not keydir:
        return
    gpg = GPG(context, gpg_home=gpg_home)
    fingerprints = []
    messages = []
    if not os.path.isdir(os.path.realpath(keydir)):
        raise ScriptWorkerGPGException("consume_valid_keys: {} is not a dir!".format(keydir))
    filepaths = filepaths_in_dir(keydir)
    for filepath in filepaths:
        if has_suffix(filepath, ignore_suffixes):
            continue
        path = os.path.join(keydir, filepath)
        with open(path, "r") as fh:
            result = import_key(gpg, fh.read(), return_type='result')
            for fp in result:
                if fp['fingerprint'] is not None:
                    fingerprints.append(fp['fingerprint'])
                else:
                    messages.append("Can't import key from {}: {}!".format(path, fp['text']))
    if messages:
        raise ScriptWorkerGPGException('\n'.join(messages))
    return fingerprints


def rebuild_gpg_home(context, tmp_gpg_home, my_pub_key_path, my_priv_key_path):
    """import my key and create gpg.conf and trustdb.gpg

    Args:
        gpg (gnupg.GPG): the GPG instance.
        tmp_gpg_home (str): the path to the tmp gpg_home.  This should already
            exist.
        my_pub_key_path (str): the ascii public key file we want to import as the
            primary key
        my_priv_key_path (str): the ascii private key file we want to import as
            the primary key

    Returns:
        str: my fingerprint
    """
    os.chmod(tmp_gpg_home, 0o700)
    gpg = GPG(context, gpg_home=tmp_gpg_home)
    for path in (my_pub_key_path, my_priv_key_path):
        with open(path, "r") as fh:
            my_fingerprint = import_key(gpg, fh.read())[0]
    create_gpg_conf(tmp_gpg_home, my_fingerprint=my_fingerprint)
    update_ownertrust(context, my_fingerprint, gpg_home=tmp_gpg_home)
    return my_fingerprint


def overwrite_gpg_home(tmp_gpg_home, real_gpg_home):
    """Take the contents of tmp_gpg_home and copy them to real_gpg_home.

    For now, back up real_gpg_home before doing so.  We may want to revisit
    for disk space reasons: only keep N backups?

    Args:
        tmp_gpg_home (str): path to the rebuilt gpg_home with the new keychains+
            trust models
        real_gpg_home (str): path to the old gpg_home to overwrite
    """
    log.info("overwrite_gpg_home: {} to {}".format(tmp_gpg_home, real_gpg_home))
    # Back up real_gpg_home until we have more confidence in blowing this away
    if os.path.exists(real_gpg_home):
        backup = "{}.{}".format(real_gpg_home, str(arrow.utcnow().timestamp))
        log.info("Backing up {} to {}".format(real_gpg_home, backup))
        os.rename(real_gpg_home, backup)
    makedirs(real_gpg_home)
    os.chmod(real_gpg_home, 0o700)
    for filepath in filepaths_in_dir(tmp_gpg_home):
        os.rename(
            os.path.join(tmp_gpg_home, filepath),
            os.path.join(real_gpg_home, filepath)
        )
    # for now, don't clean up tmp_gpg_home, because we call this with tempfile
    # contexts that expect to clean up tmp_gpg_home on exiting the block.


async def rebuild_gpg_home_flat(context, real_gpg_home, my_pub_key_path,
                                my_priv_key_path, consume_path, ignore_suffixes=(),
                                consume_function=consume_valid_keys):
    """Rebuild `real_gpg_home` with new trustdb, pub+secrings, gpg.conf.

    In this 'flat' model, import all the pubkeys in `consume_path` and sign
    them directly.  This makes them valid but not trusted.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        real_gpg_home (str): the gpg_home path we want to rebuild
        my_pub_key_path (str): the ascii public key file we want to import as the
            primary key
        my_priv_key_path (str): the ascii private key file we want to import as the
            primary key
        consume_path (str): the path to the directory tree to import pubkeys
            from
        ignore_suffixes (list, optional): the suffixes to ignore in consume_path.
            Defaults to ()
    """
    # Create a new tmp_gpg_home to import into
    with tempfile.TemporaryDirectory() as tmp_gpg_home:
        my_fingerprint = rebuild_gpg_home(
            context, tmp_gpg_home, my_pub_key_path, my_priv_key_path
        )
        # import all the keys
        fingerprints = consume_function(
            context, keydir=consume_path,
            ignore_suffixes=ignore_suffixes, gpg_home=tmp_gpg_home
        )
        # sign all the keys
        for fingerprint in fingerprints:
            log.info("signing {} with {}".format(fingerprint, my_fingerprint))
            await sign_key(
                context, fingerprint, signing_key=my_fingerprint,
                gpg_home=tmp_gpg_home
            )
        # Copy tmp_gpg_home/* to real_gpg_home/* before nuking tmp_gpg_home/
        overwrite_gpg_home(tmp_gpg_home, real_gpg_home)


async def rebuild_gpg_home_signed(context, real_gpg_home, my_pub_key_path,
                                  my_priv_key_path, trusted_path,
                                  untrusted_path=None, ignore_suffixes=(),
                                  consume_function=consume_valid_keys):
    """Rebuild `real_gpg_home` with new trustdb, pub+secrings, gpg.conf.

    In this 'signed' model, import all the pubkeys in `trusted_path`, sign
    them directly, and trust them.  Then import all the pubkeys in
    `untrusted_path` with no signing.  The intention is that one of the keys
    in `trusted_path` has already signed the keys in `untrusted_path`, making
    them valid.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        real_gpg_home (str): the gpg_home path we want to rebuild
        my_pub_key_path (str): the ascii public key file we want to import as the
            primary key
        my_priv_key_path (str): the ascii private key file we want to import as the
            primary key
        trusted_path (str): the path to the directory tree to import trusted
            pubkeys from
        untrusted_path (str, optional): the path to the directory tree to import
            untrusted but valid pubkeys from
        ignore_suffixes (list, optional): the suffixes to ignore in consume_path.
            Defaults to ()
    """
    # Create a new tmp_gpg_home to import into
    log.info("rebuilding gpg_home for {} at {}...".format(my_pub_key_path, real_gpg_home))
    with tempfile.TemporaryDirectory() as tmp_gpg_home:
        gpg = GPG(context, gpg_home=tmp_gpg_home)
        my_fingerprint = rebuild_gpg_home(
            context, tmp_gpg_home, my_pub_key_path, my_priv_key_path
        )
        my_keyid = fingerprint_to_keyid(gpg, my_fingerprint)
        # import all the trusted keys
        trusted_fingerprints = consume_function(
            context, keydir=trusted_path,
            ignore_suffixes=ignore_suffixes, gpg_home=tmp_gpg_home
        )
        trusted_fingerprints_to_keyid = {}
        # sign all the keys
        for fingerprint in set(trusted_fingerprints):
            await sign_key(
                context, fingerprint, signing_key=my_fingerprint,
                gpg_home=tmp_gpg_home
            )
            get_list_sigs_output(
                context, fingerprint, gpg_home=tmp_gpg_home,
                expected={
                    'sig_keyids': [my_keyid],
                },
            )
            trusted_fingerprints_to_keyid[fingerprint] = fingerprint_to_keyid(gpg, fingerprint)
        # trust trusted_fingerprints
        update_ownertrust(
            context, my_fingerprint, trusted_fingerprints=trusted_fingerprints,
            gpg_home=tmp_gpg_home
        )
        check_ownertrust(context, gpg_home=tmp_gpg_home)
        # import valid_fingerprints; don't sign or trust (one of the trusted
        # fingerprints should have already signed them).
        consume_function(
            context, keydir=untrusted_path,
            ignore_suffixes=ignore_suffixes, gpg_home=tmp_gpg_home
        )
        # Copy tmp_gpg_home/* to real_gpg_home/* before nuking tmp_gpg_home/
        overwrite_gpg_home(tmp_gpg_home, real_gpg_home)


# git {{{1
def verify_signed_git_commit_output(output):
    """Verify the latest non-merge-commit is signed by a trusted fingerprint.

    If the key is missing, output looks like::

        commit 6efb4ebe8900ad1920f6eaaf64b615fe6e6e839a
        gpg: directory `/Users/asasaki/.gnupg' created
        gpg: new configuration file `/Users/asasaki/.gnupg/gpg.conf' created
        gpg: WARNING: options in `/Users/asasaki/.gnupg/gpg.conf' are not yet active during this run
        gpg: keyring `/Users/asasaki/.gnupg/pubring.gpg' created
        gpg: Signature made Mon Sep 19 21:50:53 2016 PDT
        gpg:                using RSA key FC829B7FFAA9AC38
        gpg: Can't check signature: No public key
        Author: Aki Sasaki <aki@escapewindow.com>
        Date:   Mon Sep 19 21:50:35 2016 -0700

            add another check + small fixes + comments

    If the key is in the keyring but not trusted, the output looks like::

        commit 6efb4ebe8900ad1920f6eaaf64b615fe6e6e839a
        gpg: Signature made Mon Sep 19 21:50:53 2016 PDT
        gpg:                using RSA key FC829B7FFAA9AC38
        gpg: Good signature from "Aki Sasaki (2016.09.16) <aki@escapewindow.com>" [unknown]
        gpg:                 aka "Aki Sasaki (2016.09.16) <aki@mozilla.com>" [unknown]
        gpg:                 aka "Aki Sasaki (2016.09.16) <asasaki@mozilla.com>" [unknown]
        gpg:                 aka "[jpeg image of size 5283]" [unknown]
        gpg: WARNING: This key is not certified with a trusted signature!
        gpg:          There is no indication that the signature belongs to the owner.
        Primary key fingerprint: 83A4 B550 BC68 2F0B 0601  57B0 4654 904B B484 B6B2
             Subkey fingerprint: CC62 C097 98FD EFBB 4CC9  4D9C FC82 9B7F FAA9 AC38
        Author: Aki Sasaki <aki@escapewindow.com>
        Date:   Mon Sep 19 21:50:35 2016 -0700

            add another check + small fixes + comments

    If the key is in the keyring and trusted, the output looks like::

        commit 6efb4ebe8900ad1920f6eaaf64b615fe6e6e839a
        gpg: Signature made Mon Sep 19 21:50:53 2016 PDT
        gpg:                using RSA key FC829B7FFAA9AC38
        gpg: checking the trustdb
        gpg: 3 marginal(s) needed, 1 complete(s) needed, PGP trust model
        gpg: depth: 0  valid:   1  signed:   0  trust: 0-, 0q, 0n, 0m, 0f, 1u
        gpg: next trustdb check due at 2018-09-17
        gpg: Good signature from "Aki Sasaki (2016.09.16) <aki@escapewindow.com>" [ultimate]
        gpg:                 aka "Aki Sasaki (2016.09.16) <aki@mozilla.com>" [ultimate]
        gpg:                 aka "Aki Sasaki (2016.09.16) <asasaki@mozilla.com>" [ultimate]
        gpg:                 aka "[jpeg image of size 5283]" [ultimate]
        Author: Aki Sasaki <aki@escapewindow.com>
        Date:   Mon Sep 19 21:50:35 2016 -0700

            add another check + small fixes + comments

    or::

        commit 02dc29251021519ebac4508545477a7b23efea49
        gpg: Signature made Tue Sep 20 04:22:57 2016 UTC
        gpg:                using RSA key 0xFC829B7FFAA9AC38
        gpg: Good signature from "Aki Sasaki (2016.09.16) <aki@escapewindow.com>"
        gpg:                 aka "Aki Sasaki (2016.09.16) <aki@mozilla.com>"
        gpg:                 aka "Aki Sasaki (2016.09.16) <asasaki@mozilla.com>"
        gpg:                 aka "[jpeg image of size 5283]"
        Author: Aki Sasaki <aki@escapewindow.com>
        Date:   Mon Sep 19 21:22:40 2016 -0700

            add travis tests for commit signatures.


    Args:
        output (str): the output from `git log --no-merges -n 1 --show-signature`

    Raises:
        ScriptWorkerGPGException: on error.
    """
    BAD = {
        "gpg: Can't check signature:": "",
        "gpg: WARNING: This key is not certified with a trusted signature!": "",
    }
    GOOD = re.compile(r"""^gpg: Good signature from ".*"( \[(ultimate|trusted)\])?$""")
    messages = []
    lines = output.splitlines()
    status = False
    for line in lines:
        m = GOOD.match(line)
        if m is not None:
            status = True
            continue
        for k, v in BAD.items():
            if line.startswith(k):
                messages.append(v)
                continue
    if not status:
        messages.append("No trusted signature!")
    if messages:
        raise ScriptWorkerGPGException("\n".join(messages + ["output:", output]))


async def get_git_revision(path, exec_function=asyncio.create_subprocess_exec):
    """Get the git revision of path.

    Args:
        path (str): the path to run `git rev-parse HEAD` in.

    Returns:
        str: the revision.

    Raises:
        ScriptWorkerRetryException: on failure.
    """
    proc = await exec_function(
        'git', "rev-parse", "HEAD", cwd=path,
        stdout=PIPE, stderr=DEVNULL, stdin=DEVNULL, close_fds=True,
    )
    revision, err = await proc.communicate()
    exitcode = await proc.wait()
    if exitcode:
        raise ScriptWorkerRetryException(
            "Can't get repo revision at {}: {}!".format(path, err)
        )
    return revision.decode('utf-8').rstrip()


async def update_signed_git_repo(context, repo="origin", revision="master",
                                 exec_function=asyncio.create_subprocess_exec,
                                 log_function=pipe_to_log):
    """Update a git repo with signed git commits, and verify the signature.

    This function updates the repo.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        repo (str, optional): the repo to update from.  Defaults to 'origin'.
        revision (str, optional): the revision to update to.  Defaults to 'master'.

    Returns:
        bool: True if there has been a change; False otherwise.

    Raises:
        ScriptWorkerGPGException: on signature validation failure.
        ScriptWorkerRetryException: on `git pull` failure.
    """
    path = context.config['git_key_repo_dir']
    old_revision = await get_git_revision(path)
    proc = await exec_function(
        "git", "pull", "--ff-only", repo, revision, cwd=path,
        stdout=PIPE, stderr=STDOUT, stdin=DEVNULL, close_fds=True,
    )
    await log_function(proc.stdout)
    exitcode = await proc.wait()
    if exitcode:
        raise ScriptWorkerRetryException(
            "Can't update repo at {}!".format(path)
        )
    revision = await get_git_revision(path)
    return old_revision != revision


async def verify_signed_git_commit(context, path=None,
                                   exec_function=asyncio.create_subprocess_exec):
    """Verify `context.config['git_key_repo_dir']` is on a valid signed commit.

    This function calls `verify_signed_git_commit_output` to make sure the
    latest non-merge-commit commit is signed with a key that lives in
    `context.cot_config['git_commit_signing_pubkey_dir']`.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        path (str, optional): the path to the git repo to verify.  If None,
            use context.config['git_key_repo_dir'].  Defaults to None.

    Raises:
        ScriptWorkerGPGException: on bad verification.
    """
    path = path or context.config['git_key_repo_dir']
    proc = await exec_function(
        "git", "log", "--no-merges", "-n", "1", "--show-signature", cwd=path,
        stdout=PIPE, stderr=DEVNULL, stdin=DEVNULL, close_fds=True,
    )
    output = ""
    while True:
        line = await proc.stdout.readline()
        if line:
            output += line.decode('utf-8')
        else:
            break
    verify_signed_git_commit_output(output)


# build gpg homedirs from repo {{{1
async def build_gpg_homedirs_from_repo(
    context, basedir=None, verify_function=verify_signed_git_commit,
    flat_function=rebuild_gpg_home_flat, signed_function=rebuild_gpg_home_signed,
):
    """Build gpg homedirs in `basedir`, from the context-defined git repo.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        basedir (str, optional): the path to the base directory to create the
            gpg homedirs in.  This directory will be wiped if it exists.
            If None, use `context.config['base_gpg_home_dir']`.  Defaults to None.

    Returns:
        str: on success.

    Raises:
        ScriptWorkerGPGException: on rebuild exception.
    """
    basedir = basedir or context.config['base_gpg_home_dir']
    repo_path = context.config['git_key_repo_dir']
    lockfile = os.path.join(basedir, ".lock")
    if os.path.exists(lockfile):
        log.warning("Skipping build_gpg_homedirs_from_repo: lockfile {} exists!".format(lockfile))
        return
    rm(basedir)
    makedirs(basedir)
    try:
        # create lockfile
        with open(lockfile, "w") as fh:
            print(str(arrow.utcnow().timestamp), file=fh, end="")
        # verify our input.  Hardcoding the check before importing, as opposed
        # to expecting something else to run the check for us.
        await verify_function(context)
        # create gpg homedirs
        tasks = []
        for worker_class, worker_config in context.cot_config['gpg_homedirs'].items():
            source_path = os.path.join(repo_path, worker_class)
            real_gpg_home = os.path.join(basedir, worker_class)
            my_pub_key_path = context.cot_config['pubkey_path']
            my_priv_key_path = context.cot_config['privkey_path']
            if worker_config['type'] == 'flat':
                tasks.append(asyncio.ensure_future(
                    flat_function(
                        context, real_gpg_home, my_pub_key_path, my_priv_key_path,
                        source_path, ignore_suffixes=worker_config['ignore_suffixes']
                    )
                ))
            else:
                trusted_path = os.path.join(source_path, "trusted")
                untrusted_path = os.path.join(source_path, "valid")
                tasks.append(asyncio.ensure_future(
                    signed_function(
                        context, real_gpg_home, my_pub_key_path, my_priv_key_path,
                        trusted_path, untrusted_path=untrusted_path,
                        ignore_suffixes=worker_config['ignore_suffixes']
                    )
                ))
            await raise_future_exceptions(tasks)
    finally:
        rm(lockfile)
    return basedir


async def rebuild_gpg_homedirs_loop(context, basedir):
    """Run a loop to update the git repo and rebuild the homedirs.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        basedir (str): the base directory path, to create the gpg homedirs under.
            This should be a temporary directory, so we can create the gpg
            homedirs in the background without affecting anything.
            The presence of this directory with a lockfile means something is
            still generating the gpg homedirs.  The presence of this directory
            without the lockfile means we're waiting to overwrite our gpg homedirs
            with the contents of this tmp dir.
    """
    rm(basedir)
    if not context.config['sign_chain_of_trust'] and not context.config['verify_chain_of_trust']:
        log.warning("sign_chain_of_trust and verify_chain_of_trust are False; exiting rebuild_gpg_homedirs_loop!")
        return
    while True:
        await asyncio.sleep(context.config['poll_git_interval'])
        if os.path.exists(basedir):
            log.warning("rebuild_gpg_homedirs_loop: {} exists; sleeping another {}!".format(basedir, str(context.config['poll_git_interval'])))
            continue
        try:
            message = "build_gpg_homedirs_from_repo error updating git repo!\n{}"
            result = await retry_async(
                update_signed_git_repo, retry_exceptions=(ScriptWorkerRetryException, ),
                args=(context, )
            )
            if not result:  # no updates
                continue
            message = "build_gpg_homedirs_from_repo error in build_gpg_homedirs_from_repo!\n{}"
            build_gpg_homedirs_from_repo(context, basedir=basedir)
        except ScriptWorkerException as exc:
            # We don't want these exceptions to be fatal; this will happen in the background
            # of scriptworker tasks
            log.error(message.format(str(exc)))
            continue


def create_initial_gpg_homedirs():
    """Create the initial gpg homedirs.

    This should be called before scriptworker is run.

    Raises:
        SystemExit: on failure.
    """
    logging.basicConfig()
    context, _ = get_context_from_cmdln(sys.argv[1:])
    log.info("create_initial_gpg_homedirs()...")
    trusted_path = context.cot_config['git_commit_signing_pubkey_dir']
    makedirs(context.config['git_key_repo_dir'])
    event_loop = asyncio.get_event_loop()
    try:
        with tempfile.TemporaryDirectory() as tmp_gpg_home:
            event_loop.run_until_complete(
                rebuild_gpg_home_signed(
                    context, tmp_gpg_home,
                    context.cot_config['pubkey_path'],
                    context.cot_config['privkey_path'],
                    trusted_path
                )
            )
            overwrite_gpg_home(tmp_gpg_home, guess_gpg_home(context))
        log.info("Updating git repo")
        event_loop.run_until_complete(
            retry_async(
                update_signed_git_repo, retry_exceptions=(ScriptWorkerRetryException, ),
                args=(context, )
            )
        )
        event_loop.run_until_complete(verify_signed_git_commit(context))
        log.info("Updating gpg homedirs")
        event_loop.run_until_complete(
            build_gpg_homedirs_from_repo(context, basedir=context.config['base_gpg_home_dir'])
        )
        event_loop.close()
    except ScriptWorkerException as exc:
        traceback.print_exc()
        sys.exit(exc.exit_code)
