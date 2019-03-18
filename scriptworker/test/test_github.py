from types import SimpleNamespace

import pytest

from unittest.mock import MagicMock, patch

from scriptworker import github
from scriptworker.context import Context
from scriptworker.exceptions import ConfigError


@pytest.yield_fixture(scope='function')
def context():
    yield Context()


@pytest.yield_fixture(scope='function')
def github_repository(mocker):
    github_repository_mock = MagicMock()
    github_repository_mock.html_url = 'https://github.com/some-user/some-repo/'
    github_repository_mock.tags.return_value = [
        SimpleNamespace(name='v1.0.0', commit=SimpleNamespace(sha='hashforv100')),
    ]
    github_instance_mock = MagicMock()
    github_instance_mock.repository.return_value = github_repository_mock
    mocker.patch.object(github, 'GitHub', return_value=github_instance_mock)
    yield github.GitHubRepository('some-user', 'some-repo')


@pytest.mark.parametrize('args, expected_class_kwargs', ((
    ('some-user', 'some-repo', 'some-token'), {'token':'some-token'}
), (
    ('some-user', 'some-repo'), {'token':''}
)))
def test_constructor(mocker, args, expected_class_kwargs):
    github_instance_mock = MagicMock()
    github_class_mock = mocker.patch.object(github, 'GitHub', return_value=github_instance_mock)

    github.GitHubRepository(*args)

    github_class_mock.assert_called_once_with(**expected_class_kwargs)
    github_instance_mock.repository.assert_called_once_with('some-user', 'some-repo')


def test_get_definition(github_repository):
    github_repository._github_repository.as_dict.return_value = {'foo': 'bar'}
    assert github_repository.definition == {'foo': 'bar'}
    github_repository._github_repository.as_dict.assert_called_once_with()


def test_get_commit(github_repository):
    github_repository.get_commit('somehash')
    github_repository._github_repository.commit.assert_called_once_with('somehash')


def test_get_pull_request(github_repository):
    github_repository.get_pull_request(1)
    github_repository._github_repository.pull_request.assert_called_once_with(1)


def test_get_release(github_repository):
    github_repository.get_release('some-tag')
    github_repository._github_repository.release_from_tag.assert_called_once_with('some-tag')


@pytest.mark.parametrize('tags, raises, expected', ((
    [SimpleNamespace(
        name='some-tag',
        commit=SimpleNamespace(sha='somecommit'),
    )],
    False,
    'somecommit',
), (
    [SimpleNamespace(
        name='another-tag',
        commit=SimpleNamespace(sha='anothercommit'),
    ), SimpleNamespace(
        name='some-tag',
        commit=SimpleNamespace(sha='somecommit'),
    )],
    False,
    'somecommit',
), (
    [SimpleNamespace(
        name='another-tag',
        commit=SimpleNamespace(sha='anothercommit'),
    )],
    True,
    None
), (
    [],
    True,
    None,
)))
def test_get_tag_hash(github_repository, tags, raises, expected):
    github_repository._github_repository.tags.return_value = tags

    if raises:
        with pytest.raises(ValueError):
            github_repository.get_tag_hash('some-tag')
    else:
        assert github_repository.get_tag_hash('some-tag') == expected



