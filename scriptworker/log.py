#!/usr/bin/env python
"""scriptworker logging
"""
import logging
import os

from contextlib import contextmanager

from scriptworker.utils import makedirs, to_unicode

log = logging.getLogger(__name__)


def update_logging_config(context):
    top_level_name = __name__.split('.')[0]
    top_level_logger = logging.getLogger(top_level_name)
    # TODO put these in config?
    datefmt = '%H:%M:%S'
    fmt = '%(asctime)s %(levelname)8s - %(message)s'

    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)
    if context.config.get("verbose"):
        top_level_logger.setLevel(logging.DEBUG)
        if len(top_level_logger.handlers) == 0:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            top_level_logger.addHandler(handler)
    top_level_logger.addHandler(logging.NullHandler())


async def log_errors(reader, log_fh, error_fh):
    while True:
        line = await reader.readline()
        if not line:
            break
        line = to_unicode(line)
        log.debug('ERROR {}'.format(line.rstrip()))
        print('ERROR {}'.format(line), file=log_fh, end="")
        print(line, file=error_fh, end="")


async def read_stdout(stdout, log_fh):
    while True:
        line = await stdout.readline()
        if line:
            log.debug(to_unicode(line.rstrip()))
            print(to_unicode(line), file=log_fh, end="")
        else:
            break


def get_log_filenames(context):
    log_file = os.path.join(context.config['log_dir'], 'task_output.log')
    error_file = os.path.join(context.config['log_dir'], 'task_error.log')
    return log_file, error_file


@contextmanager
def get_log_fhs(context):
    log_file, error_file = get_log_filenames(context)
    makedirs(context.config['log_dir'])
    with open(log_file, "w") as log_fh:
        with open(error_file, "w") as error_fh:
            yield (log_fh, error_fh)
