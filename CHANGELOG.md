# Change Log
All notable changes to this project will be documented in this file.
This project adheres to [Semantic Versioning](http://semver.org/).

## Unreleased
### Changed
- we now upload artifacts to public/env/`filename`.

### Fixed
- the config defaults are now a bit more sane.

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
