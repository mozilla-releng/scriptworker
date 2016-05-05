#!/usr/bin/env python
import aiohttp
import arrow
import asyncio
import logging
import sys

from scriptworker.poll import find_task, get_azure_urls, update_poll_task_urls
from scriptworker.config import create_config, read_worker_creds
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerException
from scriptworker.log import update_logging_config
from scriptworker.task import complete_task, reclaim_task, run_task, upload_artifacts
from scriptworker.utils import cleanup, retry_request

log = logging.getLogger(__name__)


async def run_loop(context, creds_key="credentials"):
    """Split this out of the async_main while loop for easier testing.
    """
    loop = asyncio.get_event_loop()
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
            loop.create_task(reclaim_task(context))
            running_task = loop.create_task(run_task(context))
            status = await running_task
            await upload_artifacts(context)
            await complete_task(context, running_task.result())
            cleanup(context)
            await asyncio.sleep(1)
            return status
    else:
        await asyncio.sleep(context.config['poll_interval'])
        if arrow.utcnow().timestamp - context.credentials_timestamp > context.config['credential_update_interval']:
            credentials = read_worker_creds(key=creds_key)
            if credentials and credentials != context.credentials:
                context.credentials = credentials


async def async_main(context):
    """Main async loop, following the drawing at
    http://docs.taskcluster.net/queue/worker-interaction/
    """
    while True:
        await run_loop(context)


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
    context.config, credentials = create_config(**kwargs)
    update_logging_config(context)
    cleanup(context)
    conn = aiohttp.TCPConnector(limit=context.config["max_connections"])
    loop = asyncio.get_event_loop()
    with aiohttp.ClientSession(connector=conn) as session:
        context.session = session
        context.credentials = credentials
        while True:
            try:
                loop.create_task(async_main(context))
                loop.run_forever()
            except RuntimeError:
                pass
