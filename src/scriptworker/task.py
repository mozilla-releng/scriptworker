#!/usr/bin/env python
"""Scriptworker task execution.

Attributes:
    REPO_SCOPE_REGEX (regex): the regex for the ``repo_scope`` of a task
    log (logging.Logger): the log object for the module

"""

import asyncio
import logging
import os
import pprint
import re
from asyncio.subprocess import PIPE
from copy import deepcopy

import aiohttp
import taskcluster
import taskcluster.exceptions
from scriptworker.constants import get_reversed_statuses
from scriptworker.exceptions import ScriptWorkerTaskException, WorkerShutdownDuringTask
from scriptworker.github import (
    GitHubRepository,
    extract_github_repo_and_revision_from_source_url,
    extract_github_repo_owner_and_name,
    is_github_repo_owner_the_official_one,
    is_github_url,
)
from scriptworker.log import get_log_filehandle, pipe_to_log
from scriptworker.task_process import TaskProcess
from scriptworker.utils import get_parts_of_url_path, retry_async
from taskcluster.exceptions import TaskclusterFailure

log = logging.getLogger(__name__)

REPO_SCOPE_REGEX = re.compile("^assume:repo:[^:]+:action:[^:]+$")


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


# get_task_definition {{{1
async def get_task_definition(queue, task_id, exception=TaskclusterFailure):
    """Get the task definition from the queue.

    Detect whether the task definition is empty, per bug 1618731.

    Args:
        queue (taskcluster.aio.Queue): the taskcluster Queue object
        task_id (str): the taskId of the task
        exception (Exception, optional): the exception to raise if unsuccessful.
            Defaults to ``TaskclusterFailure``.

    """
    task_defn = await queue.task(task_id)
    if "payload" not in task_defn:
        raise exception("Task definition for {} is empty!\n {}".format(task_id, task_defn))
    return task_defn


async def retry_get_task_definition(queue, task_id, exception=TaskclusterFailure, **kwargs):
    """Retry ``get_task_definition``.

    Args:
        queue (taskcluster.aio.Queue): the taskcluster Queue object
        task_id (str): the taskId of the task
        exception (Exception, optional): the exception to raise if unsuccessful.
            Defaults to ``TaskclusterFailure``.

    """
    kwargs.setdefault("retry_exceptions", tuple(set([TaskclusterFailure, exception])))
    return await retry_async(get_task_definition, args=(queue, task_id), kwargs={"exception": exception}, **kwargs)


# get_task_id {{{1
def get_task_id(claim_task):
    """Given a claim_task json dict, return the taskId.

    Args:
        claim_task (dict): the claim_task dict.

    Returns:
        str: the taskId.

    """
    return claim_task["status"]["taskId"]


# get_run_id {{{1
def get_run_id(claim_task):
    """Given a claim_task json dict, return the runId.

    Args:
        claim_task (dict): the claim_task dict.

    Returns:
        int: the runId.

    """
    return claim_task["runId"]


# get_action_callback_name {{{1
def get_action_callback_name(task):
    """Get the callback name of an action task.

    Args:
        obj (ChainOfTrust or LinkOfTrust): the trust object to inspect

    Returns:
        str: the name.
        None: if not found.

    """
    return _extract_from_env_in_payload(task, "ACTION_CALLBACK")


# get_commit_message {{{1
def get_commit_message(task):
    """Get the commit message for a task.

    Args:
        obj (ChainOfTrust or LinkOfTrust): the trust object to inspect

    Returns:
        str: the commit message.

    """
    return _extract_from_env_in_payload(task, "GECKO_COMMIT_MSG", default=" ")


# get_decision_task_id {{{1
def get_decision_task_id(task):
    """Given a task dict, return the decision taskId.

    By convention, the decision task of the ``taskId`` is the task's ``taskGroupId``.

    Args:
        task (dict): the task dict.

    Returns:
        str: the taskId of the decision task.

    """
    return task["taskGroupId"]


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
    return task.get("extra", {}).get("parent", get_decision_task_id(task))


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
    repo = _extract_from_env_in_payload(task, source_env_prefix + "_HEAD_REPOSITORY")
    if repo is not None:
        repo = repo.rstrip("/")
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
    return _extract_from_env_in_payload(task, source_env_prefix + "_HEAD_REV")


def get_branch(task, source_env_prefix):
    """Get the branch on top of which the graph was made.

    Args:
        obj (ChainOfTrust or LinkOfTrust): the trust object to inspect
        source_env_prefix (str): The environment variable prefix that is used
            to get repository information.

    Returns:
        str: the username of the entity who triggered the graph.
        None: if not defined for this task.

    """
    return _extract_from_env_in_payload(task, source_env_prefix + "_HEAD_BRANCH", _extract_from_env_in_payload(task, source_env_prefix + "_HEAD_REF"))


