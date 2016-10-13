===============================
scriptworker
===============================

.. image:: https://travis-ci.org/mozilla-releng/scriptworker.svg?branch=master
    :target: https://travis-ci.org/mozilla-releng/scriptworker

.. image:: https://coveralls.io/repos/github/mozilla-releng/scriptworker/badge.svg?branch=master
    :target: https://coveralls.io/github/mozilla-releng/scriptworker?branch=master

.. image:: https://readthedocs.org/projects/scriptworker/badge/?version=latest
    :target: http://scriptworker.readthedocs.io/en/latest/?badge=latest
    :alt: Documentation Status

Scriptworker implements the `TaskCluster worker model`_, then launches a pre-defined script.

.. _TaskCluster worker model: http://docs.taskcluster.net/queue/worker-interaction/

This worker was designed for `Releng processes`_ that need specific, limited, and pre-defined capabilities.

.. _Releng processes: https://bugzilla.mozilla.org/show_bug.cgi?id=1245837

Free software: MPL2 license

-----
Usage
-----
* Create a config file.  By default scriptworker will look in ``./scriptworker.json``, but this config path can be specified as the first and only commandline argument.  There is an `example config file`_, and all config items are specified in `scriptworker.constants.DEFAULT_CONFIG`_.

.. _example config file: https://github.com/mozilla-releng/scriptworker/blob/master/config_example.json
.. _scriptworker.constants.DEFAULT_CONFIG: https://github.com/mozilla-releng/scriptworker/blob/master/scriptworker/constants.py)

Credentials can live in ``./scriptworker.json``, ``./secrets.json``, ``~/.scriptworker``, or in environment variables:  ``TASKCLUSTER_ACCESS_TOKEN``, ``TASKCLUSTER_CLIENT_ID``, and ``TASKCLUSTER_CERTIFICATE``.

* If using either ``verify_chain_of_trust`` or ``sign_chain_of_trust``, you will also need a ``cot_config.json``, which is either specified as the 2nd argument in the commandline, or in ``./cot_config.json``.

* Launch: ``scriptworker [config_path] [cot_config_path]``

-------
Testing
-------

Note: GPG tests require gpg 2.0.x!

Without integration tests,

``NO_TESTS_OVER_WIRE=1 python setup.py test``

With integration tests, first create a client with the ``assume:project:taskcluster:worker-test-scopes`` scope.

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

``python setup.py test``
