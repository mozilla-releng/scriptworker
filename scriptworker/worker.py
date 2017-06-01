#!/usr/bin/env python
"""Scriptworker worker functions.

Attributes:
    log (logging.Logger): the log object for the module.

"""
import aiohttp
import arrow
import asyncio
import logging
import os
import sys

from scriptworker.artifacts import upload_artifacts
from scriptworker.config import get_context_from_cmdln
from scriptworker.constants import STATUSES
from scriptworker.cot.generate import generate_cot
from scriptworker.cot.verify import ChainOfTrust, verify_chain_of_trust
from scriptworker.gpg import get_tmp_base_gpg_home_dir, is_lockfile_present, rm_lockfile
from scriptworker.exceptions import ScriptWorkerException
from scriptworker.task import claim_work, complete_task, reclaim_task, run_task, worst_level
from scriptworker.utils import cleanup, rm

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
        None: if no task run.

    """
    loop = asyncio.get_event_loop()
    tasks = await claim_work(context)
    status = None
    if tasks:
        # Assume only a single task, but should more than one fall through,
        # run them sequentially.  A side effect is our return status will
        # be the status of the final task run.
        for task_defn in tasks.get('tasks', []):
            context.claim_task = task_defn
            log.info("Going to run task!")
            status = 0
            loop.create_task(reclaim_task(context, context.task))
            try:
                if context.config['verify_chain_of_trust']:
                    chain = ChainOfTrust(context, context.config['cot_job_type'])
                    await verify_chain_of_trust(chain)
                status = await run_task(context)
                generate_cot(context)
            except ScriptWorkerException as e:
                status = worst_level(status, e.exit_code)
                log.error("Hit ScriptWorkerException: {}".format(e))
            try:
                await upload_artifacts(context)
            except ScriptWorkerException as e:
                status = worst_level(status, e.exit_code)
                log.error("Hit ScriptWorkerException: {}".format(e))
            except aiohttp.ClientError as e:
                status = worst_level(status, STATUSES['intermittent-task'])
                log.error("Hit aiohttp error: {}".format(e))
            await complete_task(context, status)
            cleanup(context)
            await asyncio.sleep(1)
    await asyncio.sleep(context.config['poll_interval'])
    return status


async def async_main(context):
    """Run the main async loop.

    http://docs.taskcluster.net/queue/worker-interaction/

    This is a simple loop, mainly to keep each function more testable.

    Args:
        context (scriptworker.context.Context): the scriptworker context.
    """
    tmp_gpg_home = get_tmp_base_gpg_home_dir(context)
    state = is_lockfile_present(context, "scriptworker", logging.DEBUG)
    if os.path.exists(tmp_gpg_home) and state == "ready":
        try:
            rm(context.config['base_gpg_home_dir'])
            os.rename(tmp_gpg_home, context.config['base_gpg_home_dir'])
        finally:
            rm_lockfile(context)
    await run_loop(context)
    await asyncio.sleep(context.config['poll_interval'])


def main():
    """Scriptworker entry point: get everything set up, then enter the main loop."""
    context, credentials = get_context_from_cmdln(sys.argv[1:])
    log.info("Scriptworker starting up at {} UTC".format(arrow.utcnow().format()))
    cleanup(context)
    conn = aiohttp.TCPConnector(limit=context.config['aiohttp_max_connections'])
    loop = asyncio.get_event_loop()
    with aiohttp.ClientSession(connector=conn) as session:
        context.session = session
        context.credentials = credentials
        while True:
            try:
                loop.run_until_complete(async_main(context))
            except Exception:
                log.critical("Fatal exception", exc_info=1)
                raise
