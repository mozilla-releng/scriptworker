# Change Log
All notable changes to this project will be documented in this file.
This project adheres to [Semantic Versioning](http://semver.org/).

## [23.0.4] - 2019-05-06
### Fixed
- [Issue #334](https://github.com/mozilla-releng/scriptworker/issues/334): Github's `web-flow` user breaking Chain of Trust.

## [23.0.3] - 2019-04-19
### Added
- Support for `application-services` in CoT for beetmoverworkers

### Changed
- `_get_additional_github_releases_jsone_context`'s `clone_url` now returns the correct url suffixing in `git`

## [23.0.2] - 2019-04-11
### Fixed
- `s,scriptharness,scriptworker` in `docs/conf.py`
- specify `rootUrl` for `verify_cot` if used without credentials.

### Changed
- Upload .tar.gz without gzip encoding. Gzip encoding resulted in uncompressing the tarball during download, breaking cot hash verification

## [23.0.1] - 2019-04-11
### Fixed
- CoT on Github: PRs merged by someone else break CoT

## [23.0.0] - 2019-03-27
### Added
- added `CODE_OF_CONDUCT.md`.
- `verify_cot` now has a `--verify-sigs` option to test level 3 chains of trust with signature verification on.
- added a `verify_ed25519_signature` endpoint helper script.

### Changed
- Updated documentation to reflect the new ed25519-only chain of trust world.
- `docker/run.sh` no longer points `/dev/random` to `/dev/urandom`, and no longer has hacks to install an old version of gpg.
- `public/chain-of-trust.json` is now a mandatory artifact in cot verification. `public/chain-of-trust.json.sig` is mandatory if signature verification is on. `public/chainOfTrust.json.asc` is no longer used.
- similarly, `public/chainOfTrust.json.asc` is no longer generated or uploaded by scriptworker.
- `add_enumerable_item_to_dict` now uses `setdefault` instead of `try/except`.

### Fixed
- added missing modules to the source documentation.
- restored missing test branch coverage.
- `get_all_artifacts_per_task_id` now returns a sorted, unique list of artifacts, preventing duplicate concurrent downloads of the same file.
- `test_verify_production_cot` now tests win64 repackage-signing instead of linux64 repackage-signing because linux64 stopped running repackage-signing. We also test an esr60 index.

### Removed
- removed gpg support from chain of trust verification.
- removed `scriptworker.gpg` module and associated tests.
- removed the `defusedxml`, `pexpect`, and `python-gnupg` dependencies.
- removed the `create_gpg_keys.py` and `gpg_helper.sh` helper scripts.
- removed gpg-specific config.
- removed `ScriptWorkerGPGException`
- removed the `rebuild_gpg_homedirs` endpoint.
- removed the `check_pubkeys.py` and `gen1000keys.py` test scripts.

## [22.1.0] - 2019-03-19
### Added
- `event.repository.full_name` and `event.pull_request.base.repo.full_name` on `cot_verify` (for GitHub repos)

## [22.0.1] - 2019-03-13
### Fixed
- Allow snapcraft beta scope on mozilla-release

## [22.0.0] - 2019-03-07
### Added
- ed25519 cot signature generation and verification support.
- `scripts/gen_ed25519_key.py` - a standalone script to generate an ed25519 keypair
- `ed25519_private_key_path` and `ed25519_public_keys` config items
- `scriptworker.ed25519` module
- `verify_link_gpg_cot_signature` is a new function, but is deprecated and will be removed in a future release.
- `verify_link_ed25519_cot_signature` is a new function.
- added `write_to_file` and `read_from_file` utils

### Changed
- gpg support in chain of trust is now deprecated, and will be removed in a future release.
- `generate_cot`'s `path` kwarg is now `parent_path`.
- `generate_cot` now generates up to 3 files: `chainOfTrust.json.asc`, `chain-of-trust.json`, and `chain-of-trust.json.sig`.
- `download_cot` now also downloads `chain-of-trust.json` as an optional artifact, and adds `chain-of-trust.json.sig` as an optional artifact if signature verification is enabled. These will become mandatory artifacts in a future release.
- `chainOfTrust.json.asc` is now a mandatory artifact in cot verification, but is deprecated. We will remove this artifact in a future release.
- `verify_cot_signatures` verifies ed25519, and falls back to gpg. We will make ed25519 signature verification mandatory in a future release, and remove gpg verification.
- we now require `cryptography>=2.6.1` for ed25519 support.

### Removed
- `is_task_required_by_any_mandatory_artifact` is removed

## [21.0.0] - 2019-03-05
### Changed
- `is_try_or_pull_request()` is now an async (instead of a sync property). So is `is_pull_request()`.
- `extract_github_repo_owner_and_name()`, `extract_github_repo_and_revision_from_source_url()` have been moved to the `github` module.

### Added
- In the `github` module:
  - `is_github_url()`,`get_tag_hash()`, `has_commit_landed_on_repository()`, `is_github_repo_owner_the_official_one()`
- `utils.get_parts_of_url_path()`

## [20.0.1] - 2019-02-21
### Changed
- update `ci-admin` and `ci-configuration` to reflect their new homes

## [20.0.0] - 2019-02-21
### Added
- mobile can create in-tree docker images
- Chain of Trust is now able to validate the following `tasks_for`:
  - github-pull-request (even though pull requests seem risky at first, this enables smoother
    staging releases - à la gecko's try)
  - github-push
- github.py is a new module to deal with the GitHub API URLs.

### Changed
- Config must know provide a GitHub OAuth token to request the GitHub API more than 60 times an
    hour
- load_json_or_yaml() load file handles as if they were always encoded
    in utf-8. The GitHub API includes emojis in its reponses.
- The mobile decision tasks must define "MOBILE_PUSH_DATE_TIME". github-release
    is the only `tasks_for` to not use this variable (because the piece of
    data is exposed by the GitHub API)
- `is_try` in `scriptworker.cot.verify` was changed by `is_try_or_pull_request`
- `tasks_for` are now allowed per cot-product in constants.py

### Removed
- `scriptworker.task.KNOWN_TASKS_FOR` in favor of `context.config['valid_tasks_for']` which depends
    on the `cot_product`

## [19.0.0] - 2019-02-13
### Added
- added `running_tasks` property to `Context`
- added `WorkerShutdownDuringTask` exception
- added `TaskProcess` object and `task_process` submodule
- added a `RunTasks` object

### Changed
- `upload_artifacts` now takes a `files` arg
- `run_task` now takes a `to_cancellable_process` arg
- `do_run_task` takes two new args
- `do_upload` takes a `files` arg

### Fixed
- scriptworker should now handle SIGTERM more gracefully, reporting `worker-shutdown`

### Removed
- removed `kill_pid` and `kill_proc` functions
- removed `noop_sync` from utils

## [18.1.0] - 2019-02-01
### Added
- added `ownTaskId` to `jsone_context`.
- added an `_EXTENSION_TO_MIME_TYPE` list to allow for differences in system mimetypes

## [18.0.1] - 2019-01-29
### Fixed
- added `clientId` to action hooks' `jsone_context`

## [18.0.0] - 2019-01-28
### Added
- Added `git_path` in config to specify an explicit git binary

### Changed
- Added a `context` argument to `get_git_revision`, `get_latest_tag`

### Fixed
- Fixed some markdown syntax

## [17.2.2] - 2019-01-25
### Added
- Added slowest 10 tests measurement
- Added `BaseDownloadError` and `Download404` exceptions

### Changed
- No longer retry downloads on a 404.

### Fixed
- Fixed pytest-random-order behavior
- Addressed a number of aiohttp + deprecation warnings

## [17.2.1] - 2019-01-11
### Changed
- added `fenix` to the list of approved repositories

## [17.2.0] - 2019-01-03
### Added
- support for GitHub staging releases

## [17.1.1] - 2019-01-02
### Changed
- get `actionPerm` from `action_defn['extra']['actionPerm']` before `action_defn['actionPerm']`.

## [17.1.0] - 2018-12-28
### Added
- added an entrypoint to the test docker image and updated docs.
- added relpro action hook support.
- added some filterwarnings to tox.ini to suppress warnings for dependencies.

### Changed
- pointed `/dev/random` at `/dev/urandom` in test docker image to speed up gpg tests.
- changed filesystem layout of docker image for more test file separation.
- renamed some of the private `jsone_context` functions in `scriptworker.cot.verify`.

### Fixed
- clarified new instance docs.
- fixed common intermittent test failures on travis by removing pytest-xdist.

### Removed

## [17.0.1] - 2018-11-29
### Fixed
- Regression around json-e context for mozilla-mobile projects

## [17.0.0] - 2018-11-27
### Changed
- Cron tasks are now expected to use correct push information
- Documentation for deploying new instances in AWS has been updated.
- Requirements are now generated using pip-compile-multi.
- Docker images have been updated in preperation for moving to docker deployements.

## [16.2.1] - 2018-10-15
### Added
- whitelisted `mozilla-mobile/android-components` and `mozilla-mobile/reference-browser` repos

## [16.2.0] - 2018-10-15
### Added
- `rootUrl` support for `taskcluster>=5.0.0`
- Python 3.7 dockerfile
- support for `github-release`
- support cron task scheduled as `github-release` in the case `cot_product == "mobile"`

### Removed
- when `cot_product == "mobile"`, json-e verification is no longer skipped

### Changed
- `test` and `gnupg` dockerfiles are now one.

### Fixed
- `verify_cot` for `taskcluster>=5.0.0`

## [16.1.0] - 2018-10-10
### Added
- add `taskcluster_root_url` to support taskcluster>=5.0.0

### Fixed
- fixed some pytest warnings

## [16.0.1] - 2018-09-14
### Fixed
- Look for the `cb_name` of actions with kind `task`.

## [16.0.0] - 2018-09-12
### Added
- add `get_action_callback_name`

### Fixed
- verify actions properly, even if they share the same name with another action (`cb_name` is unique; `name` is not).

### Removed
- remove `get_action_name`

## [15.0.4] - 2018-09-11
### Added
- Allow staging branches access to staging ship-it and mock snap workers.

### Fixed
- Retry download artifacts on timeouts.

## [15.0.3] - 2018-09-05
### Added
- Allow mozilla-central to update bouncer locations.

## [15.0.2] - 2018-08-31
### Added
- Allow any branch access to the -dev bouncer scriptwork.

## [15.0.1] - 2018-08-31
### Changed
- use `task.tags.worker-implementation` as the worker implementation, if specified.

## [15.0.0] - 2018-07-26
### Changed
- require py37 to be green
- support and require taskcluster>=4.0.0 (`taskcluster.aio` rather than `taskcluster.async`, because `async` is a py37 keyword)

## [14.0.0] - 2018-07-16
### Changed
- tests that need an event loop are now all `@pytest.mark.asyncio` and/or using the pytest-asyncio `event_loop` fixture, rather than using the now-removed local `event_loop` fixture. This addresses our intermittent test failures, though we need additional work (e.g., PR #244)
- added more test cases around `get_upstream_artifacts_full_paths_per_task_id`, to allow for multiple `upstreamArtifacts` entries for a single `taskId`

### Fixed
- fixed the hang in `run_task` -- we were waiting for the `max_timeout` future to exit, which it did after sleeping for `task_max_timeout` seconds, so every task took the full timeout to complete. Now we use `asyncio.wait(timeout=...)`.
- fixed the unclosed session warnings in tests

### Removed
- removed `get_future_exception` after removing its last caller
- removed `max_timeout` after moving timeout handling into `run_task` via `asyncio.wait`
- removed the `event_loop` test fixture; this may have conflicted with the `pytest-asyncio` `event_loop` fixture

## [13.0.0] - 2018-07-04
### Added
- added `task_max_timeout_status`, `reversed_statuses`, and `invalid_reclaim_status` to `DEFAULT_CONFIG`
- added `get_reversed_statuses` for config-driven reversed statuses
- added `task.kill_pid` to kill a process tree
- added `task.kill_proc` to kill a subprocess proc
- added unit and integration tests for user cancel
- added `utils.get_future_exception` to get the status of a single future

### Changed
- integration tests now require the `queue:cancel-task:test-dummy-scheduler/*` scope
- unit tests now run in random order
- `max_timeout` is now an async function with sleeps rather than a synchronous function using `call_later`
- split `run_tasks` into several helper functions
- all negative exit statuses now log `Automation Error`

### Fixed
- task timeouts should result in an `intermittent-task`, rather than a crashed scriptworker
- we now kill the task on a `reclaim_task` result of 409, allowing for user cancellation
- added logging for uncaught exceptions in `run_tasks`
- cancelled the `reclaim_task` future on task completion
- pointed docs at the new `mdc1` puppet server
- cot verification now renders the entire template rather than the first task

### Removed
- `REVERSED_STATUSES` is removed, in favor of `get_reversed_statuses`
- `task.kill` has been removed in favor of `kill_pid` and `kill_proc`.
- quieted cot verification a bit by removing some `log.debug` lines

## [12.1.0] - 2018-06-05
### Changed
- added `loop_function` kwarg to `sync_main` for testing

### Fixed
- fixed tests against aiohttp 3.3.0
- fixed concurrent test intermittent errors

## [12.0.1] - 2018-05-31
### Fixed
- fixed `mobile` `prebuilt_docker_image_task_types`
- we now log exceptions rather than printing a traceback to stderr

## [12.0.0] - 2018-05-29
### Added
- added a restriction on a.m.o. production scopes.
- added `prebuilt_docker_image_task_types`. These are the task types that allow non-artifact docker images; if `None`, all task types are allowed.
- added `get_in_tree_template`, `get_action_context_and_template`, `get_jsone_context_and_template` to help support new action hooks.
- added `verify_repo_matches_url` to stop using `.startswith()` to compare urls
- added `REPO_SCOPE_REGEX` to allow us to find the `repo_scope` in a task's scopes.
- added `get_repo_scope` to return the `repo_scope` in a task's scopes (or `None`)
- added a `test/data/cotv3` dir for action hook test data.

### Changed
- set `cot_version` to 3.
- set `min_cot_version` to 2.
- we now require cot artifacts in `verify_docker_image_sha`.
- we no longer check docker image shas against an allowlist; they either match chain of trust artifact shas, or they're a task type that allows prebuilt docker images. If these are defined in-tree, we trace the request to the tree, so these should be as trustable as the tree in question.
- we no longer allow for ignoring decision tasks' `taskGroupId`s. If they differ from the `taskId`, we follow the chain back.
- we no longer skip `verify_docker_worker_task` for `mobile` `cot_product`; but we do allow for prebuilt docker images on all task types.
- `get_source_url` now throws a `CoTError` if both the source url and repo are defined, and the source url doesn't match the repo.
- quieted the test output significantly.
- default test verbosity is toggled on by the `SCRIPTWORKER_VERBOSE_TESTS` env var.
- by default, tests now run concurrently for faster results. To allow this, we no longer close the event loop anywhere.

### Fixed
- we now log the exception at bad git tag signature verification.

### Removed
- removed cotv1 support
- removed `docker_image_allowlists`
- removed `gecko-decision` from the decision `workerType`s
- removed `ACTION_MACH_COMMANDS` and `DECISION_MACH_COMMANDS`
- removed "fuzzy matching" task definitions in `task-graph.json`. With json-e enabled actions, we should be able to match the `taskId` exactly.
- removed `verify_decision_command`; rebuilding the task definition via json-e is more precise.
- removed `get_jsone_template` in favor of the other, more specific template functions.

### Fixed
- added `.pytest_cache` to `.gitignore`

## [11.1.0] - 2018-05-16
### Added
- added py37 testing. This is currently broken due to `ldna_ssl` and `PyYAML`; marked this test in `allow_failures`.
- Support for `mobile` projects and more precisely Firefox Focus

## [11.0.0] - 2018-05-10
### Changed
- updated docs to reflect python 3.6.5 update
- updated to add aiohttp 3 support. aiohttp <3 is likely busted.
- stopped closing the event loop.

### Removed
- dropped python 3.5 support.

## [10.6.2] - 2018-05-01
### Fixed
- find try: in any line of an hg push comment, and strip any preceding characters

## [10.6.1] - 2018-04-30
### Fixed
- restrict compariston to  the first line of hg push comments for try

## [10.6.0] - 2018-04-26
### Added
- added mozilla-esr60 to restricted branches

### Changed
- changed `retry_async` logging to be more informative

## [10.5.0] - 2018-04-24
### Added
- added decision docker 2.1.0 to the allowlist

### Fixed
- cot logging now shows retries
- updated cron user to `cron`

## [10.4.0] - 2018-04-13
### Added
- added restricted scopes for thunderbird

### Changed
- update the output filenames of `create_gpg_keys`
- updated the docs to not hardcode cltsign.
- update release instructions to generate and use wheels

## [10.3.0] - 2018-04-04
### Added
- added support for addon_scriptworker

## [10.2.0] - 2018-03-14
### Changed
- `client.sync_main()` now loads the task
- `client.sync_main()` optionally verifies the loaded task
- `client.sync_main()` accepts optional default configuration
- `client.sync_main()` stubs out `context.write_json()`

## [10.1.0] - 2018-03-07
### Added
- added functions used in script depending on scriptworker.
  - added `utils.get_single_item_from_sequence()`
  - added `script.sync_main()` and `script.validate_task_schema()`
  - added `exceptions.TaskVerificationError`

## [10.0.0] - 2018-03-05
### Added
- added `get_loggable_url` to avoid logging secrets
- added integration test for private artifacts

### Changed
- `create_artifact` now has a default expiration of the task expiration date.
- `get_artifact_url` now supports signed URLs for private artifacts
- `get_artifact_url` no longer returns unquoted urls (breaks signed urls)
- `validate_artifact_url` unquotes paths before returning them

### Fixed
- fix integration tests for osx py36 [#135](https://github.com/mozilla-releng/scriptworker/issues/135)

### Removed
- removed the config for `artifact_expiration_hours`.
- removed support for taskcluster 0.3.x

## [9.0.0] - 2018-02-27
### Added
- added support for bouncer scriptworker

### Changed
- renamed `run_loop` to `run_tasks`
- `run_tasks` now shuts down gracefully after receiving a SIGTERM: it finishes the current task(s), and exits.

### Fixed
- `run_tasks` now sleeps 5 if there were no tasks claimed.

## [8.1.1] - 2018-02-13
### Fixed
- Freeze aiohttp to 2.x.y

## [8.1.0] - 2018-01-31
### Added
- `valid_vcs_rules`, `source_env_prefix`, `extra_run_task_arguments` depend on `cot_product`
- `cot_product` is defined in example configuration
- Support for ship-it tasks

## [8.0.0] - 2018-01-19
### Added
- Added `scriptworker.cot.verify.get_jsone_template`, because action tasks use actions.json instead of .taskcluster.yml

### Changed
- Added a `tasks_for` argument to `populate_jsone_context`.
- Used `format_json` instead of `pprint.pformat` in most `scriptworker.cot.verify` functions.

### Removed
- Removed `scriptworker.utils.render_jsone`, since it reduced to a `jsone.render` call.
- Removed the now-unused `scriptworker.constants.max_jsone_iterations`

## [7.0.0] - 2018-01-18
### Added
- Added `scriptworker.cot.verify.verify_parent_task_definition`. This is the core change in this release, aka CoT version 2. We now use json-e to rebuild the decision/action task definitions from the tree.
- Added `json-e` and `dictdiffer` dependencies.
- `arrow`, `certifi`, `multidict`, `taskcluster`, and `yarl` have updated their major version numbers.
- Added `Context.projects` and `Context.populate_projects`.
- Added `load_json_or_yaml_from_url`.
- Added `DEFAULT_CONFIG['cot_version']` and `DEFAULT_CONFIG['min_cot_version']`; this is cotv2. If `min_cot_version` is 1, we allow for falling back to the old cot v1 logic.
- Added `DEFAULT_CONFIG['project_configuration_url']` and `DEFAULT_CONFIG['pushlog_url']`.
- Added `scriptworker.task.KNOWN_TASKS_FOR`, `scriptworker.task.get_action_name`, `scriptworker.task.get_commit_message`, `scriptworker.task.get_and_check_project`, `scriptworker.task.get_and_check_tasks_for`
- Added `scriptworker.utils.remove_empty_keys` since the taskgraph drops key/value pairs where the value is empty. See https://github.com/taskcluster/json-e/issues/223
- Added `scriptworker.utils.render_jsone` to generically render json-e.
- Added `max_jsone_iterations` pref; sometimes the values to replace template values are several layers deep.
- Added `scriptworker.cot.verify.get_pushlog_info`, `scriptworker.cot.verify.get_scm_level`, `scriptworker.cot.verify.populate_jsone_context`, and `scriptworker.cot.verify.compare_jsone_task_definition`.
- Added test files to `scriptworker/test/data/cotv2/`.

### Changed
- Renamed `load_json` to `load_json_or_yaml`. This now takes a `file_type` kwarg that defaults to `json`.
- Moved `get_repo`, `get_revision`, `is_try`, and `is_action` from `scriptworker.cot.verify` to `scriptworker.task`
- Moved the sub-function path callback from `scriptworker.cot.verify` to `scriptworker.utils.match_url_path_callback`
- `scriptworker.cot.verify.guess_task_type` takes a 2nd arg, `task_defn`, to differentiate action tasks from decision/cron tasks.
- `scriptworker.cot.verify.get_all_artifacts_per_task_id` adds `public/actions.json` and `public/parameters.yml` to decision task artifacts to download, for action task verification.
- Removed the `firefox` from `scriptworker.cot.verify` function names.
- Tweaked the task ID logging in `verify_cot`.

### Fixed
- Updated `path_regexes` to identify most (all?) valid hg.m.o repo paths, instead of returning `None`.

### Removed
- Removed `scriptworker.cot.verify.verify_decision_task` and `scriptworker.cot.verify.verify_action_task` in favor of `scriptworker.cot.verify.verify_parent_task`.

## [6.0.2] - 2018-01-17
### Added
- `max_chain_length` pref, defaulting to the arbitrary (but larger than the current 5) int 20.

### Changed
- Stopped hardcoding the max chain length to 5 due to longer-than-5 valid chains in production.

## [6.0.1] - 2018-01-03
### Added
- Allow projects/birch to use project:releng:signing:cert:release-signing

## [6.0.0] - 2018-01-03
### Added
- `scriptworker.cot.verify.download_cot` now supports optional upstream artifacts
- `scriptworker.artifacts.get_optional_artifacts_per_task_id`, `scriptworker.cot.verify.(is_task_required_by_any_mandatory_artifact, is_artifact_optional)`, and `scriptworker.utils.(get_results_and_future_exceptions, add_enumerable_item_to_dict)` are defined and publicly exposed.

### Changed
- `scriptworker.artifacts.get_upstream_artifacts_full_paths_per_task_id` returns 2 dictionaries instead of 1.
- `scriptworker.cot.verify.(verify_docker_image_sha, download_cot_artifact)` don't error out if cot isn't defined (missing cot are detected earlier)

## [5.2.3] - 2017-10-20
### Fixed
- Made the exit status more explicit on exit code -11.
- Fixed `verify_sig` to return the message body if `gpg.decrypt` returns an empty body.

## [5.2.2] - 2017-10-16
### Added
- Added integration tests that run `verify_chain_of_trust` against production tasks, to make sure `cot.verify` changes are backwards compatible.

### Fixed
- stopped verifying docker-worker cot on the chain object, which may not have a cot artifact to verify.
- updated the `retry_exceptions` for `retry_request` to include `asyncio.TimeoutError`.

### Removed
- Removed the `await asyncio.sleep(1)` after running a task.

## [5.2.1] - 2017-10-11
### Added
- scriptworker will now retry (`intermittent-task` status) on a script exit code of -11, which corresponds to a python segfault.

## [5.2.0] - 2017-10-03
### Added
- `scriptworker.task.get_parent_task_id` to support the new `task.extra.parent` breadcrumb.
- `scriptworker.cot.verify.ACTION_MACH_COMMANDS` and `cot.verify.PARENT_TASK_TYPES` to separate action task verification from decision task verification.
- `scriptworker.cot.verify.ChainOfTrust.parent_task_id` to find the `parent_task_id` later.
- `scriptworker.cot.verify.LinkOfTrust.parent_task_id` to find the `parent_task_id` later.
- added a new `action` task type. This uses the same sha allowlist as the `decision` task type.
- `scriptworker.cot.verify.is_action`, since differentiating between a decision task and an action task requires some task definition introspection.
- `verify_firefox_decision_command` now takes a `mach_commands` kwarg; for action tasks, we set this to `ACTION_MACH_COMMANDS`
- `verify_action_task` verifies the action task command.
- `verify_parent_task` runs the checks previously in `verify_decision_task`; we run this for both action and decision tasks.

### Changed
- `find_sorted_task_dependencies` now uses the `parent_task_id` rather than the `decision_task_id` for its `parent_tuple`.
- `download_firefox_cot_artifacts` now downloads `task-graph.json` from action tasks as well as decision tasks
- `verify_decision_task` now only checks the command. The other checks have been moved to `verify_parent_task`.
- decision tasks now run `verify_parent_task`.

### Fixed
- Updated `README.md` to specify `tox` rather than `python setup.py test`

## [5.1.5] - 2017-10-02
### Added
- added maple to the list of privileged branches.

### Changed
- changed the default `poll_interval` to 10.

### Fixed
- updated post-task sleep to 1; we only sleep `poll_interval` only between polls.

### Removed
- removed date from the list of privileged branches.

## [5.1.4] - 2017-09-06
### Fixed
- no longer add a decision task's decision task to the chain of trust to verify. This was a regression.

### Removed
- cleaned up aurora references from everything but pushapk, which uses it.

## [5.1.3] - 2017-09-01
### Fixed
- specify the correct docker shas for the new docker images.

## [5.1.2] - 2017-09-01
### Fixed
- fixed new false error raised on missing command in payload

## [5.1.1] - 2017-08-31
### Fixed
- updated cot verification to allow for the new docker-image and decision paths (/home/worker -> /builds/worker)

## [5.1.0] - 2017-08-31
### Added
- added `DECISION_MACH_COMMANDS` to `cot.verify`, to support action task verification
- added `DECISION_TASK_TYPES` to `cot.verify`, to support verifying decision tasks via `verify_cot`
- added `ChainOfTrust.is_decision` to find if the chain object is a decision task
- added `ChainOfTrust.get_all_links_in_chain`. Previously, we ran certain tests against all the links in the chain, and other tests against all links + the chain object. Now, the chain itself may be a decision task; we will add the decision task as a link in the chain, and we no longer want to run verification tests against the chain object.
- added new docker image shas

### Changed
- we now support testing any verifiable `taskType` via `verify_cot`! Previously, only scriptworker task types were verifiable via the commandline tool.
- we now support testing action task commandlines in `verify_firefox_decision_command`
- we no longer ignore the decision task if the task-to-verify is the decision task in `find_sorted_task_dependencies`. We want to make sure we verify it.
- we no longer raise a `CoTError` if the `ChainOfTrust` object is not a scriptworker implementation

### Fixed
- fixed `partials` task verification

## [5.0.2] - 2017-08-28
### Added
- added .json as an `ignore_suffix` for docker-worker
- added `partials` as a valid task type

## [5.0.1] - 2017-08-25
### Added
- added sparse checkout decision task support in cot verification.
- added decision image 0.1.10 sha to allowlist

## [5.0.0] - 2017-08-22
### Added
- `watch_log_file` pref, to watch the log file for `logrotate.d` (or other) rotation. Set this to true in production.

### Changed
- switched from `RotatingFileHandler` to `WatchedFileHandler` or `FileHandler`, depending on whether `watch_log_file` is set.

### Removed
- Non-backwards-compatible: removed `log_max_bytes` and `log_num_backups` prefs. If set in a config file, this will break scriptworker launch. I don't believe anything sets these, but bumping the major version in case.

### Removed

## [4.2.0] - 2017-08-21
### Added
- added `prepare_to_run_task` to create a new `current_task_info.json` in `work_dir` for easier debugging.

### Changed
- `.diff` files now upload as `text/plain`.

## [4.1.4] - 2017-08-16
### Changed
- updated the decision + docker-image `workerType`s

### Fixed
- closed the contextual log handler to avoid filling up disk with open filehandles

## [4.1.3] - 2017-07-13
### Added
- added a check to verify the cot `taskId` matches the task `taskId`
- added a a `claimWork` debug log message
- added a check to prevent `python setup.py register` and `python setup.py upload`

### Fixed
- updated the docs to more accurately reflect the new instance steps
- updated the docs to avoid using `python setup.py register sdist upload`
- allowed the decision task to be an additional runtime dep

## [4.1.2] - 2017-06-14
### Changed
- rewrote chain of trust docs.

### Fixed
- fixed artifact list verification in `task.payload` for generic-worker tasks.

### Removed
- removed old format balrog scope.

## [4.1.1] - 2017-05-31
### Added
- added `.sh` as an `ignore_suffix` for generic-worker

## [4.1.0] - 2017-05-31
### Added

- added generic-worker chain of trust support
- `scriptworker.cot.verify.verify_generic_worker_task`, currently noop

### Changed

- generic-worker `ignore_suffixes` now includes `.in`

## [4.0.1] - 2017-05-23
### Changed

- Updated Google Play scopes to allow Nightly to ship to the Aurora product

## [4.0.0] - 2017-05-15
### Added
- added `scriptworker.task.claim_work` to use the `claimWork` endpoint instead of polling.

### Changed

- changed `worker.run_loop` to use the new `claim_work` function.  In theory this can handle multiple tasks serially, but in practice should only get one at a time.  In the future we can allow for multiple tasks run in parallel in separate `work_dir`s, if desired.
- `worker.run_loop` now always sleeps the `poll_interval`.  We can adjust this if desired.

### Fixed

- tweaked docstrings to pass pydocstyle>=2.0

### Removed
- removed `Context.poll_task_urls`
- removed `scriptworker.poll` completely

## [3.1.2] - 2017-04-14
### Changed
- allowed for retriggering tasks with a subset of `task.dependencies`, specifically to get around expiration of the breakpoint dependency of pushapk tasks.

## [3.1.1] - 2017-04-07
### Added
- added oak to `all-nightly-branches`, for update testing.
- added `repackage` as a valid, verifiable task type for cot.

## [3.1.0] - 2017-04-05
### Added
- added log message on startup.

### Changed
- updated docker image allowlists
- changed balrog nightly branches to `all-nightly-branches`

## [3.0.0] - 2017-03-23
## Added
- `scriptworker.artifacts` now has new functions to deal with `upstreamArtifacts`: `get_upstream_artifacts_full_paths_per_task_id`, `get_and_check_single_upstream_artifact_full_path`, and `get_single_upstream_artifact_full_path`.
- added a `LinkOfTrust.get_artifact_full_path` method
- new `helper_scripts` directory: `gpg_helper.sh` is a wrapper to call gpg against a given gpg home directory.  `create_gpg_keys.py` is a script to create new scriptworker gpg keys.

## Changed
- updated support, and now require, `aiohttp>=2.0.0`
- pointed the pushapk scopes at new `betatest` and `auroratest` `cot_restricted_trees` aliases
- renamed `find_task_dependencies` to `find_sorted_task_dependencies`

## Fixed
- `aiohttp` 2.0.0 no longer burns travis jobs.

## [2.6.0] - 2017-03-06
### Changed
- update balrog restricted scopes to include `project:releng:balrog:nightly` until we're done with it

## [2.5.0] - 2017-03-06
### Changed
- allow for `/bin/bash` in decision task command line

### Fixed
- don't add a decision task's decision task to the dependency chain.  In 2.2.0 we stopped verifying that a decision task was part of its decision task's task graph, but still verified the decision task's decision task (if any).  This release stops tracing back to the original decision task altogether.

## [2.4.0] - 2017-02-28
### Changed
- updated balrog restricted scopes

## [2.3.0] - 2017-02-22
### Changed
- updated balrog and beetmover restricted scopes

## [2.2.0] - 2017-02-15
### Changed
- decision tasks are no longer traced back to decision tasks, even if their `taskGroupId` doesn't match their `taskId`.

### Fixed
- tests now pass under python 3.6; we'll update the supported version list when taskcluster-client.py has full py36 support
- fixed closed event loop errors from the new aiohttp
- git tests now use a local git repo tarball, instead of running tests on the scriptworker repo

### Removed
- removed the check for max number of decision tasks per graph

## [2.1.1] - 2017-02-02
### Fixed
- `get_artifact_url` now works with `taskcluster==1.0.2`, while keeping 0.3.x compatibility
- more verbose upload status

## [2.1.0] - 2017-01-31
### Added
- `intermittent-task` status
- `scriptworker.utils.calculate_sleep_time`
- added `retry_async_kwargs` kwarg to `retry_request`
- added `sleeptime_kwargs` kwarg to `retry_async`

### Changed
- renamed `release` and `nightly` branch aliases to `all-release-branches` and `all-nightly-branches`
- updated pushapk restricted scopes
- reduced `aiohttp_max_connections` to 15
- `aiohttp` exceptions now result in an `intermittent-task` status, rather than `resource-unavailable`

## [2.0.0] - 2017-01-25
### Added
- `scriptworker.artifacts` is a new submodule that defines artifact behavior
- we now support `pushapk` scriptworker instance types in `cot.verify`

### Changed
- `freeze_values` is now `get_frozen_copy`, and now returns a frozen copy instead of modifying the object in place.
- `unfreeze_values` is now `get_unfrozen_copy`
- `check_config` now calls `get_frozen_copy` on the `config` before comparing against `DEFAULT_CONFIG`
- `create_config` calls `get_unfrozen_copy`, resulting in a recursively frozen config
- `DEFAULT_CONFIG` now uses `frozendict`s and `tuple`s in nested config items.
- `.asc` files are now forced to `text/plain`
- all `text/plain` artifacts are now gzipped, including .log, .asc, .json, .html, .xml
- we no longer have `task_output.log` and `task_error.log`.  Instead, we have `live_backing.log`, for more treeherder-friendliness

### Removed
- stop testing for task environment variables.  This is fragile and provides little benefit; let's push on [bug 1328719](https://bugzilla.mozilla.org/show_bug.cgi?id=1328719) instead.

## [1.0.0b7] - 2017-01-18
### Added
- `unfreeze_values`, to unfreeze a `freeze_values` frozendict.

### Changed
- `freeze_values` now recurses.

### Fixed
- delete azure queue entries on status code 409 (already claimed or cancelled).  This allows us to clean up cancelled tasks from the queue, speeding up future polling.
- more retries and catches in `find_task`, making it more robust.

## [1.0.0b6] - 2017-01-12
### Fixed
- balrog tasks are now verifiable in chain of trust.

## [1.0.0b5] - 2017-01-10
### Added
- `verify_signed_tag`, which verifies the tag's signature and makes sure we're updated to it.

### Changed
- `rebuild_gpg_homedirs` now uses git tags instead of checking for signed commits.
- `get_git_revision` now takes a `ref` kwarg; it finds the revision for that ref (e.g., tag, branch).
- `update_signed_git_repo` `revision` kwarg is now named `ref`.  It also verifies and updates to the signed git tag instead of `ref`.
- `update_signed_git_repo` now returns a tuple (revision, tag)
- `build_gpg_homedirs_from_repo` now uses `verify_signed_tag` instead of `verify_signed_git_commit`, and takes a new `tag` arg.

### Fixed
- the curl command in `Dockerfile.gnupg` now retries on failure.

### Removed
- `verify_signed_git_commit_output`
- `verify_signed_git_commit`

## [1.0.0b4] - 2016-12-19
### Added
- beetmover and balrog scriptworker support in chain of trust verification
- `cot_restricted_trees` config, which maps branch-nick to branches

### Changed
- Changed `cot_restricted_scopes` to be a scope to branch-nick dict, indexed by `cot_product`

### Fixed
- nuke then move the tmp gpg homedir, rather than trying to [wrongly] use `overwrite_gpg_home` on a parent dir

## [1.0.0b3] - 2016-12-07
### Added
- Dockerfiles: one for general testing and one for gpg homedir testing, with readme updates
- `flake8_docstrings` in tox.ini
- log chain of trust verification more verbosely, since we no longer have real artifacts uploaded alongside

### Changed
- download cot artifacts into `work_dir/cot` instead of `artifact_dir/public/cot`, to avoid massive storage dups
- `download_artifacts` now returns a list of full paths instead of relative paths. Since `upstreamArtifacts` contains the relative paths, this should be more helpful.
- `contextual_log_handler` now takes a `logging.Formatter` kwarg rather than a log format string.

### Changed
- check for a new gpg homedir before `run_loop`, because puppet will now use `rebuild_gpg_homedirs`

### Fixed
- updated all docstrings to pass `flake8_docstrings`
- switched to a three-phase lockfile for gpg homedir creation to avoid race conditions (locked, ready, unlocked)
- catch `aiohttp.errors.DisconnectedError` and `aiohttp.errors.ClientError` in `run_loop` during `upload_artifacts`
- compare the built docker-image tarball hash against `imageArtifactHash`

### Removed
- the `create_initial_gpg_homedirs` entry point has been removed in favor of `rebuild_gpg_homedirs`.

## [1.0.0b2] - 2016-11-28
### Changed
- `scriptworker.cot.verify.raise_on_errors` now takes a kwarg of `level`, which defaults to `logging.CRITICAL`.  This is to support fuzzy task matching, where not matching a task is non-critical.
- `scriptworker.cot.verify.verify_link_in_task_graph` now supports fuzzy task matching.  If the Link's `task_id` isn't in the task graph, try to match the task definition against the task graph definitions, and throw `CoTError` on failure.  This is to support Taskcluster retriggers.
- `verify_cot` is now an entry point, rather than a helper script in `scriptworker/test/data/`.

### Fixed
- allowed for `USE_SCCACHE` as a build env var

## [1.0.0b1] - 2016-11-14
### Added
- `scriptworker.cot.verify` now verifies the chain of trust for the graph.
- `scriptworker.exceptions.CoTError` now marks chain of trust validation errors.
- `scriptworker.task.get_task_id`, `scriptworker.task.get_run_id`, `scriptworker.task.get_decision_task_id`, `scriptworker.task.get_worker_type`
- `scriptworker.log.contextual_log_handler` for short-term logs
- added framework for new docs

### Changed
- config files are now yaml, to enable comments.  `config_example.json` and `cot_config_example.json` have been consolidated into `scriptworker.yaml.tmpl`.  `context.cot_config` items now live in `context.config`.
- `validate_artifact_url` now takes a list of dictionaries as rules, leading to more configurable url checking.
- `scriptworker.cot` is now `scriptworker.cot.generate`.  The `get_environment` function has been renamed to `get_cot_environment`.
- `scriptworker.gpg.get_body` now takes a `verify_sig` kwarg.
- `download_artifacts` now takes `valid_artifact_task_ids` as a kwarg.
- `max_connections` is now `aiohttp_max_connections`
- scriptworker task definitions now expect an `upstreamArtifacts` list of dictionaries

### Fixed
- docstring single backticks are now double backticks
- catch aiohttp exceptions on upload

### Removed
- removed all references to `cot_config`
- removed the credential update, since puppet restarts scriptworker on config change.

## [0.9.0] - 2016-11-01
### Added
- `gpg_lockfile` and `last_good_git_revision_file` in config
- `get_last_good_git_revision` and `write_last_good_git_revision` now return the last good git revision, and write it to `last_good_git_revision_file`, respectively.
- `get_tmp_base_gpg_home_dir` is a helper function to avoid duplication in logic.
- `rebuild_gpg_homedirs` is a new entry point script that allows us to recreate the gpg homedirs in a tmpdir, in a separate process
- `is_lockfile_present`, `create_lockfile`, and `rm_lockfile` as helper functions for the two gpg homedir entry points.

### Changed
- `sign_key`, `rebuild_gpg_home_flat`, `rebuild_gpg_home_signed`, `build_gpg_homedirs_from_repo` are no longer async.
- `overwrite_gpg_home` only keeps one backup.
- `update_signed_git_repo` now returns the latest git revision, instead of a boolean marking whether the revision is new or not.  This will help avoid the scenario where we update, fail to generate the gpg homedirs, and then stay on an old revision until the next push.
- `update_logging_config` now takes a `file_name` kwarg, which allows us to create new log files for the `rebuild_gpg_homedirs` and `create_initial_gpg_homedirs` entry points.

### Fixed
- `build_gpg_homedirs_from_repo` now waits to verify the contents of the updated git repo before nuking the previous base gpg homedir.
- `create_initial_gpg_homedirs` now creates a logfile

### Removed
- `rebuild_gpg_homedirs_loop` is no longer needed, and is removed.

## [0.8.2] - 2016-10-24
### Changed
- logged the stacktrace if the `main` loop hits an exception.  No longer catch and ignore `RuntimeError`, since it wasn't clear why that was put in.
- updated `check_config` to make sure taskcluster-related configs match taskcluster requirements

### Fixed
- changed the way the polling loop works: `async_main` is now a single pass, which `main` calls in a `while True` loop.  This should fix the situation where polling was dying silently while the git update loop continued running every 5 minutes.

## [0.8.1] - 2016-10-18
### Fixed
- explicitly pass `taskId` and `runId` to `claim_task`.  There's a new `hintId` property that appears in `message_info['task_info']` that broke things.

## [0.8.0] - 2016-10-13
### Added
- added `git_key_repo_dir`, `base_gpg_home_dir`, `my_email`, and `gpg_path` to `config_example.json`
- added `cot_config_example.json`, `cot_config_schema.json`, and `scriptworker.config.get_cot_config` for ChainOfTrust config
- added `update_signed_git_repo`, `verify_signed_git_commit`, `build_gpg_homedirs_from_repo`, `rebuild_gpg_homedirs_loop`, and `create_initial_gpg_homedirs` for gpg homedir creation and updates in the background.
- added a background call to update the gpg homedirs in `scriptworker.worker.async_main`
- added another entry point, `create_initial_gpg_homedirs`, for puppet to create the first gpg homedirs

### Changed
- default config filename is now `scriptworker.json` instead of `config.json`
- moved `scriptworker.config.get_context_from_cmdln` out of `scriptworker.worker.main`; now using argparse
- changed default `sign_chain_of_trust` to True
- `scriptworker.gpg.sign_key`, `scriptworker.gpg.rebuild_gpg_home_flat`, and `scriptworker.gpg.rebuild_gpg_home_signed` are now async, so they can happen in parallel in the background
- renamed `scriptworker.gpg.latest_signed_git_commit` to `scriptworker.gpg.verify_signed_git_commit_output`
- combined `scriptworker.log.log_errors` and `scriptworker.log.read_stdout` into `scriptworker.log.pipe_to_log`
- added `taskGroupId` to the list of default valid `taskId`s to download from.  This logic will need to change in version 0.9.0 due to the new [chain of trust dependency traversal logic](https://gist.github.com/escapewindow/a6a6944f51d4219d08284ededc65aa30)

### Fixed
- added missing docstrings to the `download_artifacts` and `download_file` functions
- fixed coverage version in `tox.ini py35-coveralls`
- `sign_key` now supports signing keys with multiple subkeys

## [0.7.0] - 2016-09-23
### Added
- added `DownloadError` exception for `download_file`
- added `scriptworker.task.download_artifacts`
- added `scriptworker.util.download_file`

### Changed
- `DEFAULT_CONFIG`, `STATUSES`, and `REVERSED_STATUSES` have moved to `scriptworker.constants`.
- `list_to_tuple` has been renamed `freeze_values`, and also converts dict values to frozendicts.

## [0.6.0] - 2016-09-15
### Added
- significant gpg support
- ability to create new gpg homedirs
- scriptworker now requires `pexpect` for gpg key signing
- docstrings!
- helper scripts to generate 1000 pubkeys and time importing them.
- added `scriptworker.utils.rm` as an `rm -rf` function

### Changed
- `utils.makedirs` now throws `ScriptWorkerException` if the path exists and is not a directory or a softlink pointing to a directory.
- gpg functions now take a `gpg_home` kwarg to specify a different homedir
- moved `scriptworker.client.integration_create_task_payload` into `scriptworker.test`
- renamed `scriptworker.util.get-_hash` kwarg `hash_type` to `hash_alg`
- renamed `firefox_cot_schema.json` to `cot_v1_schema.json`; also, the schema has changed.
- the chain of trust schema has changed to version 1.

### Fixed
- pass a `task` to `scriptworker.task.reclaimTask` and exit the loop if it doesn't match `context.task`
- we now verify that `context.task` is the same task we scheduled `reclaim_task` for.

### Removed
- Removed `get_temp_creds_from_file`, since we're not writing `temp_creds` to disk anymore
- Removed `scriptworker.task.get_temp_queue`, since we already have `context.temp_queue`
- Removed `pytest-asyncio` dependency.  It doesn't play well with `pytest-xdist`.
- Removed `scriptworker.task.get_temp_queue`; we can use `context.temp_queue`
- Removed `pytest-asyncio` usage to try to use `pytest-xdist`, then turned that back off when it conflicted with the event loop

## [0.5.0] - 2016-08-29
### Added
- added `firefox_cot_schema.json` for firefox chain of trust
- added gpg signature creation + verification
- added chain of trust generation
- added `scriptworker.task.worst_level` function for determining overall result of task

### Changed
- `unsignedArtifacts` url paths are now unquoted, so `%2F` becomes `/`
- `validate_task_schema` renamed to `validate_json_schema`
- write task log files directly to the `task_log_dir`; this should be a subdir of `artifact_dir` if we want them uploaded.
- `ScriptWorkerException` now has an `exit_code` of 5 (`internal-error`); `ScriptWorkerRetryException` now has an `exit_code` of 4 (`resource-unavailable`)
- moved `tests` directory to `scriptworker/test`

### Fixed
- Functions in `test_config` now ignore existing `TASKCLUSTER_` env vars for a clean testing environment
- `raise_future_exceptions` no longer throws an exception for an empty list of tasks
- Updated `CONTRIBUTING.rst` to reflect reality

## [0.4.0] - 2016-08-19
### Added
- add `scriptworker.utils.filepaths_in_dir`
- added setup.cfg for wheels
- added `scriptworker.client.validate_artifact_url`.
- added python-gnupg dependency

### Changed
- test files no longer use a test class.
- `upload_artifacts` now uploads files in subdirectories of `artifact_dir`, preserving the relative paths.

### Removed
- Removed unneeded creds file generation.

## [0.3.0] - 2016-08-11
### Added
- Added `requirements-*.txt` files.  The `-prod` files have pinned versions+hashes, via `reqhash`.
- Added `raise_future_exceptions` function from signingscript

### Changed
- Upload artifacts to public/env/`filename`.
- Enabled coverage branches in testing.
- Enabled environment variable configuration for credentials+workerid
- Moved source repo to [mozilla-releng/scriptworker](https://github.com/mozilla-releng/scriptworker)
- No longer prepend stderr log lines with ERROR
- Reduced debug logging

### Fixed
- Tweaked the config defaults to be a bit more sane.
- Fixed an exception where automated processes without HOME set would fail to launch scriptworker

### Removed
- Removed `scheduler_id` from config; it's only used to schedule integration tests.

## [0.2.1] - 2016-06-27
### Fixed
- `upload_artifacts` now specifies a `content_type` of `text/plain` for the task logfiles, to fix linux uploading.

## [0.2.0] - 2016-06-24
### Changed
- Context now has a `claim_task` property that stores the output from `claimTask`.  `Context.task` is now the task definition itself.
- `scriptworker.utils.request` now takes additional kwargs to be a more versatile function.

## [0.1.3] - 2016-06-24
### Added
- bundled version.json
- CHANGELOG.md

### Changed
- Pinned `pytest-asyncio` to 0.3.0 because 0.4.1 hits closed event loop errors.
