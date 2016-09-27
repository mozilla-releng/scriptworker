#!/usr/bin/env python
"""Take the output of gen1000keys.py and test the various
scriptworker.gpg.consume_* functions.
"""
import arrow
import asyncio
import glob
import json
import logging
import os
import shutil
import tempfile
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerGPGException
import scriptworker.gpg

log = logging.getLogger(__name__)
TRUSTED_KEY_DIR = os.path.join(os.path.dirname(__file__), "gpg", "keys")
# TODO 1000pubkeys instead of pubkeys
PUBKEY_DIR = os.path.join(os.path.dirname(__file__), "pubkeys")
MY_EMAIL = "scriptworker@example.com"


def get_trusted_emails(trusted_key_dir):
    filepaths = glob.glob(os.path.join(trusted_key_dir, "*.sec"))
    emails = []
    for filepath in filepaths:
        if 'unknown@' in filepath or 'scriptworker@' in filepath:
            continue
        emails.append(os.path.basename(filepath)[:-4])
    return emails


def print_times(start, end, msg=""):
    log.info("{} took {} seconds.".format(msg, str(end.timestamp - start.timestamp)))


def check_sigs(context, manifest, pubkey_dir, trusted_emails=None):
    messages = []
    gpg = scriptworker.gpg.GPG(context)
    for fingerprint, info in manifest.items():
        log.info("fingerprint {} uid {}".format(fingerprint, info['uid']))
        try:
            with open(os.path.join(pubkey_dir, "data", "{}.asc".format(fingerprint))) as fh:
                message = scriptworker.gpg.get_body(gpg, fh.read())
            if message != info['message'] + '\n':
                messages.append(
                    "Unexpected message '{}', expected '{}' {}".format(message, info['message'], info['signing_email'])
                )
        except ScriptWorkerGPGException as exc:
            if trusted_emails and info['signing_email'] not in trusted_emails:
                pass
            else:
                messages.append("{} {} error: {}".format(fingerprint, info['signing_email'], str(exc)))
    return messages


def get_context(gpg_home):
    context = Context()
    context.config = {}
    for k, v in DEFAULT_CONFIG.items():
        if k.startswith("gpg_"):
            context.config[k] = v
    context.config["gpg_home"] = gpg_home
    return context


def main(trusted_key_dir, name=None):
    if name not in (None, "__main__"):
        return
    log.setLevel(logging.DEBUG)
    log.addHandler(logging.StreamHandler())
    slog = logging.getLogger("scriptworker")
#    slog.setLevel(logging.INFO)
    slog.setLevel(logging.DEBUG)
    slog.addHandler(logging.StreamHandler())
    event_loop = asyncio.get_event_loop()
    dirs = {}
    messages = []
    pubkey_dir = PUBKEY_DIR
    my_email = MY_EMAIL
    times = {'start': arrow.utcnow()}
    with open(os.path.join(pubkey_dir, "manifest.json"), "r") as fh:
        manifest = json.load(fh)
    try:
        dirs['gpg_home1'] = tempfile.mkdtemp()
        # consume unsigned and verify sigs
        context = get_context(dirs['gpg_home1'])
        log.info("rebuild_gpg_home_flat")
        event_loop.run_until_complete(
            scriptworker.gpg.rebuild_gpg_home_flat(
                context,
                context.config['gpg_home'],
                os.path.join(trusted_key_dir, "{}.pub".format(my_email)),
                os.path.join(trusted_key_dir, "{}.sec".format(my_email)),
                os.path.join(pubkey_dir, "unsigned"),
            )
        )
        times['checkpoint1'] = arrow.utcnow()
        print_times(times['start'], times['checkpoint1'], msg="rebuild_home_flat")
        messages = check_sigs(
            context, manifest, pubkey_dir,
        )
        times['checkpoint2'] = arrow.utcnow()
        print_times(times['checkpoint1'], times['checkpoint2'], "verifying flat sigs")
        if messages:
            raise Exception('\n'.join(messages))
        for email in get_trusted_emails(trusted_key_dir):
            times["{}.1".format(email)] = arrow.utcnow()
            dirs[email] = tempfile.mkdtemp()
            my_trusted_dir = tempfile.mkdtemp()
            dirs["{}-trusted".format(email)] = my_trusted_dir
            context = get_context(dirs[email])
            gpg = scriptworker.gpg.GPG(context)
            log.info("rebuild_gpg_home_signed {}".format(email))
            for f in glob.glob(os.path.join(trusted_key_dir, "{}*".format(email))):
                shutil.copyfile(f, os.path.join(my_trusted_dir, os.path.basename(f)))
            event_loop.run_until_complete(
                scriptworker.gpg.rebuild_gpg_home_signed(
                    context,
                    dirs[email],
                    os.path.join(trusted_key_dir, "{}.pub".format(my_email)),
                    os.path.join(trusted_key_dir, "{}.sec".format(my_email)),
                    my_trusted_dir,
                )
            )
            for fingerprint, info in manifest.items():
                with open(os.path.join(pubkey_dir, info['signed_path'])) as fh:
                    scriptworker.gpg.import_key(gpg, fh.read())
                if info['signing_email'] == email:
                    # validate key
                    scriptworker.gpg.get_list_sigs_output(
                        context, fingerprint,
                        expected={'sig_keyids': [info['signing_keyid']]}
                    )
            times["{}.2".format(email)] = arrow.utcnow()
            print_times(
                times['{}.1'.format(email)], times['{}.2'.format(email)],
                msg="{} rebuild_home_signed".format(email)
            )
            messages = check_sigs(
                context, manifest, pubkey_dir, trusted_emails=[email]
            )
            if messages:
                raise Exception("My email: {} trusted_email: {}\n".format(my_email, email) + '\n'.join(messages))
            times["{}.3".format(email)] = arrow.utcnow()
            print_times(
                times['{}.2'.format(email)], times['{}.3'.format(email)],
                msg="{} check_sigs".format(email)
            )
    finally:
        for path in dirs.values():
            scriptworker.utils.rm(path)
        times['end'] = arrow.utcnow()
        log.info("Overall time:")
        print_times(times['start'], times['end'])


main(TRUSTED_KEY_DIR, name=__name__)
