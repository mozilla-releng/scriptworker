#!/usr/bin/env python
"""scriptworker context.

Most functions need access to a similar set of objects.  Rather than
having to pass them all around individually or create a monolithic 'self'
object, let's point to them from a single context object.

::

               BaseContext
                     |
          -----------------------
          |                     |
    ScriptContext       BaseWorkerContext
                                |
                     -----------------------
                     |                     |
               WorkerContext          TaskContext

Attributes:
    log (logging.Logger): the log object for the module.

"""
import aiohttp
import asyncio
from copy import deepcopy
import logging
import os
import tempfile

from scriptworker.utils import load_json_or_yaml_from_url
from taskcluster.aio import Queue

log = logging.getLogger(__name__)


# BaseContext {{{1
class BaseContext(object):
    """Base context object.

    Allows for passing around config and easier overriding in tests.
    Most likely we'll be using non-Base context objects.

    Attributes:
        config (dict): the running config.  In production this will be a
            FrozenDict.
        session (aiohttp.ClientSession): the default aiohttp session

    """

    config = None
    session = None


# ScriptContext {{{1
class ScriptContext(BaseContext):
    """Script context object (e.g. scriptworker.client).

    We'll use this until we transition away from using context objects
    in our scripts.

    Attributes:
        task (dict): the running task definition

    """

    task = None


# BaseWorkerContext {{{1
class BaseWorkerContext(BaseContext):
    """Base worker context.

    Contains shared structure between both ``WorkerContext`` and
    ``TaskContext``.

    Scripts shouldn't need to use worker context objects

        queue (taskcluster.aio.Queue): the taskcluster Queue object
            containing the scriptworker credentials.

    """

    queue = None
    _credentials = None
    _event_loop = None
    _projects = None

    @property
    def projects(self):
        """dict: The current contents of ``projects.yml``, which defines CI configuration.

        I'd love to auto-populate this; currently we need to set this from
        the config's ``project_configuration_url``.

        """
        if self._projects:
            return dict(deepcopy(self._projects))

    @projects.setter
    def projects(self, projects):
        self._projects = projects

    async def populate_projects(self, force=False):
        """Download the ``projects.yml`` file and populate ``self.projects``.

        This only sets it once, unless ``force`` is set.

        Args:
            force (bool, optional): Re-run the download, even if ``self.projects``
                is already defined. Defaults to False.

        """
        if force or not self.projects:
            with tempfile.TemporaryDirectory() as tmpdirname:
                self.projects = await load_json_or_yaml_from_url(
                    self, self.config['project_configuration_url'],
                    os.path.join(tmpdirname, 'projects.yml')
                )

    @property
    def event_loop(self):
        """asyncio.BaseEventLoop: the running event loop.

        This fixture mainly exists to allow for overrides during unit tests.

        """
        if not self._event_loop:
            self._event_loop = asyncio.get_event_loop()
        return self._event_loop

    @event_loop.setter
    def event_loop(self, event_loop):
        self._event_loop = event_loop

    @property
    def credentials(self):
        """dict: The current scriptworker credentials.

        These come from the config or CREDS_FILES or environment.

        When setting credentials, also create a new ``self.queue``.

        """
        if self._credentials:
            return dict(deepcopy(self._credentials))

    @credentials.setter
    def credentials(self, creds):
        self._credentials = creds
        self.queue = self.create_queue(self.credentials)

    def create_queue(self, credentials):
        """Create a taskcluster queue.

        Args:
            credentials (dict): taskcluster credentials.

        """
        if credentials:
            session = self.session or aiohttp.ClientSession(loop=self.event_loop)
            return Queue(
                options={
                    'credentials': credentials,
                    'rootUrl': self.config['taskcluster_root_url'],
                },
                session=session
            )


# WorkerContext {{{1
class WorkerContext(BaseWorkerContext):
    """The context for the running scriptworker.

    Attributes:
        running_tasks (list): a list of running TaskContext objects.

    """

    running_tasks = []


