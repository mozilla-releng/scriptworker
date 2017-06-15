# Change Log
All notable changes to this project will be documented in this file.
This project adheres to [Semantic Versioning](http://semver.org/).

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
