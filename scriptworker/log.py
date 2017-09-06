#!/usr/bin/env python
"""Scriptworker logging.

Attributes:
    log (logging.Logger): the log object for this module.

"""
import logging
import logging.handlers
import os

from contextlib import contextmanager

from scriptworker.utils import makedirs, to_unicode

log = logging.getLogger(__name__)


def update_logging_config(context, log_name=None, file_name='worker.log'):
    """Update python logging settings from config.

    By default, this sets the ``scriptworker`` log settings, but this will
    change if some other package calls this function or specifies the ``log_name``.

    * Use formatting from config settings.
    * Log to screen if ``verbose``
    * Add a rotating logfile from config settings.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        log_name (str, optional): the name of the Logger to modify.
            If None, use the top level module ('scriptworker').
            Defaults to None.

    """
    log_name = log_name or __name__.split('.')[0]
    top_level_logger = logging.getLogger(log_name)

    datefmt = context.config['log_datefmt']
    fmt = context.config['log_fmt']
    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)

    if context.config.get("verbose"):
        top_level_logger.setLevel(logging.DEBUG)
        if len(top_level_logger.handlers) == 0:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            top_level_logger.addHandler(handler)
    else:
        top_level_logger.setLevel(logging.INFO)

    # Rotating log file
    makedirs(context.config['log_dir'])
    path = os.path.join(context.config['log_dir'], file_name)
    if context.config["watch_log_file"]:
        # If we rotate the log file via logrotate.d, let's watch the file
        # so we can automatically close/reopen on move.
        handler = logging.handlers.WatchedFileHandler(path)
    else:
        # Avoid using WatchedFileHandler during scriptworker unittests
        handler = logging.FileHandler(path)
    handler.setFormatter(formatter)
    top_level_logger.addHandler(handler)
    top_level_logger.addHandler(logging.NullHandler())


async def pipe_to_log(pipe, filehandles=(), level=logging.INFO):
    """Log from a subprocess PIPE.

    Args:
        pipe (filehandle): subprocess process STDOUT or STDERR
        filehandles (list of filehandles, optional): the filehandle(s) to write
            to.  If empty, don't write to a separate file.  Defaults to ().
        level (int, optional): the level to log to.  Defaults to ``logging.INFO``.

    """
    while True:
        line = await pipe.readline()
        if line:
            line = to_unicode(line)
            log.log(level, line.rstrip())
            for filehandle in filehandles:
                print(line, file=filehandle, end="")
        else:
            break


def get_log_filename(context):
    """Get the task log/error file paths.

    Args:
        context (scriptworker.context.Context): the scriptworker context.

    Returns:
        string: log file path

    """
    # XXX Even though our logs aren't live, Treeherder looks for live_backing.log to show errors in failures summary
    return os.path.join(context.config['task_log_dir'], 'live_backing.log')


@contextmanager
def get_log_filehandle(context):
    """Open the log and error filehandles.

    Args:
        context (scriptworker.context.Context): the scriptworker context.

    Yields:
        log filehandle

    """
    log_file_name = get_log_filename(context)
    makedirs(context.config['task_log_dir'])
    with open(log_file_name, "w", encoding="utf-8") as filehandle:
        yield filehandle


@contextmanager
def contextual_log_handler(context, path, log_obj=None, level=logging.DEBUG,
                           formatter=None):
    """Add a short-lived log with a contextmanager for cleanup.

    Args:
        context (scriptworker.context.Context): the scriptworker context
        path (str): the path to the log file to create
        log_obj (logging.Logger): the log object to modify.  If None, use
            ``scriptworker.log.log``.  Defaults to None.
        level (int, optional): the logging level.  Defaults to logging.DEBUG.
        formatter (logging.Formatter, optional): the logging formatter. If None,
            defaults to ``logging.Formatter(fmt=fmt)``. Default is None.

    Yields:
        None: but cleans up the handler afterwards.

    """
    log_obj = log_obj or log
    formatter = formatter or logging.Formatter(
        fmt=context.config['log_fmt'],
        datefmt=context.config['log_datefmt'],
    )
    parent_path = os.path.dirname(path)
    makedirs(parent_path)
    contextual_handler = logging.FileHandler(path, encoding='utf-8')
    contextual_handler.setLevel(level)
    contextual_handler.setFormatter(formatter)
    log_obj.addHandler(contextual_handler)
    yield
    contextual_handler.close()
    log_obj.removeHandler(contextual_handler)
