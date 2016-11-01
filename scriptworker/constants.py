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
# When making changes to DEFAULT_CONFIG that may be of interest to scriptworker
# instance maintainers, also make changes to ``scriptworker.yaml.tmpl``.
# Often DEFAULT_CONFIG changes will require test changes as well.
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

    # Worker log settings
    "log_datefmt": "%Y-%m-%dT%H:%M:%S",
    "log_fmt": "%(asctime)s %(levelname)8s - %(message)s",
    "log_max_bytes": 1024 * 1024 * 512,
    "log_num_backups": 10,

    # intervals are expressed in seconds
    "artifact_expiration_hours": 24,
    "task_max_timeout": 60 * 20,
    "reclaim_interval": 300,
    "poll_interval": 5,
    "sign_key_timeout": 60 * 2,

    "task_script": ("bash", "-c", "echo foo && sleep 19 && exit 1"),

    "verbose": True,

    # Task settings
    "work_dir": "...",
    "log_dir": "...",
    "artifact_dir": "...",
    "task_log_dir": "...",  # set this to ARTIFACT_DIR/public/logs
    "git_commit_signing_pubkey_dir": "...",
    "artifact_upload_timeout": 60 * 20,

    # chain of trust settings
    "sign_chain_of_trust": True,
    "verify_chain_of_trust": False,  # TODO True
    "verify_cot_signature": False,

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

    "base_gpg_home_dir": "...",
    "gpg_lockfile": os.path.join(os.getcwd(), "gpg_homedir.lock"),
    "git_key_repo_dir": "...",
    "git_key_repo_url": "https://github.com/mozilla-releng/cot-gpg-keys.git",
    "last_good_git_revision_file": os.path.join(os.getcwd(), "git_revision"),
    "pubkey_path": "...",
    "privkey_path": "...",
    "my_email": "scriptworker@example.com",

    "chain_of_trust_hash_algorithm": "sha256",
    "cot_schema_path": os.path.join(os.path.dirname(__file__), "data", "cot_v1_schema.json"),

    # for download url validation.  The regexes need to define a 'filepath'.
    'valid_artifact_rules': ({
        "schemes": ["https"],
        "netlocs": ["queue.taskcluster.net"],
        "path_regexes": ["^/v1/task/(?P<taskId>[^/]+)(/runs/\\d+)?/artifacts/(?P<filepath>.*)$"]
    }, ),

    # docker image shas
    "docker_image_allowlists": frozendict({
        "decision": [
            "sha256:31035ed23eba3ede02b988be39027668d965b9fc45b74b932b2338a4e7936cf9"
        ],
        "docker-image": [
            "sha256:74c5a18ce1768605ce9b1b5f009abac1ff11b55a007e2d03733cd6e95847c747"
        ]
    }),
    # git gpg homedir layout
    "gpg_homedirs": frozendict({
        "docker-worker": {
            "type": "flat",
            "ignore_suffixes": [".md"]
        },
        "generic-worker": {
            "type": "flat",
            "ignore_suffixes": [".md"]
        },
        "scriptworker": {
            "type": "signed",
            "ignore_suffixes": [".md"]
        }
    }),
    # scriptworker identification
    "scriptworker_worker_types": (
        "signing-linux-v1",
    ),
    "scriptworker_provisioners": (
        "scriptworker-prov-v1",
    ),
    # valid hash algorithms for chain of trust artifacts
    "valid_hash_algorithms": (
        "sha256",
        "sha512",
    ),
    # decision worker types
    "valid_decision_worker_types": (
        "gecko-decision",
    ),

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
