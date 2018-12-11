#!/bin/bash -x

# TODO? ability to set up a prod env + launch scriptworker, given
#  - taskcluster client creds
#  - scriptworker.yaml
#  - a script to run
#    - potentially a script requirements.txt to install
#  - script_config.json

test_env() {
    cd /builds/scriptworker
    pip3 install -r requirements/test.in
    python3 setup.py develop
    cp /builds/test/secrets.json .
}

if [ $1 == "unittest" ]; then
    test_env
    rm /dev/random && ln -s /dev/urandom /dev/random  # speed up gpg tests
    PYVER=`cat /builds/test/pyver`
    tox -e py$PYVER
    rc=$?
    exit $rc
elif [ $1 == "gpg" ] ; then
    test_env
    cp /builds/test/gnupg.yaml .
    exec /bin/bash -il
else
   echo "unknown mode: $1"
   exit 1
fi
