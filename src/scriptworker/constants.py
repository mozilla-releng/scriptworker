#!/usr/bin/env python
"""scriptworker constants.

Attributes:
    DEFAULT_CONFIG (immutabledict): the default config for scriptworker.  Running configs
        are validated against this.
    STATUSES (dict): maps taskcluster status (string) to exit code (int).

"""
import os
from typing import Any, Dict

from immutabledict import immutabledict

STATUSES = {
    "success": 0,
    "failure": 1,
    "worker-shutdown": 2,
    "malformed-payload": 3,
    "resource-unavailable": 4,
    "internal-error": 5,
    "superseded": 6,
    "intermittent-task": 7,
}

# DEFAULT_CONFIG {{{1
# When making changes to DEFAULT_CONFIG that may be of interest to scriptworker
# instance maintainers, also make changes to ``scriptworker.yaml.tmpl``.
#
# Often DEFAULT_CONFIG changes will require test changes as well.
#
# When adding new complex config, make sure all `list`s are `tuple`s, and all
# `dict`s are `immutabledict`s!  (This should get caught by config tests.)
DEFAULT_CONFIG: immutabledict[str, Any] = immutabledict(
    {
        "taskcluster_root_url": os.environ.get("TASKCLUSTER_ROOT_URL", "https://firefox-ci-tc.services.mozilla.com/"),
        # Worker identification
        "provisioner_id": "test-dummy-provisioner",
        "worker_group": "test-dummy-workers",
        "worker_type": "dummy-worker-myname",
        "worker_id": os.environ.get("SCRIPTWORKER_WORKER_ID", "dummy-worker-myname1"),
        "credentials": immutabledict({"clientId": "...", "accessToken": "...", "certificate": "..."}),
        # Worker log settings
        "log_datefmt": "%Y-%m-%dT%H:%M:%S",
        "log_fmt": "%(asctime)s %(levelname)8s - %(message)s",
        "watch_log_file": False,
        # intervals are expressed in seconds
        "task_max_timeout": 60 * 20,
        "reclaim_interval": 300,
        "poll_interval": 10,
        "sign_key_timeout": 60 * 2,
        "reversed_statuses": immutabledict({245: "intermittent-task", 241: "intermittent-task"}),
        # Report this status on max_timeout. `intermittent-task` will rerun the
        # task automatically. `internal-error` or other will require manual
        # intervention.
        "task_max_timeout_status": STATUSES["intermittent-task"],
        "invalid_reclaim_status": STATUSES["intermittent-task"],
        "task_script": ("bash", "-c", "echo foo && sleep 19 && exit 1"),
        # Logging settings
        "verbose": True,
        "log_max_bytes": 0,
        "log_max_backups": 10,
        # Task settings
        "work_dir": "...",
        "log_dir": "...",
        "artifact_dir": "...",
        "task_log_dir": "...",  # set this to ARTIFACT_DIR/public/logs
        "artifact_upload_timeout": 60 * 20,
        "max_concurrent_downloads": 5,
        # chain of trust settings
        "sign_chain_of_trust": True,
        "verify_chain_of_trust": False,  # TODO True
        "verify_cot_signature": False,
        "cot_job_type": "unknown",  # e.g., signing
        "cot_product": "firefox",
        "cot_version": 3,
        "min_cot_version": 2,
        "max_chain_length": 20,
        # Calls to Github API are limited to 60 an hour. Using an API token allows to raise the limit to
        # 5000 per hour. https://developer.github.com/v3/#rate-limiting
        "github_oauth_token": "",
        # ed25519 settings
        "ed25519_private_key_path": "...",
        "ed25519_public_keys": immutabledict(
            {
                "docker-worker": tuple(
                    [
                        # Feb 2023 rotation, RELENG-1055
                        "Ts3wztzAV828NpyiC32PXdSXNxp3HyzFtSSmmhRgU+Y=",
                        # Dec 2023 rotation (bug 1868558)
                        "kni6ts7z/MRkvs7i6+SF/T6UWj0hAJoHEcrgHB8BBR0=",
                    ]
                ),
                "generic-worker": tuple(
                    [
                        # Feb 2023 rotation, RELENG-1055
                        "NSkHdX/EffmnuITcKHRTJXK3bNxuLFOUN8ErZOkRQGo=",
                        # Dec 2023 rotation (bug 1868558)
                        "Kz/aZIVeR6NP8gQU1U+2CCIZqvbd+4QCP6J63lflwik=",
                    ]
                ),
                "scriptworker": tuple(
                    [
                        # Jan 2023 rotation key
                        "kG5eQqe8AuTIGqW55+6vTxxTansuTOU0drJS7C3VyPo=",
                        # Dec 2023 rotation (bug 1868558)
                        "jFmyvf3lQiiX0qIFxal5KgIIq6VpUBTQfAtD6hEi8Ms=",
                    ]
                ),
            }
        ),
        "project_configuration_url": "https://hg.mozilla.org/ci/ci-configuration/raw-file/default/projects.yml",
        "pushlog_url": "{repo}/json-pushes?changeset={revision}&version=2&full=1",
        "chain_of_trust_hash_algorithm": "sha256",
        "cot_schema_path": os.path.join(os.path.dirname(__file__), "data", "cot_v1_schema.json"),
        # for download url validation.  The regexes need to define a 'filepath'.
        "valid_artifact_rules": (
            immutabledict(
                {
                    "schemes": ("https",),
                    "netlocs": ("queue.taskcluster.net",),
                    "path_regexes": (r"^/v1/task/(?P<taskId>[^/]+)(/runs/\\d+)?/artifacts/(?P<filepath>.*)$",),
                }
            ),
            immutabledict(
                {
                    "schemes": ("https",),
                    "netlocs": ("firefox-ci-tc.services.mozilla.com", "stage.taskcluster.nonprod.cloudops.mozgcp.net"),
                    "path_regexes": (r"^/api/queue/v1/task/(?P<taskId>[^/]+)(/runs/\\d+)?/artifacts/(?P<filepath>.*)$",),
                }
            ),
        ),
        "scriptworker_provisioners": ("scriptworker-prov-v1", "scriptworker-k8s"),
        # valid hash algorithms for chain of trust artifacts
        "valid_hash_algorithms": ("sha256", "sha512"),
        "cot_product_type": immutabledict(
            {
                "by-cot-product": immutabledict(
                    {
                        "firefox": "hg",
                        "thunderbird": "hg",
                        "mobile": "github",
                        "mozillavpn": "github",
                        "app-services": "github",
                        "glean": "github",
                        "xpi": "github",
                        "adhoc": "github",
                        "scriptworker": "github",
                    }
                )
            }
        ),
        # decision task cot
        "valid_decision_worker_pools": immutabledict(
            {
                "by-cot-product": immutabledict(
                    {
                        "firefox": (
                            "gecko-1/decision",
                            "gecko-2/decision",
                            "gecko-3/decision",
                            "gecko-1/decision-gcp",
                            "gecko-2/decision-gcp",
                            "gecko-3/decision-gcp",
                        ),
                        "thunderbird": (
                            "comm-1/decision",
                            "comm-2/decision",
                            "comm-3/decision",
                            "comm-1/decision-gcp",
                            "comm-2/decision-gcp",
                            "comm-3/decision-gcp",
                        ),
                        "mobile": ("mobile-1/decision", "mobile-3/decision", "mobile-1/decision-gcp", "mobile-3/decision-gcp"),
                        "mozillavpn": ("mozillavpn-1/decision", "mozillavpn-3/decision", "mozillavpn-1/decision-gcp", "mozillavpn-3/decision-gcp"),
                        "app-services": ("app-services-1/decision", "app-services-3/decision", "app-services-1/decision-gcp", "app-services-3/decision-gcp"),
                        "glean": ("glean-1/decision", "glean-3/decision", "glean-1/decision-gcp", "glean-3/decision-gcp"),
                        "xpi": ("xpi-1/decision", "xpi-3/decision", "xpi-1/decision-gcp", "xpi-3/decision-gcp"),
                        "adhoc": ("adhoc-1/decision", "adhoc-3/decision", "adhoc-1/decision-gcp", "adhoc-3/decision-gcp"),
                        "scriptworker": ("scriptworker-1/decision", "scriptworker-3/decision" "scriptworker-1/decision-gcp", "scriptworker-3/decision-gcp"),
                    }
                )
            }
        ),
        # docker-image cot
        "valid_docker_image_worker_pools": immutabledict(
            {
                "by-cot-product": immutabledict(
                    {
                        "firefox": ("gecko-1/images", "gecko-2/images", "gecko-3/images", "gecko-1/images-gcp", "gecko-2/images-gcp", "gecko-3/images-gcp"),
                        "thunderbird": ("comm-1/images", "comm-2/images", "comm-3/images", "comm-1/images-gcp", "comm-2/images-gcp", "comm-3/images-gcp"),
                        "mobile": ("mobile-1/images", "mobile-3/images", "mobile-1/images-gcp", "mobile-3/images-gcp"),
                        "mozillavpn": ("mozillavpn-1/images", "mozillavpn-3/images", "mozillavpn-1/images-gcp", "mozillavpn-3/images-gcp"),
                        "app-services": ("app-services-1/images", "app-services-3/images", "app-services-1/images-gcp", "app-services-3/images-gcp"),
                        "glean": ("glean-1/images", "glean-3/images", "glean-1/images-gcp", "glean-3/images-gcp"),
                        "xpi": ("xpi-1/images", "xpi-3/images", "xpi-1/images-gcp", "xpi-3/images-gcp"),
                        "adhoc": ("adhoc-1/images", "adhoc-3/images", "adhoc-1/images-gcp", "adhoc-3/images-gcp"),
                        "scriptworker": ("scriptworker-1/images", "scriptworker-3/images", "scriptworker-1/images-gcp", "scriptworker-3/images-gcp"),
                    }
                )
            }
        ),
        # for trace_back_to_*_tree.  These repos have access to restricted scopes;
        # all other repos are relegated to CI scopes.
        "trusted_vcs_rules": {
            "by-cot-product": immutabledict(
                {
                    "firefox": (
                        immutabledict(
                            {
                                "schemes": ("https", "ssh"),
                                "netlocs": ("hg.mozilla.org",),
                                "path_regexes": (
                                    r"^(?P<path>/mozilla-(central|unified))(/|$)",
                                    r"^(?P<path>/integration/autoland)(/|$)",
                                    r"^(?P<path>/releases/mozilla-(beta|release|esr\d+))(/|$)",
                                    # bug 1845368: a permanent project branch for testing updates
                                    r"^(?P<path>/projects/(pine|maple))(/|$)",
                                ),
                            }
                        ),
                    ),
                    # XXX We should also check the mozilla-central tree that is being used.
                    "thunderbird": (
                        immutabledict(
                            {
                                "schemes": ("https", "ssh"),
                                "netlocs": ("hg.mozilla.org",),
                                "path_regexes": (r"^(?P<path>/comm-central)(/|$)", r"^(?P<path>/releases/comm-(beta|release|esr\d+))(/|$)"),
                            }
                        ),
                    ),
                    "mobile": (
                        immutabledict(
                            {
                                "schemes": ("https", "ssh"),
                                "netlocs": ("github.com",),
                                "path_regexes": tuple([r"^(?P<path>/mozilla-mobile/(?:firefox-android|reference-browser))(/|.git|$)"]),
                            }
                        ),
                    ),
                    "mozillavpn": (
                        immutabledict(
                            {
                                "schemes": ("https", "ssh"),
                                "netlocs": ("github.com",),
                                "path_regexes": tuple([r"^(?P<path>/mozilla-mobile/(?:mozilla-vpn-client))(/|.git|$)"]),
                            }
                        ),
                    ),
                    "app-services": (
                        immutabledict(
                            {"schemes": ("https", "ssh"), "netlocs": ("github.com",), "path_regexes": (r"^(?P<path>/mozilla/application-services)(/|.git|$)",)}
                        ),
                    ),
                    "glean": (
                        immutabledict({"schemes": ("https", "ssh"), "netlocs": ("github.com",), "path_regexes": (r"^(?P<path>/mozilla/glean)(/|.git|$)",)}),
                    ),
                    "xpi": (
                        immutabledict(
                            {
                                "schemes": ("https", "ssh"),
                                "netlocs": ("github.com",),
                                "path_regexes": tuple([r"^(?P<path>/mozilla-extensions/xpi-manifest)(/|.git|$)"]),
                            }
                        ),
                    ),
                    "adhoc": (
                        immutabledict(
                            {
                                "schemes": ("https", "ssh"),
                                "netlocs": ("github.com",),
                                "path_regexes": tuple([r"^(?P<path>/mozilla-releng/(?:adhoc-signing|adhoc-manifest))(/|.git|$)"]),
                            }
                        ),
                    ),
                    "scriptworker": (
                        immutabledict(
                            {
                                "schemes": ("https", "ssh"),
                                "netlocs": ("github.com",),
                                "path_regexes": tuple([r"^(?P<path>/mozilla-releng/scriptworker(?:|-scripts))(/|.git|$)"]),
                            }
                        ),
                    ),
                }
            )
        },
        "valid_tasks_for": {
            "by-cot-product": immutabledict(
                {
                    "firefox": ("hg-push", "cron", "action"),
                    "thunderbird": ("hg-push", "cron", "action"),
                    "mobile": (
                        "action",
                        "cron",
                        # On staging releases, level 1 docker images may be built in the pull-request graph
                        "github-pull-request",
                        # Similarly, docker images can be built on regular push. This is usually the case
                        # for level 3 images
                        "github-push",
                        "github-release",
                    ),
                    "mozillavpn": ("cron", "github-pull-request", "github-push", "github-release", "action"),
                    "app-services": (
                        "action",
                        "cron",
                        # On staging releases, level 1 docker images may be built in the pull-request graph
                        "github-pull-request",
                        # Similarly, docker images can be built on regular push. This is usually the case
                        # for level 3 images
                        "github-push",
                        "github-release",
                    ),
                    "glean": (
                        "action",
                        "cron",
                        # On staging releases, level 1 docker images may be built in the pull-request graph
                        "github-pull-request",
                        # Similarly, docker images can be built on regular push. This is usually the case
                        # for level 3 images
                        "github-push",
                        "github-release",
                    ),
                    "xpi": ("action", "cron", "github-pull-request", "github-push", "github-release"),
                    "adhoc": ("action", "github-pull-request", "github-push"),
                    "scriptworker": ("action", "cron", "github-pull-request", "github-push", "github-release"),
                }
            )
        },
        "official_github_repos_owner": {
            "by-cot-product": immutabledict(
                {
                    "firefox": "",
                    "thunderbird": "",
                    "mobile": "mozilla-mobile",
                    "mozillavpn": "mozilla-mobile",
                    "app-services": "mozilla",
                    "glean": "mozilla",
                    "xpi": "mozilla-extensions",
                    "adhoc": "mozilla-releng",
                    "scriptworker": "mozilla-releng",
                }
            )
        },
        # Map scopes to restricted-level
        "cot_restricted_scopes": {
            "by-cot-product": immutabledict(
                {
                    "firefox": immutabledict(
                        {
                            "project:releng:addons.mozilla.org:server:production": "all-release-branches",
                            "project:releng:balrog:server:nightly": "all-nightly-branches",
                            "project:releng:balrog:server:beta": "beta",
                            "project:releng:balrog:server:release": "release",
                            "project:releng:balrog:server:esr": "esr",
                            "project:releng:beetmover:bucket:nightly": "all-nightly-branches",
                            "project:releng:beetmover:bucket:release": "all-release-branches",
                            "project:releng:bouncer:server:production": "all-production-branches",
                            "project:releng:signing:cert:nightly-signing": "all-nightly-branches",
                            "project:releng:signing:cert:release-signing": "all-release-branches",
                            "project:releng:flathub:firefox:beta": "beta-or-release",  # Needed on release for RCs
                            "project:releng:flathub:firefox:stable": "release",
                            "project:releng:ship-it:production": "all-production-branches",
                            "project:releng:treescript:action:push": "all-production-branches-and-autoland",
                            "project:releng:microsoftstore:beta": "beta",
                            "project:releng:microsoftstore:release": "release",
                        }
                    ),
                    "thunderbird": immutabledict(
                        {
                            "project:comm:thunderbird:releng:balrog:server:nightly": "all-nightly-branches",
                            "project:comm:thunderbird:releng:balrog:server:beta": "beta",
                            "project:comm:thunderbird:releng:balrog:server:release": "release-or-esr",
                            "project:comm:thunderbird:releng:balrog:server:esr": "esr",
                            "project:comm:thunderbird:releng:beetmover:bucket:nightly": "all-nightly-branches",
                            "project:comm:thunderbird:releng:beetmover:bucket:release": "all-release-branches",
                            "project:comm:thunderbird:releng:bouncer:server:production": "all-nightly-branches",
                            "project:comm:thunderbird:releng:signing:cert:nightly-signing": "all-nightly-branches",
                            "project:comm:thunderbird:releng:signing:cert:release-signing": "all-release-branches",
                            "project:comm:thunderbird:releng:flathub:beta": "beta",
                            "project:comm:thunderbird:releng:flathub:stable": "release-or-esr",
                            "project:comm:thunderbird:releng:microsoftstore:beta": "beta",
                            "project:comm:thunderbird:releng:microsoftstore:release": "release-or-esr",
                        }
                    ),
                    "mobile": immutabledict(
                        {
                            "project:mobile:firefox-android:releng:github:project:firefox-android": "firefox-android-repo",
                            "project:mobile:firefox-android:releng:beetmover:bucket:maven-production": "firefox-android-repo",
                            "project:mobile:firefox-android:releng:beetmover:bucket:maven-snapshot-production": "firefox-android-repo",
                            "project:mobile:firefox-android:releng:signing:cert:release-signing": "firefox-android-repo",
                            "project:mobile:firefox-android:releng:signing:cert:production-signing": "firefox-android-repo",
                            "project:mobile:firefox-android:releng:googleplay:product:focus-android": "firefox-android-repo",
                            "project:mobile:reference-browser:releng:googleplay:product:reference-browser": "reference-browser-repo",
                            "project:mobile:reference-browser:releng:signing:cert:release-signing": "reference-browser-repo",
                        }
                    ),
                    "mozillavpn": immutabledict(
                        {
                            "project:mozillavpn:releng:signing:cert:nightly-signing": "mozillavpn-repo",
                            "project:mozillavpn:releng:signing:cert:release-signing": "mozillavpn-repo",
                            "project:mozillavpn:releng:googleplay:product:mozillavpn": "mozillavpn-repo",
                            "project:mozillavpn:releng:beetmover:bucket:release": "mozillavpn-repo",
                        }
                    ),
                    "app-services": immutabledict(
                        {
                            "project:mozilla:app-services:releng:beetmover:bucket:maven-production": "app-services-repo",
                            "project:mozilla:app-services:releng:beetmover:bucket:release": "app-services-repo",
                            "project:mozilla:app-services:releng:signing:cert:release-signing": "app-services-repo",
                        }
                    ),
                    "glean": immutabledict({"project:mozilla:glean:releng:beetmover:bucket:maven-production": "glean-repo"}),
                    "xpi": immutabledict(
                        {
                            "project:xpi:signing:cert:release-signing": "xpi-manifest-repo",
                            "project:xpi:releng:github:project:mozilla-extensions/*": "xpi-manifest-repo",
                            "project:xpi:ship-it:production": "xpi-manifest-repo",
                            "project:xpi:beetmover:bucket:release": "xpi-manifest-repo",
                            "project:xpi:balrog:server:release": "xpi-manifest-repo",
                        }
                    ),
                    "adhoc": immutabledict({"project:adhoc:signing:cert:release-signing": "adhoc-signing-repos"}),
                    "scriptworker": immutabledict(
                        {
                            "project:scriptworker:dockerhub:production": "scriptworker-scripts-repo",
                            "project:scriptworker:pypi:production": "all-production-repos",
                        }
                    ),
                }
            )
        },
        # Map restricted-level to trees
        "cot_restricted_trees": {
            "by-cot-product": immutabledict(
                {
                    "firefox": immutabledict(
                        {
                            # Which repos can perform release actions?
                            "all-release-branches": (
                                "/releases/mozilla-beta",
                                "/releases/mozilla-release",
                                "/releases/mozilla-esr115",
                                "/projects/birch",
                                # Bug 1821839 hneiva using to test hardened signing
                                "/projects/maple",
                            ),
                            # Limit things like pushapk to just these branches
                            "release": ("/releases/mozilla-release",),
                            "beta": ("/releases/mozilla-beta",),
                            "beta-or-release": (
                                "/releases/mozilla-beta",
                                "/releases/mozilla-release",
                            ),
                            "esr": ("/releases/mozilla-esr115",),
                            "nightly": ("/mozilla-central",),
                            # Which repos can do nightly signing?
                            "all-nightly-branches": (
                                "/mozilla-central",
                                "/releases/mozilla-unified",
                                "/releases/mozilla-beta",
                                "/releases/mozilla-release",
                                "/releases/mozilla-esr115",
                                # bug 1845368: a permanent project branch for testing updates
                                "/projects/pine",
                            ),
                            "all-production-branches": (
                                "/mozilla-central",
                                "/releases/mozilla-beta",
                                "/releases/mozilla-release",
                                "/releases/mozilla-esr115",
                            ),
                            "all-production-branches-and-autoland": (
                                "/mozilla-central",
                                "/releases/mozilla-beta",
                                "/releases/mozilla-release",
                                "/releases/mozilla-esr115",
                                "/integration/autoland",
                            ),
                        }
                    ),
                    "thunderbird": immutabledict(
                        {
                            "all-release-branches": (
                                "/releases/comm-beta",
                                "/releases/comm-release",
                                "/releases/comm-esr115",
                            ),
                            "beta": ("/releases/comm-beta",),
                            "release": ("/releases/comm-release",),
                            "release-or-esr": ("/releases/comm-release", "/releases/comm-esr115"),
                            "esr": ("/releases/comm-esr115",),
                            "all-nightly-branches": (
                                "/comm-central",
                                "/releases/comm-beta",
                                "/releases/comm-release",
                                "/releases/comm-esr115",
                            ),
                            "nightly": ("/comm-central",),
                        }
                    ),
                    "mobile": immutabledict(
                        {
                            "firefox-android-repo": ("/mozilla-mobile/firefox-android",),
                            "reference-browser-repo": ("/mozilla-mobile/reference-browser",),
                        }
                    ),
                    "mozillavpn": immutabledict({"mozillavpn-repo": ("/mozilla-mobile/mozilla-vpn-client",)}),
                    "app-services": immutabledict({"app-services-repo": ("/mozilla/application-services",)}),
                    "glean": immutabledict({"glean-repo": ("/mozilla/glean",)}),
                    "xpi": immutabledict({"xpi-manifest-repo": ("/mozilla-extensions/xpi-manifest",)}),
                    "adhoc": immutabledict({"adhoc-signing-repos": ("/mozilla-releng/adhoc-signing", "/mozilla-releng/adhoc-manifest")}),
                    "scriptworker": immutabledict(
                        {
                            "scriptworker-scripts-repo": ("/mozilla-releng/scriptworker-scripts",),
                            "all-production-repos": ("/mozilla-releng/scriptworker", "/mozilla-releng/scriptworker-scripts"),
                        }
                    ),
                }
            )
        },
        "prebuilt_docker_image_task_types": {
            "by-cot-product": immutabledict(
                {
                    "firefox": ("decision", "action", "docker-image"),
                    "thunderbird": ("decision", "action", "docker-image"),
                    # XXX now that we're on taskgraph, we should limit these.
                    "mobile": "any",  # all allowed
                    "mozillavpn": "any",  # all allowed
                    "app-services": "any",  # all allowed
                    "glean": "any",  # all allowed
                    "xpi": "any",  # all allowed
                    "adhoc": "any",  # all allowed
                    "scriptworker": ("decision", "action", "docker-image"),
                }
            )
        },
        "source_env_prefix": {
            "by-cot-product": immutabledict(
                {
                    "firefox": "GECKO",
                    "thunderbird": "COMM",
                    "mobile": "MOBILE",
                    "mozillavpn": "MOZILLAVPN",
                    "app-services": "APPSERVICES",
                    "glean": "GLEAN",
                    "xpi": "XPI",
                    "adhoc": "ADHOC",
                    "scriptworker": "SCRIPTWORKER",
                }
            )
        },
    }
)


# get_reversed_statuses {{{1
def get_reversed_statuses(context: Any) -> Dict[int, str]:
    """Return a mapping of exit codes to status strings.

    Args:
        context (scriptworker.context.Context): the scriptworker context

    Returns:
        dict: the mapping of exit codes to status strings.

    """
    _rev = {v: k for k, v in STATUSES.items()}
    _rev.update(dict(context.config["reversed_statuses"]))
    return _rev
