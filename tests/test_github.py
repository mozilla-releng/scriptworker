from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from scriptworker import github
from scriptworker.exceptions import ConfigError

# No longer need caching/memoization mocks since we're using the official GitHub API


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
def github_repository(mocker):
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
    yield github.GitHubRepository("some-user", "some-repo")


@pytest.mark.parametrize(
    "args, expected_class_kwargs", ((("some-user", "some-repo", "some-token"), {"token": "some-token"}), (("some-user", "some-repo"), {"token": ""}))
)
def test_constructor(mocker, args, expected_class_kwargs):
    github_instance_mock = MagicMock()
    github_instance_mock.repository.__name__ = "github_instance_repository_mock"
    github_class_mock = mocker.patch.object(github, "GitHub", return_value=github_instance_mock)
    github_class_mock.__name__ = github_class_mock.name

    github.GitHubRepository(*args)

    github_class_mock.assert_called_once_with(**expected_class_kwargs)
    github_instance_mock.repository.assert_called_once_with("some-user", "some-repo")


retry_count = {}


def test_constructor_uses_retry_sync(mocker):
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
    mocker.patch.object(github, "_GITHUB_LIBRARY_SLEEP_TIME_KWARGS", {"delay_factor": 0.1})
    github.GitHubRepository("some-user", "some-repo", "some-token")

    assert retry_count["fail_first"] == 2


def test_get_definition(github_repository):
    github_repository._github_repository.as_dict.return_value = {"foo": "bar"}
    assert github_repository.definition == {"foo": "bar"}
    github_repository._github_repository.as_dict.assert_called_once_with()


@pytest.mark.asyncio
async def test_get_commit(github_repository):
    await github_repository.get_commit("somehash")
    github_repository._github_repository.commit.assert_called_once_with("somehash")


@pytest.mark.asyncio
async def test_get_pull_request(github_repository):
    await github_repository.get_pull_request(1)
    github_repository._github_repository.pull_request.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_get_release(github_repository):
    await github_repository.get_release("some-tag")
    github_repository._github_repository.release_from_tag.assert_called_once_with("some-tag")


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
    github_repository._github_repository.tags.return_value = tags

    if raises:
        with pytest.raises(ValueError):
            await github_repository.get_tag_hash("some-tag")
    else:
        tag_hash = await github_repository.get_tag_hash("some-tag")
        assert tag_hash == expected


@pytest.mark.parametrize(
    "commitish, expected_url, api_response, raises, expected",
    (
        # Commit with only unmerged PRs - should return False
        (
            "0129abcdef012345643456789abcdef012345678",
            "https://api.github.com/repos/some-user/some-repo/commits/0129abcdef012345643456789abcdef012345678/pulls",
            [{"id": 123, "merged_at": None}],  # Unmerged PR
            False,
            False,
        ),
        # Commit with no associated PRs - direct commit, should return True
        (
            "0f0123456789abcdef012123456789abcde34565",
            "https://api.github.com/repos/some-user/some-repo/commits/0f0123456789abcdef012123456789abcde34565/pulls",
            [],  # No PRs = direct commit
            False,
            True,
        ),
        # Commit that doesn't exist (404) - should return False
        (
            "0123456789abcdef0123456789abcdef01234568",
            "https://api.github.com/repos/some-user/some-repo/commits/0123456789abcdef0123456789abcdef01234568/pulls",
            {"message": "Not Found"},  # 404 response
            False,
            False,
        ),
        # Commit with merged PR - should return True
        (
            "06789abcdf0123ef01123456789abcde45234569",
            "https://api.github.com/repos/some-user/some-repo/commits/06789abcdf0123ef01123456789abcde45234569/pulls",
            [{"id": 1234, "merged_at": "2021-01-01T00:00:00Z"}],  # Merged PR
            False,
            True,
        ),
        # Tag that resolves to a commit with merged PR - should return True
        (
            "v1.0.0",
            "https://api.github.com/repos/some-user/some-repo/commits/hashforv100/pulls",
            [{"id": 1234, "merged_at": "2021-01-01T00:00:00Z"}],  # Merged PR
            False,
            True,
        ),
        # Non-existing tag - should raise ValueError
        ("non-existing-tag", None, None, True, None),
    ),
)
async def test_has_commit_landed_on_repository(context, github_repository, commitish, expected_url, api_response, raises, expected):
    async def retry_request(_, url, **kwargs):
        if expected_url:
            assert url == expected_url
        return api_response

    with patch("scriptworker.github.retry_request", retry_request):
        if raises:
            with pytest.raises(ValueError):
                await github_repository.has_commit_landed_on_repository(context, commitish)
        else:
            assert await github_repository.has_commit_landed_on_repository(context, commitish) == expected


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
