#!/usr/bin/env python
"""Generic utils for scriptworker.

Attributes:
    log (logging.Logger): the log object for the module

"""
import aiohttp
import arrow
import asyncio
import async_timeout
from copy import deepcopy
import functools
import hashlib
import json
import logging
import os
import random
import re
import shutil
from urllib.parse import unquote, urlparse
import yaml
from taskcluster.client import createTemporaryCredentials
from scriptworker.exceptions import (
    DownloadError,
    Download404,
    ScriptWorkerException,
    ScriptWorkerRetryException,
    ScriptWorkerTaskException,
)

log = logging.getLogger(__name__)


# request {{{1
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
    loggable_url = get_loggable_url(url)
    async with async_timeout.timeout(timeout):
        log.debug("{} {}".format(method.upper(), loggable_url))
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


# retry_request {{{1
async def retry_request(*args, retry_exceptions=(asyncio.TimeoutError,
                                                 ScriptWorkerRetryException),
                        retry_async_kwargs=None, **kwargs):
    """Retry the ``request`` function.

    Args:
        *args: the args to send to request() through retry_async().
        retry_exceptions (list, optional): the exceptions to retry on.
            Defaults to (ScriptWorkerRetryException, ).
        retry_async_kwargs (dict, optional): the kwargs for retry_async.
            If None, use {}.  Defaults to None.
        **kwargs: the kwargs to send to request() through retry_async().

    Returns:
        object: the value from request().

    """
    retry_async_kwargs = retry_async_kwargs or {}
    return await retry_async(request, retry_exceptions=retry_exceptions,
                             args=args, kwargs=kwargs, **retry_async_kwargs)


# datestring_to_timestamp {{{1
def datestring_to_timestamp(datestring):
    """Create a timetamp from a taskcluster datestring.

    Args:
        datestring (str): the datestring to convert. isoformat, like
            "2016-04-16T03:46:24.958Z"

    Returns:
        int: the corresponding timestamp.

    """
    return arrow.get(datestring).timestamp


# to_unicode {{{1
def to_unicode(line):
    """Avoid ``b'line'`` type messages in the logs.

    Args:
        line (str): The bytecode or unicode string.

    Returns:
        str: the unicode-decoded string, if ``line`` was a bytecode string.
            Otherwise return ``line`` unmodified.

    """
    try:
        line = line.decode('utf-8')
    except (UnicodeDecodeError, AttributeError):
        pass
    return line


# makedirs {{{1
def makedirs(path):
    """Equivalent to mkdir -p.

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


# rm {{{1
def rm(path):
    """Equivalent to rm -rf.

    Make sure ``path`` doesn't exist after this call.  If it's a dir,
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


# cleanup {{{1
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


# calculate_sleep_time {{{1
def calculate_sleep_time(attempt, delay_factor=5.0, randomization_factor=.5, max_delay=120):
    """Calculate the sleep time between retries, in seconds.

    Based off of `taskcluster.utils.calculateSleepTime`, but with kwargs instead
    of constant `delay_factor`/`randomization_factor`/`max_delay`.  The taskcluster
    function generally slept for less than a second, which didn't always get
    past server issues.

    Args:
        attempt (int): the retry attempt number
        delay_factor (float, optional): a multiplier for the delay time.  Defaults to 5.
        randomization_factor (float, optional): a randomization multiplier for the
            delay time.  Defaults to .5.
        max_delay (float, optional): the max delay to sleep.  Defaults to 120 (seconds).

    Returns:
        float: the time to sleep, in seconds.

    """
    if attempt <= 0:
        return 0

    # We subtract one to get exponents: 1, 2, 3, 4, 5, ..
    delay = float(2 ** (attempt - 1)) * float(delay_factor)
    # Apply randomization factor.  Only increase the delay here.
    delay = delay * (randomization_factor * random.random() + 1)
    # Always limit with a maximum delay
    return min(delay, max_delay)


