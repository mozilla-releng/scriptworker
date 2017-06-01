#!/usr/bin/env python
"""scriptworker constants.

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
#
# Often DEFAULT_CONFIG changes will require test changes as well.
#
# When adding new complex config, make sure all `list`s are `tuple`s, and all
# `dict`s are `frozendict`s!  (This should get caught by config tests.)
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
    "aiohttp_max_connections": 15,

    # chain of trust settings
    "sign_chain_of_trust": True,
    "verify_chain_of_trust": False,  # TODO True
    "verify_cot_signature": False,
    "cot_job_type": "unknown",  # e.g., signing
    "cot_product": "firefox",

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
    'valid_artifact_rules': (frozendict({
        "schemes": ("https", ),
        "netlocs": ("queue.taskcluster.net", ),
        "path_regexes": ("^/v1/task/(?P<taskId>[^/]+)(/runs/\\d+)?/artifacts/(?P<filepath>.*)$", ),
    }), ),

    # docker image shas
    "docker_image_allowlists": frozendict({
        "decision": (
            "sha256:31035ed23eba3ede02b988be39027668d965b9fc45b74b932b2338a4e7936cf9",
            "sha256:7320c720c770e9f93df26f7da742db72b334b7ded77539fb240fc4a28363de5a",
            "sha256:9db282317340838f0015335d74ed56c4ee0dbad588be33e6999928a181548587",
            "sha256:a22b90c7e16191a701760ef4f9159e86289ba598bf8ff5b22b7b94867530460d",
        ),
        "docker-image": (
            "sha256:74c5a18ce1768605ce9b1b5f009abac1ff11b55a007e2d03733cd6e95847c747",
            "sha256:d438d7818b6a47a0b1d49943ab12b5c504b65161806658e4c28f5f2aac821b9e",
            "sha256:13b80a7a6b8e10c6096aba5a435529fbc99b405f56012e57cc6835facf4b40fb",
            "sha256:f5e7548ca4313beb7a324681a5f6adf9adfeabbc7b8ad63ce170cf3010546851",
        )
    }),

    # git gpg homedir layout
    "gpg_homedirs": frozendict({
        "docker-worker": frozendict({
            "type": "flat",
            "ignore_suffixes": (".md", )
        }),
        "generic-worker": frozendict({
            "type": "flat",
            "ignore_suffixes": (".md", ".in", ".sh")
        }),
        "scriptworker": frozendict({
            "type": "signed",
            "ignore_suffixes": (".md", )
        }),
    }),

    # scriptworker identification
    "scriptworker_worker_types": (
        "balrogworker-v1",
        "beetmoverworker-v1",
        "pushapk-v1",
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

    # decision task cot
    "valid_decision_worker_types": (
        "gecko-decision",
    ),

    # docker-image cot
    "valid_docker_image_worker_types": (
        "taskcluster-images",   # TODO: Remove this image once docker-images is the only valid worker type
        "gecko-images",
    ),

    # for trace_back_to_*_tree.  These repos have access to restricted scopes;
    # all other repos are relegated to CI scopes.
    'valid_vcs_rules': (frozendict({
        # TODO index by cot_product
        "schemes": ("https", "ssh", ),
        "netlocs": ("hg.mozilla.org", ),
        "path_regexes": (
            "^(?P<path>/mozilla-(central|unified))(/|$)",
            "^(?P<path>/integration/(autoland|fx-team|mozilla-inbound))(/|$)",
            "^(?P<path>/releases/mozilla-(aurora|beta|release|esr45|esr52))(/|$)",
            # XXX remove /projects/date when taskcluster nightly migration is
            #     tier1 and landed on mozilla-central
            # XXX remove /projects/jamun when we no longer release firefox
            #     from it
            # XXX remove /projects/oak when we no longer test updates against it
            "^(?P<path>/projects/(date|jamun|oak))(/|$)",
        ),
    }), ),

    # Map scopes to restricted-level
    'cot_restricted_scopes': frozendict({
        'firefox': frozendict({
            'project:releng:balrog:server:nightly': 'all-nightly-branches',
            'project:releng:balrog:server:aurora': 'aurora',
            'project:releng:balrog:server:beta': 'beta',
            'project:releng:balrog:server:release': 'release',
            'project:releng:balrog:server:esr': 'esr',
            'project:releng:beetmover:bucket:release': 'all-release-branches',
            'project:releng:googleplay:release': 'release',
            'project:releng:signing:cert:release-signing': 'all-release-branches',
            'project:releng:googleplay:beta': 'beta',
            # As part of the Dawn project we decided to use the Aurora Google Play
            # app to ship Firefox Nightly. This means that the "nightly" trees need
            # to have the scopes to ship to this product.
            # https://bugzilla.mozilla.org/show_bug.cgi?id=1357808 has additional
            # background and discussion.
            'project:releng:googleplay:aurora': 'nightly',
            'project:releng:beetmover:bucket:nightly': 'all-nightly-branches',
            'project:releng:signing:cert:nightly-signing': 'all-nightly-branches',
        })
    }),
    # Map restricted-level to trees
    'cot_restricted_trees': frozendict({
        'firefox': frozendict({
            # Which repos can perform release actions?
            # Allow aurora for staging betas.
            # XXX remove /projects/jamun when we no longer release firefox
            #     from it
            'all-release-branches': (
                "/releases/mozilla-aurora",
                "/releases/mozilla-beta",
                "/releases/mozilla-release",
                "/releases/mozilla-esr45",
                "/releases/mozilla-esr52",
                "/projects/jamun",
            ),
            # Limit things like pushapk to just these branches
            'release': (
                "/releases/mozilla-release",
            ),
            'beta': (
                "/releases/mozilla-beta",
            ),
            'aurora': (
                "/releases/mozilla-aurora",
            ),
            'esr': (
                "/releases/mozilla-esr45",
                "/releases/mozilla-esr52",
            ),
            'nightly': (
                "/mozilla-central",
            ),

            # Which repos can do nightly signing?
            # XXX remove /projects/date when taskcluster nightly migration is
            #     tier1 and landed on mozilla-central
            # XXX remove /projects/jamun when we no longer release firefox
            #     from it
            # XXX remove /projects/oak when we no longer test updates against it
            'all-nightly-branches': (
                "/mozilla-central",
                "/releases/mozilla-unified",
                "/releases/mozilla-aurora",
                "/releases/mozilla-beta",
                "/releases/mozilla-release",
                "/releases/mozilla-esr45",
                "/releases/mozilla-esr52",
                "/projects/jamun",
                "/projects/oak",
                "/projects/date",
            ),
        }),
    }),
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
    'intermittent-task': 7,
}
REVERSED_STATUSES = {v: k for k, v in STATUSES.items()}
