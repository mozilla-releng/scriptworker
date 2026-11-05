import asyncio
from copy import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import taskcluster.exceptions

from scriptworker import github
from scriptworker.exceptions import ConfigError, ScriptWorkerRetryException


@pytest.fixture(autouse=True)
def clear_github_cache():
    github._COMPARE_CACHE.clear()
    yield
    github._COMPARE_CACHE.clear()


@pytest.fixture(scope="function")
def context(mobile_rw_context):
    ctx = mobile_rw_context
    ctx.task = {"taskGroupId": "bobo"}
    yield ctx


@pytest.fixture(scope="function")
def vpn_context(vpn_private_rw_context):
    ctx = vpn_private_rw_context
    ctx.task = {"taskGroupId": "bobo"}
    yield ctx


@pytest.fixture(scope="function")
def token_context():
    return SimpleNamespace(
        config={"github_oauth_token": "fallback-token", "github_app_name": "read", "taskcluster_root_url": "https://tc.example.com"},
        credentials={"a": "b"},
    )


@pytest.fixture(scope="function")
def github_repository(mocker, token_context):
    github_repository_mock = MagicMock()
    github_repository_mock.__name__ = "GithubRepositoryMock"
    github_repository_mock.html_url = "https://github.com/some-user/some-repo/"
    github_repository_mock.tags.__name__ = "GithubTagsMock"
    github_repository_mock.tags.return_value = [SimpleNamespace(name="v1.0.0", commit=SimpleNamespace(sha="hashforv100"))]
    github_instance_mock = MagicMock()
    github_instance_mock.__name__ = "github_instance_mock"
    github_instance_mock.repository.__name__ = "GithubRepositoryMock"
    github_instance_mock.repository.return_value = github_repository_mock
    github_class_mock = mocker.patch.object(github, "GitHub", return_value=github_instance_mock)
    github_class_mock.__name__ = github_class_mock.name
    mocker.patch.object(github, "Auth", side_effect=taskcluster.exceptions.TaskclusterFailure("disabled in tests"))
    yield github.GitHubRepository(token_context, "some-user", "some-repo")


@pytest.mark.asyncio
async def test_constructor(mocker, token_context):
    github_instance_mock = MagicMock()
    github_instance_mock.repository.__name__ = "github_instance_repository_mock"
    github_class_mock = mocker.patch.object(github, "GitHub", return_value=github_instance_mock)
    github_class_mock.__name__ = github_class_mock.name
    mocker.patch.object(github, "Auth", side_effect=taskcluster.exceptions.TaskclusterFailure("disabled in tests"))

    repo = github.GitHubRepository(token_context, "some-user", "some-repo")
    await repo._get_repository()

    github_class_mock.assert_called_once_with(token="fallback-token")
    github_instance_mock.repository.assert_called_once_with("some-user", "some-repo")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raises, expected_token",
    (
        (False, "scoped-token"),
        (True, "fallback-token"),
    ),
)
async def test_constructor_with_context(mocker, token_context, raises, expected_token):
    github_instance_mock = MagicMock()
    github_instance_mock.repository.__name__ = "github_instance_repository_mock"
    github_class_mock = mocker.patch.object(github, "GitHub", return_value=github_instance_mock)
    github_class_mock.__name__ = github_class_mock.name

    auth_instance_mock = MagicMock()
    if raises:
        auth_instance_mock.githubRepoToken = AsyncMock(side_effect=taskcluster.exceptions.TaskclusterRestFailure("missing scopes", None, status_code=403))
    else:
        auth_instance_mock.githubRepoToken = AsyncMock(return_value={"token": "scoped-token", "expires": "2020-01-01T00:00:00Z"})
    auth_class_mock = mocker.patch.object(github, "Auth", return_value=auth_instance_mock)

    repo = github.GitHubRepository(token_context, "some-user", "some-repo")
    await repo._get_repository()

    github_class_mock.assert_called_once_with(token=expected_token)
    auth_class_mock.assert_called_once_with(options={"rootUrl": "https://tc.example.com", "credentials": {"a": "b"}})
    auth_instance_mock.githubRepoToken.assert_called_once_with(
        "read", "some-user", payload={"repositories": ["some-repo"], "permissions": github.GitHubRepository.GITHUB_PERMISSIONS}
    )


