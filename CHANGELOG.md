# Change Log
All notable changes to this project will be documented in this file.
This project adheres to [Semantic Versioning](http://semver.org/).

## Unreleased
### Added
- added setup.cfg for wheels
- added `scriptworker.client.validate_artifact_url`

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
