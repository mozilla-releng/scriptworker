#!/usr/bin/env python
"""Scriptworker task execution.

Attributes:
    KNOWN_TASKS_FOR (tuple): the known reasons for creating decision/action tasks.
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
from urllib.parse import unquote, urlparse

import taskcluster
import taskcluster.exceptions

from scriptworker.constants import REVERSED_STATUSES
from scriptworker.log import get_log_filehandle, pipe_to_log
from scriptworker.utils import match_url_path_callback, match_url_regex

log = logging.getLogger(__name__)

KNOWN_TASKS_FOR = ('hg-push', 'cron', 'action')


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


# get_action_name {{{1
def get_action_name(task):
    """Get the name of an action task.

    Args:
        obj (ChainOfTrust or LinkOfTrust): the trust object to inspect

    Returns:
        str: the name.

    """
    name = task['extra'].get('action', {}).get('name')
    return name


# get_commit_message {{{1
def get_commit_message(task):
    """Get the commit message for a task.

    Args:
        obj (ChainOfTrust or LinkOfTrust): the trust object to inspect

    Returns:
        str: the commit message.

    """
    msg = task['payload'].get('env', {}).get('GECKO_COMMIT_MSG', ' ')
    return msg


# get_decision_task_id {{{1
def get_decision_task_id(task):
    """Given a task dict, return the decision taskId.

    By convention, the decision task of the ``taskId`` is the task's ``taskGroupId``.

    Args:
        task (dict): the task dict.

    Returns:
        str: the taskId of the decision task.

    """
    return task['taskGroupId']


# get_parent_task_id {{{1
def get_parent_task_id(task):
    """Given a task dict, return the parent taskId.

    The parent taskId could be a decision taskId, or an action taskId.
    The parent is the task that created this task; it should have a
    ``task-graph.json`` containing this task's definition as an artifact.

    Args:
        task (dict): the task dict

    Returns:
        str: the taskId of the parent.

    """
    return task.get('extra', {}).get('parent', get_decision_task_id(task))


# get_repo {{{1
def get_repo(task, source_env_prefix):
    """Get the repo for a task.

    Args:
        task (ChainOfTrust or LinkOfTrust): the trust object to inspect
        source_env_prefix (str): The environment variable prefix that is used
            to get repository information.

    Returns:
        str: the source url.
        None: if not defined for this task.

    """
    repo = task['payload'].get('env', {}).get(source_env_prefix + '_HEAD_REPOSITORY')
    if repo is not None:
        repo = repo.rstrip('/')
    return repo


# get_revision {{{1
def get_revision(task, source_env_prefix):
    """Get the revision for a task.

    Args:
        obj (ChainOfTrust or LinkOfTrust): the trust object to inspect
        source_env_prefix (str): The environment variable prefix that is used
            to get repository information.

    Returns:
        str: the revision.
        None: if not defined for this task.

    """
    revision = task['payload'].get('env', {}).get(source_env_prefix + '_HEAD_REV')
    return revision


# get_worker_type {{{1
def get_worker_type(task):
    """Given a task dict, return the workerType.

    Args:
        task (dict): the task dict.

    Returns:
        str: the workerType.

    """
    return task['workerType']


# get_and_check_project {{{1
def get_and_check_project(valid_vcs_rules, source_url):
    """Given vcs rules and a source_url, return the project.

    The project is in the path, but is the repo name.
    `releases/mozilla-beta` is the path; `mozilla-beta` is the project.

    Args:
        valid_vcs_rules (tuple of frozendicts): the valid vcs rules, per
            ``match_url_regex``.
        source_url (str): the source url to find the project for.

    Raises:
        RuntimeError: on failure to find the project.

    Returns:
        str: the project.

    """
    project_path = match_url_regex(valid_vcs_rules, source_url, match_url_path_callback)
    if project_path is None:
        raise ValueError("Unknown repo for source url {}!".format(source_url))
    project = project_path.split('/')[-1]
    return project


# get_and_check_tasks_for {{{1
def get_and_check_tasks_for(task, msg_prefix=''):
    """Given a parent task, return the reason the parent task was spawned.

    ``.taskcluster.yml`` uses this to know whether to spawn an action,
    cron, or decision task definition.  The current known ``tasks_for`` are in
    ``KNOWN_TASKS_FOR``.

    Args:
        task (dict): the task definition.
        msg_prefix (str): the string prefix to use for an exception.

    Raises:
        (KeyError, ValueError): on failure to find a valid ``tasks_for``.

    Returns:
        str: the ``tasks_for``

    """
    tasks_for = task['extra']['tasks_for']
    if tasks_for not in KNOWN_TASKS_FOR:
        raise ValueError(
            '{}Unknown tasks_for: {}'.format(msg_prefix, tasks_for)
        )
    return tasks_for


# is_try {{{1
def _is_try_url(url):
    parsed = urlparse(url)
    path = unquote(parsed.path).lstrip('/')
    parts = path.split('/')
    if "try" in parts[0]:
        return True
    return False


def is_try(task, source_env_prefix):
    """Determine if a task is a 'try' task (restricted privs).

    This goes further than get_repo.  We may or may not want
    to keep this.

    This checks for the following things::

        * ``task.payload.env.GECKO_HEAD_REPOSITORY`` == "https://hg.mozilla.org/try/"
        * ``task.payload.env.MH_BRANCH`` == "try"
        * ``task.metadata.source`` == "https://hg.mozilla.org/try/..."
        * ``task.schedulerId`` in ("gecko-level-1", )

    Args:
        task (dict): the task definition to check
        source_env_prefix (str): The environment variable prefix that is used
            to get repository information.

    Returns:
        bool: True if it's try

    """
    result = False
    env = task['payload'].get('env', {})
    repo = get_repo(task, source_env_prefix)
    if repo:
        result = result or _is_try_url(repo)
    if env.get("MH_BRANCH"):
        result = result or 'try' in task['payload']['env']['MH_BRANCH']
    if task['metadata'].get('source'):
        result = result or _is_try_url(task['metadata']['source'])
    result = result or task['schedulerId'] in ("gecko-level-1", )
    return result


# is_action {{{1
def is_action(task):
    """Determine if a task is an action task.

    Trusted decision and action tasks are important in that they can generate
    other valid tasks. The verification of decision and action tasks is slightly
    different, so we need to be able to tell them apart.

    This checks for the following things::

        * ``task.payload.env.ACTION_CALLBACK`` exists
        * ``task.extra.action`` exists

    Args:
        task (dict): the task definition to check

    Returns:
        bool: True if it's an action

    """
    result = False
    env = task['payload'].get('env', {})
    if env.get("ACTION_CALLBACK"):
        result = True
    if task.get('extra', {}).get('action') is not None:
        result = True
    return result


# prepare_to_run_task {{{1
def prepare_to_run_task(context, claim_task):
    """Given a `claim_task` json dict, prepare the `context` and `work_dir`.

    Set `context.claim_task`, and write a `work_dir/current_task_info.json`

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        claim_task (dict): the claim_task dict.

    Returns:
        dict: the contents of `current_task_info.json`

    """
    current_task_info = {}
    context.claim_task = claim_task
    current_task_info['taskId'] = get_task_id(claim_task)
    current_task_info['runId'] = get_run_id(claim_task)
    log.info("Going to run taskId {taskId} runId {runId}!".format(
        **current_task_info
    ))
    context.write_json(
        os.path.join(context.config['work_dir'], 'current_task_info.json'),
        current_task_info, "Writing current task info to {path}..."
    )
    return current_task_info


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
        if exitcode == -11:
            status_line = "Automation Error: python exited with signal {}".format(exitcode)
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
        elif result != 1 and result in REVERSED_STATUSES:
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
    log.debug("Calling claimWork...")
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