retry_count = {}


@pytest.mark.asyncio
async def test_constructor_uses_retry_sync(mocker, token_context):
    global retry_count
    retry_count["fail_first"] = 0

    def fail_first(*args, **kwargs):
        global retry_count
        retry_count["fail_first"] += 1
        if retry_count["fail_first"] < 2:
            raise ScriptWorkerRetryException("first")

        github_instance_mock = MagicMock()
        github_instance_mock.repository.__name__ = "github_instance_repository_mock"
        return github_instance_mock

    github_class_mock = mocker.patch.object(github, "GitHub", side_effect=fail_first)
    github_class_mock.__name__ = github_class_mock.name
    mocker.patch.object(github, "Auth", side_effect=taskcluster.exceptions.TaskclusterFailure("disabled in tests"))
    mocker.patch.object(github, "_GITHUB_LIBRARY_SLEEP_TIME_KWARGS", {"delay_factor": 0.1})
    repo = github.GitHubRepository(token_context, "some-user", "some-repo")
    await repo._get_repository()

    assert retry_count["fail_first"] == 2


@pytest.mark.asyncio
async def test_get_definition(github_repository):
    repository = await github_repository._get_repository()
    repository.as_dict.return_value = {"foo": "bar"}
    assert await github_repository.get_definition() == {"foo": "bar"}
    repository.as_dict.assert_called_once_with()


@pytest.mark.asyncio
async def test_get_file_contents_caches_commit_hash(github_repository, tmp_path):
    github_repository._context.config["work_dir"] = str(tmp_path)
    repository = await github_repository._get_repository()
    repository.file_contents.return_value.decoded = b"tasks: []\n"
    ref = "a" * 40

    assert await github_repository.get_file_contents(".taskcluster.yml", ref=ref) == "tasks: []\n"
    assert await github_repository.get_file_contents(".taskcluster.yml", ref=ref) == "tasks: []\n"
    repository.file_contents.assert_called_once_with(".taskcluster.yml", ref=ref)


@pytest.mark.asyncio
@pytest.mark.parametrize("ref", (None, "main"))
async def test_get_file_contents_no_cache_for_mutable_ref(github_repository, tmp_path, ref):
    github_repository._context.config["work_dir"] = str(tmp_path)
    repository = await github_repository._get_repository()
    repository.file_contents.return_value.decoded = b"tasks: []\n"

    await github_repository.get_file_contents(".taskcluster.yml", ref=ref)
    await github_repository.get_file_contents(".taskcluster.yml", ref=ref)
    assert repository.file_contents.call_count == 2


@pytest.mark.asyncio
async def test_get_commit(github_repository):
    await github_repository.get_commit("somehash")
    repository = await github_repository._get_repository()
    repository.commit.assert_called_once_with("somehash")


@pytest.mark.asyncio
async def test_get_pull_request(github_repository):
    await github_repository.get_pull_request(1)
    repository = await github_repository._get_repository()
    repository.pull_request.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_get_release(github_repository):
    await github_repository.get_release("some-tag")
    repository = await github_repository._get_repository()
    repository.release_from_tag.assert_called_once_with("some-tag")


@pytest.mark.parametrize(
    "tags, raises, expected",
    (
        ([SimpleNamespace(name="some-tag", commit=SimpleNamespace(sha="somecommit"))], False, "somecommit"),
        (
            [
                SimpleNamespace(name="another-tag", commit=SimpleNamespace(sha="anothercommit")),
                SimpleNamespace(name="some-tag", commit=SimpleNamespace(sha="somecommit")),
            ],
            False,
            "somecommit",
        ),
        ([SimpleNamespace(name="another-tag", commit=SimpleNamespace(sha="anothercommit"))], True, None),
        ([], True, None),
    ),
)
@pytest.mark.asyncio
async def test_get_tag_hash(github_repository, tags, raises, expected):
    repository = await github_repository._get_repository()
    repository.tags.return_value = tags

    if raises:
        with pytest.raises(ValueError):
            await github_repository.get_tag_hash("some-tag")
    else:
        tag_hash = await github_repository.get_tag_hash("some-tag")
        assert tag_hash == expected


