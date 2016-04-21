#!/usr/bin/env python
# X  queue - poll task urls
# X   signedPollUrls
# X  for each url, azure get(SignedPollUrls[i++ % n])
# X   polling...
# X   <QueueMessagesList/>
# X  queue - claimTask
# X   status
# X    on 409, try the next one
# X   azure - delete <PopReceipt/>
# X  executing task
# X   - create config files
# X    - temp creds - in the task json
# X    - job metadata, payload - in the task json
# X   - launch script
# X   during task, queue - reclaimTask periodically
# _  createArtifact
# X  queue -> reportCompleted
# _ worker logfile
# _ log rotation
import aiohttp
import asyncio
import atexit
import base64
import datetime
import defusedxml.ElementTree
import json
import logging
import os
import pprint
import shutil
import time
import urllib.parse

from asyncio.subprocess import PIPE
from contextlib import contextmanager
from frozendict import frozendict

import taskcluster
import taskcluster.exceptions
from taskcluster.async import Queue

DEFAULT_CONFIG = {
    "provisioner_id": "test-dummy-provisioner",
    "scheduler_id": "test-dummy-scheduler",
    "worker_group": "test-dummy-workers",
    "worker_type": "dummy-worker-aki",
    "taskcluster_client_id": "...",
    "taskcluster_access_token": "...",
    "work_dir": "...",
    "log_dir": "...",
    "artifact_dir": "...",
    "worker_id": "dummy-worker-aki1",
    "max_connections": 30,
    "reclaim_interval": 5,  # TODO 300
    "poll_interval": 5,  # TODO 1 ?
    "task_script": ("bash", "-c", "echo foo && sleep 19 && exit 2"),
    "verbose": True
}
log = logging.getLogger(__name__)


def create_config(filename="secrets.json"):
    # TODO configurability -- cmdln arguments
    with open(filename, "r") as fh:
        secrets = json.load(fh)

    config = dict(DEFAULT_CONFIG).copy()
    config.update(secrets)
    # TODO verify / dtd
    config = frozendict(config)
    return config


async def fetch(context, url, timeout=60, method='get', good=(200, )):
    session = context.session
    with aiohttp.Timeout(timeout):
        log.debug("{} {}".format(method.upper(), url))
        async with session.request(method, url) as resp:
            log.debug("Status {}".format(resp.status))
            assert resp.status in good  # TODO log/retry
            return await resp.text()


def datestring_to_timestamp(datestring):
    """ Create a timetamp from a taskcluster datestring
    datestring: a string in the form of "2016-04-16T03:46:24.958Z"
    """
    datestring = datestring.split('.')[0]
    return time.mktime(
        datetime.datetime.strptime(datestring, "%Y-%m-%dT%H:%M:%S").timetuple()
    )


def parse_message(message):
    message_info = {}
    interesting_keys = {
        "MessageId": "messageId",
        "PopReceipt": "popReceipt",
        "MessageText": "messageText",
    }
    for element in message:
        if element.tag in interesting_keys:
            message_info[interesting_keys[element.tag]] = element.text
            log.debug("{} {}".format(element.tag, element.text))
    message_info['popReceipt'] = urllib.parse.quote(message_info['popReceipt'])
    message_info['task_info'] = json.loads(
        base64.b64decode(message_info['messageText']).decode('utf-8')
    )
    return message_info


def parse_xml(xml):
    et = defusedxml.ElementTree.fromstring(xml)
    for message in et:
        yield parse_message(message)


async def claim_task(queue, config, taskId, runId):
    payload = {
        'workerGroup': config['worker_group'],
        'workerId': config['worker_id'],
    }
    try:
        result = await queue.claimTask(taskId, runId, payload)
        log.debug("claim_task:")
        log.debug(pprint.pformat(result))
        return result
    except taskcluster.exceptions.TaskclusterFailure as exc:
        # TODO 409 is expected.  Not sure if we should ignore other errors?
        log.debug("Got %s" % exc)
        return None


def get_azure_urls(context):
    for queue_defn in context.poll_task_urls['queues']:
        yield queue_defn['signedPollUrl'], queue_defn['signedDeleteUrl']


async def find_task(context, poll_url, delete_url, fetch_function):
    xml = await fetch_function(context, poll_url)
    log.debug("find_task xml:")
    log.debug(xml)
    for message_info in parse_xml(xml):
        log.debug(message_info['task_info'])
        task = await claim_task(context.queue, context.config, **message_info['task_info'])
        delete_url = delete_url.replace("{{", "{").replace("}}", "}").format(**message_info)
        response = await fetch_function(context, delete_url, method='delete', good=[200, 204])
        log.debug(response)
        if task is not None:
            return task


def update_logging_config(context, log):
    datefmt = '%H:%M:%S'
    fmt = '%(asctime)s %(levelname)8s - %(message)s'

    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)
    if context.config.get("verbose"):
        log.setLevel(logging.DEBUG)
        if len(log.handlers) == 0:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            log.addHandler(handler)
    log.addHandler(logging.NullHandler())


async def update_poll_task_urls(context, callback, min_seconds_left=300, args=(), kwargs=None):
    """Queue.pollTaskUrls() returns an ordered list of Azure url pairs to
    poll for task "hints".  This list is valid until expiration.

    This function checks for an up-to-date poll_task_urls; if non-existent
    or near expiration, get new poll_task_urls.

    http://docs.taskcluster.net/queue/worker-interaction/
    """
    urls = context.poll_task_urls
    if urls is not None:
        # check expiration
        expires = datestring_to_timestamp(urls['expires'])
        # is this right? 7+ hrs?
        seconds_left = int(expires - time.time())
        log.debug("poll_task_urls expires in %d seconds" % seconds_left)
        if seconds_left >= min_seconds_left:
            return
    log.debug("Updating poll_task_urls...")
    kwargs = kwargs or {}
    context.poll_task_urls = await callback(*args, **kwargs)


