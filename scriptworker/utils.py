#!/usr/bin/env python
"""Utils for scriptworker
"""
import aiohttp
import asyncio
import datetime
import logging
import os
import shutil
import time

log = logging.getLogger(__name__)


async def request(context, url, timeout=60, method='get', good=(200, )):
    """Async aiohttp request wrapper
    """
    session = context.session
    with aiohttp.Timeout(timeout):
        log.debug("{} {}".format(method.upper(), url))
        async with session.request(method, url) as resp:
            log.debug("Status {}".format(resp.status))
            assert resp.status in good  # TODO log/retry
            return await resp.text()


def datestring_to_timestamp(datestring):
    """ Create a timetamp from a taskcluster datestring
    datestring: a string in the form of "2016-04-16T03:46:24.958Z"
    """
    datestring = datestring.split('.')[0]
    return time.mktime(
        datetime.datetime.strptime(datestring, "%Y-%m-%dT%H:%M:%S").timetuple()
    )


def to_unicode(line):
    """Avoid |b'line'| type messages in the logs
    """
    try:
        line = line.decode('utf-8')
    except (UnicodeDecodeError, AttributeError):
        pass
    return line


def makedirs(path):
    """mkdir -p
    """
    if not os.path.exists(path):
        log.debug("makedirs({})".format(path))
        os.makedirs(path)


def close_asyncio_loop():
    """This runs atexit to avoid asyncio loop error messages.

    https://bugs.python.org/msg240248
    """
    loop = None
    try:
        loop = asyncio.get_event_loop()
    except AttributeError:
        pass
    if loop is not None:
        log.debug("Closing event loop with the following tasks still scheduled:")
        log.debug(asyncio.Task.all_tasks(loop=loop))
        loop.close()


def cleanup(context):
    """Clean up the work_dir and artifact_dir between task runs.
    """
    for name in 'work_dir', 'artifact_dir':
        path = context.config[name]
        if os.path.exists(path):
            log.debug("rmtree({})".format(path))
            shutil.rmtree(path)
        makedirs(path)
