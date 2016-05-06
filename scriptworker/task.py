#!/usr/bin/env python
"""Scriptworker task execution
"""
import aiohttp.hdrs
import arrow
import asyncio
import glob
import logging
import mimetypes
import os
import pprint
import signal

from asyncio.subprocess import PIPE

import taskcluster
import taskcluster.exceptions
from taskcluster.async import Queue

from scriptworker.exceptions import ScriptWorkerRetryException
from scriptworker.log import get_log_fhs, get_log_filenames, log_errors, read_stdout
from scriptworker.utils import retry_async

log = logging.getLogger(__name__)


STATUSES = {
    'success': 0,
    'failure': 1,
    'worker-shutdown': 2,
    'malformed-payload': 3,
    'resource-unavailable': 4,
    'internal-error': 5,
    'superseded': 6,
}
REVERSED_STATUSES = {v: k for k, v in STATUSES.items()}


async def run_task(context):
    """Run the task, sending stdout+stderr to files.

    https://github.com/python/asyncio/blob/master/examples/subprocess_shell.py
    """
    loop = asyncio.get_event_loop()
    kwargs = {
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
        tasks.append(log_errors(context.proc.stderr, log_fh, error_fh))
        tasks.append(read_stdout(context.proc.stdout, log_fh))
        await asyncio.wait(tasks)
        exitcode = await context.proc.wait()
        status_line = "exit code: {}".format(exitcode)
        log.debug(status_line)
        print(status_line, file=log_fh)

    context.proc = None
    return exitcode


def get_temp_queue(context):
    """Create an async taskcluster client Queue from the latest temp
    credentials.
    """
    temp_queue = Queue({
        'credentials': context.temp_credentials,
    }, session=context.session)
    return temp_queue


async def reclaim_task(context):
    """Try to reclaim a task from the queue.
    This is a keepalive / heartbeat.  Without it the job will expire and
    potentially be re-queued.  Since this is run async from the task, the
    task may complete before we run, in which case we'll get a 409 the next
    time we reclaim.
    """
    while True:
        await asyncio.sleep(context.config['reclaim_interval'])
        log.debug("Reclaiming task...")
        temp_queue = get_temp_queue(context)
        taskId = context.task['status']['taskId']
        runId = context.task['runId']
        try:
            result = await temp_queue.reclaimTask(taskId, runId)
            log.debug(pprint.pformat(result))
            context.reclaim_task = result
        except taskcluster.exceptions.TaskclusterRestFailure as exc:
            if exc.status_code == 409:
                log.debug("409: not reclaiming task.")
                break
            else:
                raise


def get_expiration_arrow(context):
    """Return an arrow, `artifact_expiration_hours` in the future from now.
    """
    now = arrow.utcnow()
    return now.replace(hours=context.config['artifact_expiration_hours'])


def guess_content_type(path):
    """Guess the content type of a path, using `mimetypes`
    """
    content_type, _ = mimetypes.guess_type(path)
    return content_type


async def create_artifact(context, path, storage_type='s3', expires=None,
                          content_type=None):
    """Create an artifact and upload it.  This should support s3 and azure
    out of the box; we'll need some tweaking if we want to support
    redirect/error artifacts.
    """
    temp_queue = get_temp_queue(context)
    filename = os.path.basename(path)
    payload = {
        "storageType": storage_type,
        "expires": expires or get_expiration_arrow(context).isoformat(),
        "contentType": content_type or guess_content_type(path),
    }
    args = [context.task['status']['taskId'], context.task['runId'], filename, payload]
    tc_response = await temp_queue.createArtifact(*args)
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


async def retry_create_artifact(*args, **kwargs):
    return await retry_async(
        create_artifact,
        retry_exceptions=(ScriptWorkerRetryException, ),
        args=args,
        kwargs=kwargs
    )


async def upload_artifacts(context):
    """Upload the task logs and any files in `artifact_dir`.
    Currently we do not support recursing into subdirectories.
    """
    files = glob.glob(os.path.join(context.config['artifact_dir'], '*'))
    files.extend(get_log_filenames(context))
    tasks = []
    for path in files:
        tasks.append(retry_create_artifact(context, path))
    await asyncio.wait(tasks)


async def complete_task(context, result):
    """Mark the task as completed in the queue.

    Decide whether to call reportCompleted, reportFailed, or reportException
    based on the exit status of the script.

    If the task has expired or been cancelled, we'll get a 409 status.
    """
    temp_queue = get_temp_queue(context)
    args = [context.task['status']['taskId'], context.task['runId']]
    try:
        if result == 0:
            log.debug("Reporting task complete...")
            await temp_queue.reportCompleted(*args)
        elif result in list(range(2, 7)):
            reason = REVERSED_STATUSES[result]
            log.debug("Reporting task exception {}...".format(reason))
            payload = {"reason": reason}
            await temp_queue.reportException(*args, payload)
        else:
            log.debug("Reporting task failed...")
            await temp_queue.reportFailed(*args)
    except taskcluster.exceptions.TaskclusterRestFailure as exc:
        if exc.status_code == 409:
            log.debug("409: not reporting complete/failed.")
        else:
            raise


async def kill(pid, sleep_time=1):
    siglist = [signal.SIGINT, signal.SIGTERM]
    while True:
        sig = signal.SIGKILL
        if siglist:
            sig = siglist.pop(0)
        try:
            os.kill(pid, sig)
            await asyncio.sleep(sleep_time)
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return


def max_timeout(context, proc, timeout):
    if proc != context.proc:
        return
    pid = context.proc.pid
    log.debug("Exceeded timeout of {} seconds: {}".format(timeout, pid))
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.wait([
        asyncio.ensure_future(kill(-pid)),
        asyncio.ensure_future(kill(pid))
    ]))
