"""GitHub helper functions."""

import asyncio
import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from github3 import GitHub
from github3.exceptions import GitHubException, NotFoundError
from taskcluster.aio import Auth
from taskcluster.exceptions import TaskclusterFailure

from scriptworker.exceptions import ConfigError
from scriptworker.utils import get_parts_of_url_path, get_single_item_from_sequence, retry_async_decorator, retry_sync

_GIT_FULL_HASH_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_GIT_HASH_LIKE_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")
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
                Defaults to the repository's default branch. Results for full
                commit hashes are cached on disk in `work_dir`.

        Returns:
            str: the decoded contents of the file

        """
        # Files at a full commit hash are immutable, so they're safe to cache on disk.
        cache_path = None
        if ref and _is_git_full_hash(ref):
            cache_key = hashlib.sha1(f"{self._owner}/{self._repo_name}@{ref}:{path}".encode("utf-8")).hexdigest()
            cache_path = Path(self._context.config["work_dir"]) / ".cache" / "github_files" / cache_key
            if cache_path.exists():
                return cache_path.read_text(encoding="utf-8")

        repository = await self._get_repository()
        contents = repository.file_contents(path, ref=ref)
        decoded = contents.decoded.decode("utf-8")

        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(decoded, encoding="utf-8")
        return decoded

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

    async def has_commit_landed_on_repository(self, context, revision, ref):
        """Tell if a commit was landed on the repository or if it just comes from a fork or a pull request.

        GitHub serves commits from forks through the upstream repository, so the
        commit merely existing isn't enough: it must be reachable from a ref of
        this repository.

        Args:
            context (scriptworker.context.Context): the scriptworker context.
            revision (str): the commit hash or the tag name.
            ref (str): the branch or tag of this repository that ``revision`` is
                expected to be on, e.g. ``refs/heads/main``. Ignored if ``revision``
                is a tag name.

        Returns:
            bool: True if the commit is reachable from ``ref`` in this repository

        """
        if any(vcs_rule.get("require_secret") for vcs_rule in context.config["trusted_vcs_rules"]):
            # XXX This check isn't implemented for private repositories, assume it's true.
            log.info("has_commit_landed_on_repository() not implemented for private repositories, assume True")
            return True

        if not _is_git_full_hash(revision):
            # The tag is looked up in this repository, so the commit it points to
            # is reachable from one of its refs. This raises if there's no such tag.
            await self.get_tag_hash(tag_name=revision)
            return True

        qualified_ref = _qualify_ref(ref)
        if qualified_ref is None:
            log.warning(f"Cannot tell if {revision} landed on {self._owner}/{self._repo_name}: no usable ref (got {ref!r})")
            return False

        status = await _fetch_github_compare_status(self, qualified_ref, revision)
        # "behind" and "identical" mean that `revision` is an ancestor of, or equal to, `ref`.
        # "ahead" and "diverged" mean that `revision` isn't reachable from `ref`.
        landed = status in ("behind", "identical")
        if not landed:
            log.warning(f"{revision} is not on {ref} of {self._owner}/{self._repo_name} (comparison status: {status})")
        return landed

    @retry_async_decorator(retry_exceptions=GitHubException)
    async def get_compare_status(self, base, head):
        """Compare two commitishes of the repository.

        Args:
            base (str): the base ref or commit
            head (str): the head ref or commit

        Returns:
            str: the status of ``head`` relative to ``base``: one of "ahead", "behind",
                "diverged" or "identical", or None if either side doesn't exist

        """
        repository = await self._get_repository()
        try:
            return repository.compare_commits(base, head).status
        except NotFoundError:
            return None


_COMPARE_CACHE_TTL_IN_SECONDS = 10 * 60  # 10 minutes
_COMPARE_CACHE = {}


async def _fetch_github_compare_status(github_repository, base, head):
    cache_key = (github_repository._owner, github_repository._repo_name, base, head)

    if cache_key in _COMPARE_CACHE:
        return await _COMPARE_CACHE[cache_key]

    future = asyncio.get_running_loop().create_future()
    _COMPARE_CACHE[cache_key] = future

    try:
        result = await github_repository.get_compare_status(base, head)
        future.set_result(result)
        asyncio.get_running_loop().call_later(
            _COMPARE_CACHE_TTL_IN_SECONDS,
            _COMPARE_CACHE.pop,
            cache_key,
            None,
        )
    except BaseException as e:
        _COMPARE_CACHE.pop(cache_key, None)
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
    if len(parts) < 2:
        raise ValueError(f"Could not extract repo owner and name from GitHub URL: {url}")
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

    parsed = urlparse(url)
    parts = unquote(parsed.path).lstrip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"Could not extract repo owner and name from GitHub URL: {url}")
    repo_owner = parts[0]
    repo_name = _strip_trailing_dot_git(parts[1])
    try:
        revision = parts[3]
    except IndexError:
        raise ValueError(f"Revision cannot be extracted from url: {url}")

    repo_url = f"{parsed.scheme}://{parsed.netloc}/{repo_owner}/{repo_name}"

    return repo_url, revision


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


def _qualify_ref(ref):
    """Turn ``ref`` into a branch or tag ref that can prove a commit is in the repository.

    Only branches and tags count: GitHub also exposes refs like ``refs/pull/123/head``
    for pull requests, including ones from forks. GitHub resolves short names
    loosely (``pull/123/head`` matches that pull request ref), so bare names are
    qualified as branches, e.g. ``main`` becomes ``refs/heads/main``.

    A commit is trivially reachable from itself, so (possibly abbreviated) hashes
    prove nothing. ``owner:ref`` would make GitHub look up the ref in another
    repository of the network, like a fork.

    Args:
        ref (str): the ref, e.g. ``refs/heads/main``, ``refs/tags/v1.0.0`` or ``main``

    Returns:
        str: the fully qualified ref, or None if ``ref`` can't be used.

    """
    if not ref or not isinstance(ref, str) or ":" in ref or ".." in ref:
        return None
    if ref.startswith("refs/"):
        prefix, _, name = ref.partition("/")[2].partition("/")
        if prefix in ("heads", "tags") and name:
            return ref
        return None
    if _GIT_HASH_LIKE_PATTERN.match(ref):
        return None
    return f"refs/heads/{ref}"


def _check_github_url_is_supported(url):
    if not is_github_url(url):
        raise ValueError('"{}" is not a supported GitHub URL!'.format(url))
