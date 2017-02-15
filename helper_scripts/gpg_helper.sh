#!/bin/sh
OPTIND=1

while getopts "b:h:" opt; do
    case "$opt" in
        b)
            GPGBIN=${OPTARG:-$GPGBIN}
            ;;
        h)
            GPGHOME=${OPTARG:-$GPGHOME}
            ;;
        esac
done

shift $((OPTIND-1))

[ "$1" = "--" ] && shift

if [ -z "$GPGBIN" ];
    then GPGBIN="/usr/bin/gpg"
fi

$GPGBIN --no-default-keyring --secret-keyring "$GPGHOME"/secring.gpg --keyring "$GPGHOME"/pubring.gpg "$@"
