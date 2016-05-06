#!/usr/bin/env python
"""Exceptions
"""


class ScriptWorkerException(Exception):
    pass


class ScriptWorkerRetryException(ScriptWorkerException):
    pass


class ScriptWorkerTaskException(ScriptWorkerException):
    """To use:

    import sys
    import traceback
    try:
        ...
    except ScriptWorkerTaskException as exc:
        traceback.print_exc()
        sys.exit(exc.exit_code)
    """
    def __init__(self, *args, exit_code=1, **kwargs):
        self.exit_code = exit_code
        super(ScriptWorkerTaskException, self).__init__(*args, **kwargs)
