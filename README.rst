===================
Scriptworker Readme
===================

.. image:: https://travis-ci.org/mozilla-releng/scriptworker.svg?branch=master
    :target: https://travis-ci.org/mozilla-releng/scriptworker

.. image:: https://coveralls.io/repos/github/mozilla-releng/scriptworker/badge.svg?branch=master
    :target: https://coveralls.io/github/mozilla-releng/scriptworker?branch=master

.. image:: https://readthedocs.org/projects/scriptworker/badge/?version=latest
    :target: http://scriptworker.readthedocs.io/en/latest/?badge=latest
    :alt: Documentation Status

Scriptworker implements the `TaskCluster worker model`_, then launches a pre-defined script.

.. _TaskCluster worker model: https://firefox-ci-tc.services.mozilla.com/docs/reference/platform/queue/worker-interaction

This worker was designed for `Releng processes`_ that need specific, limited, and pre-defined capabilities.

.. _Releng processes: https://bugzilla.mozilla.org/show_bug.cgi?id=1245837

Free software: MPL2 License

-----
Usage
-----
* Create a config file.  By default scriptworker will look in ``./scriptworker.yaml``, but this config path can be specified as the first and only commandline argument.  There is an `example config file`_, and all config items are specified in `scriptworker.constants.DEFAULT_CONFIG`_.

.. _example config file: https://github.com/mozilla-releng/scriptworker/blob/master/scriptworker.yaml.tmpl
.. _scriptworker.constants.DEFAULT_CONFIG: https://github.com/mozilla-releng/scriptworker/blob/master/src/scriptworker/constants.py

Credentials can live in ``./scriptworker.yaml``, ``./secrets.json``, ``~/.scriptworker``, or in environment variables:  ``TASKCLUSTER_ACCESS_TOKEN``, ``TASKCLUSTER_CLIENT_ID``, and ``TASKCLUSTER_CERTIFICATE``.

* Launch: ``scriptworker [config_path]``

-------
Testing
-------

Without integration tests, install tox, then

``NO_CREDENTIALS_TESTS=1 tox -e py36``

Without any tests connecting ot the net, then

``NO_TESTS_OVER_WIRE=1 tox -e py36``

With integration tests, first create a client with the scopes::

    queue:cancel-task:test-dummy-scheduler/*
    queue:claim-work:test-dummy-provisioner/dummy-worker-*
    queue:create-task:lowest:test-dummy-provisioner/dummy-worker-*
    queue:define-task:test-dummy-provisioner/dummy-worker-*
    queue:get-artifact:SampleArtifacts/_/X.txt
    queue:scheduler-id:test-dummy-scheduler
    queue:schedule-task:test-dummy-scheduler/*
    queue:task-group-id:test-dummy-scheduler/*
    queue:worker-id:test-dummy-workers/dummy-worker-*

Then  create a ``./secrets.json`` or ``~/.scriptworker`` that looks like::

    {
        "integration_credentials": {
            "clientId": "...",
            "accessToken": "...",
            "certificate": "..."
        }
    }


(``certificate`` is only specified if using temp creds)


then

``tox``
