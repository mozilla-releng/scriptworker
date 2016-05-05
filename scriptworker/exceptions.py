#!/usr/bin/env python
"""Exceptions
"""


class ScriptWorkerException(Exception):
    pass


class ScriptWorkerRetryException(ScriptWorkerException):
    def __init__(self, msg, **kwargs):
        super(ScriptWorkerRetryException, self).__init__(self, msg)
        self.kwargs = kwargs


class ScriptWorkerTaskException(ScriptWorkerException):
    def __init__(self, msg, **kwargs):
        super(ScriptWorkerTaskException, self).__init__(self, msg)
        self.kwargs = kwargs
