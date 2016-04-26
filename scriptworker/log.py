#!/usr/bin/env python
"""scriptworker logging
"""
import logging
import logging.handlers
import os

from contextlib import contextmanager

from scriptworker.utils import makedirs, to_unicode

log = logging.getLogger(__name__)


def update_logging_config(context, log_name=None):
    """Update python logging settings from config.

    By default, this sets the `scriptworker` log settings, but this will
    change if some other package calls this function or specifies the `log_name`.

    * Use formatting from config settings.
    * Log to screen if `verbose`
    * Add a rotating logfile from config settings.
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
    path = os.path.join(context.config['log_dir'], 'worker.log')
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=context.config['log_max_bytes'],
        backupCount=context.config['log_num_backups'],
    )
    handler.setFormatter(formatter)
    top_level_logger.addHandler(handler)
    top_level_logger.addHandler(logging.NullHandler())


async def log_errors(reader, log_fh, error_fh):
    """Log STDERR from the task subprocess to both the log and error
    filehandles.
    """
    while True:
        line = await reader.readline()
        if not line:
            break
        line = to_unicode(line)
        log.debug('ERROR {}'.format(line.rstrip()))
        print('ERROR {}'.format(line), file=log_fh, end="")
        print(line, file=error_fh, end="")


async def read_stdout(stdout, log_fh):
    """Log STDOUT from the task subprocess to the log filehandle.
    """
    while True:
        line = await stdout.readline()
        if line:
            log.debug(to_unicode(line.rstrip()))
            print(to_unicode(line), file=log_fh, end="")
        else:
            break


def get_log_filenames(context):
    """Helper function to get the task log/error file paths.
    """
    log_file = os.path.join(context.config['log_dir'], 'task_output.log')
    error_file = os.path.join(context.config['log_dir'], 'task_error.log')
    return log_file, error_file


@contextmanager
def get_log_fhs(context):
    """Helper contextmanager function to open the log and error
    filehandles.
    """
    log_file, error_file = get_log_filenames(context)
    makedirs(context.config['log_dir'])
    with open(log_file, "w") as log_fh:
        with open(error_file, "w") as error_fh:
            yield (log_fh, error_fh)
