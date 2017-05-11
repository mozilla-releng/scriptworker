#!/usr/bin/env python
"""Scriptworker task execution.

Attributes:
    log (logging.Logger): the log object for the module

"""
import aiohttp
import asyncio
from asyncio.subprocess import PIPE
from copy import deepcopy
import logging
import os
import pprint
import signal

import taskcluster
import taskcluster.exceptions

from scriptworker.constants import REVERSED_STATUSES
from scriptworker.log import get_log_filehandle, pipe_to_log

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
    with get_log_filehandle(context) as log_filehandle:
        tasks.append(pipe_to_log(context.proc.stderr, filehandles=[log_filehandle]))
        tasks.append(pipe_to_log(context.proc.stdout, filehandles=[log_filehandle]))
        await asyncio.wait(tasks)
        exitcode = await context.proc.wait()
        status_line = "exit code: {}".format(exitcode)
        log.info(status_line)
        print(status_line, file=log_filehandle)

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


# claim_work {{{1
async def claim_work(context):
    """Find and claim the next pending task in the queue, if any.

    Args:
        context (scriptworker.context.Context): the scriptworker context.

    Returns:
        dict: a dict containing a list of the task definitions of the tasks claimed.

    """
    payload = {
        'workerGroup': context.config['worker_group'],
        'workerId': context.config['worker_id'],
        # Hardcode one task at a time.  Make this a pref if we allow for
        # parallel tasks in multiple `work_dir`s.
        'tasks': 1,
    }
    try:
        return await context.queue.claimWork(
            context.config['provisioner_id'],
            context.config['worker_type'],
            payload
        )
    except (taskcluster.exceptions.TaskclusterFailure, aiohttp.ClientError) as exc:
        log.warning("{} {}".format(exc.__class__, exc))
