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

## Release files
If you're changing any dependencies, please update `setup.py`.

If you add change the list of files that need to be packaged (either adding new files, or removing previous packaged files), modify `MANIFEST.in`.

### Versioning
Modify `scriptworker/version.py` to set the `__version__` to the appropriate tuple.  This is either a 3- or 4-part tuple, e.g.

```python
# 0.10.0a1
__version__ = (0, 10, 0, "alpha1")

# 1.0.0b2
__version__ = (1, 0, 0, "beta2")

# 0.9.3
__version__ = (0, 9, 3)
```

Then run `version.py`:

```bash
# Using the local venv python>=3.5,
python scriptworker/version.py
```

This will update `version.json`.  Verify both files look correct.

## Tagging

To enable gpg signing in git,

1. you need a [gpg keypair](https://wiki.mozilla.org/Security/Guidelines/Key_Management#PGP.2FGnuPG)
2. you need to set your [`user.signingkey`](https://git-scm.com/book/en/v2/Git-Tools-Signing-Your-Work#GPG-Introduction) in your `~/.gitconfig` or `scriptworker/.git/config`
3. If you want to specify a specific gpg executable, specify your `gpg.program` in your `~/.gitconfig` or `scriptworker/.git/config`

Tag and sign!

```bash
    # make sure you've committed your changes first!
    VERSION=0.9.0
    git tag -s $VERSION -m"$VERSION"
```

Push!

```bash
    # By default this will push the new tag to origin; make sure the tag gets pushed to
    # mozilla-releng/scriptworker
    git push --tags
```

## Pypi

Someone with access to the scriptworker package on `pypi.python.org` needs to do the following:

```bash
    # from https://packaging.python.org/tutorials/distributing-packages/#uploading-your-project-to-pypi
    # Don't use `python setup.py register` or `python setup.py upload`; this may use
    # cleartext auth!
    # Using a python with `twine` in the virtualenv:
    VERSION=4.1.2
    # create the source tarball and wheel
    python setup.py sdist bdist_wheel
    # upload the source tarball + wheel
    twine upload dist/scriptworker-${VERSION}.tar.gz dist/scriptworker-${VERSION}-py2.py3-none-any.whl
```

That creates source tarball and wheel, and uploads it.

## Rollout

To roll out to the scriptworker kubernetes pools, wait for a few minutes after the pypi upload, run [pin.sh](https://github.com/mozilla-releng/scriptworker-scripts/blob/master/maintenance/pin.sh) to bump all the workers, get review on that change, then push to the `production` branch when you're ready to roll out. (Use the `production-___script` branches if you only want to update scriptworker on a subset of workers.) We'll see a notification in Slack `#releng-notifications` as each pool rolls out.

To roll out to the mac signers, get review for a patch like [this](https://github.com/mozilla-platform-ops/ronin_puppet/commit/d08be5473a425e12a3d865a038a3b6a9f71c1548) and merge. The mac signer maintainers will roll out to the `production-mac-signing` branch as appropriate. We don't get notifications anywhere, so we likely just need to give this a half hour or so to roll out.
