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
If you're changing any dependencies, please update `requirements-dev.txt`, `requirements-test-dev.txt`, and `setup.py`.

If you add change the list of files that need to be packaged (either adding new files, or removing previous packaged files), modify `MANIFEST.in`.

### Requirements
It's good practice to keep `requirements-prod.txt` and `requirements-test-prod.txt` up to date.  To do so:

```bash
    # Using the local venv python>=3.5,
    pip install dephash
    dephash gen requirements-dev.txt > requirements-prod.txt
    dephash gen requirements-test-dev.txt > requirements-test-prod.txt
```

A `git diff` will then show what has changed in the scriptworker dependencies since the last time dephash was run.  Assuming we only add the new dependencies when tox is green, we have a last-known-good set of dependencies.  Add these to the list of changes to commit.

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
    # You may hit problems with this using py>=35?
    python setup.py register sdist upload
```

That creates the new version in pypi, creates the source tarball, and uploads it.

## Puppet

Connect to Releng VPN.

Copy the tarball from `dist/` to `releng-puppet2.srv.releng.scl3.mozilla.com`:

```bash
scp dist/scriptworker-$VERSION.tar.gz releng-puppet2.srv.releng.scl3.mozilla.com:
ssh releng-puppet2.srv.releng.scl3.mozilla.com
cd /data/python/packages-3.5
sudo mv ~/scriptworker-$VERSION.tar.gz .
```

Bump the [scriptworker version](https://hg.mozilla.org/build/puppet/file/b67965cc83e6/modules/signing_scriptworker/manifests/init.pp#l43) in the appropriate scriptworker instance puppet configs.

If desired, test in your [user environment](https://wiki.mozilla.org/ReleaseEngineering/PuppetAgain/HowTo/Set_up_a_user_environment) first.  Otherwise, get review, land, and merge to production.