def to_unicode(line):
    try:
        line = line.decode('utf-8')
    except UnicodeDecodeError:
        pass
    return line


async def log_errors(reader, log_fh, error_fh):
    while True:
        line = await reader.readline()
        if not line:
            break
        line = to_unicode(line)
        log.debug('ERROR {}'.format(line.rstrip()))
        print('ERROR {}'.format(line), file=log_fh, end="")
        print(line, file=error_fh, end="")


async def read_stdout(stdout, log_fh):
    while True:
        line = await stdout.readline()
        if line:
            log.debug(to_unicode(line.rstrip()))
            print(to_unicode(line), file=log_fh, end="")
        else:
            break


def get_log_filenames(context):
    log_file = os.path.join(context.config['log_dir'], 'task_output.log')
    error_file = os.path.join(context.config['log_dir'], 'task_error.log')
    return log_file, error_file


@contextmanager
def get_log_fhs(context):
    log_file, error_file = get_log_filenames(context)
    makedirs(context.config['log_dir'])
    with open(log_file, "w") as log_fh:
        with open(error_file, "w") as error_fh:
            yield (log_fh, error_fh)


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


def makedirs(path):
    if not os.path.exists(path):
        os.makedirs(path)


class Context(object):
    """ Basic config object.

    Avoids putting everything in a big object, but allows for passing around
    config and easier overriding in tests.
    """
    config = None
    poll_task_urls = None
    session = None
    queue = None
    _task = None  # This assumes a single task per worker.
    _temp_credentials = None  # This assumes a single task per worker.
    _reclaim_task = None

    @property
    def task(self):
        return self._task

    @task.setter
    def task(self, task):
        self._task = task
        path = os.path.join(self.config['work_dir'], "task.json")
        self.write_json(path, task, "Writing task file to {path}...")
        self.temp_credentials = task['credentials']
        self.reclaim_task = None
        # TODO payload.json ?

    @property
    def reclaim_task(self):
        return self._reclaim_task

    @reclaim_task.setter
    def reclaim_task(self, value):
        self._reclaim_task = value
        if value is not None:
            path = os.path.join(self.config['work_dir'],
                                "reclaim_task.{}.json".format(int(time.time())))
            self.write_json(path, value, "Writing reclaim_task file to {path}...")
            # TODO we may not need the reclaim_task.json or credentials.json...
            self.temp_credentials = value['credentials']

    @property
    def temp_credentials(self):
        return self._temp_credentials

    @temp_credentials.setter
    def temp_credentials(self, credentials):
        self._temp_credentials = credentials
        path = os.path.join(self.config['work_dir'],
                            "credentials.{}.json".format(int(time.time())))
        self.write_json(path, credentials, "Writing credentials file to {path}...")

    def write_json(self, path, contents, message):
        log.debug(message.format(path=path))
        parent_dir = os.path.dirname(path)
        if parent_dir:
            makedirs(os.path.dirname(path))
        with open(path, "w") as fh:
            json.dump(contents, fh, indent=2, sort_keys=True)


def close_asyncio_loop():
    """https://bugs.python.org/msg240248
    """
    loop = None
    try:
        loop = asyncio.get_event_loop()
    except AttributeError:
        pass
    if loop is not None:
        log.debug("Closing event loop with the following tasks still scheduled:")
        log.debug(asyncio.Task.all_tasks(loop=loop))
        loop.close()


def get_temp_queue(context):
    temp_queue = Queue({
        'credentials': context.temp_credentials,
    }, session=context.session)
    return temp_queue


async def reclaim_task(context, task):
    """
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
    loop = asyncio.get_event_loop()
    loop.create_task(reclaim_task(context, task))


def cleanup(context):
    for name in 'work_dir', 'artifact_dir':
        path = context.config[name]
        if os.path.exists(path):
            log.debug("rmtree({})".format(path))
            shutil.rmtree(path)
        makedirs(path)


async def async_main(context):
    loop = asyncio.get_event_loop()
    while True:
        await update_poll_task_urls(
            context, context.queue.pollTaskUrls,
            args=(context.config['provisioner_id'], context.config['worker_type']),
        )
        for poll_url, delete_url in get_azure_urls(context):
            task_defn = await find_task(context, poll_url, delete_url, fetch)
            if task_defn:
                log.info("Going to run task!")
                context.task = task_defn
                # TODO write this to a known location for the script:
                # script work_dir ?
                loop.call_later(context.config['reclaim_interval'],
                                schedule_reclaim_task, context, context.task)
                running_task = loop.create_task(run_task(context))
                await running_task
                # TODO upload artifacts
                await complete_task(context, running_task.result())
                # TODO cleanup(context)
                break
        else:
            await asyncio.sleep(context.config['poll_interval'])


def main():
    context = Context()
    context.config = create_config()
    update_logging_config(context, log)
    cleanup(context)
    conn = aiohttp.TCPConnector(limit=context.config["max_connections"])
    loop = asyncio.get_event_loop()
    atexit.register(close_asyncio_loop)
    with aiohttp.ClientSession(connector=conn) as session:
        context.session = session
        context.queue = Queue({
            'credentials': {
                'clientId': context.config['taskcluster_client_id'],
                'accessToken': context.config['taskcluster_access_token'],
            }
        }, session=context.session)
        loop.create_task(async_main(context))
        loop.run_forever()


if __name__ == '__main__':
    main()
