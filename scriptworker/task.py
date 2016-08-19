#!/usr/bin/env python
"""Scriptworker task execution
"""
import aiohttp.hdrs
import arrow
import asyncio
import logging
import mimetypes
import os
import signal

from asyncio.subprocess import PIPE

import taskcluster
import taskcluster.exceptions
from taskcluster.async import Queue

from scriptworker.exceptions import ScriptWorkerRetryException, ScriptWorkerTaskException
from scriptworker.log import get_log_fhs, get_log_filenames, log_errors, read_stdout
from scriptworker.utils import filepaths_in_dir, raise_future_exceptions, retry_async

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
        tasks.append(log_errors(context.proc.stderr, log_fh, error_fh))
        tasks.append(read_stdout(context.proc.stdout, log_fh))
        await asyncio.wait(tasks)
        exitcode = await context.proc.wait()
        status_line = "exit code: {}".format(exitcode)
        log.info(status_line)
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
        log.debug("waiting %s seconds before reclaiming..." % context.config['reclaim_interval'])
        await asyncio.sleep(context.config['reclaim_interval'])
        log.debug("Reclaiming task...")
        temp_queue = get_temp_queue(context)
        taskId = context.claim_task['status']['taskId']
        runId = context.claim_task['runId']
        try:
            result = await temp_queue.reclaimTask(taskId, runId)
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
    return content_type or "application/binary"


async def create_artifact(context, path, target_path, storage_type='s3',
                          expires=None, content_type=None):
    """Create an artifact and upload it.  This should support s3 and azure
    out of the box; we'll need some tweaking if we want to support
    redirect/error artifacts.
    """
    temp_queue = get_temp_queue(context)
    payload = {
        "storageType": storage_type,
        "expires": expires or get_expiration_arrow(context).isoformat(),
        "contentType": content_type or guess_content_type(path),
    }
    args = [context.claim_task['status']['taskId'], context.claim_task['runId'],
            target_path, payload]
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


def _update_upload_file_list(file_list, upload_config):
    """Helper function to update `file_list` with upload_config, while
    making sure that only one file will be uploaded per `target_path`
    """
    target_path = upload_config['target_path']
    value = file_list.setdefault(target_path, upload_config)
    if value != upload_config:
        raise ScriptWorkerTaskException(
            "Conflict in upload_artifacts target_paths: {} and {} are both {}!".format(
                value['path'], upload_config['path'], target_path
            ),
            exit_code=STATUSES['malformed-payload']
        )


async def upload_artifacts(context):
    """Upload the task logs and any files in `artifact_dir`.
    Currently we do not support recursing into subdirectories.
    """
    file_list = {}
    for target_path in filepaths_in_dir(context.config['artifact_dir']):
        path = os.path.join(context.config['artifact_dir'], target_path)
        if not target_path.startswith('public/'):
            target_path = 'public/{}'.format(target_path)
        upload_config = {
            'path': path,
            'target_path': target_path,
            'content_type': None,
        }
        _update_upload_file_list(file_list, upload_config)

    for path in get_log_filenames(context):
        target_path = 'public/logs/{}'.format(os.path.basename(path))
        upload_config = {
            'path': path,
            'target_path': target_path,
            'content_type': 'text/plain'
        }
        _update_upload_file_list(file_list, upload_config)
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


async def complete_task(context, result):
    """Mark the task as completed in the queue.

    Decide whether to call reportCompleted, reportFailed, or reportException
    based on the exit status of the script.

    If the task has expired or been cancelled, we'll get a 409 status.
    """
    temp_queue = get_temp_queue(context)
    args = [context.claim_task['status']['taskId'], context.claim_task['runId']]
    try:
        if result == 0:
            log.info("Reporting task complete...")
            await temp_queue.reportCompleted(*args)
        elif result in list(range(2, 7)):
            reason = REVERSED_STATUSES[result]
            log.info("Reporting task exception {}...".format(reason))
            payload = {"reason": reason}
            await temp_queue.reportException(*args, payload)
        else:
            log.info("Reporting task failed...")
            await temp_queue.reportFailed(*args)
    except taskcluster.exceptions.TaskclusterRestFailure as exc:
        if exc.status_code == 409:
            log.info("409: not reporting complete/failed.")
        else:
            raise


async def kill(pid, sleep_time=1):
    """Kill `pid`.
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


def max_timeout(context, proc, timeout):
    """Make sure the proc pid's process and process group are killed.
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
