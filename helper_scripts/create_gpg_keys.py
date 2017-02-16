#!/usr/bin/env python

import argparse
import gnupg
import os
import shutil
import scriptworker.gpg


class FullPaths(argparse.Action):
    """Expand user- and relative-paths"""

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, os.path.abspath(os.path.expanduser(values)))


parser = argparse.ArgumentParser(description="GPG keypair creation and export script")
parser.add_argument('-b', '--gpgbin', nargs='?', help="GPG binary used", action=FullPaths,
                    default="/usr/local/bin/gpg2")
parser.add_argument('-o', '--gpghome', nargs='?', help="GPG home folder", action=FullPaths,
                    default=os.path.join(os.getcwd(), "gpg"))
parser.add_argument('-u', '--username', nargs='?', help="Email username", default="cltsign")
parser.add_argument('-s', '--hosts', nargs='+', help="Host names to generate for",
                    default=["signing-linux-1.srv.releng.use1.mozilla.com",
                             "signing-linux-2.srv.releng.usw2.mozilla.com",
                             "signing-linux-3.srv.releng.use1.mozilla.com",
                             "signing-linux-4.srv.releng.usw2.mozilla.com"])
parser.add_argument('-e', '--expires', nargs='?', help="Validity period for key", default="2y")
parser.add_argument('--clean', action='store_true', default=False)
args = parser.parse_args()

gpgbinary = args.gpgbin
gpghome = args.gpghome
user = args.username
hosts = args.hosts
duration = args.expires
cleanup = args.clean

gpg = gnupg.GPG(
    gnupghome=gpghome,
    keyring=os.path.join(gpghome, "pubring.gpg"),
    secret_keyring=os.path.join(gpghome, "secring.gpg"),
    gpgbinary=gpgbinary,
)

if cleanup:
    shutil.rmtree(gpghome)
    os.makedirs(gpghome)

for host in hosts:
    name = host.split('.')[0]
    fingerprint = scriptworker.gpg.generate_key(
        gpg, name, '', user + '@{}'.format(host),
        expiration=duration
    )
    for pvt in (True, False):
        key = scriptworker.gpg.export_key(gpg, fingerprint, private=pvt)
        suffix = ".pub"
        if pvt:
            suffix = ".sec"
        with open("{}{}".format(name, suffix), "w") as fh:
            print(key, file=fh, end='')