@pytest.mark.parametrize(
    "commitish, ref, base, compare, raises, expected",
    (
        # Commit reachable from the ref
        ("0129abcdef012345643456789abcdef012345678", "refs/heads/main", "refs/heads/main", "behind", False, True),
        ("0129abcdef012345643456789abcdef012345678", "refs/heads/main", "refs/heads/main", "identical", False, True),
        ("0129abcdef012345643456789abcdef012345678", "refs/tags/v1.0.0", "refs/tags/v1.0.0", "identical", False, True),
        # Bare names, like *_HEAD_BRANCH or a release's target_commitish, are branches
        ("0129abcdef012345643456789abcdef012345678", "main", "refs/heads/main", "behind", False, True),
        ("0129abcdef012345643456789abcdef012345678", "release/v1", "refs/heads/release/v1", "behind", False, True),
        # GitHub resolves this short name to a pull request ref, but as a branch it doesn't exist
        (
            "0129abcdef012345643456789abcdef012345678",
            "pull/123/head",
            "refs/heads/pull/123/head",
            github.NotFoundError(MagicMock(status_code=404)),
            False,
            False,
        ),
        # Commit not reachable from the ref, e.g. it comes from a fork
        ("0129abcdef012345643456789abcdef012345678", "refs/heads/main", "refs/heads/main", "diverged", False, False),
        ("0129abcdef012345643456789abcdef012345678", "refs/heads/main", "refs/heads/main", "ahead", False, False),
        # Unknown ref or commit
        (
            "0129abcdef012345643456789abcdef012345678",
            "refs/heads/does-not-exist",
            "refs/heads/does-not-exist",
            github.NotFoundError(MagicMock(status_code=404)),
            False,
            False,
        ),
        # No usable ref: we can't tell, so we don't trust the commit
        ("0129abcdef012345643456789abcdef012345678", None, None, None, False, False),
        ("0129abcdef012345643456789abcdef012345678", "", None, None, False, False),
        ("0129abcdef012345643456789abcdef012345678", "0129abcdef012345643456789abcdef012345678", None, None, False, False),
        ("0129abcdef012345643456789abcdef012345678", "0129abcd", None, None, False, False),
        ("0129abcdef012345643456789abcdef012345678", "some-fork-owner:main", None, None, False, False),
        ("0129abcdef012345643456789abcdef012345678", "main..other", None, None, False, False),
        # Only branches and tags count: pull request refs exist for unmerged pull requests, including from forks
        ("0129abcdef012345643456789abcdef012345678", "refs/pull/123/head", None, None, False, False),
        ("0129abcdef012345643456789abcdef012345678", "refs/pull/123/merge", None, None, False, False),
        ("0129abcdef012345643456789abcdef012345678", "refs/notes/commits", None, None, False, False),
        ("0129abcdef012345643456789abcdef012345678", "refs/heads/", None, None, False, False),
        ("0129abcdef012345643456789abcdef012345678", "refs/tags", None, None, False, False),
        # Tags are looked up in the repository itself, no comparison needed
        ("v1.0.0", None, None, None, False, True),
        ("v1.0.0", "refs/heads/main", None, None, False, True),
        ("non-existing-tag", "refs/heads/main", None, None, True, None),
    ),
)
@pytest.mark.asyncio
async def test_has_commit_landed_on_repository(context, github_repository, commitish, ref, base, compare, raises, expected):
    repository = await github_repository._get_repository()
    if isinstance(compare, Exception):
        repository.compare_commits.side_effect = compare
    else:
        repository.compare_commits.return_value = SimpleNamespace(status=compare)

    if raises:
        with pytest.raises(ValueError):
            await github_repository.has_commit_landed_on_repository(context, commitish, ref)
    else:
        assert await github_repository.has_commit_landed_on_repository(context, commitish, ref) == expected

    if base is None:
        repository.compare_commits.assert_not_called()
    else:
        repository.compare_commits.assert_called_once_with(base, commitish)


