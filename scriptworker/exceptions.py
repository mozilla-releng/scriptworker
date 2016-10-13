#!/usr/bin/env python
"""scriptworker exceptions
"""


class ScriptWorkerException(Exception):
    """The base exception in scriptworker.

    When raised inside of the run_loop loop, set the taskcluster task
    status to at least `self.exit_code`.

    Attributes:
        exit_code (int): this is set to 5 (internal-error).
    """
    exit_code = 5


class ScriptWorkerGPGException(ScriptWorkerException):
    """Scriptworker GPG error.

    Attributes:
        exit_code (int): this is set to 5 (internal-error).
    """
    exit_code = 5


class ScriptWorkerRetryException(ScriptWorkerException):
    """ScriptWorkerRetryException.

    Attributes:
        exit_code (int): this is set to 4 (resource-unavailable)
    """
    exit_code = 4


class ScriptWorkerTaskException(ScriptWorkerException):
    """
    To use::

        import sys
        import traceback
        try:
            ...
        except ScriptWorkerTaskException as exc:
            traceback.print_exc()
            sys.exit(exc.exit_code)

    Args:
        exit_code (int, optional): The exit_code we should exit with when
            this exception is raised.  Defaults to 1 (failure).

    Attributes:
        exit_code (int): this is 1 by default (failure)
    """
    def __init__(self, *args, exit_code=1, **kwargs):
        self.exit_code = exit_code
        super(ScriptWorkerTaskException, self).__init__(*args, **kwargs)


class DownloadError(ScriptWorkerTaskException):
    """Failure in `scriptworker.utils.download_file`.

    Attributes:
        exit_code (int): this is set to 4 (resource-unavailable).
    """
    def __init__(self, msg):
        super(DownloadError, self).__init__(
            msg, exit_code=4
        )
