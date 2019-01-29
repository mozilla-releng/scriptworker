"""GitHub helper functions."""

from github3 import GitHub


class GitHubRepository():
    """Wrapper around GitHub API. Used to access public data."""

    def __init__(self, owner, repo_name, token=''):
        """Build the GitHub API URL which points to the definition of the repository.

        Args:
            owner (str): the owner's GitHub username
            repo_name (str): the name of the repository
            token (str): the GitHub API token

        Returns:
            dict: a representation of the repo definition

        """
        self._github_repository = GitHub(token=token).repository(owner, repo_name)

    @property
    def definition(self):
        """Fetch the definition of the repository, exposed by the GitHub API.

        Returns:
            dict: a representation of the repo definition

        """
        return self._github_repository.as_dict()

    def get_commit(self, commit_hash):
        """Fetch the definition of the commit, exposed by the GitHub API.

        Args:
            commit_hash (str): the hash of the git commit

        Returns:
            dict: a representation of the commit

        """
        return self._github_repository.commit(commit_hash).as_dict()

    def get_pull_request(self, pull_request_number):
        """Fetch the definition of the pull request, exposed by the GitHub API.

        Args:
            pull_request_number (int): the ID of the pull request

        Returns:
            dict: a representation of the pull request

        """
        return self._github_repository.pull_request(pull_request_number).as_dict()

    def get_release(self, tag_name):
        """Fetch the definition of the release matching the tag name.

        Args:
            tag_name (str): the tag linked to the release

        Returns:
            dict: a representation of the tag

        """
        return self._github_repository.release_from_tag(tag_name).as_dict()
