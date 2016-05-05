Script Worker
===============================

[![Build Status](https://travis-ci.org/escapewindow/scriptworker.svg?branch=master)](https://travis-ci.org/escapewindow/scriptworker) [![Coverage Status](https://coveralls.io/repos/github/escapewindow/scriptworker/badge.svg?branch=master)](https://coveralls.io/github/escapewindow/scriptworker?branch=master)

Script worker implements the [TaskCluster](http://docs.taskcluster.net/queue/worker-interaction/) worker model, then launches a pre-defined script.

This worker was designed for [Releng processes](https://bugzilla.mozilla.org/show_bug.cgi?id=1245837) that need specific, limited, and pre-defined capabilities.

Free software: MPL2 license

Usage
-----
* Create a config file.  By default scriptworker will look in `./config.json`, but this config path can be specified as the first and only commandline argument.  There is an [example config file](https://github.com/escapewindow/scriptworker/blob/master/config_example.json) and all config items are specified in [`scriptworker.config.DEFAULT_CONFIG`](https://github.com/escapewindow/scriptworker/blob/master/scriptworker/config.py#L13-L45).
* Launch: `scriptworker [config_path]`

Testing
-------
Without integration tests,

`NO_TESTS_OVER_WIRE=1 python setup.py test`

With integration tests, first create a client with the `assume:project:taskcluster:worker-test-scopes` scope.

Then  create a `./secrets.json` or `~/.scriptworker` that looks like

```json
{
    "integration_credentials": {
        "clientId": "...",
        "accessToken": "...",
        "certificate": "..."
    }
}
```

(certificate is only specified if using temp creds)


then

`python setup.py test`
