#!/bin/sh
if [ "$HOMEDIR." == "." ] ; then
    HOMEDIR=./gpg
fi
/usr/local/bin/gpg2 --homedir $HOMEDIR --no-default-keyring --secret-keyring $HOMEDIR/secring.gpg --keyring $HOMEDIR/pubring.gpg "$@"
