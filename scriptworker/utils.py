#!/usr/bin/env python
"""Generic utils for scriptworker

Attributes:
    log (logging.Logger): the log object for the module
"""
import aiohttp
import arrow
import asyncio
import functools
import hashlib
import json
import logging
import os
import shutil
from taskcluster.utils import calculateSleepTime
from taskcluster.client import createTemporaryCredentials
from scriptworker.exceptions import DownloadError, ScriptWorkerRetryException, ScriptWorkerException

log = logging.getLogger(__name__)


async def request(context, url, timeout=60, method='get', good=(200, ),
                  retry=tuple(range(500, 512)), return_type='text', **kwargs):
    """Async aiohttp request wrapper.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        url (str): the url to request
        timeout (int, optional): timeout after this many seconds. Default is 60.
        method (str, optional): The request method to use.  Default is 'get'.
        good (list, optional): the set of good status codes.  Default is (200, )
        retry (list, optional): the set of status codes that result in a retry.
            Default is tuple(range(500, 512)).
        return_type (str, optional): The type of value to return.  Takes
            'json' or 'text'; other values will return the response object.
            Default is text.
        **kwargs: the kwargs to send to the aiohttp request function.

    Returns:
        object: the response text() if return_type is 'text'; the response
            json() if return_type is 'json'; the aiohttp request response
            object otherwise.

    Raises:
        ScriptWorkerRetryException: if the status code is in the retry list.
        ScriptWorkerException: if the status code is not in the retry list or
            good list.
    """
    session = context.session
    with aiohttp.Timeout(timeout):
        log.debug("{} {}".format(method.upper(), url))
        async with session.request(method, url, **kwargs) as resp:
            log.debug("Status {}".format(resp.status))
            message = "Bad status {}".format(resp.status)
            if resp.status in retry:
                raise ScriptWorkerRetryException(message)
            if resp.status not in good:
                raise ScriptWorkerException(message)
            if return_type == 'text':
                return await resp.text()
            elif return_type == 'json':
                return await resp.json()
            else:
                return resp


async def retry_request(*args, retry_exceptions=(ScriptWorkerRetryException, ),
                        **kwargs):
    """Retry the `request` function

    Args:
        *args: the args to send to request() through retry_async().
        retry_exceptions (list, optional): the exceptions to retry on.
            Defaults to (ScriptWorkerRetryException, ).
        **kwargs: the kwargs to send to request() through retry_async().

    Returns:
        object: the value from request().
    """
    return await retry_async(request, retry_exceptions=retry_exceptions,
                             args=args, kwargs=kwargs)


def datestring_to_timestamp(datestring):
    """ Create a timetamp from a taskcluster datestring

    Args:
        datestring (str): the datestring to convert. isoformat, like
            "2016-04-16T03:46:24.958Z"

    Returns:
        int: the corresponding timestamp.
    """
    return arrow.get(datestring).timestamp


def to_unicode(line):
    """Avoid ``|b'line'|`` type messages in the logs

    Args:
        line (str): The bytecode or unicode string.

    Returns:
        str: the unicode-decoded string, if `line` was a bytecode string.
            Otherwise return `line` unmodified.
    """
    try:
        line = line.decode('utf-8')
    except (UnicodeDecodeError, AttributeError):
        pass
    return line


def makedirs(path):
    """mkdir -p

    Args:
        path (str): the path to mkdir -p

    Raises:
        ScriptWorkerException: if path exists already and the realpath is not a dir.
    """
    if path:
        if not os.path.exists(path):
            log.debug("makedirs({})".format(path))
            os.makedirs(path)
        else:
            realpath = os.path.realpath(path)
            if not os.path.isdir(realpath):
                raise ScriptWorkerException(
                    "makedirs: {} already exists and is not a directory!".format(path)
                )


def rm(path):
    """rm -rf

    Make sure `path` doesn't exist after this call.  If it's a dir,
    shutil.rmtree(); if it's a file, os.remove(); if it doesn't exist,
    ignore.

    Args:
        path (str): the path to nuke.
    """
    if path and os.path.exists(path):
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)


def cleanup(context):
    """Clean up the work_dir and artifact_dir between task runs, then recreate.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
    """
    for name in 'work_dir', 'artifact_dir', 'task_log_dir':
        path = context.config[name]
        if os.path.exists(path):
            log.debug("rm({})".format(path))
            rm(path)
        makedirs(path)


