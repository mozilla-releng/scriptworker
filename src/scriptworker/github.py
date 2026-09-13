"""GitHub helper functions."""

import asyncio
import logging
import re

from github3 import GitHub
from github3.exceptions import GitHubException
from taskcluster.aio import Auth
from taskcluster.exceptions import TaskclusterFailure

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

    GITHUB_PERMISSIONS = {"contents": "read", "metadata": "read", "pull_requests": "read"}

    def __init__(self, context, owner, repo_name):
        """Store the repository coordinates. The github3 repository object is built lazily.

        Args:
            context (scriptworker.context.Context): the scriptworker context
            owner (str): the owner of the repository
            repo_name (str): the name of the repository

        """
        self._context = context
        self._owner = owner
        self._repo_name = repo_name
        self._repository_cache = None
        self._repository_lock = asyncio.Lock()

    async def _get_repository(self):
        """Build and cache the github3 repository object.

        Returns:
            github3.repos.repo.Repository: the github3 repository object

        """
        async with self._repository_lock:
            if self._repository_cache is None:
                token = await self._get_token(self._context, self._owner, self._repo_name)
                github = retry_sync(GitHub, kwargs={"token": token}, sleeptime_kwargs=_GITHUB_LIBRARY_SLEEP_TIME_KWARGS)
                self._repository_cache = retry_sync(github.repository, args=(self._owner, self._repo_name), sleeptime_kwargs=_GITHUB_LIBRARY_SLEEP_TIME_KWARGS)

        return self._repository_cache

    async def _get_token(self, context, owner, repo_name):
        """Get a repository scoped GitHub token from Taskcluster's auth service.

        Falls back to ``context.config["github_oauth_token"]`` if the auth service call
        fails, e.g. because of missing scopes.

        Args:
            context (scriptworker.context.Context): the scriptworker context
            owner (str): the owner of the repository
            repo_name (str): the name of the repository

        Returns:
            str: the scoped GitHub token, or the fallback token

        """
        if not context.credentials:
            return context.config.get("github_oauth_token", "")

        try:
            auth = Auth(options={"rootUrl": context.config["taskcluster_root_url"], "credentials": context.credentials})
            response = await auth.githubRepoToken(
                context.config["github_app_name"], owner, payload={"repositories": [repo_name], "permissions": self.GITHUB_PERMISSIONS}
            )
            return response["token"]
        except TaskclusterFailure as e:
            # TODO When opening a PR from a fork, we're guaranteed to hit this
            # fallback as the task won't have auth service scopes for the repo
            # fork. We'll need to improve this before we can stop depending on
            # `github_oauth_token`.
            log.warning(f"Could not obtain Github token from Taskcluster for {owner}/{repo_name}, falling back to `github_oauth_token`: {e}")
            return context.config.get("github_oauth_token", "")

    async def get_definition(self):
        """Fetch the definition of the repository, exposed by the GitHub API.

        Returns:
            dict: a representation of the repo definition

        """
        repository = await self._get_repository()
        return repository.as_dict()

    @retry_async_decorator(retry_exceptions=GitHubException)
    async def get_file_contents(self, path, ref=None):
        """Fetch the decoded contents of a file in the repository.

        Args:
            path (str): the path to the file, relative to the repository root
            ref (str, optional): the commit/branch/tag to read the file from.
                Defaults to the repository's default branch.

        Returns:
            str: the decoded contents of the file

        """
        repository = await self._get_repository()
        contents = repository.file_contents(path, ref=ref)
        return contents.decoded.decode("utf-8")

    @retry_async_decorator(retry_exceptions=GitHubException)
    async def get_commit(self, commit_hash):
        """Fetch the definition of the commit, exposed by the GitHub API.

        Args:
            commit_hash (str): the hash of the git commit

        Returns:
            dict: a representation of the commit

        """
        repository = await self._get_repository()
        return repository.commit(commit_hash).as_dict()

    @retry_async_decorator(retry_exceptions=GitHubException)
    async def get_pull_request(self, pull_request_number):
        """Fetch the definition of the pull request, exposed by the GitHub API.

        Args:
            pull_request_number (int): the ID of the pull request

        Returns:
            dict: a representation of the pull request

        """
        repository = await self._get_repository()
        return repository.pull_request(pull_request_number).as_dict()

    @retry_async_decorator(retry_exceptions=GitHubException)
    async def get_release(self, tag_name):
        """Fetch the definition of the release matching the tag name.

        Args:
            tag_name (str): the tag linked to the release

        Returns:
            dict: a representation of the tag

        """
        repository = await self._get_repository()
        return repository.release_from_tag(tag_name).as_dict()

    @retry_async_decorator(retry_exceptions=GitHubException)
    async def get_tag_hash(self, tag_name):
        """Fetch the commit hash that was tagged with ``tag_name``.

        Args:
            tag_name (str): the name of the tag

        Returns:
            str: the commit hash linked by the tag

        """
        repository = await self._get_repository()
        tag_object = get_single_item_from_sequence(
            sequence=repository.tags(),
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
            log.info("has_commit_landed_on_repository() not implemented for private repositories, assume True")
            return True

        # Revision may be a tag name. `branch_commits` doesn't work on tags
        if not _is_git_full_hash(revision):
            revision = await self.get_tag_hash(tag_name=revision)

        repository = await self._get_repository()
        html_text = await _fetch_github_branch_commits_data(context, repository.html_url, revision)

        # https://github.com/{repo_owner}/{repo_name}/branch_commits/{revision} just returns some \n
        # when the commit hasn't landed on the origin repo. Otherwise, some HTML data is returned - it
        # represents the branches on which the given revision is present.
        return html_text != ""


_BRANCH_COMMITS_CACHE_TTL_IN_SECONDS = 10 * 60  # 10 minutes
_BRANCH_COMMITS_CACHE = {}


async def _fetch_github_branch_commits_data(context, repo_html_url, revision):
    # Include context identity because different contexts carry
    # different HTTP sessions that may be closed independently.
    cache_key = (id(context), repo_html_url, revision)

    if cache_key in _BRANCH_COMMITS_CACHE:
        return await _BRANCH_COMMITS_CACHE[cache_key]

    future = asyncio.get_running_loop().create_future()
    _BRANCH_COMMITS_CACHE[cache_key] = future

    try:
        url = "/".join((repo_html_url.rstrip("/"), "branch_commits", revision))
        html_text = await retry_request(context, url)
        result = html_text.strip()
        future.set_result(result)
        asyncio.get_running_loop().call_later(
            _BRANCH_COMMITS_CACHE_TTL_IN_SECONDS,
            _BRANCH_COMMITS_CACHE.pop,
            cache_key,
            None,
        )
    except BaseException as e:
        _BRANCH_COMMITS_CACHE.pop(cache_key, None)
        future.set_exception(e)
        raise

    return result


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
            'This worker does not have a defined owner for official GitHub repositories. Given "official_github_repos_owner": {}'.format(official_repo_owner)
        )

    elif isinstance(official_repo_owner, tuple):
        return repo_owner in official_repo_owner
    return official_repo_owner == repo_owner


def _is_git_full_hash(revision):
    return _GIT_FULL_HASH_PATTERN.match(revision) is not None


def _check_github_url_is_supported(url):
    if not is_github_url(url):
        raise ValueError('"{}" is not a supported GitHub URL!'.format(url))
