#!/usr/bin/env python
from __future__ import print_function

import aiohttp
import argparse
import asyncio
from copy import deepcopy
import logging
import os
import pprint
import sys
import tempfile
from scriptworker.config import read_worker_creds
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.context import Context
from scriptworker.cot.verify import ChainOfTrust, verify_chain_of_trust
from scriptworker.utils import rm


def main(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('task_id')
    parser.add_argument('--cleanup', dest='cleanup', action='store_true', default=False)
    opts = parser.parse_args(args)
    tmp = tempfile.mkdtemp()
    log = logging.getLogger('scriptworker')
    log.setLevel(logging.DEBUG)
    logging.basicConfig()
    loop = asyncio.get_event_loop()
    conn = aiohttp.TCPConnector()
    try:
        with aiohttp.ClientSession(connector=conn) as session:
            context = Context()
            context.session = session
            context.credentials = read_worker_creds()
            context.task = loop.run_until_complete(context.queue.task(opts.task_id))
            context.config = dict(deepcopy(DEFAULT_CONFIG))
            context.config.update({
                'artifact_dir': os.path.join(tmp, 'artifacts'),
                'base_gpg_home_dir': os.path.join(tmp, 'gpg'),
            })
            cot = ChainOfTrust(context, 'signing', task_id=opts.task_id)
            loop.run_until_complete(verify_chain_of_trust(cot))
            pprint.pprint(cot.dependent_task_ids())
            print("Cot task_id: {}".format(cot.task_id))
            for link in cot.links:
                print("task_id: {}".format(link.task_id))
            context.session.close()
        context.queue.session.close()
        loop.close()
    finally:
        if opts.cleanup:
            rm(tmp)
        else:
            log.info("Artifacts are in {}".format(tmp))


__name__ == '__main__' and main(sys.argv[1:])