def get_triggered_by(task, source_env_prefix):
    """Get who triggered the graph.

    Args:
        obj (ChainOfTrust or LinkOfTrust): the trust object to inspect
        source_env_prefix (str): The environment variable prefix that is used
            to get repository information.

    Returns:
        str: the username of the entity who triggered the graph.
        None: if not defined for this task.

    """
    return _extract_from_env_in_payload(task, source_env_prefix + "_TRIGGERED_BY")


def get_pull_request_number(task, source_env_prefix):
    """Get what Github pull request created the graph.

    Args:
        obj (ChainOfTrust or LinkOfTrust): the trust object to inspect
        source_env_prefix (str): The environment variable prefix that is used
            to get repository information.

    Returns:
        int: the pull request number.
        None: if not defined for this task.

    """
    pull_request = _extract_from_env_in_payload(task, source_env_prefix + "_PULL_REQUEST_NUMBER")
    if pull_request is not None:
        pull_request = int(pull_request)
    return pull_request


def get_push_date_time(task, source_env_prefix):
    """Get when a Github commit was pushed.

    We usually need to extract this piece of data from the task itself because Github doesn't
    expose reliable push data in the 3rd version of their API. This may happen in their future
    v4 API: https://developer.github.com/v4/object/push/.

    Args:
        obj (ChainOfTrust or LinkOfTrust): the trust object to inspect
        source_env_prefix (str): The environment variable prefix that is used
            to get repository information.

    Returns:
        str: the string when the event was pushed. It's usually formated as ISO 8601. However, it
            may be an epoch timestamp, (known case: github-push events).
        None: if not defined for this task.

    """
    return _extract_from_env_in_payload(task, source_env_prefix + "_PUSH_DATE_TIME")


def _extract_from_env_in_payload(task, key, default=None):
    return task["payload"].get("env", {}).get(key, default)


# get_worker_type {{{1
def get_worker_type(task):
    """Given a task dict, return the workerType.

    Args:
        task (dict): the task dict.

    Returns:
        str: the workerType.

    """
    return task["workerType"]


# get_provisioner_id {{{1
def get_provisioner_id(task):
    """Given a task dict, return the provisionerId.

    Args:
        task (dict): the task dict.

    Returns:
        str: the provisionerId.

    """
    return task["provisionerId"]


# get_worker_pool_id {{{1
def get_worker_pool_id(task):
    """Given a task dict, return the worker pool id.

    This corresponds to `{provisioner_id}/{workerType}`.

    Args:
        task (dict): the task dict.

    Returns:
        str: the workerPoolId.

    """
    return "{}/{}".format(get_provisioner_id(task), get_worker_type(task))


# get_project {{{1
async def get_project(context, source_url):
    """Given a source_url, return the project.

    The project is in the path, but is the repo name.
    `releases/mozilla-beta` is the path; `mozilla-beta` is the project.

    Args:
        source_url (str): the source url to find the project for.

    Raises:
        RuntimeError: on failure to find the project.

    Returns:
        str: the project.

    """
    await context.populate_projects()
    for project, config in context.projects.items():
        if source_url == config["repo"] or source_url.startswith(config["repo"] + "/"):
            return project
    raise ValueError("Unknown repo for source url {}!".format(source_url))


# get_and_check_tasks_for {{{1
def get_and_check_tasks_for(context, task, msg_prefix=""):
    """Given a parent task, return the reason the parent task was spawned.

    ``.taskcluster.yml`` uses this to know whether to spawn an action,
    cron, or decision task definition.  ``tasks_for`` must be a valid one defined in the context.

    Args:
        task (dict): the task definition.
        msg_prefix (str): the string prefix to use for an exception.

    Raises:
        (KeyError, ValueError): on failure to find a valid ``tasks_for``.

    Returns:
        str: the ``tasks_for``

    """
    tasks_for = task["extra"]["tasks_for"]
    if tasks_for not in context.config["valid_tasks_for"]:
        raise ValueError("{}Unknown tasks_for: {}".format(msg_prefix, tasks_for))
    return tasks_for


# get_repo_scope {{{1
def get_repo_scope(task, name):
    """Given a parent task, return the repo scope for the task.

    Background in https://bugzilla.mozilla.org/show_bug.cgi?id=1459705#c3

    Args:
        task (dict): the task definition.

    Raises:
        ValueError: on too many `repo_scope`s (we allow for 1 or 0).

    Returns:
        str: the ``repo_scope``
        None: if no ``repo_scope`` is found

    """
    repo_scopes = []
    for scope in task["scopes"]:
        if REPO_SCOPE_REGEX.match(scope):
            repo_scopes.append(scope)
    if len(repo_scopes) > 1:
        raise ValueError("{}: Too many repo_scopes: {}!".format(name, repo_scopes))
    if repo_scopes:
        return repo_scopes[0]


