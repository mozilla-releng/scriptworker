#!/usr/bin/env python
"""scriptworker exceptions."""

from scriptworker.constants import STATUSES


class ScriptWorkerException(Exception):
    """The base exception in scriptworker.

    When raised inside of the run_loop loop, set the taskcluster task
    status to at least ``self.exit_code``.

    Attributes:
        exit_code (int): this is set to 5 (internal-error).

    """

    exit_code = STATUSES['internal-error']


class ScriptWorkerGPGException(ScriptWorkerException):
    """Scriptworker GPG error.

    Attributes:
        exit_code (int): this is set to 5 (internal-error).

    """

    exit_code = STATUSES['internal-error']


class ScriptWorkerRetryException(ScriptWorkerException):
    """Scriptworker retry error.

    Attributes:
        exit_code (int): this is set to 4 (resource-unavailable)

    """

    exit_code = STATUSES['resource-unavailable']


class ScriptWorkerTaskException(ScriptWorkerException):
    """Scriptworker task error.

    To use::

        import sys
        try:
            ...
        except ScriptWorkerTaskException as exc:
            log.exception("log message")
            sys.exit(exc.exit_code)

    Attributes:
        exit_code (int): this is 1 by default (failure)

    """

    def __init__(self, *args, exit_code=1, **kwargs):
        """Initialize ScriptWorkerTaskException.

        Args:
            *args: These are passed on via super().
            exit_code (int, optional): The exit_code we should exit with when
                this exception is raised.  Defaults to 1 (failure).
            **kwargs: These are passed on via super().

        """
        self.exit_code = exit_code
        super(ScriptWorkerTaskException, self).__init__(*args, **kwargs)


class TaskVerificationError(ScriptWorkerTaskException):
    """Verification error on a Taskcluster task.

    Use it when your script fails to validate any input from the task definition

    """

    def __init__(self, msg):
        """Initialize TaskVerificationError.

        Args:
            msg (string): the error message

        """
        super().__init__(msg, exit_code=STATUSES['malformed-payload'])


class DownloadError(ScriptWorkerTaskException):
    """Failure in ``scriptworker.utils.download_file``.

    Attributes:
        exit_code (int): this is set to 4 (resource-unavailable).

    """

    def __init__(self, msg):
        """Initialize DownloadError.

        Args:
            msg (string): the error message

        """
        super(DownloadError, self).__init__(
            msg, exit_code=STATUSES['resource-unavailable']
        )


class CoTError(ScriptWorkerTaskException, KeyError):
    """Failure in Chain of Trust verification.

    Attributes:
        exit_code (int): this is set to 3 (malformed-payload).

    """

    def __init__(self, msg):
        """Initialize CoTError.

        Args:
            msg (string): the error message

        """
        super(CoTError, self).__init__(
            msg, exit_code=STATUSES['malformed-payload']
        )


class ConfigError(ScriptWorkerException):
    """Invalid configuration provided to scriptworker.

    Attributes:
        exit_code (int): this is set to 5 (internal-error).

    """