@pytest.mark.parametrize(
    "ref, expected",
    (
        # Not a ref
        (None, None),
        ("", None),
        (123, None),
        # Fully qualified branches and tags are used as-is
        ("refs/heads/main", "refs/heads/main"),
        ("refs/heads/release/v1", "refs/heads/release/v1"),
        ("refs/tags/v1.0.0", "refs/tags/v1.0.0"),
        ("refs/tags/releases/v1.0.0", "refs/tags/releases/v1.0.0"),
        # GitHub looks up fully qualified refs strictly, so this is a branch named "pull/123/head"
        ("refs/heads/pull/123/head", "refs/heads/pull/123/head"),
        # A branch or tag namespace without a name
        ("refs/heads/", None),
        ("refs/tags/", None),
        ("refs/heads", None),
        ("refs/tags", None),
        ("refs/", None),
        ("refs//heads/main", None),
        # Refs that aren't branches or tags
        ("refs/pull/123/head", None),
        ("refs/pull/123/merge", None),
        ("refs/notes/commits", None),
        ("refs/remotes/origin/main", None),
        ("refs/changes/12/345/6", None),
        # Bare names are qualified as branches, so GitHub doesn't resolve them loosely
        ("main", "refs/heads/main"),
        ("release/v1", "refs/heads/release/v1"),
        ("pull/123/head", "refs/heads/pull/123/head"),
        ("heads/main", "refs/heads/heads/main"),
        ("tags/v1.0.0", "refs/heads/tags/v1.0.0"),
        ("refs", "refs/heads/refs"),
        # Commit hashes, which a commit is trivially reachable from
        ("0129abcdef012345643456789abcdef012345678", None),
        ("0129abc", None),
        # Too short to be an abbreviated hash, or not lowercase hex: a branch name
        ("012abc", "refs/heads/012abc"),
        ("0129ABC", "refs/heads/0129ABC"),
        # Qualified, it's a branch, which GitHub looks up strictly
        ("refs/heads/0129abcdef012345643456789abcdef012345678", "refs/heads/0129abcdef012345643456789abcdef012345678"),
        # Refs from other repositories of the network, like forks
        ("some-fork-owner:main", None),
        ("some-fork-owner:refs/heads/main", None),
        ("refs/heads/main:other", None),
        # Ranges
        ("main..other", None),
        ("main...other", None),
        ("refs/heads/main..refs/heads/other", None),
    ),
)
def test_qualify_ref(ref, expected):
    assert github._qualify_ref(ref) == expected


@pytest.mark.asyncio
async def test_has_commit_landed_on_repository_private(vpn_context, github_repository):
    """For private repos we don't actually query against github."""
    commitish = "06789abcdf0123ef01123456789abcde45234569"
    repository = await github_repository._get_repository()

    assert await github_repository.has_commit_landed_on_repository(vpn_context, commitish, "refs/heads/main")
    repository.compare_commits.assert_not_called()