# retry_async {{{1
async def retry_async(func, attempts=5, sleeptime_callback=calculate_sleep_time,
                      retry_exceptions=Exception, args=(), kwargs=None,
                      sleeptime_kwargs=None):
    """Retry ``func``, where ``func`` is an awaitable.

    Args:
        func (function): an awaitable function.
        attempts (int, optional): the number of attempts to make.  Default is 5.
        sleeptime_callback (function, optional): the function to use to determine
            how long to sleep after each attempt.  Defaults to ``calculateSleepTime``.
        retry_exceptions (list or exception, optional): the exception(s) to retry on.
            Defaults to ``Exception``.
        args (list, optional): the args to pass to ``function``.  Defaults to ()
        kwargs (dict, optional): the kwargs to pass to ``function``.  Defaults to
            {}.
        sleeptime_kwargs (dict, optional): the kwargs to pass to ``sleeptime_callback``.
            If None, use {}.  Defaults to None.

    Returns:
        object: the value from a successful ``function`` call

    Raises:
        Exception: the exception from a failed ``function`` call, either outside
            of the retry_exceptions, or one of those if we pass the max
            ``attempts``.

    """
    kwargs = kwargs or {}
    attempt = 1
    while True:
        try:
            return await func(*args, **kwargs)
        except retry_exceptions:
            attempt += 1
            if attempt > attempts:
                log.warning("retry_async: {}: too many retries!".format(func.__name__))
                raise
            sleeptime_kwargs = sleeptime_kwargs or {}
            sleep_time = sleeptime_callback(attempt, **sleeptime_kwargs)
            log.debug("retry_async: {}: sleeping {} seconds before retry".format(func.__name__, sleep_time))
            await asyncio.sleep(sleep_time)


# create_temp_creds {{{1
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


# raise_future_exceptions {{{1
async def raise_future_exceptions(tasks):
    """Given a list of futures, await them, then raise their exceptions if any.

    Without something like this, a bare::

        await asyncio.wait(tasks)

    will swallow exceptions.

    Args:
        tasks (list): the list of futures to await and check for exceptions.

    Returns:
        list: the list of results from the futures.

    Raises:
        Exception: any exceptions in task.exception()

    """
    succeeded_results, _ = await _process_future_exceptions(tasks, raise_at_first_error=True)
    return succeeded_results


# get_results_and_future_exceptions {{{1
async def get_results_and_future_exceptions(tasks):
    """Given a list of futures, await them, then return results and exceptions.

    This is similar to raise_future_exceptions, except that it doesn't raise any
    exception. They are returned instead. This allows some tasks to optionally fail.
    Please consider that no exception will be raised when calling this function.
    You must verify the content of the second item of the tuple. It contains all
    exceptions raised by the futures.

    Args:
        tasks (list): the list of futures to await and check for exceptions.

    Returns:
        tuple: the list of results from the futures, then the list of exceptions.

    """
    return await _process_future_exceptions(tasks, raise_at_first_error=False)


async def _process_future_exceptions(tasks, raise_at_first_error):
    succeeded_results = []
    error_results = []

    if tasks:
        await asyncio.wait(tasks)
        for task in tasks:
            exc = task.exception()
            if exc:
                if raise_at_first_error:
                    raise exc
                else:
                    log.warning('Async task failed with error: {}'.format(exc))
                    error_results.append(exc)
            else:
                succeeded_results.append(task.result())

    return succeeded_results, error_results


# filepaths_in_dir {{{1
def filepaths_in_dir(path):
    """Find all files in a directory, and return the relative paths to those files.

    Args:
        path (str): the directory path to walk

    Returns:
        list: the list of relative paths to all files inside of ``path`` or its
            subdirectories.

    """
    filepaths = []
    for root, directories, filenames in os.walk(path):
        for filename in filenames:
            filepath = os.path.join(root, filename)
            filepath = filepath.replace(path, '').lstrip('/')
            filepaths.append(filepath)
    return filepaths


