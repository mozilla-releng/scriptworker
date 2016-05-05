#!/usr/bin/env python
"""Exceptions
"""


class ScriptWorkerException(Exception):
    def __init__(self, msg, **kwargs):
        super(ScriptWorkerException, self).__init__(self, msg)
        self.kwargs = kwargs


class ScriptWorkerRetryException(ScriptWorkerException):
    pass


class ScriptWorkerTaskException(ScriptWorkerException):
    pass
