#!/usr/bin/env python
"""Scriptworker task execution.

Attributes:
    log (logging.Logger): the log object for the module
"""
import aiohttp.hdrs
import aiohttp.errors
import arrow
import asyncio
from asyncio.subprocess import PIPE
from copy import deepcopy
import logging
import mimetypes
import os
import pprint
import signal
from urllib.parse import unquote, urljoin

import taskcluster
import taskcluster.exceptions

from scriptworker.client import validate_artifact_url
from scriptworker.constants import REVERSED_STATUSES
from scriptworker.exceptions import ScriptWorkerRetryException
from scriptworker.log import get_log_fhs, pipe_to_log
from scriptworker.utils import filepaths_in_dir, raise_future_exceptions, retry_async, download_file

log = logging.getLogger(__name__)


# worst_level {{{1
def worst_level(level1, level2):
    """Given two int levels, return the larger.

    Args:
        level1 (int): exit code 1.
        level2 (int): exit code 2.

    Returns:
        int: the larger of the two levels.
    """
    return level1 if level1 > level2 else level2


# get_task_id {{{1
def get_task_id(claim_task):
    """Given a claim_task json dict, return the taskId.

    Args:
        claim_task (dict): the claim_task dict.

    Returns:
        str: the taskId.
    """
    return claim_task['status']['taskId']


# get_run_id {{{1
def get_run_id(claim_task):
    """Given a claim_task json dict, return the runId.

    Args:
        claim_task (dict): the claim_task dict.

    Returns:
        int: the runId.
    """
    return claim_task['runId']


# get_decision_task_id {{{1
def get_decision_task_id(task):
    """Given a task dict, return the decision taskId.

    Args:
        task (dict): the task dict.

    Returns:
        str: the taskId.
    """
    return task['taskGroupId']


def get_worker_type(task):
    """Given a task dict, return the workerType.

    Args:
        task (dict): the task dict.

    Returns:
        str: the workerType.
    """
    return task['workerType']


# run_task {{{1
async def run_task(context):
    """Run the task, sending stdout+stderr to files.

    https://github.com/python/asyncio/blob/master/examples/subprocess_shell.py

    Args:
        context (scriptworker.context.Context): the scriptworker context.

    Returns:
        int: exit code
    """
    loop = asyncio.get_event_loop()
    kwargs = {  # pragma: no branch
        'stdout': PIPE,
        'stderr': PIPE,
        'stdin': None,
        'close_fds': True,
        'preexec_fn': lambda: os.setsid(),
    }
    context.proc = await asyncio.create_subprocess_exec(*context.config['task_script'], **kwargs)
    loop.call_later(context.config['task_max_timeout'], max_timeout, context, context.proc, context.config['task_max_timeout'])

    tasks = []
    with get_log_fhs(context) as (log_fh, error_fh):
        tasks.append(pipe_to_log(context.proc.stderr, filehandles=[log_fh, error_fh]))
        tasks.append(pipe_to_log(context.proc.stdout, filehandles=[log_fh]))
        await asyncio.wait(tasks)
        exitcode = await context.proc.wait()
        status_line = "exit code: {}".format(exitcode)
        log.info(status_line)
        print(status_line, file=log_fh)

    context.proc = None
    return exitcode


# reclaim_task {{{1
async def reclaim_task(context, task):
    """Try to reclaim a task from the queue.

    This is a keepalive / heartbeat.  Without it the job will expire and
    potentially be re-queued.  Since this is run async from the task, the
    task may complete before we run, in which case we'll get a 409 the next
    time we reclaim.

    Args:
        context (scriptworker.context.Context): the scriptworker context

    Raises:
        taskcluster.exceptions.TaskclusterRestFailure: on non-409 status_code
            from taskcluster.async.Queue.reclaimTask()
    """
    while True:
        log.debug("waiting %s seconds before reclaiming..." % context.config['reclaim_interval'])
        await asyncio.sleep(context.config['reclaim_interval'])
        if task != context.task:
            return
        log.debug("Reclaiming task...")
        try:
            context.reclaim_task = await context.temp_queue.reclaimTask(
                get_task_id(context.claim_task),
                get_run_id(context.claim_task),
            )
            clean_response = deepcopy(context.reclaim_task)
            clean_response['credentials'] = "{********}"
            log.debug("Reclaim task response:\n{}".format(pprint.pformat(clean_response)))
        except taskcluster.exceptions.TaskclusterRestFailure as exc:
            if exc.status_code == 409:
                log.debug("409: not reclaiming task.")
                break
            else:
                raise


