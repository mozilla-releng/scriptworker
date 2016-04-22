#!/usr/bin/env python
"""Scriptworker task execution
"""
import asyncio
import logging
import pprint

from asyncio.subprocess import PIPE

import taskcluster
import taskcluster.exceptions
from taskcluster.async import Queue

from scriptworker.log import get_log_fhs, log_errors, read_stdout

log = logging.getLogger(__name__)


async def run_task(context):
    """Run the task, sending stdout+stderr to files.

    https://github.com/python/asyncio/blob/master/examples/subprocess_shell.py
    """
    kwargs = {
        'stdout': PIPE,
        'stderr': PIPE,
        'stdin': None,
    }
    proc = await asyncio.create_subprocess_exec(*context.config['task_script'], **kwargs)

    tasks = []
    with get_log_fhs(context) as (log_fh, error_fh):
        tasks.append(log_errors(proc.stderr, log_fh, error_fh))
        tasks.append(read_stdout(proc.stdout, log_fh))
        await asyncio.wait(tasks)
        exitcode = await proc.wait()
        status_line = "exit code: {}".format(exitcode)
        log.debug(status_line)
        print(status_line, file=log_fh)

    return exitcode


def get_temp_queue(context):
    """Create an async taskcluster client Queue from the latest temp
    credentials.
    """
    temp_queue = Queue({
        'credentials': context.temp_credentials,
    }, session=context.session)
    return temp_queue


async def reclaim_task(context, task):
    """Try to reclaim a task from the queue.
    This is a keepalive / heartbeat.  Without it the job will expire and
    potentially be re-queued.  Since this is run async from the task, the
    task may complete before we run, in which case we'll get a 409 the next
    time we reclaim.
    """
    while True:
        # TODO stop checking for this once we rely on the 409
        log.debug("Reclaiming task...")
        temp_queue = get_temp_queue(context)
        taskId = task['status']['taskId']
        runId = task['runId']
        try:
            result = await temp_queue.reclaimTask(taskId, runId)
            log.debug(pprint.pformat(result))
            context.reclaim_task = result
            await asyncio.sleep(context.config['reclaim_interval'])
        except taskcluster.exceptions.TaskclusterRestFailure as exc:
            if exc.status_code == 409:
                log.debug("409: not reclaiming task.")
                break
            else:
                raise


async def complete_task(context, result):
    """Mark the task as completed in the queue.

    Decide whether to call reportCompleted, reportFailed, or reportException
    based on the exit status of the script.

    If the task has expired or been cancelled, we'll get a 409 status.
    """
    temp_queue = get_temp_queue(context)
    args = [context.task['status']['taskId'], context.task['runId']]
    # TODO try/except, retry
    try:
        if result == 0:
            log.debug("Reporting task complete...")
            await temp_queue.reportCompleted(*args)
        else:
            log.debug("Reporting task failed...")
            await temp_queue.reportFailed(*args)
        # TODO exception:
        #  worker-shutdown malformed-payload resource-unavailable internal-error superseded
    except taskcluster.exceptions.TaskclusterRestFailure as exc:
        if exc.status_code == 409:
            log.debug("409: not reporting complete/failed.")
        else:
            # TODO retry?
            raise


def schedule_reclaim_task(context, task):
    """Helper function to start calling reclaim_task() after reclaim_interval
    seconds.  This is a non-async function that can be called with
    loop.call_later()
    """
    loop = asyncio.get_event_loop()
    loop.create_task(reclaim_task(context, task))
