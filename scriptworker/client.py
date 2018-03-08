#!/usr/bin/env python
"""Scripts running in scriptworker will use functions in this file.

This module should be largely standalone.  This should only depend on
scriptworker.exceptions and scriptworker.constants, or other standalone
modules, to avoid circular imports.

Attributes:
    log (logging.Logger): the log object for the module

"""
import aiohttp
import asyncio
import jsonschema
import logging
import os
import sys
import traceback
from urllib.parse import unquote

from scriptworker.constants import STATUSES
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerException, ScriptWorkerTaskException, TaskVerificationError
from scriptworker.utils import load_json_or_yaml, match_url_regex

log = logging.getLogger(__name__)


def get_task(config):
    """Read the task.json from work_dir.

    Args:
        config (dict): the running config, to find work_dir.

    Returns:
        dict: the contents of task.json

    Raises:
        ScriptWorkerTaskException: on error.

    """
    path = os.path.join(config['work_dir'], "task.json")
    message = "Can't read task from {}!\n%(exc)s".format(path)
    contents = load_json_or_yaml(path, is_path=True, message=message)
    return contents


def validate_json_schema(data, schema, name="task"):
    """Given data and a jsonschema, let's validate it.

    This happens for tasks and chain of trust artifacts.

    Args:
        data (dict): the json to validate.
        schema (dict): the jsonschema to validate against.
        name (str, optional): the name of the json, for exception messages.
            Defaults to "task".

    Raises:
        ScriptWorkerTaskException: on failure

    """
    try:
        jsonschema.validate(data, schema)
    except jsonschema.exceptions.ValidationError as exc:
        raise ScriptWorkerTaskException(
            "Can't validate {} schema!\n{}".format(name, str(exc)),
            exit_code=STATUSES['malformed-payload']
        )


def validate_task_schema(context, schema_key='schema_file'):
    """Validate the task definition.

    Args:
        context (scriptworker.context.Context): the scriptworker context. It must contain a task and
            the config pointing to the schema file
        schema_key: the key in `context.config` where the path to the schema file is. Key can contain
            dots (e.g.: 'schema_files.file_a'), in which case

    Raises:
        TaskVerificationError: if the task doesn't match the schema

    """
    schema_path = context.config
    schema_keys = schema_key.split('.')
    for key in schema_keys:
        schema_path = schema_path[key]

    task_schema = load_json_or_yaml(schema_path, is_path=True)
    log.debug('Task is validated against this schema: {}'.format(task_schema))

    try:
        validate_json_schema(context.task, task_schema)
    except ScriptWorkerTaskException as e:
        raise TaskVerificationError('Cannot validate task against schema. Task: {}.'.format(context.task)) from e


def validate_artifact_url(valid_artifact_rules, valid_artifact_task_ids, url):
    """Ensure a URL fits in given scheme, netloc, and path restrictions.

    If we fail any checks, raise a ScriptWorkerTaskException with
    ``malformed-payload``.

    Args:
        valid_artifact_rules (tuple): the tests to run, with ``schemas``, ``netlocs``,
            and ``path_regexes``.
        valid_artifact_task_ids (list): the list of valid task IDs to download from.
        url (str): the url of the artifact.

    Returns:
        str: the ``filepath`` of the path regex.

    Raises:
        ScriptWorkerTaskException: on failure to validate.

    """
    def callback(match):
        path_info = match.groupdict()
        # make sure we're pointing at a valid task ID
        if 'taskId' in path_info and \
                path_info['taskId'] not in valid_artifact_task_ids:
            return
        if 'filepath' not in path_info:
            return
        return path_info['filepath']

    filepath = match_url_regex(valid_artifact_rules, url, callback)
    if filepath is None:
        raise ScriptWorkerTaskException(
            "Can't validate url {}".format(url),
            exit_code=STATUSES['malformed-payload']
        )
    return unquote(filepath).lstrip('/')


def sync_main(async_main, config_path=None):
    """Entry point for scripts using scriptworker.

    This function sets up the basic needs for a script to run. More specifically:
        * it creates the scriptworker context and initializes it with the provided config
        * the path to the config file is either taken from `config_path` or from `sys.argv[1]`.
        * it verifies `sys.argv` doesn't have more arguments than the config path.
        * it creates the asyncio event loop so that `async_main` can run

    Args:
        async_main (function): The function to call once everything is set up
        config_path (str): The path to the file to load the config from. Loads from `sys.argv[1]` if `None`
        close_loop (bool): Closes the event loop at the end of the run. Not closing it allows to run several tests on main()
    """
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
