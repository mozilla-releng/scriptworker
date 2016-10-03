#!/usr/bin/env python
import aiohttp
import arrow
import asyncio
import logging
import os
import sys

from scriptworker.poll import find_task, get_azure_urls, update_poll_task_urls
from scriptworker.config import get_context_from_cmdln, read_worker_creds
from scriptworker.cot import generate_cot
from scriptworker.gpg import overwrite_gpg_home, rebuild_gpg_homedirs_loop
from scriptworker.exceptions import ScriptWorkerException
from scriptworker.task import complete_task, reclaim_task, run_task, upload_artifacts, worst_level
from scriptworker.utils import cleanup, retry_request

log = logging.getLogger(__name__)


async def run_loop(context, creds_key="credentials"):
    """Split this out of the async_main while loop for easier testing.

    args:
        context (scriptworker.context.Context): the scriptworker context.
        creds_key (str, optional): when reading the creds file, this dict key
            corresponds to the credentials value we want to use.  Defaults to
            "credentials".

    Returns:
        int: status
    """
    loop = asyncio.get_event_loop()
    await update_poll_task_urls(
        context, context.queue.pollTaskUrls,
        args=(context.config['provisioner_id'], context.config['worker_type']),
    )
    for poll_url, delete_url in get_azure_urls(context):
        try:
            claim_task_defn = await find_task(context, poll_url, delete_url,
                                              retry_request)
        except ScriptWorkerException:
            await asyncio.sleep(context.config['poll_interval'])
            break
        if claim_task_defn:
            log.info("Going to run task!")
            status = 0
            context.claim_task = claim_task_defn
            loop.create_task(reclaim_task(context, context.task))
            try:
                # TODO download and verify chain of trust artifacts if
                # context.config['verify_chain_of_trust']
                # write an audit logfile to task_log_dir; copy cot into
                # artifact_dir/cot ?
                status = await run_task(context)
                generate_cot(context)
            except ScriptWorkerException as e:
                status = worst_level(status, e.exit_code)
                log.error("Hit ScriptWorkerException: {}".format(str(e)))
            try:
                await upload_artifacts(context)
            except ScriptWorkerException as e:
                status = worst_level(status, e.exit_code)
                log.error("Hit ScriptWorkerException: {}".format(str(e)))
            await complete_task(context, status)
            cleanup(context)
            await asyncio.sleep(1)
            return status
    else:
        await asyncio.sleep(context.config['poll_interval'])
        if arrow.utcnow().timestamp - context.credentials_timestamp > context.config['credential_update_interval']:  # pragma: no branch
            credentials = read_worker_creds(key=creds_key)
            if credentials and credentials != context.credentials:
                context.credentials = credentials


async def async_main(context):
    """Main async loop, following the drawing at
    http://docs.taskcluster.net/queue/worker-interaction/

    This is a simple loop, mainly to keep each function more testable.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
    """
    loop = asyncio.get_event_loop()
    tmp_gpg_home = "{}.tmp".format(context.config['base_gpg_home_dir'])
    lockfile = os.path.join(tmp_gpg_home, ".lock")
    loop.create_task(
        rebuild_gpg_homedirs_loop(
            context, tmp_gpg_home
        )
    )
    while True:
        await run_loop(context)
        await asyncio.sleep(context.config['poll_interval'])
        if os.path.exists(tmp_gpg_home) and not os.path.exists(lockfile):
            overwrite_gpg_home(tmp_gpg_home, context.config['base_gpg_home_dir'])


def main():
    """Scriptworker entry point: get everything set up, then enter the main loop
    """
    context, credentials = get_context_from_cmdln(sys.argv[1:])
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
