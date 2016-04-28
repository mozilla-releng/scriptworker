#!/usr/bin/env python
import aiohttp
import asyncio
import functools
import logging
import sys

from taskcluster.async import Queue

from scriptworker.poll import find_task, get_azure_urls, update_poll_task_urls
from scriptworker.config import create_config
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerException
from scriptworker.log import update_logging_config
from scriptworker.task import complete_task, reclaim_task, run_task, schedule_async, upload_artifacts
from scriptworker.utils import cleanup, retry_request

log = logging.getLogger(__name__)


async def async_main(context):
    """Main async loop, following the drawing at
    http://docs.taskcluster.net/queue/worker-interaction/
    """
    loop = asyncio.get_event_loop()
    while True:
        await update_poll_task_urls(
            context, context.queue.pollTaskUrls,
            args=(context.config['provisioner_id'], context.config['worker_type']),
        )
        for poll_url, delete_url in get_azure_urls(context):
            try:
                task_defn = await find_task(context, poll_url, delete_url,
                                            retry_request)
            except ScriptWorkerException:
                await asyncio.sleep(context.config['poll_interval'])
                break
            if task_defn:
                log.info("Going to run task!")
                context.task = task_defn
                loop.call_later(
                    context.config['reclaim_interval'],
                    functools.partial(schedule_async, reclaim_task, args=(context, ))
                )
                running_task = loop.create_task(run_task(context))
                await running_task
                await upload_artifacts(context)
                await complete_task(context, running_task.result())
                cleanup(context)
                await asyncio.sleep(1)
                break
        else:
            await asyncio.sleep(context.config['poll_interval'])


def main():
    """Scriptworker entry point: get everything set up, then enter the main loop
    """
    context = Context()
    kwargs = {}
    if len(sys.argv) > 1:
        if len(sys.argv) > 2:
            print("Usage: {} [configfile]".format(sys.argv[0]), file=sys.stderr)
            sys.exit(1)
        kwargs['path'] = sys.argv[1]
    context.config = create_config(**kwargs)
    update_logging_config(context)
    cleanup(context)
    conn = aiohttp.TCPConnector(limit=context.config["max_connections"])
    loop = asyncio.get_event_loop()
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
