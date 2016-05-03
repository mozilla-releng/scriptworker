Script Worker
===============================

Script worker implements the [TaskCluster](http://docs.taskcluster.net/queue/worker-interaction/) worker model, then launches a pre-defined script.

This worker was designed for [Releng processes](https://bugzilla.mozilla.org/show_bug.cgi?id=1245837) that need specific, limited, and pre-defined capabilities.

Usage:
* Create a config file.  By default scriptworker will look in `./secrets.json`, but this config path can be specified as the first and only commandline argument.  There is an [example config file](https://github.com/escapewindow/scriptworker/blob/master/config_example.json) and all config items are specified in [`scriptworker.config.DEFAULT_CONFIG`](https://github.com/escapewindow/scriptworker/blob/master/scriptworker/config.py#L13-L45).
* Launch: `scriptworker [config_path]`

Free software: MPL2 license