@pytest.mark.asyncio
async def test_has_commit_landed_on_repository_cache(context, github_repository):
    repository = await github_repository._get_repository()
    repository.compare_commits.return_value = SimpleNamespace(status="behind")

    await asyncio.gather(
        *[github_repository.has_commit_landed_on_repository(context, "0129abcdef012345643456789abcdef012345678", "refs/heads/main") for _ in range(4)]
    )
    # Even though all calls were fired at once, just a single call was made
    assert repository.compare_commits.call_count == 1

    await github_repository.has_commit_landed_on_repository(context, "456789abcdef0123456780129abcdef012345643", "refs/heads/main")
    # New commit means new request
    assert repository.compare_commits.call_count == 2

    await github_repository.has_commit_landed_on_repository(context, "456789abcdef0123456780129abcdef012345643", "refs/heads/beta")
    # New ref means new request
    assert repository.compare_commits.call_count == 3

    different_context = copy(context)
    different_context.task = {"taskGroupId": "someOtherTaskId"}
    await github_repository.has_commit_landed_on_repository(different_context, "456789abcdef0123456780129abcdef012345643", "refs/heads/beta")
    # The answer doesn't depend on the context
    assert repository.compare_commits.call_count == 3

    other_github_repository = github.GitHubRepository(github_repository._context, "some-other-user", "some-repo")
    await other_github_repository.has_commit_landed_on_repository(context, "456789abcdef0123456780129abcdef012345643", "refs/heads/beta")
    # New repository means new request
    assert repository.compare_commits.call_count == 4


@pytest.mark.asyncio
async def test_has_commit_landed_on_repository_cache_error(context, github_repository):
    """Errors aren't cached."""
    repository = await github_repository._get_repository()
    repository.compare_commits.side_effect = [github.GitHubException("boom")] * 5 + [SimpleNamespace(status="behind")]

    with patch("scriptworker.utils.asyncio.sleep", AsyncMock()):
        with pytest.raises(github.GitHubException):
            await github_repository.has_commit_landed_on_repository(context, "0129abcdef012345643456789abcdef012345678", "refs/heads/main")
        assert await github_repository.has_commit_landed_on_repository(context, "0129abcdef012345643456789abcdef012345678", "refs/heads/main")


@pytest.mark.parametrize(
    "url, expected",
    (
        ("https://github.com/", True),
        ("https://github.com/some-user", True),
        ("https://github.com/some-user/some-repo", True),
        ("https://github.com/some-user/some-repo/raw/somerevision/.taskcluster.yml", True),
        ("https://hg.mozilla.org", False),
        (None, False),
        ("ssh://hg.mozilla.org/some-repo", False),
        ("ssh://github.com/some-user", True),
        ("ssh://github.com/some-user/some-repo.git", True),
    ),
)
def test_is_github_url(url, expected):
    assert github.is_github_url(url) == expected


@pytest.mark.parametrize(
    "repo_url, expected_user, expected_repo_name, raises",
    (
        ("https://github.com/mozilla-mobile/reference-browser", "mozilla-mobile", "reference-browser", False),
        ("https://github.com/mozilla-mobile/reference-browser.git", "mozilla-mobile", "reference-browser", False),
        ("https://github.com/mozilla-releng/staging-reference-browser", "mozilla-releng", "staging-reference-browser", False),
        (
            "https://github.com/mozilla-releng/staging-reference-browser/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml",
            "mozilla-releng",
            "staging-reference-browser",
            False,
        ),
        ("https://github.com/mozilla-firefox/firefox", "mozilla-firefox", "firefox", False),
        ("https://github.com/mozilla-firefox", None, None, True),
        ("https://hg.mozilla.org/mozilla-central", None, None, True),
    ),
)
def test_extract_github_repo_owner_and_name(repo_url, expected_user, expected_repo_name, raises):
    if raises:
        with pytest.raises(ValueError):
            github.extract_github_repo_owner_and_name(repo_url)
    else:
        assert github.extract_github_repo_owner_and_name(repo_url) == (expected_user, expected_repo_name)


@pytest.mark.parametrize(
    "repo_url, expected, raises",
    (
        ("https://github.com/mozilla-mobile/reference-browser", "mozilla-mobile/reference-browser", False),
        ("https://github.com/mozilla-mobile/reference-browser.git", "mozilla-mobile/reference-browser", False),
        ("https://github.com/mozilla-releng/staging-reference-browser", "mozilla-releng/staging-reference-browser", False),
        (
            "https://github.com/mozilla-releng/staging-reference-browser/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml",
            "mozilla-releng/staging-reference-browser",
            False,
        ),
        ("https://hg.mozilla.org/mozilla-central", None, True),
    ),
)
def test_extract_github_repo_full_name(repo_url, expected, raises):
    if raises:
        with pytest.raises(ValueError):
            github.extract_github_repo_full_name(repo_url)
    else:
        assert github.extract_github_repo_full_name(repo_url) == expected


