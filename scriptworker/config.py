#!/usr/bin/env python
"""Config for scriptworker
"""
import json
import logging
import os
import sys

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
    "artifact_expiration_hours": 24,
    "artifact_upload_timeout": 60 * 20,
    "task_script": ("bash", "-c", "echo foo && sleep 19 && exit 2"),
    "task_max_timeout": 60 * 20,
    "verbose": True,
}


def list_to_tuple(dictionary):
    for key, value in dictionary.items():
        if isinstance(value, list):
            dictionary[key] = tuple(value)


def check_config(config, path):
    messages = []
    for key, value in config.items():
        if key not in DEFAULT_CONFIG:
            messages.append("Unknown key {} in {}!".format(key, path))
            continue
        value_type = type(value)
        default_type = type(DEFAULT_CONFIG[key])
        if value_type != default_type:
            messages.append(
                "{} {}: type {} is not {}!".format(path, key, value_type, default_type)
            )
        if value == "...":
            messages.append("{} {} needs to be defined!".format(path, key))
    return messages


def create_config(path="secrets.json"):
    """Create a config from DEFAULT_CONFIG, arguments, and config file.
    """
    if not os.path.exists(path):
        print("{} doesn't exist! Exiting create_config()...".format(path),
              file=sys.stderr)
        print("Exiting...", file=sys.stderr)
        sys.exit(1)
    with open(path, "r") as fh:
        secrets = json.load(fh)
    config = dict(DEFAULT_CONFIG).copy()
    list_to_tuple(secrets)
    config.update(secrets)
    messages = check_config(config, path)
    if messages:
        print('\n'.join(messages), file=sys.stderr)
        print("Exiting...", file=sys.stderr)
        sys.exit(1)
    config = frozendict(config)
    return config
