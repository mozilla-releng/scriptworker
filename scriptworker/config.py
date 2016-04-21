#!/usr/bin/env python
"""Config for scriptworker
"""
import json
import logging

from frozendict import frozendict

log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "provisioner_id": "test-dummy-provisioner",
    "scheduler_id": "test-dummy-scheduler",
    "worker_group": "test-dummy-workers",
    "worker_type": "dummy-worker-aki",
    "taskcluster_client_id": "...",
    "taskcluster_access_token": "...",
    "work_dir": "...",
    "log_dir": "...",
    "artifact_dir": "...",
    "worker_id": "dummy-worker-aki1",
    "max_connections": 30,
    "reclaim_interval": 5,  # TODO 300
    "poll_interval": 5,  # TODO 1 ?
    "task_script": ("bash", "-c", "echo foo && sleep 19 && exit 2"),
    "verbose": True
}


def create_config(filename="secrets.json"):
    # TODO configurability -- cmdln arguments
    with open(filename, "r") as fh:
        secrets = json.load(fh)

    config = dict(DEFAULT_CONFIG).copy()
    config.update(secrets)
    # TODO verify / dtd
    config = frozendict(config)
    return config
