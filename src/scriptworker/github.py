"""GitHub helper functions."""

import logging
import re

from aiomemoizettl import memoize_ttl
from github3 import GitHub
from github3.exceptions import GitHubException

from scriptworker.exceptions import ConfigError
from scriptworker.utils import get_parts_of_url_path, get_single_item_from_sequence, retry_async_decorator, retry_request, retry_sync

_GIT_FULL_HASH_PATTERN = re.compile(r"^[0-9a-f]{40}$")
# The github3 library already retries requests. It gives a round of waiting of usually 15 seconds.
# A delay factor of 7.5s means the second round of waiting will occur ~15s after the first one,
# the third one ~30s and so on.
_GITHUB_LIBRARY_SLEEP_TIME_KWARGS = {"delay_factor": 7.5}


log = logging.getLogger(__name__)


class GitHubRepository:
    """Wrapper around GitHub API. Used to access public data."""

    def __init__(self, owner, repo_name, token=""):
        """Build the GitHub API URL which points to the definition of the repository.

        Args:
            owner (str): the owner's GitHub username
            repo_name (str): the name of the repository
            token (str): the GitHub API token

        Returns:
            dict: a representation of the repo definition

        """
        github = retry_sync(GitHub, kwargs={"token": token}, sleeptime_kwargs=_GITHUB_LIBRARY_SLEEP_TIME_KWARGS)
        self._github_repository = retry_sync(github.repository, args=(owner, repo_name), sleeptime_kwargs=_GITHUB_LIBRARY_SLEEP_TIME_KWARGS)

    @property
    def definition(self):
        """Fetch the definition of the repository, exposed by the GitHub API.

        Returns:
            dict: a representation of the repo definition

        """
        return self._github_repository.as_dict()

    @retry_async_decorator(retry_exceptions=GitHubException)
    async def get_commit(self, commit_hash):
        """Fetch the definition of the commit, exposed by the GitHub API.

        Args:
            commit_hash (str): the hash of the git commit

        Returns:
            dict: a representation of the commit

        """
        return self._github_repository.commit(commit_hash).as_dict()

    @retry_async_decorator(retry_exceptions=GitHubException)
    async def get_pull_request(self, pull_request_number):
        """Fetch the definition of the pull request, exposed by the GitHub API.

        Args:
            pull_request_number (int): the ID of the pull request

        Returns:
            dict: a representation of the pull request

        """
        return self._github_repository.pull_request(pull_request_number).as_dict()

    @retry_async_decorator(retry_exceptions=GitHubException)
    async def get_release(self, tag_name):
        """Fetch the definition of the release matching the tag name.

        Args:
            tag_name (str): the tag linked to the release

        Returns:
            dict: a representation of the tag

        """
        return self._github_repository.release_from_tag(tag_name).as_dict()

    @retry_async_decorator(retry_exceptions=GitHubException)
    async def get_tag_hash(self, tag_name):
        """Fetch the commit hash that was tagged with ``tag_name``.

        Args:
            tag_name (str): the name of the tag

        Returns:
            str: the commit hash linked by the tag

        """
        tag_object = get_single_item_from_sequence(
            sequence=self._github_repository.tags(),
            condition=lambda tag: tag.name == tag_name,
            no_item_error_message='No tag "{}" exist'.format(tag_name),
            too_many_item_error_message='Too many tags "{}" found'.format(tag_name),
        )

        return tag_object.commit.sha

    async def has_commit_landed_on_repository(self, context, revision):
        """Tell if a commit was landed on the repository or if it just comes from a pull request.

        Args:
            context (scriptworker.context.Context): the scriptworker context.
            revision (str): the commit hash or the tag name.

        Returns:
            bool: True if the commit is present in one of the branches of the main repository

        """
        if any(vcs_rule.get("require_secret") for vcs_rule in context.config["trusted_vcs_rules"]):
            # This check uses unofficial API on github, which we can't easily
            # check for private repos, assume its true in the private case.
            log.info("has_commit_landed_on_repository() not implemented for private" "repositories, assume True")
            return True

        # Revision may be a tag name. `branch_commits` doesn't work on tags
        if not _is_git_full_hash(revision):
            revision = await self.get_tag_hash(tag_name=revision)

        html_text = await _fetch_github_branch_commits_data(context, self._github_repository.html_url, revision)

        # https://github.com/{repo_owner}/{repo_name}/branch_commits/{revision} just returns some \n
        # when the commit hasn't landed on the origin repo. Otherwise, some HTML data is returned - it
        # represents the branches on which the given revision is present.
        return html_text != ""


