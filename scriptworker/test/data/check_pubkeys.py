#!/usr/bin/env python
"""Take the output of gen1000keys.py and test the various
scriptworker.gpg.consume_* functions.
"""
import arrow
import json
import logging
import os
import tempfile
from scriptworker.config import DEFAULT_CONFIG
from scriptworker.context import Context
import scriptworker.gpg

log = logging.getLogger(__name__)
TRUSTED_KEY_DIR = os.path.join(os.path.dirname(__file__), "gpg", "keys")
PUBKEY_DIR = os.path.join(os.path.dirname(__file__), "pubkeys")
MY_EMAIL = "scriptworker@example.com"


def print_times(start, end):
    log.info("Took {} seconds.".format(str(start.timestamp - end.timestamp)))


def main(trusted_key_dir, name=None):
    if name not in (None, "__main__"):
        return
    log.setLevel(logging.DEBUG)
    log.addHandler(logging.StreamHandler())
    context = Context()
    dirs = {}
    messages = []
    pubkey_dir = PUBKEY_DIR
    my_email = MY_EMAIL
    times = {'start': arrow.utcnow()}
    with open(os.path.join(pubkey_dir, "manifest.json"), "r") as fh:
        manifest = json.load(fh)
    # time it!
    #  consume unsigned - gpg_home 1
    #   - check data sigs -- all valid
    # read manifest.json
    #  consume signed 1-2 - gpg_home 2-3
    #   - check data sigs -- only locally signed are valid
    try:
        dirs['gpg_home1'] = tempfile.mkdtemp()
        # consume unsigned and verify sigs
        context.config = {}
        for k, v in DEFAULT_CONFIG.items():
            if k.startswith("gpg_"):
                context.config[k] = v
        context.config["gpg_home"] = dirs['gpg_home1']
        log.info("rebuild_gpg_home_flat")
        scriptworker.gpg.rebuild_gpg_home_flat(
            context,
            context.config['gpg_home'],
            os.path.join(trusted_key_dir, "{}.pub".format(my_email)),
            os.path.join(trusted_key_dir, "{}.sec".format(my_email)),
            os.path.join(pubkey_dir, "unsigned"),
        )
        times['checkpoint1'] = arrow.utcnow()
        print_times(times['start'], times['checkpoint1'])
        for fingerprint, info in manifest.items():
            log.info("uid {}".format(info['uid']))
            with open(os.path.join(pubkey_dir, "data", "{}.asc".format(fingerprint))) as fh:
                message = scriptworker.gpg.get_body(
                    scriptworker.gpg.GPG(context),
                    fh.read()
                )
            if message != info['message'] + '\n':
                messages.append("Unexpected message '{}', expected '{}'".format(message, info['message']))
        if messages:
            raise Exception('\n'.join(messages))
    finally:
        for path in dirs.values():
            # scriptworker.utils.rm(path)
            log.info(path)
        times['end'] = arrow.utcnow()
        log.info("Overall time:")
        print_times(times['start'], times['end'])


main(TRUSTED_KEY_DIR, name=__name__)
