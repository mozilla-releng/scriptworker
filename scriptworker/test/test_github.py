import pytest

from unittest.mock import MagicMock

from scriptworker import github
from scriptworker.context import Context


@pytest.yield_fixture(scope='function')
def github_repository(mocker):
    github_repository_mock = MagicMock()
    github_instance_mock = MagicMock()
    github_instance_mock.repository = github_repository_mock
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
    github_repository.definition
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