# TODO Use memoize_ttl() as decorator once https://github.com/michalc/aiomemoizettl/issues/2 is done
async def _fetch_github_branch_commits_data_helper(context, repo_html_url, revision):
    url = "/".join((repo_html_url.rstrip("/"), "branch_commits", revision))
    log.info('Cache does not exist for URL "{}" (in this context), fetching it...'.format(url))
    html_text = await retry_request(context, url)
    return html_text.strip()


# XXX memoize_ttl() uses all function parameters to create a key that stores its cache.
# This means new contexts cannot use the memoized value, even though they're calling the same
# repo and revision. jlorenzo tried to take the context out of the memoize_ttl() call, but
# whenever the cache is invalidated, request() doesn't work anymore because the session carried
# by the context has been long closed.
# Therefore, the defined TTL has 2 purposes:
#  a. it memoizes calls for the time of a single cot_verify() run
#  b. it clears the cache automatically, so we don't have to manually invalidate it.
_BRANCH_COMMITS_CACHE_TTL_IN_SECONDS = 10 * 60  # 10 minutes
_fetch_github_branch_commits_data = memoize_ttl(_fetch_github_branch_commits_data_helper, get_ttl=lambda _: _BRANCH_COMMITS_CACHE_TTL_IN_SECONDS)


def is_github_url(url):
    """Tell if a given URL matches a Github one.

    Args:
        url (str): The URL to test. It can be None.

    Returns:
        bool: False if the URL is not a string or if it doesn't match a Github URL

    """
    if isinstance(url, str):
        return url.startswith(("https://github.com/", "ssh://github.com/"))
    else:
        return False


def extract_github_repo_owner_and_name(url):
    """Given an URL, return the repo name and who owns it.

    Args:
        url (str): The URL to the GitHub repository

    Raises:
        ValueError: on url that aren't from github

    Returns:
        str, str: the owner of the repository, the repository name

    """
    _check_github_url_is_supported(url)

    parts = get_parts_of_url_path(url)
    repo_owner = parts[0]
    repo_name = parts[1]

    return repo_owner, _strip_trailing_dot_git(repo_name)


def extract_github_repo_full_name(url):
    """Given an URL, return the full name of it.

    The full name is ``RepoOwner/RepoName``.

    Args:
        url (str): The URL to the GitHub repository

    Raises:
        ValueError: on url that aren't from github

    Returns:
        str: the full name.

    """
    return "/".join(extract_github_repo_owner_and_name(url))


def extract_github_repo_ssh_url(url):
    """Given an URL, return the ssh url.

    Args:
        url (str): The URL to the GitHub repository

    Raises:
        ValueError: on url that aren't from github

    Returns:
        str: the ssh url

    """
    return "git@github.com:{}.git".format(extract_github_repo_full_name(url))


def extract_github_repo_and_revision_from_source_url(url):
    """Given an URL, return the repo name and who owns it.

    Args:
        url (str): The URL to the GitHub repository

    Raises:
        ValueError: on url that aren't from github or when the revision cannot be extracted

    Returns:
        str, str: the owner of the repository, the repository name

    """
    _check_github_url_is_supported(url)

    parts = get_parts_of_url_path(url)
    repo_name = parts[1]
    try:
        revision = parts[3]
    except IndexError:
        raise ValueError("Revision cannot be extracted from url: {}".format(url))

    end_index = url.index(repo_name) + len(repo_name)
    repo_url = url[:end_index]

    return _strip_trailing_dot_git(repo_url), revision


def _strip_trailing_dot_git(url):
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url


def is_github_repo_owner_the_official_one(context, repo_owner):
    """Given a repo_owner, check if it matches the one configured to be the official one.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        repo_owner (str): the repo_owner to verify

    Raises:
        scriptworker.exceptions.ConfigError: when no official owner was defined

    Returns:
        bool: True when ``repo_owner`` matches the one configured to be the official one

    """
    official_repo_owner = context.config["official_github_repos_owner"]
    if not official_repo_owner:
        raise ConfigError(
            "This worker does not have a defined owner for official GitHub repositories. " 'Given "official_github_repos_owner": {}'.format(official_repo_owner)
        )

    return official_repo_owner == repo_owner


def _is_git_full_hash(revision):
    return _GIT_FULL_HASH_PATTERN.match(revision) is not None


def _check_github_url_is_supported(url):
    if not is_github_url(url):
        raise ValueError('"{}" is not a supported GitHub URL!'.format(url))
