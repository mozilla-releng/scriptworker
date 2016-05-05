#!/usr/bin/env python
"""Most functions need access to a similar set of objects.  Rather than
having to pass them all around individually or create a monolithic 'self'
object, let's point to them from a single context object.
"""
import arrow
from copy import deepcopy
import json
import logging
import os
import time

from scriptworker.utils import makedirs
from taskcluster.async import Queue

log = logging.getLogger(__name__)


# TODO create a WorkerContext child, so child tasks can use Context?
class Context(object):
    """ Basic config holding object.

    Avoids putting everything in a big object, but allows for passing around
    config and easier overriding in tests.
    """
    config = None
    credentials_timestamp = None
    poll_task_urls = None
    proc = None
    queue = None
    session = None
    temp_queue = None
    _credentials = None
    _task = None  # This assumes a single task per worker.
    _temp_credentials = None  # This assumes a single task per worker.
    _reclaim_task = None

    @property
    def task(self):
        """The current or most recent claimed task definition json from the queue.
        """
        return self._task

    @task.setter
    def task(self, task):
        """Set the task, then write a task.json to disk and update
        `self.temp_credentials`.  Zero out `self.reclaim_task` because we
        haven't reclaimed this task yet.
        """
        self._task = task
        self.reclaim_task = None
        self.proc = None
        path = os.path.join(self.config['work_dir'], "task.json")
        self.write_json(path, task, "Writing task file to {path}...")
        if task:
            self.temp_credentials = task['credentials']
        else:
            self.temp_credentials = None

    @property
    def credentials(self):
        """The current or most recent claimed task definition json from the queue.
        """
        if self._credentials:
            return dict(deepcopy(self._credentials))

    @credentials.setter
    def credentials(self, creds):
        """Set the credentials, and create a new Queue.
        """
        self._credentials = creds
        self.queue = self.create_queue(self.credentials)
        if creds:
            self.credentials_timestamp = arrow.utcnow().timestamp

    def create_queue(self, credentials):
        if credentials:
            return Queue({
                'credentials': credentials,
            }, session=self.session)

    @property
    def reclaim_task(self):
        """The most recent reclaimTask definition -- this contains the newest
        expiration time and the newest temp credentials.

        reclaim_task will be None if there hasn't been a claimed task yet,
        or if a task has been claimed more recently than the most recent
        reclaimTask call.
        """
        return self._reclaim_task

    @reclaim_task.setter
    def reclaim_task(self, value):
        """Set the reclaim_task json (or None if a new task has been claimed)

        If `value` is json, write it to disk with a timestamp so we can try to
        avoid i/o race conditions.  Then update `self.temp_credentials`
        """
        self._reclaim_task = value
        if value is not None:
            path = os.path.join(self.config['work_dir'],
                                "reclaim_task.{}.json".format(time.time()))
            self.write_json(path, value, "Writing reclaim_task file to {path}...")
            # TODO we may not need the reclaim_task.json or credentials.json...
            self.temp_credentials = value['credentials']

    @property
    def temp_credentials(self):
        """The latest temp credentials, or None if we haven't claimed a task
        yet.
        """
        if self._temp_credentials:
            return dict(deepcopy(self._temp_credentials))

    @temp_credentials.setter
    def temp_credentials(self, credentials):
        """Set the temp_credentials from the latest claimTask or reclaimTask
        call.

        Write these to disk with a timestamp so we can try to avoid i/o race
        conditions.
        """
        self._temp_credentials = credentials
        self.temp_queue = self.create_queue(self.temp_credentials)
        path = os.path.join(self.config['work_dir'],
                            "credentials.{}.json".format(time.time()))
        self.write_json(path, credentials, "Writing credentials file to {path}...")

    def write_json(self, path, contents, message):
        """Write json to disk.
        """
        if contents:
            log.debug(message.format(path=path))
            parent_dir = os.path.dirname(path)
            if parent_dir:
                makedirs(os.path.dirname(path))
            with open(path, "w") as fh:
                json.dump(contents, fh, indent=2, sort_keys=True)
