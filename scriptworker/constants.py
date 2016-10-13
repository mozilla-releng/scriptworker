#!/usr/bin/env python
"""scriptworker constants

Attributes:
    DEFAULT_CONFIG (frozendict): the default config for scriptworker.  Running configs
        are validated against this.
    STATUSES (dict): maps taskcluster status (string) to exit code (int).
    REVERSED_STATUSES (dict): the same as STATUSES, except it maps the exit code
        (int) to the taskcluster status (string).
"""
from frozendict import frozendict
import os

# DEFAULT_CONFIG {{{1
DEFAULT_CONFIG = frozendict({
    # Worker identification
    "provisioner_id": "test-dummy-provisioner",
    "worker_group": "test-dummy-workers",
    "worker_type": "dummy-worker-myname",
    "worker_id": os.environ.get("SCRIPTWORKER_WORKER_ID", "dummy-worker-myname1"),

    "credentials": frozendict({
        "clientId": "...",
        "accessToken": "...",
        "certificate": "...",
    }),

    # for download url validation.  The regexes need to define a 'filepath'.
    'valid_artifact_schemes': ('https', ),
    'valid_artifact_netlocs': ('queue.taskcluster.net', ),
    'valid_artifact_path_regexes': (
        r'''^/v1/task/(?P<taskId>[^/]+)(/runs/\d+)?/artifacts/(?P<filepath>.*)$''',
    ),
    'valid_artifact_task_ids': (),

    # Worker settings; these probably don't need tweaking
    "max_connections": 30,
    # intervals are expressed in seconds
    "credential_update_interval": 300,
    "reclaim_interval": 300,
    "poll_git_interval": 300,
    "poll_interval": 5,

    # chain of trust settings
    "verify_chain_of_trust": False,  # TODO True
    "sign_chain_of_trust": True,
    "my_email": "scriptworker@example.com",
    "chain_of_trust_hash_algorithm": "sha256",
    "cot_schema_path": os.path.join(os.path.dirname(__file__), "data", "cot_v1_schema.json"),
    "cot_config_schema_path": os.path.join(os.path.dirname(__file__), "data", "cot_config_schema.json"),
    "cot_config_path": os.path.join(os.getcwd(), "cot_config.json"),

    # Specify a default gpg home other than ~/.gnupg
    "gpg_home": None,
    # A list of additional gpg cmdline options
    "gpg_options": None,
    # The path to the gpg executable.
    "gpg_path": None,
    # The path to the public/secret keyrings, if we're not using the default
    "gpg_public_keyring": '%(gpg_home)s/pubring.gpg',
    "gpg_secret_keyring": '%(gpg_home)s/secring.gpg',
    # Boolean to use the gpg agent
    "gpg_use_agent": False,
    "gpg_encoding": 'utf-8',

    # Worker log settings
    "log_datefmt": "%Y-%m-%dT%H:%M:%S",
    "log_fmt": "%(asctime)s %(levelname)8s - %(message)s",
    "log_max_bytes": 1024 * 1024 * 512,
    "log_num_backups": 10,

    # Task settings
    "work_dir": "...",
    "log_dir": "...",
    "artifact_dir": "...",
    "task_log_dir": "...",  # set this to ARTIFACT_DIR/public/logs
    "git_key_repo_dir": "...",
    "base_gpg_home_dir": "...",
    "artifact_expiration_hours": 24,
    "artifact_upload_timeout": 60 * 20,
    "sign_key_timeout": 60 * 2,
    "task_script": ("bash", "-c", "echo foo && sleep 19 && exit 1"),
    "task_max_timeout": 60 * 20,
    "verbose": True,
})

# STATUSES and REVERSED_STATUSES {{{1
STATUSES = {
    'success': 0,
    'failure': 1,
    'worker-shutdown': 2,
    'malformed-payload': 3,
    'resource-unavailable': 4,
    'internal-error': 5,
    'superseded': 6,
}
REVERSED_STATUSES = {v: k for k, v in STATUSES.items()}
