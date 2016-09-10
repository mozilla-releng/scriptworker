#!/usr/bin/env python
"""Create N keys, and export the pubkeys + signed files to a directory for testing.

"""
import arrow
import glob
import gnupg
import logging
import os
import pprint
import tempfile

import scriptworker.gpg
import scriptworker.utils

log = logging.getLogger(__name__)
TRUSTED_KEY_DIR = os.path.join(os.path.dirname(__file__), "gpg", "keys")


def import_priv_keys(gpg, trusted_key_dir):
    file_list = glob.glob("{}/*.sec".format(trusted_key_dir))
    trusted_fingerprint_dict = {}
    for path in file_list:
        if 'unknown@' in path:  # treat unknown@example.com as a real unknown key
            continue
        email = os.path.filename(path).replace('.sec', '')
        with open(path, "r") as fh:
            trusted_fingerprint_dict[email] = scriptworker.gpg.import_key(gpg, fh.read())[0]
    return trusted_fingerprint_dict


def write_key(gpg, fingerprint, path, private=False):
    parent_dir = os.path.dirname(path)
    scriptworker.utils.makedirs(parent_dir)
    with open(path, "w") as fh:
        print(gpg.export_keys(fingerprint, private), file=fh, end="")


def build_pubkeys_dir(pubkey_dir, trusted_key_dir, num_keys, key_length=2048):
    start = arrow.utcnow()
    manifest = {}

    with tempfile.TemporaryDirectory() as tmp:
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
            manifest[fingerprint] = {
                "uid": "{} ({}) <{}>".format(str_i, str_i, str_i)
            }
            write_key(
                gpg, fingerprint,
                os.path.join(pubkey_dir, "unsigned", "{}.pub".format(fingerprint))
            )
            signed_data = gpg.sign(str_i, keyid=fingerprint)
            with open(os.path.join(pubkey_dir, "data", "{}.asc".format(fingerprint)), "w") as fh:
                print(signed_data, file=fh, end="")
            signing_email = trusted_list.pop(0)
            trusted_list.append(signing_email)
            # TODO sign the generated pubkey with trusted key -- need CONTEXT
            # TODO write to pubkey_dir/email
            # TODO add to manifest
        # TODO create a json file with all the fingerprint + signature info
    end = arrow.utcnow()
    print("Took %s seconds" % str(end.timestamp - start.timestamp))


def main(*args, name=None, **kwargs):
    if name not in (None, "__main__"):
        return
    build_pubkeys_dir(*args, **kwargs)


main(os.path.join(os.getcwd(), 10, "pubkeys"), TRUSTED_KEY_DIR, name=__name__)