async def retry_async(func, attempts=5, sleeptime_callback=calculateSleepTime,
                      retry_exceptions=(Exception, ), args=(), kwargs=None):
    """Retry `func`, where `func` is an awaitable.

    Args:
        func (function): an awaitable function.
        attempts (int, optional): the number of attempts to make.  Default is 5.
        sleeptime_callback (function, optional): the function to use to determine
            how long to sleep after each attempt.  Defaults to `calculateSleepTime`.
        retry_exceptions (list, optional): the exceptions to retry on.  Defaults
            to (Exception, )
        args (list, optional): the args to pass to `function`.  Defaults to ()
        kwargs (dict, optional): the kwargs to pass to `function`.  Defaults to
            {}.

    Returns:
        object: the value from a successful `function` call

    Raises:
        Exception: the exception from a failed `function` call, either outside
            of the retry_exceptions, or one of those if we pass the max
            `attempts`.
    """
    kwargs = kwargs or {}
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
    """Request temp TC creds with our permanent creds.

    Args:
        client_id (str): the taskcluster client_id to use
        access_token (str): the taskcluster access_token to use
        start (str, optional): the datetime string when the credentials will
            start to be valid.  Defaults to 10 minutes ago, for clock skew.
        expires (str, optional): the datetime string when the credentials will
            expire.  Defaults to 31 days after 10 minutes ago.
        scopes (list, optional): The list of scopes to request for the temp
            creds.  Defaults to ['assume:project:taskcluster:worker-test-scopes', ]
        name (str, optional): the name to associate with the creds.

    Returns:
        dict: the temporary taskcluster credentials.
    """
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


async def raise_future_exceptions(tasks):
    """Given a list of futures, await them, then raise their exceptions if any.

    Without something like this, a bare::

        await asyncio.wait(tasks)

    will swallow exceptions.

    Args:
        tasks (list): the list of futures to await and check for exceptions.

    Raises:
        Exception: any exceptions in task.exception()
    """
    if not tasks:
        return
    await asyncio.wait(tasks)
    for task in tasks:
        exc = task.exception()
        if exc is not None:
            raise exc


def filepaths_in_dir(path):
    """Find all files in a directory, and return the relative paths to those files.

    Args:
        path (str): the directory path to walk

    Returns:
        list: the list of relative paths to all files inside of `path` or its
            subdirectories.
    """
    filepaths = []
    for root, directories, filenames in os.walk(path):
        for filename in filenames:
            filepath = os.path.join(root, filename)
            filepath = filepath.replace(path, '').lstrip('/')
            filepaths.append(filepath)
    return filepaths


def get_hash(path, hash_alg="sha256"):
    """Get the hash of the file at `path`.

    I'd love to make this async, but evidently file i/o is always ready

    Args:
        path (str): the path to the file to hash.
        hash_alg (str, optional): the algorithm to use.  Defaults to 'sha256'.

    Returns:
        str: the hexdigest of the hash.
    """
    h = hashlib.new(hash_alg)
    with open(path, "rb") as f:
        for chunk in iter(functools.partial(f.read, 4096), b''):
            h.update(chunk)
    return h.hexdigest()


def format_json(data):
    """Format json as a sorted string (indents of 2)

    Args:
        data (dict): the json to format.

    Returns:
        str: the formatted json.
    """
    return json.dumps(data, indent=2, sort_keys=True)


async def download_file(context, url, abs_filename, session=None, chunk_size=128):
    """Download a file, async.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        url (str): the url to download
        abs_filename (str): the path to download to
        session (aiohttp.ClientSession, optional): the session to use.  If
            None, use context.session.  Defaults to None.
        chunk_size (int, optional): the chunk size to read from the response
            at a time.  Default is 128.
    """
    session = session or context.session
    log.info("Downloading %s", url)
    parent_dir = os.path.dirname(abs_filename)
    async with session.get(url) as resp:
        if resp.status != 200:
            raise DownloadError("{} status {} is not 200!".format(url, resp.status))
        makedirs(parent_dir)
        with open(abs_filename, 'wb') as fd:
            while True:
                chunk = await resp.content.read(chunk_size)
                if not chunk:
                    break
                fd.write(chunk)
    log.info("Done")
