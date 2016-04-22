#!/usr/bin/env python
"""Config for scriptworker
"""
import json
import logging

from frozendict import frozendict

log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    # Worker identification
    "provisioner_id": "test-dummy-provisioner",
    "scheduler_id": "test-dummy-scheduler",
    "worker_group": "test-dummy-workers",
    "worker_type": "dummy-worker-aki",
    "worker_id": "dummy-worker-aki1",

    # Worker credentials
    "taskcluster_client_id": "...",
    "taskcluster_access_token": "...",

    # Worker settings; these probably don't need tweaking
    "max_connections": 30,
    "reclaim_interval": 5,  # TODO 300
    "poll_interval": 5,  # TODO 1 ?

    # Worker log settings
    "log_datefmt": "%Y-%m-%dT%H:%M:%S",
    "log_fmt": "%(asctime)s %(levelname)8s - %(message)s",
    "log_max_bytes": 1024 * 1024 * 512,
    "log_num_backups": 10,

    # Task settings
    "work_dir": "...",
    "log_dir": "...",
    "artifact_dir": "...",
    "task_script": ("bash", "-c", "echo foo && sleep 19 && exit 2"),
    "verbose": True,
}


def create_config(filename="secrets.json"):
    """Create a config from DEFAULT_CONFIG, arguments, and config file.
    """
    # TODO configurability -- cmdln arguments
    with open(filename, "r") as fh:
        secrets = json.load(fh)

    config = dict(DEFAULT_CONFIG).copy()
    config.update(secrets)
    # TODO verify / dtd
    config = frozendict(config)
    return config