# get_hash {{{1
def get_hash(path, hash_alg="sha256"):
    """Get the hash of the file at ``path``.

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


# format_json {{{1
def format_json(data):
    """Format json as a sorted string (indents of 2).

    Args:
        data (dict): the json to format.

    Returns:
        str: the formatted json.

    """
    return json.dumps(data, indent=2, sort_keys=True)


# load_json_or_yaml {{{1
def load_json_or_yaml(string, is_path=False, file_type='json',
                      exception=ScriptWorkerTaskException,
                      message="Failed to load %(file_type)s: %(exc)s"):
    """Load json or yaml from a filehandle or string, and raise a custom exception on failure.

    Args:
        string (str): json/yaml body or a path to open
        is_path (bool, optional): if ``string`` is a path. Defaults to False.
        file_type (str, optional): either "json" or "yaml". Defaults to "json".
        exception (exception, optional): the exception to raise on failure.
            If None, don't raise an exception.  Defaults to ScriptWorkerTaskException.
        message (str, optional): the message to use for the exception.
            Defaults to "Failed to load %(file_type)s: %(exc)s"

    Returns:
        dict: the data from the string.

    Raises:
        Exception: as specified, on failure

    """
    if file_type == 'json':
        _load_fh = json.load
        _load_str = json.loads
    else:
        _load_fh = yaml.safe_load
        _load_str = yaml.safe_load

    try:
        if is_path:
            with open(string, 'r') as fh:
                contents = _load_fh(fh)
        else:
            contents = _load_str(string)
        return contents
    except (OSError, ValueError, yaml.scanner.ScannerError) as exc:
        if exception is not None:
            repl_dict = {'exc': str(exc), 'file_type': file_type}
            raise exception(message % repl_dict)


# write_to_file {{{1
def write_to_file(path, contents, file_type='text'):
    """Write ``contents`` to ``path`` with optional formatting.

    Small helper function to write ``contents`` to ``file`` with optional formatting.

    Args:
        path (str): the path to write to
        contents (str, object, or bytes): the contents to write to the file
        file_type (str, optional): the type of file. Currently accepts
            ``text`` or ``binary`` (contents are unchanged) or ``json`` (contents
            are formatted). Defaults to ``text``.

    Raises:
        ScriptWorkerException: with an unknown ``file_type``
        TypeError: if ``file_type`` is ``json`` and ``contents`` isn't JSON serializable

    """
    FILE_TYPES = ('json', 'text', 'binary')
    if file_type not in FILE_TYPES:
        raise ScriptWorkerException("Unknown file_type {} not in {}!".format(file_type, FILE_TYPES))
    if file_type == 'json':
        contents = format_json(contents)
    if file_type == 'binary':
        with open(path, 'wb') as fh:
            fh.write(contents)
    else:
        with open(path, 'w') as fh:
            print(contents, file=fh, end="")


# read_from_file {{{1
def read_from_file(path, file_type='text', exception=ScriptWorkerException):
    """Read from ``path``.

    Small helper function to read from ``file``.

    Args:
        path (str): the path to read from.
        file_type (str, optional): the type of file. Currently accepts
            ``text`` or ``binary``. Defaults to ``text``.
        exception (Exception, optional): the exception to raise
            if unable to read from the file.  Defaults to ``ScriptWorkerException``.

    Returns:
        None: if unable to read from ``path`` and ``exception`` is ``None``
        str or bytes: the contents of ``path``

    Raises:
        Exception: if ``exception`` is set.

    """
    FILE_TYPE_MAP = {'text': 'r', 'binary': 'rb'}
    if file_type not in FILE_TYPE_MAP:
        raise exception("Unknown file_type {} not in {}!".format(file_type, FILE_TYPE_MAP))
    try:
        with open(path, FILE_TYPE_MAP[file_type]) as fh:
            return fh.read()
    except (OSError, FileNotFoundError) as exc:
        raise exception("Can't read_from_file {}: {}".format(path, str(exc)))


# download_file {{{1
async def _log_download_error(resp, msg):
    log.debug(msg, {'url': get_loggable_url(str(resp.url)), 'status': resp.status, 'body': (await resp.text())[:1000]})
    for i, h in enumerate(resp.history):
        log.debug("Redirect history %s: %s; body=%s", get_loggable_url(str(h.url)), h.status, (await h.text())[:1000])


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
    loggable_url = get_loggable_url(url)
    log.info("Downloading %s", loggable_url)
    parent_dir = os.path.dirname(abs_filename)
    async with session.get(url) as resp:
        if resp.status == 404:
            await _log_download_error(resp, "404 downloading %(url)s: %(status)s; body=%(body)s")
            raise Download404("{} status {}!".format(loggable_url, resp.status))
        elif resp.status != 200:
            await _log_download_error(resp, "Failed to download %(url)s: %(status)s; body=%(body)s")
            raise DownloadError("{} status {} is not 200!".format(loggable_url, resp.status))
        makedirs(parent_dir)
        with open(abs_filename, "wb") as fd:
            while True:
                chunk = await resp.content.read(chunk_size)
                if not chunk:
                    break
                fd.write(chunk)
    log.info("Done")


# get_loggable_url {{{1
def get_loggable_url(url):
    """Strip out secrets from taskcluster urls.

    Args:
        url (str): the url to strip

    Returns:
        str: the loggable url

    """
    loggable_url = url or ""
    for secret_string in ("bewit=", "AWSAccessKeyId=", "access_token="):
        parts = loggable_url.split(secret_string)
        loggable_url = parts[0]
    if loggable_url != url:
        loggable_url = "{}<snip>".format(loggable_url)
    return loggable_url


def get_parts_of_url_path(url):
    """Given a url, take out the path part and split it by '/'.

    Args:
        url (str): the url slice

    returns
        list: parts after the domain name of the URL

    """
    parsed = urlparse(url)
    path = unquote(parsed.path).lstrip('/')
    parts = path.split('/')
    return parts


# load_json_or_yaml_from_url {{{1
async def load_json_or_yaml_from_url(context, url, path, overwrite=True):
    """Retry a json/yaml file download, load it, then return its data.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        url (str): the url to download
        path (str): the path to download to
        overwrite (bool, optional): if False and path exists, don't download.
            Defaults to True.

    Returns:
        dict: the url data.

    Raises:
        Exception: as specified, on failure

    """
    if path.endswith("json"):
        file_type = 'json'
    else:
        file_type = 'yaml'
    if not overwrite or not os.path.exists(path):
        await retry_async(
            download_file, args=(context, url, path),
            retry_exceptions=(DownloadError, aiohttp.ClientError),
        )
    return load_json_or_yaml(path, is_path=True, file_type=file_type)


# match_url_path_callback {{{1
def match_url_path_callback(match):
    """Return the path, as a ``match_url_regex`` callback.

    Args:
        match (re.match): the regex match object from ``match_url_regex``

    Returns:
        string: the path matched in the regex.

    """
    path_info = match.groupdict()
    return path_info['path']


# match_url_regex {{{1
def match_url_regex(rules, url, callback):
    """Given rules and a callback, find the rule that matches the url.

    Rules look like::

        (
            {
                'schemes': ['https', 'ssh'],
                'netlocs': ['hg.mozilla.org'],
                'path_regexes': [
                    "^(?P<path>/mozilla-(central|unified))(/|$)",
                ]
            },
            ...
        )

    Args:
        rules (list): a list of dictionaries specifying lists of ``schemes``,
            ``netlocs``, and ``path_regexes``.
        url (str): the url to test
        callback (function): a callback that takes an ``re.MatchObject``.
            If it returns None, continue searching.  Otherwise, return the
            value from the callback.

    Returns:
        value: the value from the callback, or None if no match.

    """
    parts = urlparse(url)
    path = unquote(parts.path)
    for rule in rules:
        if parts.scheme not in rule['schemes']:
            continue
        if parts.netloc not in rule['netlocs']:
            continue
        for regex in rule['path_regexes']:
            m = re.search(regex, path)
            if m is None:
                continue
            result = callback(m)
            if result is not None:
                return result


# add_enumerable_item_to_dict {{{1
def add_enumerable_item_to_dict(dict_, key, item):
    """Add an item to a list contained in a dict.

    For example: If the dict is ``{'some_key': ['an_item']}``, then calling this function
    will alter the dict to ``{'some_key': ['an_item', 'another_item']}``.

    If the key doesn't exist yet, the function initializes it with a list containing the
    item.

    List-like items are allowed. In this case, the existing list will be extended.

    Args:
        dict_ (dict): the dict to modify
        key (str): the key to add the item to
        item (whatever): The item to add to the list associated to the key

    """
    dict_.setdefault(key, [])
    if isinstance(item, (list, tuple)):
        dict_[key].extend(item)
    else:
        dict_[key].append(item)


# remove_empty_keys {{{1
def remove_empty_keys(values, remove=({}, None, [], 'null')):
    """Recursively remove key/value pairs where the value is in ``remove``.

    This is targeted at comparing json-e rebuilt task definitions, since
    json-e drops key/value pairs with empty values.

    Args:
        values (dict/list): the dict or list to remove empty keys from.

    Returns:
        values (dict/list): a dict or list copy, with empty keys removed.

    """
    if isinstance(values, dict):
        return {key: remove_empty_keys(value, remove=remove)
                for key, value in deepcopy(values).items() if value not in remove}
    if isinstance(values, list):
        return [remove_empty_keys(value, remove=remove)
                for value in deepcopy(values) if value not in remove]

    return values


# get_single_item_from_sequence {{{1
def get_single_item_from_sequence(
    sequence, condition,
    ErrorClass=ValueError,
    no_item_error_message='No item matched condition',
    too_many_item_error_message='Too many items matched condition',
    append_sequence_to_error_message=True
):
    """Return an item from a python sequence based on the given condition.

    Args:
        sequence (sequence): The sequence to filter
        condition: A function that serves to filter items from `sequence`. Function
            must have one argument (a single item from the sequence) and return a boolean.
        ErrorClass (Exception): The error type raised in case the item isn't unique
        no_item_error_message (str): The message raised when no item matched the condtion
        too_many_item_error_message (str): The message raised when more than one item matched the condition
        append_sequence_to_error_message (bool): Show or hide what was the tested sequence in the error message.
            Hiding it may prevent sensitive data (such as password) to be exposed to public logs

    Returns:
        The only item in the sequence which matched the condition

    """
    filtered_sequence = [item for item in sequence if condition(item)]
    number_of_items_in_filtered_sequence = len(filtered_sequence)
    if number_of_items_in_filtered_sequence == 0:
        error_message = no_item_error_message
    elif number_of_items_in_filtered_sequence > 1:
        error_message = too_many_item_error_message
    else:
        return filtered_sequence[0]

    if append_sequence_to_error_message:
        error_message = '{}. Given: {}'.format(error_message, sequence)
    raise ErrorClass(error_message)
