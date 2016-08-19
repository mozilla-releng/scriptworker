#!/usr/bin/env python
"""Config for scriptworker
"""
from copy import deepcopy
import json
import logging
import os
import sys

from frozendict import frozendict

log = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    # Worker identification
    "provisioner_id": "test-dummy-provisioner",
    "worker_group": "test-dummy-workers",
    "worker_type": "dummy-worker-myname",
    "worker_id": os.environ.get("SCRIPTWORKER_WORKER_ID", "dummy-worker-myname1"),

    "credentials": {
        "clientId": "...",
        "accessToken": "...",
        "certificate": "...",
    },

    # for download url validation.  The regexes need to define a 'filepath'.
    'valid_artifact_schemes': ('https', ),
    'valid_artifact_netlocs': ('queue.taskcluster.net', ),
    'valid_artifact_path_regexes': (
        r'''^/v1/task/(?P<taskId>[^/]+)(/runs/\d+)?/artifacts/(?P<filepath>.*)$''',
    ),
    'valid_artifact_task_ids': (),

    # Worker settings; these probably don't need tweaking
    "max_connections": 30,
    "credential_update_interval": 300,
    "reclaim_interval": 300,
    "poll_interval": 5,

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
    "task_script": ("bash", "-c", "echo foo && sleep 19 && exit 1"),
    "task_max_timeout": 60 * 20,
    "verbose": True,
}

CREDS_FILES = (
    os.path.join(os.getcwd(), 'secrets.json'),
    os.path.join(os.environ.get('HOME', '/etc/'), '.scriptworker'),
)


def list_to_tuple(dictionary):
    for key, value in dictionary.items():
        if isinstance(value, list):
            dictionary[key] = tuple(value)


def read_worker_creds(key="credentials"):
    """Get credentials from special files.
    """
    for path in CREDS_FILES:
        if not os.path.exists(path):
            continue
        with open(path, "r") as fh:
            try:
                contents = json.load(fh)
                return contents[key]
            except (json.decoder.JSONDecodeError, KeyError):
                pass
    else:
        if key == "credentials" and os.environ.get("TASKCLUSTER_ACCESS_TOKEN") and \
                os.environ.get("TASKCLUSTER_CLIENT_ID"):
            credentials = {
                "accessToken": os.environ["TASKCLUSTER_ACCESS_TOKEN"],
                "clientId": os.environ["TASKCLUSTER_CLIENT_ID"],
            }
            if os.environ.get("TASKCLUSTER_CERTIFICATE"):
                credentials['certificate'] = os.environ['TASKCLUSTER_CERTIFICATE']
            return credentials


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
        if value in ("...", b"...", None):
            messages.append("{} {} needs to be defined!".format(path, key))
    return messages


def create_config(path="config.json"):
    """Create a config from DEFAULT_CONFIG, arguments, and config file.
    """
    if not os.path.exists(path):
        print("{} doesn't exist! Exiting create_config()...".format(path),
              file=sys.stderr)
        print("Exiting...", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as fh:
        secrets = json.load(fh)
    config = deepcopy(DEFAULT_CONFIG)
    if not secrets.get("credentials"):
        secrets['credentials'] = read_worker_creds()
    list_to_tuple(secrets)
    config.update(secrets)
    messages = check_config(config, path)
    if messages:
        print('\n'.join(messages), file=sys.stderr)
        print("Exiting...", file=sys.stderr)
        sys.exit(1)
    credentials = frozendict(secrets['credentials'])
    del(config['credentials'])
    config = frozendict(config)
    return config, credentials
