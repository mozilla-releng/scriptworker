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
import json
import logging
import os
import signal
import tempfile

from scriptworker.utils import makedirs, load_json_or_yaml_from_url
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
class WorkerContext(object):
    """The context for the running scriptworker.

    Attributes:
        running_tasks (list): a list of running TaskContext objects.

    """

    running_tasks = []
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


# TaskContext {{{1
class TaskContext(BaseWorkerContext):
    """Context for a running task process inside a scriptworker.

    This was split out from WorkerContext when we decided to support
    multiple concurrent tasks per scriptworker.

    Attributes:
        claim_task (dict): the claim_task definition for the current task.
        credentials (dict): the temporary credentials for the current task.
        process (task_process.TaskProcess): when launching the script, this
            is the process object.
        stopped_due_to_worker_shutdown (bool): whether this task has stopped
            due to worker shutdown.
        task (dict): the task definition for the current task.
        work_dir (str): the path to the working directory
        artifact_dir (str): the path to the artifact directory
        task_log_dir (str): the path to the task logging directory

    """

    proc = None
    process = None
    stopped_due_to_worker_shutdown = False
    _reclaim_task = None

    def __init__(self, context, claim_task, task_num):
        """Context for an invidual task running in a scriptworker.

        This is separate from the worker context because there can be
        multiple tasks running concurrently in a single worker.

        """
        self._task_num = task_num
        self.config = context.config
        self.event_loop = context.event_loop
        self.session = context.session
        self.work_dir = os.path.join(
            self.config["base_work_dir"],
            str(self._task_num)
        )
        self.artifact_dir = os.path.join(
            self.config["base_artifact_dir"],
            str(self._task_num)
        )
        self.task_log_dir = self.config["task_log_dir"] % {
            "artifact_dir": self.artifact_dir,
        }
        makedirs(self.work_dir)
        makedirs(self.artifact_dir)
        makedirs(self.task_log_dir)
        self.claim_task = claim_task
        self.task = claim_task['task']
        self.credentials = claim_task['credentials']
        self.task_id = self.claim_task['status']['taskId']
        self.run_id = self.claim_task['runId']

    async def worker_shutdown_stop(self):
        """Invoke on worker shutdown to stop task process."""
        self.stopped_due_to_worker_shutdown = True
        await self.stop()

    async def stop(self):
        """Stop the current task process.

        Starts with SIGTERM, gives the process 1 second to terminate, then kills it

        """
        # negate pid so that signals apply to process group
        pgid = -self.process.pid
        try:
            os.kill(pgid, signal.SIGTERM)
            await asyncio.sleep(1)
            os.kill(pgid, signal.SIGKILL)
            self.running = False
        except (OSError, ProcessLookupError):
            return

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

    def write_json(self, path, contents, message):
        """Write json to disk.

        Args:
            path (str): the path to write to
            contents (dict): the contents of the json blob
            message (str): the message to log

        """
        log.debug(message.format(path=path))
        makedirs(os.path.dirname(path))
        with open(path, "w") as fh:
            json.dump(contents, fh, indent=2, sort_keys=True)