# get_expiration_arrow {{{1
def get_expiration_arrow(context):
    """Return an arrow, ``artifact_expiration_hours`` in the future from now.

    Args:
        context (scriptworker.context.Context): the scriptworker context

    Returns:
        arrow: now + artifact_expiration_hours
    """
    now = arrow.utcnow()
    return now.replace(hours=context.config['artifact_expiration_hours'])


# guess_content_type {{{1
def guess_content_type(path):
    """Guess the content type of a path, using ``mimetypes``.

    Args:
        path (str): the path to guess the mimetype of

    Returns:
        str: the content type of the file
    """
    content_type, _ = mimetypes.guess_type(path)
    if path.endswith('.log'):
        # linux mimetypes returns None for .log
        content_type = content_type or "text/plain"
    return content_type or "application/binary"


# create_artifact {{{1
async def create_artifact(context, path, target_path, storage_type='s3',
                          expires=None, content_type=None):
    """Create an artifact and upload it.

    This should support s3 and azure out of the box; we'll need some tweaking
    if we want to support redirect/error artifacts.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        path (str): the path of the file to upload.
        target_path (str):
        storage_type (str, optional): the taskcluster storage type to use.
            Defaults to 's3'
        expires (str, optional): datestring of when the artifact expires.
            Defaults to None.
        content_type (str, optional): Specify the content type of the artifact.
            If None, use guess_content_type().  Defaults to None.

    Raises:
        ScriptWorkerRetryException: on failure.
    """
    payload = {
        "storageType": storage_type,
        "expires": expires or get_expiration_arrow(context).isoformat(),
        "contentType": content_type or guess_content_type(path),
    }
    args = [get_task_id(context.claim_task), get_run_id(context.claim_task),
            target_path, payload]
    tc_response = await context.temp_queue.createArtifact(*args)
    headers = {
        aiohttp.hdrs.CONTENT_TYPE: tc_response['contentType'],
    }
    skip_auto_headers = [aiohttp.hdrs.CONTENT_TYPE]
    log.info("uploading {path} to {url}...".format(path=path, url=tc_response['putUrl']))
    with open(path, "rb") as fh:
        with aiohttp.Timeout(context.config['artifact_upload_timeout']):
            async with context.session.put(
                tc_response['putUrl'], data=fh, headers=headers,
                skip_auto_headers=skip_auto_headers, compress=False
            ) as resp:
                log.info(resp.status)
                response_text = await resp.text()
                log.info(response_text)
                if resp.status not in (200, 204):
                    raise ScriptWorkerRetryException(
                        "Bad status {}".format(resp.status),
                    )


# retry_create_artifact {{{1
async def retry_create_artifact(*args, **kwargs):
    """Retry create_artifact() calls.

    Args:
        *args: the args to pass on to create_artifact
        **kwargs: the args to pass on to create_artifact
    """
    await retry_async(
        create_artifact,
        retry_exceptions=(
            ScriptWorkerRetryException,
            aiohttp.errors.DisconnectedError,
            aiohttp.errors.ClientError
        ),
        args=args,
        kwargs=kwargs
    )


# upload_artifacts {{{1
async def upload_artifacts(context):
    """Upload the files in ``artifact_dir``, preserving relative paths.

    This function expects the directory structure in ``artifact_dir`` to remain
    the same.  So if we want the files in ``public/...``, create an
    ``artifact_dir/public`` and put the files in there.

    Args:
        context (scriptworker.context.Context): the scriptworker context.

    Raises:
        Exception: any exceptions the tasks raise.
    """
    file_list = {}
    for target_path in filepaths_in_dir(context.config['artifact_dir']):
        path = os.path.join(context.config['artifact_dir'], target_path)
        file_list[target_path] = {
            'path': path,
            'target_path': target_path,
            'content_type': None,
        }

    tasks = []
    for upload_config in file_list.values():
        tasks.append(
            asyncio.ensure_future(
                retry_create_artifact(
                    context, upload_config['path'],
                    target_path=upload_config['target_path'],
                    content_type=upload_config['content_type']
                )
            )
        )
    await raise_future_exceptions(tasks)


