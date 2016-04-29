#!/usr/bin/env python
# coding=utf-8
"""Scriptworker integration tests.
"""
import json
import os
import pytest
import slugid
# import taskcluster.async

TIMEOUT_SCRIPT = os.path.join(os.path.dirname(__file__), "data", "long_running.py")
SKIP_REASON = "NO_TESTS_OVER_WIRE: skipping integration test"


def read_worker_creds():
    """
    """
    files = (
        os.path.join(os.getcwd(), 'secrets.json'),
        os.path.join(os.environ['HOME'], '.scriptworker'),
    )
    for path in files:
        if not os.path.exists(path):
            continue
        with open(path, "r") as fh:
            try:
                contents = json.load(fh)
                creds = {}
                for key in ("taskcluster_client_id", "taskcluster_access_token"):
                    creds[key] = contents[key]
                return creds
            except (json.decoder.JSONDecodeError, KeyError):
                pass
    raise Exception(
        """To run integration tests, put your worker-test clientId creds, in json format,
in one of these files:

    {files}

with the format

    {{"taskcluster_client_id": "...", "taskcluster_access_token": "..."}}

This clientId will need the scope assume:project:taskcluster:worker-test-scopes

To skip integration tests, set the environment variable NO_TESTS_OVER_WIRE""".format(files=files)
    )


def get_config(override):
    cwd = os.getcwd()
    randstring = slugid.nice()[0:6]
    config = {
        'log_dir': os.path.join(cwd, "log"),
        'artifact_dir': os.path.join(cwd, "artifact"),
        'work_dir': os.path.join(cwd, "work"),
        "worker_type": "dummy-worker-{}".format(randstring),
        "worker_id": "dummy-worker-{}".format(randstring),
        'artifact_upload_timeout': 60 * 2,
        'artifact_expiration_hours': 1,
        'reclaim_interval': 2,
        'task_script': ('bash', '-c', '>&2 echo bar && echo foo && exit 2'),
        'task_max_timeout': 60,
    }
    config.update(read_worker_creds())
    if isinstance(override, dict):
        config.update(override)
    return config


class TestIntegration(object):
    @pytest.mark.skipif(os.environ.get("NO_TESTS_OVER_WIRE"), reason=SKIP_REASON)
    def test_run_successful_task(self, event_loop):
        config = get_config(None)
        assert config