@pytest.mark.parametrize('commitish, expected_url, html_text, raises, expected', ((
    '0123456789abcdef0123456789abcdef01234567',
    'https://github.com/some-user/some-repo/branch_commits/0123456789abcdef0123456789abcdef01234567',
    '\r\n\r\n',
    False,
    False,
), (
    '0123456789abcdef0123456789abcdef01234567',
    'https://github.com/some-user/some-repo/branch_commits/0123456789abcdef0123456789abcdef01234567',
    '\n',
    False,
    False,
), (
    '0123456789abcdef0123456789abcdef01234567',
    'https://github.com/some-user/some-repo/branch_commits/0123456789abcdef0123456789abcdef01234567',
    '',
    False,
    False,
), (
    '0123456789abcdef0123456789abcdef01234567',
    'https://github.com/some-user/some-repo/branch_commits/0123456789abcdef0123456789abcdef01234567',
    '''


    <svg class="octicon octicon-git-branch" viewBox="0 0 10 16" version="1.1" width="10" height="16" aria-hidden="true"><path fill-rule="evenodd" d="M10 5c0-1.11-.89-2-2-2a1.993 1.993 0 0 0-1 3.72v.3c-.02.52-.23.98-.63 1.38-.4.4-.86.61-1.38.63-.83.02-1.48.16-2 .45V4.72a1.993 1.993 0 0 0-1-3.72C.88 1 0 1.89 0 3a2 2 0 0 0 1 1.72v6.56c-.59.35-1 .99-1 1.72 0 1.11.89 2 2 2 1.11 0 2-.89 2-2 0-.53-.2-1-.53-1.36.09-.06.48-.41.59-.47.25-.11.56-.17.94-.17 1.05-.05 1.95-.45 2.75-1.25S8.95 7.77 9 6.73h-.02C9.59 6.37 10 5.73 10 5zM2 1.8c.66 0 1.2.55 1.2 1.2 0 .65-.55 1.2-1.2 1.2C1.35 4.2.8 3.65.8 3c0-.65.55-1.2 1.2-1.2zm0 12.41c-.66 0-1.2-.55-1.2-1.2 0-.65.55-1.2 1.2-1.2.65 0 1.2.55 1.2 1.2 0 .65-.55 1.2-1.2 1.2zm6-8c-.66 0-1.2-.55-1.2-1.2 0-.65.55-1.2 1.2-1.2.65 0 1.2.55 1.2 1.2 0 .65-.55 1.2-1.2 1.2z"/></svg>
    <ul class="branches-list">
        <li class="branch"><a href="/some-user/some-repo">master</a></li>
          <li class="pull-request">(<a title="Merged Pull Request: [glean] Create a way for glean test API functions to await async IO operations" href="/some-user/some-repo/pull/1234">#1234</a>)</li>
    </ul>
    ''',
    False,
    True,
), (
    'v1.0.0',
    'https://github.com/some-user/some-repo/branch_commits/hashforv100',
    '''


    <svg class="octicon octicon-git-branch" viewBox="0 0 10 16" version="1.1" width="10" height="16" aria-hidden="true"><path fill-rule="evenodd" d="M10 5c0-1.11-.89-2-2-2a1.993 1.993 0 0 0-1 3.72v.3c-.02.52-.23.98-.63 1.38-.4.4-.86.61-1.38.63-.83.02-1.48.16-2 .45V4.72a1.993 1.993 0 0 0-1-3.72C.88 1 0 1.89 0 3a2 2 0 0 0 1 1.72v6.56c-.59.35-1 .99-1 1.72 0 1.11.89 2 2 2 1.11 0 2-.89 2-2 0-.53-.2-1-.53-1.36.09-.06.48-.41.59-.47.25-.11.56-.17.94-.17 1.05-.05 1.95-.45 2.75-1.25S8.95 7.77 9 6.73h-.02C9.59 6.37 10 5.73 10 5zM2 1.8c.66 0 1.2.55 1.2 1.2 0 .65-.55 1.2-1.2 1.2C1.35 4.2.8 3.65.8 3c0-.65.55-1.2 1.2-1.2zm0 12.41c-.66 0-1.2-.55-1.2-1.2 0-.65.55-1.2 1.2-1.2.65 0 1.2.55 1.2 1.2 0 .65-.55 1.2-1.2 1.2zm6-8c-.66 0-1.2-.55-1.2-1.2 0-.65.55-1.2 1.2-1.2.65 0 1.2.55 1.2 1.2 0 .65-.55 1.2-1.2 1.2z"/></svg>
    <ul class="branches-list">
        <li class="branch"><a href="/some-user/some-repo">master</a></li>
          <li class="pull-request">(<a title="Merged Pull Request: [glean] Create a way for glean test API functions to await async IO operations" href="/some-user/some-repo/pull/1234">#1234</a>)</li>
    </ul>
    ''',
    False,
    True,
), (
    'non-existing-tag',
    None,
    '',
    True,
    None,
)))
@pytest.mark.asyncio
async def test_has_commit_landed_on_repository(context, github_repository, commitish, expected_url, html_text, raises, expected):
    async def retry_request(_, url):
        assert url == expected_url
        return html_text

    with patch('scriptworker.github.retry_request', retry_request):
        if raises:
            with pytest.raises(ValueError):
                await github_repository.has_commit_landed_on_repository(context, commitish)
        else:
            assert await github_repository.has_commit_landed_on_repository(context, commitish) == expected