# complete_task {{{1
async def complete_task(context, result):
    """Mark the task as completed in the queue.

    Decide whether to call reportCompleted, reportFailed, or reportException
    based on the exit status of the script.

    If the task has expired or been cancelled, we'll get a 409 status.

    Args:
        context (scriptworker.context.Context): the scriptworker context.

    Raises:
        taskcluster.exceptions.TaskclusterRestFailure: on non-409 error.
    """
    args = [get_task_id(context.claim_task), get_run_id(context.claim_task)]
    try:
        if result == 0:
            log.info("Reporting task complete...")
            response = await context.temp_queue.reportCompleted(*args)
        elif result in list(range(2, 7)):
            reason = REVERSED_STATUSES[result]
            log.info("Reporting task exception {}...".format(reason))
            payload = {"reason": reason}
            response = await context.temp_queue.reportException(*args, payload)
        else:
            log.info("Reporting task failed...")
            response = await context.temp_queue.reportFailed(*args)
        log.debug("Task status response:\n{}".format(pprint.pformat(response)))
    except taskcluster.exceptions.TaskclusterRestFailure as exc:
        if exc.status_code == 409:
            log.info("409: not reporting complete/failed.")
        else:
            raise


# kill {{{1
async def kill(pid, sleep_time=1):
    """Kill ``pid`` with various signals.

    Args:
        pid (int): the process id to kill.
        sleep_time (int, optional): how long to sleep between killing the pid
            and checking if the pid is still running.
    """
    siglist = [signal.SIGINT, signal.SIGTERM]
    while True:
        sig = signal.SIGKILL
        if siglist:  # pragma: no branch
            sig = siglist.pop(0)
        try:
            os.kill(pid, sig)
            await asyncio.sleep(sleep_time)
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return


# max_timeout {{{1
def max_timeout(context, proc, timeout):
    """Make sure the proc pid's process and process group are killed.

    First, kill the process group (-pid) and then the pid.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        proc (subprocess.Process): the subprocess proc.  This is compared against context.proc
            to make sure we're killing the right pid.
        timeout (int): Used for the log message.
    """
    # We may be called with proc1.  proc1 may finish, and proc2 may start
    # before this function is called.  Make sure we're still running the
    # proc we were called with.
    if proc != context.proc:
        return
    pid = context.proc.pid
    log.warning("Exceeded timeout of {} seconds: {}".format(timeout, pid))
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.wait([
        asyncio.ensure_future(kill(-pid)),
        asyncio.ensure_future(kill(pid))
    ]))


# get_artifact_url {{{1
def get_artifact_url(context, task_id, path):
    """Get a TaskCluster artifact url.

    Args:
        context (scriptworker.context.Context): the scriptworker context
        task_id (str): the task id of the task that published the artifact
        path (str): the relative path of the artifact

    Returns:
        str: the artifact url

    Raises:
        TaskClusterFailure: on failure.
    """
    url = urljoin(
        context.queue.options['baseUrl'],
        'v1/' +
        unquote(context.queue.makeRoute('getLatestArtifact', replDict={
            'taskId': task_id,
            'name': path
        }))
    )
    return url


# download_artifacts {{{1
async def download_artifacts(context, file_urls, parent_dir=None, session=None,
                             download_func=download_file, valid_artifact_task_ids=None):
    """Download artifacts in parallel after validating their URLs.

    Valid ``taskId``s for download include the task's dependencies and the
    ``taskGroupId``, which by convention is the ``taskId`` of the decision task.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        file_urls (list): the list of artifact urls to download.
        parent_dir (str, optional): the path of the directory to download the
            artifacts into.  If None, defaults to ``work_dir``.  Default is None.
        session (aiohttp.ClientSession, optional): the session to use to download.
            If None, defaults to context.session.  Default is None.
        download_func (function, optional): the function to call to download the files.
            default is ``download_file``.
        valid_artifact_task_ids (list, optional): the list of task ids that are
            valid to download from.  If None, defaults to all task dependencies
            plus the decision taskId.  Defaults to None.

    Returns:
        list: the full paths to the files downloaded

    Raises:
        scriptworker.exceptions.DownloadError: on download failure after
            max retries.
    """
    parent_dir = parent_dir or context.config['work_dir']
    session = session or context.session

    tasks = []
    files = []
    valid_artifact_rules = context.config['valid_artifact_rules']
    # XXX when chain of trust is on everywhere, hardcode the chain of trust task list
    valid_artifact_task_ids = valid_artifact_task_ids or list(context.task['dependencies'] + [get_decision_task_id(context.task)])
    for file_url in file_urls:
        rel_path = validate_artifact_url(valid_artifact_rules, valid_artifact_task_ids, file_url)
        abs_file_path = os.path.join(parent_dir, rel_path)
        files.append(abs_file_path)
        tasks.append(
            asyncio.ensure_future(
                retry_async(
                    download_func, args=(context, file_url, abs_file_path),
                    kwargs={'session': session},
                )
            )
        )

    await raise_future_exceptions(tasks)
    return files
