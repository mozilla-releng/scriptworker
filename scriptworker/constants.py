#!/usr/bin/env python
"""scriptworker constants.

Attributes:
    DEFAULT_CONFIG (frozendict): the default config for scriptworker.  Running configs
        are validated against this.
    STATUSES (dict): maps taskcluster status (string) to exit code (int).

"""
from frozendict import frozendict
import os

# STATUSES {{{1
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
    "watch_log_file": False,

    # intervals are expressed in seconds
    "task_max_timeout": 60 * 20,
    "reclaim_interval": 300,
    "poll_interval": 10,
    "sign_key_timeout": 60 * 2,

    "reversed_statuses": frozendict({
        -11: STATUSES['intermittent-task'],
        -15: STATUSES['intermittent-task'],
    }),
    # Report this status on max_timeout. `intermittent-task` will rerun the
    # task automatically. `internal-error` or other will require manual
    # intervention.
    "task_max_timeout_status": STATUSES['intermittent-task'],
    "invalid_reclaim_status": STATUSES['intermittent-task'],

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
    "cot_version": 3,
    "min_cot_version": 2,
    "max_chain_length": 20,

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

    "project_configuration_url": "https://hg.mozilla.org/build/ci-configuration/raw-file/default/projects.yml",
    "pushlog_url": "{repo}/json-pushes?changeset={revision}&tipsonly=1&version=2&full=1",

    "chain_of_trust_hash_algorithm": "sha256",
    "cot_schema_path": os.path.join(os.path.dirname(__file__), "data", "cot_v1_schema.json"),

    # for download url validation.  The regexes need to define a 'filepath'.
    'valid_artifact_rules': (frozendict({
        "schemes": ("https", ),
        "netlocs": ("queue.taskcluster.net", ),
        "path_regexes": ("^/v1/task/(?P<taskId>[^/]+)(/runs/\\d+)?/artifacts/(?P<filepath>.*)$", ),
    }), ),

    # git gpg homedir layout
    "gpg_homedirs": frozendict({
        "docker-worker": frozendict({
            "type": "flat",
            "ignore_suffixes": (".md", ".json")
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
        "treescriptworker-v1"
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
        "gecko-1-decision",
        "gecko-2-decision",
        "gecko-3-decision",
        # gecko-focus is for mozilla-mobile releases. It's named this way because it's a worker type
        # but using the gecko ChainOfTrust keys. See bug 1455290 for more details.
        "gecko-focus",
    ),

    # docker-image cot
    "valid_docker_image_worker_types": (
        "taskcluster-images",   # TODO: Remove this image once docker-images is the only valid worker type
        "gecko-images",  # legacy
        "gecko-1-images",
        "gecko-2-images",
        "gecko-3-images",
    ),

    # for trace_back_to_*_tree.  These repos have access to restricted scopes;
    # all other repos are relegated to CI scopes.
    'valid_vcs_rules': {
        'by-cot-product': frozendict({
            'firefox': (frozendict({
                "schemes": ("https", "ssh", ),
                "netlocs": ("hg.mozilla.org", ),
                "path_regexes": (
                    "^(?P<path>/mozilla-(central|unified))(/|$)",
                    "^(?P<path>/integration/(autoland|fx-team|mozilla-inbound))(/|$)",
                    "^(?P<path>/releases/mozilla-(beta|release|esr\d+))(/|$)",
                    "^(?P<path>/projects/([A-Za-z0-9-]+))(/|$)",
                    "^(?P<path>/(try))(/|$)",
                ),
            }),),
            # XXX We should also check the mozilla-central tree that is being used.
            'thunderbird': (frozendict({
                "schemes": ("https", "ssh", ),
                "netlocs": ("hg.mozilla.org", ),
                "path_regexes": (
                    "^(?P<path>/comm-central)(/|$)",
                    "^(?P<path>/releases/comm-(beta|esr\d+))(/|$)",
                    "^(?P<path>/(try-comm-central))(/|$)",
                ),
            }),),
            'mobile': (frozendict({
                "schemes": ("https", "ssh", ),
                "netlocs": ("github.com", ),
                "path_regexes": (
                    "^(?P<path>/mozilla-mobile/focus-android)(/|.git|$)",
                ),
            }),),
        }),
    },

    # Map scopes to restricted-level
    'cot_restricted_scopes': {
        'by-cot-product': frozendict({
            'firefox': frozendict({
                'project:releng:addons.mozilla.org:server:production': 'all-release-branches',

                'project:releng:balrog:server:nightly': 'all-nightly-branches',
                'project:releng:balrog:server:beta': 'beta',
                'project:releng:balrog:server:release': 'release',
                'project:releng:balrog:server:esr': 'esr',

                'project:releng:beetmover:bucket:nightly': 'all-nightly-branches',
                'project:releng:beetmover:bucket:release': 'all-release-branches',

                'project:releng:bouncer:server:production': 'all-production-branches',
                'project:releng:bouncer:server:staging': 'all-staging-branches',

                # As part of the Dawn project we decided to use the Aurora Google Play
                # app to ship Firefox Nightly. This means that the "nightly" trees need
                # to have the scopes to ship to this product.
                # https://bugzilla.mozilla.org/show_bug.cgi?id=1357808 has additional
                # background and discussion.
                'project:releng:googleplay:aurora': 'nightly',
                'project:releng:googleplay:beta': 'beta',
                'project:releng:googleplay:release': 'release',

                'project:releng:signing:cert:nightly-signing': 'all-nightly-branches',
                'project:releng:signing:cert:release-signing': 'all-release-branches',

                'project:releng:snapcraft:firefox:beta': 'beta',
                'project:releng:snapcraft:firefox:candidate': 'release',
                'project:releng:snapcraft:firefox:mock': 'all-staging-branches',

                'project:releng:ship-it:production': 'all-production-branches',
                'project:releng:ship-it:staging': 'all-staging-branches',

                'project:releng:treescript:action:push': 'all-release-branches',
            }),
            'thunderbird': frozendict({
                'project:comm:thunderbird:releng:balrog:server:nightly': 'all-nightly-branches',
                'project:comm:thunderbird:releng:balrog:server:beta': 'beta',
                'project:comm:thunderbird:releng:balrog:server:esr': 'esr',

                'project:comm:thunderbird:releng:beetmover:bucket:nightly': 'all-nightly-branches',
                'project:comm:thunderbird:releng:beetmover:bucket:release': 'all-release-branches',

                'project:comm:thunderbird:releng:bouncer:server:production': 'all-release-branches',

                'project:comm:thunderbird:releng:signing:cert:nightly-signing': 'all-nightly-branches',
                'project:comm:thunderbird:releng:signing:cert:release-signing': 'all-release-branches',
            }),
            'mobile': frozendict({
                'project:mobile:focus:googleplay:product:focus': 'focus-repo',
                'project:mobile:focus:releng:signing:cert:release-signing': 'focus-repo',
            }),
        }),
    },
    # Map restricted-level to trees
    'cot_restricted_trees': {
        'by-cot-product': frozendict({
            'firefox': frozendict({
                # Which repos can perform release actions?
                # XXX remove /projects/maple and birch when taskcluster relpro
                #     migration is tier1 and landed on mozilla-central
                # XXX remove /projects/jamun when we no longer run staging releases
                #     from it
                'all-release-branches': (
                    "/releases/mozilla-beta",
                    "/releases/mozilla-release",
                    "/releases/mozilla-esr52",
                    "/releases/mozilla-esr60",
                    "/projects/birch",
                    "/projects/jamun",
                    "/projects/maple",
                ),
                # Limit things like pushapk to just these branches
                'release': (
                    "/releases/mozilla-release",
                ),
                'beta': (
                    "/releases/mozilla-beta",
                ),
                'esr': (
                    "/releases/mozilla-esr52",
                    "/releases/mozilla-esr60",
                ),
                'nightly': (
                    "/mozilla-central",
                ),

                # Which repos can do nightly signing?
                # XXX remove /projects/maple and birch when taskcluster relpro
                #     migration is tier1 and landed on mozilla-central
                # XXX remove /projects/jamun when we no longer run staging releases
                #     from it
                # XXX remove /projects/oak when we no longer test updates against it
                'all-nightly-branches': (
                    "/mozilla-central",
                    "/releases/mozilla-unified",
                    "/releases/mozilla-beta",
                    "/releases/mozilla-release",
                    "/releases/mozilla-esr52",
                    "/releases/mozilla-esr60",
                    "/projects/birch",
                    "/projects/jamun",
                    "/projects/oak",
                    "/projects/maple",
                ),

                'all-production-branches': (
                    "/releases/mozilla-beta",
                    "/releases/mozilla-release",
                    "/releases/mozilla-esr52",
                    "/releases/mozilla-esr60",
                ),

                'all-staging-branches': (
                    "/projects/birch",
                    "/projects/jamun",
                    "/projects/maple",
                ),
            }),
            'thunderbird': frozendict({
                'all-release-branches': (
                    "/releases/comm-beta",
                    "/releases/comm-esr60",
                ),
                'beta': (
                    "/releases/comm-beta",
                ),
                'esr': (
                    "/releases/comm-esr60",
                ),
                'all-nightly-branches': (
                    "/comm-central",
                    "/releases/comm-beta",
                    "/releases/comm-esr60",
                ),
                'nightly': (
                    "/comm-central",
                ),
            }),
            'mobile': frozendict({
                'focus-repo': (
                    '/mozilla-mobile/focus-android',
                ),
            }),
        }),
    },
    'prebuilt_docker_image_task_types': {
        'by-cot-product': frozendict({
            'firefox': ('decision', 'action', 'docker-image'),
            'thunderbird': ('decision', 'action', 'docker-image'),
            'mobile': 'any',  # all allowed
        }),
    },
    'source_env_prefix': {
        'by-cot-product': frozendict({
            'firefox': 'GECKO',
            'thunderbird': 'COMM',
            'mobile': '',   # mozilla-mobile projects are built on GitHub instead of hg.m.o
        })
    },
    'extra_run_task_arguments': {
        'by-cot-product': frozendict({
            'firefox': (),
            'thunderbird': ('--comm-checkout=',),
            'mobile': (),
        })
    },
})


# get_reversed_statuses {{{1
def get_reversed_statuses(context):
    """Return a mapping of exit codes to status strings.

    Args:
        context (scriptworker.context.Context): the scriptworker context

    Returns:
        dict: the mapping of exit codes to status strings.

    """
    _rev = {v: k for k, v in STATUSES.items()}
    _rev.update(dict(context.config['reversed_statuses']))
    return _rev
