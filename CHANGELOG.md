# Change Log
All notable changes to this project will be documented in this file.
This project adheres to [Semantic Versioning](http://semver.org/).

## Unreleased

## [0.7.2] - 2016-10-24
### Changed
- logged the stacktrace if the `main` loop hits an exception.  No longer catch and ignore `RuntimeError`, since it wasn't clear why that was put in.
- updated `check_config` to make sure taskcluster-related configs match taskcluster requirements

### Fixed
- changed the way the polling loop works: `main` calls `loop.run_until_complete(async_main(context))` in a `while True` loop, instead of `loop.run_forever()`.


## [0.7.1] - 2016-10-18
### Fixed
- explicitly pass `taskId` and `runId` to `claim_task`.  There's a new `hintId` property that appears in `message_info['task_info']` that broke things.

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

## Removed
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
