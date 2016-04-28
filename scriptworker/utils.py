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
from taskcluster.utils import calculateSleepTime
from scriptworker.exceptions import ScriptWorkerException, ScriptWorkerRetryException

log = logging.getLogger(__name__)


async def request(context, url, timeout=60, method='get', good=(200, ),
                  retry=tuple(range(500, 512))):
    """Async aiohttp request wrapper
    """
    session = context.session
    with aiohttp.Timeout(timeout):
        log.debug("{} {}".format(method.upper(), url))
        async with session.request(method, url) as resp:
            log.debug("Status {}".format(resp.status))
            message = "Bad status {}".format(resp.status)
            if resp.status in retry:
                raise ScriptWorkerRetryException(
                    message,
                    status=resp.status
                )
            if resp.status not in good:
                raise ScriptWorkerException(message)
            return await resp.text()


async def retry_request(*args, retry_exceptions=(ScriptWorkerRetryException, ),
                        **kwargs):
    return await retry_async(request, retry_exceptions=retry_exceptions,
                             args=args, kwargs=kwargs)


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


def cleanup(context):
    """Clean up the work_dir and artifact_dir between task runs.
    """
    for name in 'work_dir', 'artifact_dir':
        path = context.config[name]
        if os.path.exists(path):
            log.debug("rmtree({})".format(path))
            shutil.rmtree(path)
        makedirs(path)


async def retry_async(func, attempts=5, sleeptime_callback=None,
                      retry_exceptions=(Exception, ), args=(), kwargs=None):
    kwargs = kwargs or {}
    sleeptime_callback = sleeptime_callback or calculateSleepTime
    attempt = 1
    while True:
        try:
            return await func(*args, **kwargs)
        except retry_exceptions:
            if attempt > attempts:
                raise
            await asyncio.sleep(sleeptime_callback(attempt))
            attempt += 1
