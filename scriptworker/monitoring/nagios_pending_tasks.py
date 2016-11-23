#!/usr/bin/env python

"""
Entrypoint for pending tasks monitoring.

"""
import asyncio
import aiohttp
import sys
import argparse


from scriptworker.config import get_context_from_cmdln
from scriptworker.utils import cleanup


# Nagios plugin exit codes
STATUS_CODE = {
    'OK': 0,
    'WARNING': 1,
    'CRITICAL': 2,
    'UNKNOWN': 3,
}

DEFAULT_WARNING = 5
DEFAULT_CRITICAL = 10


def nagios_message(status, message):
    """nagios_message
    display a message in the nagios style, and exit appropriately
    """
    print("PENDING_TASKS {0} - {1}".format(status, message))
    sys.exit(STATUS_CODE[status])


def get_args():

    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument('-w', '--warning', type=int, default=DEFAULT_WARNING,
                      help='warning threshhold for number of pending tasks')
    argp.add_argument('-c', '--critical', type=int, default=DEFAULT_CRITICAL,
                      help='critical threshhold for number of pending tasks')

    args = argp.parse_args()

    return args


def query_pending_task_count():
    """query_pending_task_count
    Query the API for the number of pending tasks, so we can
    report to nagios
    """

    args = get_args()

    context, credentials = get_context_from_cmdln(sys.argv[1:])
    cleanup(context)

    conn = aiohttp.TCPConnector(
        limit=context.config['aiohttp_max_connections'])
    loop = asyncio.get_event_loop()
    with aiohttp.ClientSession(connector=conn) as session:
        context.session = session
        context.credentials = credentials

        try:
            result = loop.run_until_complete(context.queue.pendingTasks(
                context.config['provisioner_id'], context.config['worker_type']))

        except Exception as excp:
            nagios_message(
                'UNKNOWN', 'Unable to query pending tasks: {0}'.format(excp))

        template = '{pending}/{max} pending tasks for {provisioner}:{worker}'

        if result['pendingTasks'] >= args.critical:
            nagios_message(
                'CRITICAL', template.format(
                    pending=result['pendingTasks'],
                    max=args.critical,
                    provisioner=result['provisionerId'],
                    worker=result['workerType']
                )
            )
        elif result['pendingTasks'] >= args.warning:
            nagios_message(
                'WARNING', "{0}/{1} pending tasks".format(result['pendingTasks'], args.warning))
        else:
            nagios_message(
                'OK', "{0}/{1} pending tasks".format(result['pendingTasks'], args.critical))
