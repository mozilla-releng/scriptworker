"""Common functions for scripts using scriptworker.

Attributes:
    log (logging.Logger): the log object for the module

"""
import aiohttp
import asyncio
import logging
import sys
import traceback

from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerException
from scriptworker.utils import load_json_or_yaml

log = logging.getLogger(__name__)


def sync_main(async_main, name=None, config_path=None):
    """Entry point for scripts using scriptworker.

    This function sets up the basic needs for a script to run. More specifically:
        * it checks sync_main runs under a known namespace
        * it creates the scriptworker context and initializes it with the provided config
        * the path to the config file is either taken from `config_path` or from `sys.argv[1]`.
        * it verifies `sys.argv` doesn't have more arguments than the config path.
        * it creates the asyncio event loop so that `async_main` can run

    Args:
        async_main (function): The function to call once everything is set up
        name (str): The name of the namespace to run. Must be either `None` or `'__main__'`. Otherwise function returns early.
        config_path (str): The path to the file to load the config from. Loads from `sys.argv[1]` if `None`
        close_loop (bool): Closes the event loop at the end of the run. Not closing it allows to run several tests on main()
    """
    if name not in (None, '__main__'):
        return

    context = _init_context(config_path)
    _init_logging(context)
    _handle_asyncio_loop(async_main, context)


def _init_context(config_path=None):
    context = Context()
    if config_path is None:
        if len(sys.argv) != 2:
            _usage()
        config_path = sys.argv[1]

    context.config = load_json_or_yaml(config_path, is_path=True)
    return context


def _usage():
    print('Usage: {} CONFIG_FILE'.format(sys.argv[0]), file=sys.stderr)
    sys.exit(1)


def _init_logging(context):
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.DEBUG if context.config.get('verbose') else logging.INFO
    )
    logging.getLogger('taskcluster').setLevel(logging.WARNING)


def _handle_asyncio_loop(async_main, context):
    loop = asyncio.get_event_loop()

    with aiohttp.ClientSession() as session:
        context.session = session
        try:
            loop.run_until_complete(async_main(context))
        except ScriptWorkerException as exc:
            traceback.print_exc()
            sys.exit(exc.exit_code)

    loop.close()