def _is_try_url(url):
    return "try" in get_parts_of_url_path(url)[0]


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
    # If get_repo() returns None, then _is_try_url() doesn't manage to process the URL
    repo = get_repo(task, source_env_prefix) or ""
    return any(
        (
            task["schedulerId"] in ("gecko-level-1",),
            "try" in _extract_from_env_in_payload(task, "MH_BRANCH", default=""),
            _is_try_url(repo),
            _is_try_url(task["metadata"].get("source", "")),
        )
    )


async def is_pull_request(context, task):
    """Determine if a task is a pull-request-like task (restricted privs).

    This goes further than checking ``tasks_for``. We may or may not want
    to keep this.

    This checks for the following things::

        * ``task.extra.env.tasks_for`` == "github-pull-request"
        * ``task.payload.env.MOBILE_HEAD_REPOSITORY`` doesn't come from an official repo
        * ``task.metadata.source`` doesn't come from an official repo, either
        * The last 2 items are landed on the official repo

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        task (dict): the task definition to check.

    Returns:
        bool: True if it's a pull-request. False if it either comes from the official repos or if
        the origin can't be determined. In fact, valid scriptworker tasks don't expose
        ``task.extra.env.tasks_for`` or ``task.payload.env.MOBILE_HEAD_REPOSITORY``, for instance.

    """
    tasks_for = task.get("extra", {}).get("tasks_for")
    repo_url_from_payload = get_repo(task, context.config["source_env_prefix"])
    revision_from_payload = get_revision(task, context.config["source_env_prefix"])

    metadata_source_url = task["metadata"].get("source", "")
    repo_from_source_url, revision_from_source_url = extract_github_repo_and_revision_from_source_url(metadata_source_url)

    conditions = [tasks_for == "github-pull-request"]
    urls_revisions_and_can_skip = ((repo_url_from_payload, revision_from_payload, True), (repo_from_source_url, revision_from_source_url, False))
    for repo_url, revision, can_skip in urls_revisions_and_can_skip:
        # XXX In the case of scriptworker tasks, neither the repo nor the revision is defined
        if not repo_url and can_skip:
            continue

        repo_url = repo_url.replace("git@github.com:", "ssh://github.com/", 1)

        repo_owner, repo_name = extract_github_repo_owner_and_name(repo_url)
        conditions.append(not is_github_repo_owner_the_official_one(context, repo_owner))

        if not revision and can_skip:
            continue

        github_repository = GitHubRepository(repo_owner, repo_name, context.config["github_oauth_token"])
        conditions.append(not await github_repository.has_commit_landed_on_repository(context, revision))

    return any(conditions)


async def is_try_or_pull_request(context, task):
    """Determine if a task is a try or a pull-request-like task (restricted privs).

    Checks are the ones done in ``is_try`` and ``is_pull_request``

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        task (dict): the task definition to check.

    Returns:
        bool: True if it's a pull-request or a try task

    """
    if is_github_task(task):
        return await is_pull_request(context, task)
    else:
        return is_try(task, context.config["source_env_prefix"])


def is_github_task(task):
    """Determine if a task is related to GitHub.

    This function currently looks into the ``schedulerId``, ``extra.tasks_for``, and
    ``metadata.source``.

    Args:
        task (dict): the task definition to check.

    Returns:
        bool: True if a piece of data refers to GitHub

    """
    return any(
        (
            # XXX Cron tasks don't usually define 'taskcluster-github' as their schedulerId as they
            # are scheduled within another Taskcluster task.
            task.get("schedulerId") == "taskcluster-github",
            # XXX Same here, cron tasks don't start with github
            task.get("extra", {}).get("tasks_for", "").startswith("github-"),
            is_github_url(task.get("metadata", {}).get("source", "")),
        )
    )


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
    if _extract_from_env_in_payload(task, "ACTION_CALLBACK"):
        result = True
    if task.get("extra", {}).get("action") is not None:
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
    current_task_info["taskId"] = context.task_id
    current_task_info["runId"] = get_run_id(claim_task)
    log.info("Going to run taskId {taskId} runId {runId}!".format(**current_task_info))
    context.write_json(os.path.join(context.config["work_dir"], "current_task_info.json"), current_task_info, "Writing current task info to {path}...")
    return current_task_info


