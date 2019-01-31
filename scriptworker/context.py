#!/usr/bin/env python
"""scriptworker context.

Most functions need access to a similar set of objects.  Rather than
having to pass them all around individually or create a monolithic 'self'
object, let's point to them from a single context object.

Attributes:
    log (logging.Logger): the log object for the module.

"""
import aiohttp
import arrow
import asyncio
from copy import deepcopy
import json
import logging
import os
import tempfile

from scriptworker.utils import makedirs, load_json_or_yaml_from_url
from taskcluster.aio import Queue

log = logging.getLogger(__name__)


class Context(object):
    """Basic config holding object.

    Avoids putting everything in single monolithic object, but allows for
    passing around config and easier overriding in tests.

    Attributes:
        config (dict): the running config.  In production this will be a
            FrozenDict.
        credentials_timestamp (int): the unix timestamp when we last updated
            our credentials.
        proc (task_process.TaskProcess): when launching the script, this is
            the process object.
        queue (taskcluster.aio.Queue): the taskcluster Queue object
            containing the scriptworker credentials.
        session (aiohttp.ClientSession): the default aiohttp session
        task (dict): the task definition for the current task.
        temp_queue (taskcluster.aio.Queue): the taskcluster Queue object
            containing the task-specific temporary credentials.

    """

    config = None
    credentials_timestamp = None
    proc = None
    queue = None
    session = None
    task = None
    temp_queue = None
    running_tasks = None
    _credentials = None
    _claim_task = None  # This assumes a single task per worker.
    _event_loop = None
    _temp_credentials = None  # This assumes a single task per worker.
    _reclaim_task = None
    _projects = None

    @property
    def claim_task(self):
        """dict: The current or most recent claimTask definition json from the queue.

        This contains the task definition, as well as other task-specific
        info.

        When setting ``claim_task``, we also set ``self.task`` and
        ``self.temp_credentials``, zero out ``self.reclaim_task`` and ``self.proc``,
        then write a task.json to disk.

        """
        return self._claim_task

    @claim_task.setter
    def claim_task(self, claim_task):
        self._claim_task = claim_task
        self.reclaim_task = None
        self.proc = None
        if claim_task:
            self.task = claim_task['task']
            self.temp_credentials = claim_task['credentials']
            path = os.path.join(self.config['work_dir'], "task.json")
            self.write_json(path, self.task, "Writing task file to {path}...")
        else:
            self.temp_credentials = None
            self.task = None

    @property
    def credentials(self):
        """dict: The current scriptworker credentials.

        These come from the config or CREDS_FILES or environment.

        When setting credentials, also create a new ``self.queue`` and
        update self.credentials_timestamp.

        """
        if self._credentials:
            return dict(deepcopy(self._credentials))

    @credentials.setter
    def credentials(self, creds):
        self._credentials = creds
        self.queue = self.create_queue(self.credentials)
        self.credentials_timestamp = arrow.utcnow().timestamp

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

    @property
    def reclaim_task(self):
        """dict: The most recent reclaimTask definition.

        This contains the newest expiration time and the newest temp credentials.

        When setting ``reclaim_task``, we also set ``self.temp_credentials``.

        ``reclaim_task`` will be ``None`` if there hasn't been a claimed task yet,
        or if a task has been claimed more recently than the most recent
        reclaimTask call.

        """
        return self._reclaim_task

    @reclaim_task.setter
    def reclaim_task(self, value):
        self._reclaim_task = value
        if value is not None:
            self.temp_credentials = value['credentials']

    @property
    def temp_credentials(self):
        """dict: The latest temp credentials, or None if we haven't claimed a task yet.

        When setting, create ``self.temp_queue`` from the temp taskcluster creds.

        """
        if self._temp_credentials:
            return dict(deepcopy(self._temp_credentials))

    @temp_credentials.setter
    def temp_credentials(self, credentials):
        self._temp_credentials = credentials
        self.temp_queue = self.create_queue(self.temp_credentials)

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
