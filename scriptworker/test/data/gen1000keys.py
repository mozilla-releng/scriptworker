#!/usr/bin/env python
"""Create N keys, and export the pubkeys + signed files to a directory for testing.

Usage:
    $0 [pubkey_dir] [num_keys]
"""
import arrow
import glob
import gnupg
import json
import logging
import os
import sys
import tempfile

from scriptworker.context import Context
import scriptworker.gpg
import scriptworker.utils

log = logging.getLogger(__name__)
TRUSTED_KEY_DIR = os.path.join(os.path.dirname(__file__), "gpg", "keys")


def import_priv_keys(gpg, trusted_key_dir):
    file_list = glob.glob("{}/*.sec".format(trusted_key_dir))
    trusted_fingerprint_dict = {}
    for path in file_list:
        if 'docker' not in path:
            continue
        email = os.path.basename(path).replace('.sec', '')
        with open(path, "r") as fh:
            fingerprint = scriptworker.gpg.import_key(gpg, fh.read())[0]
        keyid = scriptworker.gpg.fingerprint_to_keyid(gpg, fingerprint)
        trusted_fingerprint_dict[email] = {
            'fingerprint': fingerprint,
            'keyid': keyid
        }
    return trusted_fingerprint_dict


def write_key(gpg, fingerprint, path, private=False):
    parent_dir = os.path.dirname(path)
    scriptworker.utils.makedirs(parent_dir)
    with open(path, "w") as fh:
        print(gpg.export_keys(fingerprint, private), file=fh, end="")


def build_pubkeys_dir(pubkey_dir, trusted_key_dir, num_keys, key_length=2048):
    start = arrow.utcnow()
    manifest = {}
    context = Context()
    scriptworker.utils.rm(pubkey_dir)
    scriptworker.utils.makedirs(os.path.join(pubkey_dir, "data"))

    with tempfile.TemporaryDirectory() as tmp:
        context.config = {
            'gpg_home': tmp,
            'gpg_path': None,
            'sign_key_timeout': 60 * 2,
        }
        gpg = gnupg.GPG(gnupghome=tmp)
        trusted_fingerprint_dict = import_priv_keys(gpg, trusted_key_dir)
        trusted_list = sorted(trusted_fingerprint_dict.keys())
        for i in range(0, num_keys):
            # this part can be a helper function
            str_i = "%05d" % i
            log.info(str_i)
            key = gpg.gen_key(
                gpg.gen_key_input(
                    name_real=str_i,
                    name_comment=str_i,
                    name_email=str_i,
                    key_length=key_length
                )
            )
            fingerprint = key.fingerprint
            unsigned_path = os.path.join("unsigned", "{}.unsigned.pub".format(fingerprint))
            manifest[fingerprint] = {
                "message": str_i,
                "uid": "{} ({}) <{}>".format(str_i, str_i, str_i),
                "unsigned_path": unsigned_path,
            }
            write_key(
                gpg, fingerprint, os.path.join(pubkey_dir, unsigned_path)
            )
            signed_data = gpg.sign(str_i, keyid=fingerprint)
            with open(os.path.join(pubkey_dir, "data", "{}.asc".format(fingerprint)), "w") as fh:
                print(signed_data, file=fh, end="")
            signing_email = trusted_list.pop(0)
            trusted_list.append(signing_email)
            scriptworker.gpg.sign_key(
                context, fingerprint, signing_key=trusted_fingerprint_dict[signing_email]['fingerprint'], exportable=True
            )
            signed_path = os.path.join(signing_email, "{}.pub".format(fingerprint))
            write_key(gpg, fingerprint, os.path.join(pubkey_dir, signed_path))
            manifest[fingerprint]['signing_email'] = signing_email
            manifest[fingerprint]['signing_fingerprint'] = trusted_fingerprint_dict[signing_email]['fingerprint']
            manifest[fingerprint]['signing_keyid'] = trusted_fingerprint_dict[signing_email]['keyid']
            manifest[fingerprint]['signed_path'] = signed_path
    with open(os.path.join(pubkey_dir, "manifest.json"), "w") as fh:
        print(json.dumps(manifest, sort_keys=True, indent=2), file=fh, end="")
    end = arrow.utcnow()
    print("Took %s seconds" % str(end.timestamp - start.timestamp))


def main(trusted_key_dir, args, name=None):
    if name not in (None, "__main__"):
        return
    log.setLevel(logging.DEBUG)
    log.addHandler(logging.StreamHandler())
    num_keys = 1000
    pubkey_dir = os.path.join(os.getcwd(), "1000pubkeys")
    if len(args) > 0:
        pubkey_dir = args[0]
        if len(args) > 1:
            num_keys = int(args[1])
            if len(args) > 2:
                print("Usage: {} [PUBKEY_DIR] [NUM_KEYS]".format(sys.argv[0]))
                sys.exit(1)
    build_pubkeys_dir(pubkey_dir, trusted_key_dir, num_keys)


main(TRUSTED_KEY_DIR, sys.argv[1:], name=__name__)
