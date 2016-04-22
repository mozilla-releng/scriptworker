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
import logging

from taskcluster.async import Queue

from scriptworker.poll import find_task, get_azure_urls, update_poll_task_urls
from scriptworker.config import create_config
from scriptworker.context import Context
from scriptworker.log import update_logging_config
from scriptworker.task import complete_task, run_task, schedule_reclaim_task
from scriptworker.utils import cleanup, close_asyncio_loop, request

log = logging.getLogger(__name__)


async def async_main(context):
    loop = asyncio.get_event_loop()
    while True:
        await update_poll_task_urls(
            context, context.queue.pollTaskUrls,
            args=(context.config['provisioner_id'], context.config['worker_type']),
        )
        for poll_url, delete_url in get_azure_urls(context):
            task_defn = await find_task(context, poll_url, delete_url, request)
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
    update_logging_config(context)
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
