#!/usr/bin/env python
"""Deal with the multi-step queue polling.  At some point we may be able to
just claimTask through Taskcluster; until that point we have these functions.
"""
import base64
import defusedxml.ElementTree
import json
import logging
import pprint
import time
import urllib.parse

import taskcluster.exceptions
from scriptworker.utils import datestring_to_timestamp

log = logging.getLogger(__name__)


def parse_azure_message(message):
    """The Azure xml may have multiple messages; this deals with one.
    """
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


def parse_azure_xml(xml):
    """Generator: parse the Azure xml and pass through parse_azure_message()
    """
    et = defusedxml.ElementTree.fromstring(xml)
    for message in et:
        yield parse_azure_message(message)


async def claim_task(context, taskId, runId):
    """Attempt to claim a task that we found in the Azure queue.
    """
    payload = {
        'workerGroup': context.config['worker_group'],
        'workerId': context.config['worker_id'],
    }
    try:
        result = await context.queue.claimTask(taskId, runId, payload)
        log.debug("claim_task:")
        log.debug(pprint.pformat(result))
        return result
    except taskcluster.exceptions.TaskclusterFailure as exc:
        # TODO 409 is expected.  Not sure if we should ignore other errors?
        log.debug("Got %s" % exc)
        return None


def get_azure_urls(context):
    """Generator: yield the poll_url and delete_url from the poll_task_urls,
    in order.
    """
    for queue_defn in context.poll_task_urls['queues']:
        yield queue_defn['signedPollUrl'], queue_defn['signedDeleteUrl']


async def find_task(context, poll_url, delete_url, request_function):
    """Main polling function.

    For a given poll_url/delete_url pair, get the xml from the poll_url.
    For each message in the xml, parse and try to claim the task.
    Delete the message from the Azure queue whether the claim was successful
    or not (error 409 on claim means the task was cancelled/expired/claimed).

    If the claim was successful, return the task json.
    """
    xml = await request_function(context, poll_url)
    log.debug("find_task xml:")
    log.debug(xml)
    for message_info in parse_azure_xml(xml):
        log.debug(message_info['task_info'])
        task = await claim_task(context, **message_info['task_info'])
        delete_url = delete_url.replace("{{", "{").replace("}}", "}").format(**message_info)
        response = await request_function(context, delete_url, method='delete', good=[200, 204])
        log.debug(response)
        if task is not None:
            return task


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
        seconds_left = int(expires - time.time())
        log.debug("poll_task_urls expires in %d seconds" % seconds_left)
        if seconds_left >= min_seconds_left:
            return
    log.debug("Updating poll_task_urls...")
    kwargs = kwargs or {}
    context.poll_task_urls = await callback(*args, **kwargs)
