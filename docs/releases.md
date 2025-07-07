# Scriptworker Releases

These are the considerations and steps for a new scriptworker release.

## Code changes

Ideally, code changes should follow [clean architecture best practices](https://www.youtube.com/watch?v=DJtef410XaM)

When adding new functions, classes, or files, or when changing function arguments, please [add or modify the docstrings](http://sphinxcontrib-napoleon.readthedocs.org/en/latest/example_google.html).

## Tests and test coverage

Scriptworker has [100% test coverage](http://escapewindow.dreamwidth.org/247980.html), and we'd like to keep it that way.

[Run tests locally via tox](README.html#testing) to make sure the tests pass, and we still have 100% coverage.

## Versioning

Scriptworker follows [semver](http://semver.org/).  Essentially, increment the

1. MAJOR version when you make incompatible API changes,
2. MINOR version when you add API functionality in a backwards-compatible manner, and
3. PATCH version when you make backwards-compatible bug fixes.

## Changelog

[Update the changelog](http://keepachangelog.com/) before making a new release.

### Versioning
Modify `pyproject.toml` and set the `version` field to the appropriate version.

Commit this version bump along with the updates to the changelog.

## Create a Release

Once the version bump has landed, create a new Github Release:

1. Click "Releases" then "Draft a new release"
2. Under "Choose a Tag", type in the version you just bumped to and select "Create new tag: <tag> on publish".
3. Click "Generate release notes"
4. Verify "Set as latest release" is checked, then click "Publish release"

This will trigger the Github `pypi-publish` workflow, which builds the package
and publishes it to Pypi. You can verify the workflow succeeded under the
"Actions" tab.

## Rollout

To roll out to the scriptworker kubernetes pools, wait for a few minutes after the pypi upload, run [pin.sh](https://github.com/mozilla-releng/scriptworker-scripts/blob/master/maintenance/pin.sh) to bump all the workers, get review on that change, then push to the `production` branch when you're ready to roll out. (Use the `production-___script` branches if you only want to update scriptworker on a subset of workers.) We'll see a notification in Slack `#releng-notifications` as each pool rolls out.

To roll out to the mac signers, get review for a patch like [this](https://github.com/mozilla-platform-ops/ronin_puppet/commit/d08be5473a425e12a3d865a038a3b6a9f71c1548) and merge. The mac signer maintainers will roll out to the `production-mac-signing` branch as appropriate. We don't get notifications anywhere, so we likely just need to give this a half hour or so to roll out.