@pytest.mark.parametrize(
    "repo_url, expected, raises",
    (
        ("https://github.com/mozilla-mobile/reference-browser", "git@github.com:mozilla-mobile/reference-browser.git", False),
        ("https://github.com/mozilla-mobile/reference-browser.git", "git@github.com:mozilla-mobile/reference-browser.git", False),
        ("https://github.com/mozilla-releng/staging-reference-browser", "git@github.com:mozilla-releng/staging-reference-browser.git", False),
        (
            "https://github.com/mozilla-releng/staging-reference-browser/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml",
            "git@github.com:mozilla-releng/staging-reference-browser.git",
            False,
        ),
        ("https://hg.mozilla.org/mozilla-central", None, True),
    ),
)
def test_extract_github_repo_ssh_url(repo_url, expected, raises):
    if raises:
        with pytest.raises(ValueError):
            github.extract_github_repo_ssh_url(repo_url)
    else:
        assert github.extract_github_repo_ssh_url(repo_url) == expected


@pytest.mark.parametrize(
    "repo_url, expected_repo, expected_revision, raises",
    (
        (
            "https://github.com/mozilla-releng/staging-reference-browser/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml",
            "https://github.com/mozilla-releng/staging-reference-browser",
            "0123456789abcdef0123456789abcdef01234567",
            False,
        ),
        (
            "https://github.com/mozilla-releng/staging-reference-browser.git/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml",
            "https://github.com/mozilla-releng/staging-reference-browser",
            "0123456789abcdef0123456789abcdef01234567",
            False,
        ),
        (
            # The repo name ("firefox") also appears inside the owner
            # ("mozilla-firefox"); the repo url must not be truncated there.
            "https://github.com/mozilla-firefox/firefox/blob/61a4f8008eea8552b81923a1e0143e7c3a831c35/taskcluster/kinds/signing",
            "https://github.com/mozilla-firefox/firefox",
            "61a4f8008eea8552b81923a1e0143e7c3a831c35",
            False,
        ),
        ("https://github.com/mozilla-firefox", None, None, True),
        ("https://github.com/mozilla-mobile/reference-browser", None, None, True),
        ("https://github.com/mozilla-mobile/reference-browser.git", None, None, True),
        ("https://github.com/mozilla-releng/staging-reference-browser", None, None, True),
        ("https://hg.mozilla.org/mozilla-central", None, None, True),
    ),
)
def test_extract_github_repo_and_revision_from_source_url(repo_url, expected_repo, expected_revision, raises):
    if raises:
        with pytest.raises(ValueError):
            github.extract_github_repo_and_revision_from_source_url(repo_url)
    else:
        assert github.extract_github_repo_and_revision_from_source_url(repo_url) == (expected_repo, expected_revision)


@pytest.mark.parametrize(
    "config_repo_owner, repo_owner, raises, expected",
    (
        ("mozilla-mobile", "mozilla-mobile", False, True),
        ("mozilla-mobile", "JohanLorenzo", False, False),
        ("mozilla-mobile", "", False, False),
        ("", "", True, None),
        ("", "mozilla-mobile", True, None),
    ),
)
def test_is_github_repo_owner_the_official_one(context, config_repo_owner, repo_owner, raises, expected):
    context.config = {"official_github_repos_owner": config_repo_owner}

    if raises:
        with pytest.raises(ConfigError):
            github.is_github_repo_owner_the_official_one(context, repo_owner)
    else:
        assert github.is_github_repo_owner_the_official_one(context, repo_owner) == expected
