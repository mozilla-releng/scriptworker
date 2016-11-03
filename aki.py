#!/usr/bin/env python
# XXX this is a helpful script, but probably belongs in scriptworker/test/data
from __future__ import print_function

import aiohttp
import asyncio
from copy import deepcopy
import json
import logging
import pprint
import sys
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.context import Context
from scriptworker.cot.verify import ChainOfTrust, verify_chain_of_trust
from scriptworker.utils import rm

rm("/tmp/artifacts")
task_id = "S5pv1_I5SJWwGcjAFW1q6g"
if len(sys.argv) > 1:
    task_id = sys.argv[1]

log = logging.getLogger('scriptworker')
log.setLevel(logging.DEBUG)
logging.basicConfig()
loop = asyncio.get_event_loop()
conn = aiohttp.TCPConnector()
with aiohttp.ClientSession(connector=conn) as session:
    context = Context()
    context.session = session
    with open("/Users/asasaki/.scriptworker", "r") as fh:
        context.credentials = json.load(fh)['credentials']
    context.queue = context.create_queue(context.credentials)
    context.task = loop.run_until_complete(context.queue.task(task_id))
    context.config = dict(deepcopy(DEFAULT_CONFIG))
    context.config.update({
        'artifact_dir': '/tmp/artifacts',
        'base_gpg_home_dir': '/tmp/gpg',
    })
    cot = ChainOfTrust(context, 'signing', task_id=task_id)
    loop.run_until_complete(verify_chain_of_trust(cot))
    pprint.pprint(cot.dependent_task_ids())
    print("Cot task_id: {}".format(cot.task_id))
    for link in cot.links:
        print("task_id: {}".format(link.task_id))
    #    print(link.cot_dir)
    #    print(link.decision_task_id)
    context.session.close()
context.queue.session.close()
loop.close()
