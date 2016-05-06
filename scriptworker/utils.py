#!/usr/bin/env python
"""Utils for scriptworker
"""
import aiohttp
import arrow
import asyncio
import logging
import os
import shutil
from taskcluster.utils import calculateSleepTime
from taskcluster.client import createTemporaryCredentials
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
                raise ScriptWorkerRetryException(message)
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
    return arrow.get(datestring).timestamp


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
            log.debug("retry_async: Calling {}, attempt {}".format(func, attempt))
            return await func(*args, **kwargs)
        except retry_exceptions:
            attempt += 1
            if attempt > attempts:
                log.warning("retry_async: {}: too many retries!".format(func))
                raise
            log.debug("retry_async: {}: sleeping before retry".format(func))
            await asyncio.sleep(sleeptime_callback(attempt))


def create_temp_creds(client_id, access_token, start=None, expires=None,
                      scopes=None, name=None):
    now = arrow.utcnow().replace(minutes=-10)
    start = start or now.datetime
    expires = expires or now.replace(days=31).datetime
    scopes = scopes or ['assume:project:taskcluster:worker-test-scopes', ]
    creds = createTemporaryCredentials(client_id, access_token, start, expires,
                                       scopes, name=name)
    for key, value in creds.items():
        try:
            creds[key] = value.decode('utf-8')
        except (AttributeError, UnicodeDecodeError):
            pass
    return creds
