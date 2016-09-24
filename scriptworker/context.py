#!/usr/bin/env python
"""Most functions need access to a similar set of objects.  Rather than
having to pass them all around individually or create a monolithic 'self'
object, let's point to them from a single context object.


Attributes:
    log (logging.Logger): the log object for the module.
"""
import arrow
from copy import deepcopy
import json
import logging
import os

from scriptworker.utils import makedirs
from taskcluster.async import Queue

log = logging.getLogger(__name__)


class Context(object):
    """ Basic config holding object.

    Avoids putting everything in single monolithic object, but allows for
    passing around config and easier overriding in tests.

    Attributes:
        config (dict): the running config.  In production this will be a
            FrozenDict.
        credentials_timestamp (int): the unix timestamp when we last updated
            our credentials.
        poll_task_urls (dict): contains the Azure `queues` urls and an `expires`
            datestring.
        proc (asyncio.subprocess.Process): when launching the script, this is
            the process object.
        queue (taskcluster.async.Queue): the taskcluster Queue object
            containing the scriptworker credentials.
        session (aiohttp.ClientSession): the default aiohttp session
        task (dict): the task definition for the current task.
        temp_queue (taskcluster.async.Queue): the taskcluster Queue object
            containing the task-specific temporary credentials.
    """
    config = None
    cot_config = None
    credentials_timestamp = None
    poll_task_urls = None
    proc = None
    queue = None
    session = None
    task = None
    temp_queue = None
    _credentials = None
    _claim_task = None  # This assumes a single task per worker.
    _temp_credentials = None  # This assumes a single task per worker.
    _reclaim_task = None

    @property
    def claim_task(self):
        """dict: The current or most recent claimTask definition json from the queue.

        This contains the task definition, as well as other task-specific
        info.

        When setting `claim_task`, we also set `self.task` and
        `self.temp_credentails`, zero out `self.reclaim_task` and `self.proc`,
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
        """dict: The current scriptworker credentials, from the config or CREDS_FILES
        or environment.

        When setting credentials, also create a new `self.queue` and
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
            return Queue({
                'credentials': credentials,
            }, session=self.session)

    @property
    def reclaim_task(self):
        """dict: The most recent reclaimTask definition.

        This contains the newest expiration time and the newest temp credentials.

        When setting reclaim_task, we also set self.temp_credentials.

        reclaim_task will be None if there hasn't been a claimed task yet,
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
        """dict: The latest temp credentials, or None if we haven't claimed a
            task yet.

        When setting, create `self.temp_queue` from the temp taskcluster creds.
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