# TaskContext {{{1
class TaskContext(BaseWorkerContext):
    """Context for a running task process inside a scriptworker.

    This was split out from WorkerContext when we decided to support
    multiple concurrent tasks per scriptworker.

    Attributes:
        claim_task (dict): the claim_task definition for the current task.
        credentials (dict): the temporary credentials for the current task.
        task_process (task_process.TaskProcess): when launching the script,
            this is the process object.
        task (dict): the task definition for the current task.
        work_dir (str): the path to the working directory
        artifact_dir (str): the path to the artifact directory
        task_log_dir (str): the path to the task logging directory

    """

    artifact_dir = None
    projects = None
    run_id = None
    task = None
    task_id = None
    task_log_dir = None
    task_process = None
    work_dir = None
    _claim_task = None
    _reclaim_task = None
    _task_num = None

    @property
    def task_id(self):
        """string: The running task's taskId."""
        if self.claim_task:
            return self.claim_task['status']['taskId']

    @property
    def run_id(self):
        """string: The running task's runId."""
        if self.claim_task:
            return self.claim_task['runId']

    @property
    def claim_task(self):
        """dict: The current or most recent claimTask definition json from the queue.

        This contains the task definition, as well as other task-specific
        info.

        When setting ``claim_task``, we also set ``self.task`` and
        ``self.temp_credentials``, zero out ``self.reclaim_task`` and ``self.proc``.

        """
        return self._claim_task

    @claim_task.setter
    def claim_task(self, claim_task):
        self._claim_task = claim_task
        self.reclaim_task = None
        self.task_process = None
        self.task = claim_task['task']
        self.credentials = claim_task['credentials']

    @property
    def reclaim_task(self):
        """dict: The most recent reclaimTask definition.

        This contains the newest expiration time and the newest temp credentials.

        When setting ``reclaim_task``, we also set ``self.credentials``.

        ``reclaim_task`` will be ``None`` if there hasn't been a claimed task yet,
        or if a task has been claimed more recently than the most recent
        reclaimTask call.

        """
        return self._reclaim_task

    @reclaim_task.setter
    def reclaim_task(self, value):
        self._reclaim_task = value
        if value is not None:
            self.credentials = value['credentials']


def set_task_context_paths(task_context, task_num=None):
    """Set the various task-specific directories in a given TaskContext.

    If ``task_num`` is set, and we run more than 1 task concurrently,
    we should include ``task_num`` in our directory paths to avoid
    sharing work/artifact directories.

    Args:
        task_context (TaskContext): the task context
        task_num (int, optional): the unique number for this task. If
            we're running 3 concurrent tasks, we'll have a 0, 1, and a 2.

    """
    if task_num is not None and task_context.config["num_concurrent_tasks"] > 1:
        task_context._task_num = task_num
        task_context.work_dir = os.path.join(
            task_context.config["base_work_dir"],
            str(task_context._task_num)
        )
        task_context.artifact_dir = os.path.join(
            task_context.config["base_artifact_dir"],
            str(task_context._task_num)
        )
    else:
        task_context.work_dir = task_context.config["base_work_dir"]
        task_context.artifact_dir = task_context.config["base_artifact_dir"]
    task_context.task_log_dir = task_context.config["task_log_dir_template"] % {
        "artifact_dir": task_context.artifact_dir,
    }


def create_task_context(config, claim_task, task_num=None,
                        event_loop=None, session=None, projects=None):
    """Create a TaskContext from a WorkerContext, claim_task, and task_num.

    Args:
        config (dict): the running config
        claim_task (dict): the claimTask response
        task_num (int, optional): the task number. This differentiates
            concurrent tasks from each other. If we can claim 3 concurrent
            tasks, the task contexts would have task_nums of 0, 1, and 2.
        event_loop (asyncio.BaseEventLoop, optional): the event loop to use
        session (aiohttp.ClientSession, optional): the session to use
        projects (dict): the contents of ci-configuration/projects.yml

    Returns:
        TaskContext: the task context.

    """
    task_context = TaskContext()
    task_context.config = config
    set_task_context_paths(task_context, task_num=task_num)
    task_context.event_loop = event_loop
    task_context.session = session
    task_context.projects = projects
    task_context.claim_task = claim_task
    return task_context