@pytest.mark.parametrize('url, expected', ((
    'https://github.com/', True
), (
    'https://github.com/some-user', True
), (
    'https://github.com/some-user/some-repo', True
), (
    'https://github.com/some-user/some-repo/raw/somerevision/.taskcluster.yml', True
), (
    'https://hg.mozilla.org', False
), (
    None, False
)))
def test_is_github_url(url, expected):
    assert github.is_github_url(url) == expected


@pytest.mark.parametrize('repo_url, expected_user, expected_repo_name, raises', ((
    'https://github.com/mozilla-mobile/android-components',
    'mozilla-mobile', 'android-components', False
), (
    'https://github.com/mozilla-mobile/android-components.git',
    'mozilla-mobile', 'android-components', False
), (
    'https://github.com/JohanLorenzo/android-components',
    'JohanLorenzo', 'android-components', False
), (
    'https://github.com/JohanLorenzo/android-components/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml',
    'JohanLorenzo', 'android-components', False
), (
    'https://hg.mozilla.org/mozilla-central',
    None, None, True
)))
def test_extract_github_repo_owner_and_name(repo_url, expected_user, expected_repo_name, raises):
    if raises:
        with pytest.raises(ValueError):
            github.extract_github_repo_owner_and_name(repo_url)
    else:
        assert github.extract_github_repo_owner_and_name(repo_url) == (expected_user, expected_repo_name)


@pytest.mark.parametrize('repo_url, expected, raises', ((
    'https://github.com/mozilla-mobile/android-components',
    'mozilla-mobile/android-components', False
), (
    'https://github.com/mozilla-mobile/android-components.git',
    'mozilla-mobile/android-components', False
), (
    'https://github.com/JohanLorenzo/android-components',
    'JohanLorenzo/android-components', False
), (
    'https://github.com/JohanLorenzo/android-components/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml',
    'JohanLorenzo/android-components', False
), (
    'https://hg.mozilla.org/mozilla-central',
    None, True
)))
def test_extract_github_repo_full_name(repo_url, expected, raises):
    if raises:
        with pytest.raises(ValueError):
            github.extract_github_repo_full_name(repo_url)
    else:
        assert github.extract_github_repo_full_name(repo_url) == expected


@pytest.mark.parametrize('repo_url, expected_user, expected_repo_name, raises', ((
    'https://github.com/JohanLorenzo/android-components/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml',
    'https://github.com/JohanLorenzo/android-components', '0123456789abcdef0123456789abcdef01234567', False,
), (
    'https://github.com/JohanLorenzo/android-components.git/raw/0123456789abcdef0123456789abcdef01234567/.taskcluster.yml',
    'https://github.com/JohanLorenzo/android-components', '0123456789abcdef0123456789abcdef01234567', False,
), (
    'https://github.com/mozilla-mobile/android-components',
    None, None, True,
), (
    'https://github.com/mozilla-mobile/android-components.git',
    None, None, True,
), (
    'https://github.com/JohanLorenzo/android-components',
    None, None, True,
), (
    'https://hg.mozilla.org/mozilla-central',
    None, None, True,
)))
def test_extract_github_repo_and_revision_from_source_url(repo_url, expected_user, expected_repo_name, raises):
    if raises:
        with pytest.raises(ValueError):
            github.extract_github_repo_and_revision_from_source_url(repo_url)
    else:
        assert github.extract_github_repo_and_revision_from_source_url(repo_url) == (expected_user, expected_repo_name)


@pytest.mark.parametrize('config_repo_owner, repo_owner, raises, expected', (
    ('mozilla-mobile', 'mozilla-mobile', False, True,),
    ('mozilla-mobile', 'JohanLorenzo', False, False,),
    ('mozilla-mobile', '', False, False,),
    ('', '', True, None,),
    ('', 'mozilla-mobile', True, None,),
))
def test_is_github_repo_owner_the_official_one(context, config_repo_owner, repo_owner, raises, expected):
    context.config = {'official_github_repos_owner': config_repo_owner}

    if raises:
        with pytest.raises(ConfigError):
            github.is_github_repo_owner_the_official_one(context, repo_owner)
    else:
        assert github.is_github_repo_owner_the_official_one(context, repo_owner) == expected