# run_task {{{1
async def run_task(context, to_cancellable_process):
    """Run the task, sending stdout+stderr to files.

    https://github.com/python/asyncio/blob/master/examples/subprocess_shell.py

    Args:
        context (scriptworker.context.Context): the scriptworker context.
        to_cancellable_process (types.Callable): tracks the process so that it can be stopped if the worker is shut down

    Returns:
        int: 1 on failure, 0 on success

    """
    env = deepcopy(os.environ)
    env["TASK_ID"] = context.task_id or "None"
    kwargs = {"stdout": PIPE, "stderr": PIPE, "stdin": None, "close_fds": True, "preexec_fn": lambda: os.setsid(), "env": env}  # pragma: no branch

    subprocess = await asyncio.create_subprocess_exec(*context.config["task_script"], **kwargs)
    context.proc = await to_cancellable_process(TaskProcess(subprocess))
    timeout = context.config["task_max_timeout"]

    with get_log_filehandle(context) as log_filehandle:
        stderr_future = asyncio.ensure_future(pipe_to_log(context.proc.process.stderr, filehandles=[log_filehandle]))
        stdout_future = asyncio.ensure_future(pipe_to_log(context.proc.process.stdout, filehandles=[log_filehandle]))
        try:
            _, pending = await asyncio.wait([stderr_future, stdout_future], timeout=timeout)
            if pending:
                message = "Exceeded task_max_timeout of {} seconds".format(timeout)
                log.warning(message)
                await context.proc.stop()
                raise ScriptWorkerTaskException(message, exit_code=context.config["task_max_timeout_status"])
        finally:
            # in the case of a timeout, this will be -15.
            # this code is in the finally: block so we still get the final
            # log lines.
            exitcode = await context.proc.process.wait()
            # make sure we haven't lost any of the logs
            await asyncio.wait([stdout_future, stderr_future])
            # add an exit code line at the end of the log
            status_line = "exit code: {}".format(exitcode)
            if exitcode < 0:
                status_line = "Automation Error: python exited with signal {}".format(exitcode)
            log.info(status_line)
            print(status_line, file=log_filehandle)
            stopped_due_to_worker_shutdown = context.proc.stopped_due_to_worker_shutdown
            context.proc = None

    if stopped_due_to_worker_shutdown:
        raise WorkerShutdownDuringTask

    return 1 if exitcode != 0 else 0


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
            from taskcluster.aio.Queue.reclaimTask()

    """
    while True:
        log.debug("waiting %s seconds before reclaiming..." % context.config["reclaim_interval"])
        await asyncio.sleep(context.config["reclaim_interval"])
        if task != context.task:
            return
        log.debug("Reclaiming task...")
        try:
            context.reclaim_task = await context.temp_queue.reclaimTask(get_task_id(context.claim_task), get_run_id(context.claim_task))
            clean_response = deepcopy(context.reclaim_task)
            clean_response["credentials"] = "{********}"
            log.debug("Reclaim task response:\n{}".format(pprint.pformat(clean_response)))
        except taskcluster.exceptions.TaskclusterRestFailure as exc:
            if exc.status_code == 409:
                log.debug("409: not reclaiming task.")
                if context.proc and task == context.task:
                    message = "Killing task after receiving 409 status in reclaim_task"
                    log.warning(message)
                    await context.proc.stop()
                    raise ScriptWorkerTaskException(message, exit_code=context.config["invalid_reclaim_status"])
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
    reversed_statuses = get_reversed_statuses(context)
    try:
        if result == 0:
            log.info("Reporting task complete...")
            response = await context.temp_queue.reportCompleted(*args)
        elif result != 1 and result in reversed_statuses:
            reason = reversed_statuses[result]
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


# claim_work {{{1
async def claim_work(context):
    """Find and claim the next pending task in the queue, if any.

    Args:
        context (scriptworker.context.Context): the scriptworker context.

    Returns:
        dict: a dict containing a list of the task definitions of the tasks claimed.

    """
    log.debug("Calling claimWork for {}/{}...".format(context.config["worker_group"], context.config["worker_id"]))
    payload = {
        "workerGroup": context.config["worker_group"],
        "workerId": context.config["worker_id"],
        # Hardcode one task at a time.  Make this a pref if we allow for
        # parallel tasks in multiple `work_dir`s.
        "tasks": 1,
    }
    try:
        return await context.queue.claimWork(context.config["provisioner_id"], context.config["worker_type"], payload)
    except (taskcluster.exceptions.TaskclusterFailure, aiohttp.ClientError, asyncio.TimeoutError) as exc:
        log.warning("{} {}".format(exc.__class__, exc))
