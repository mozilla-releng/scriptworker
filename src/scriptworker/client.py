#!/usr/bin/env python
"""Scripts running in scriptworker will use functions in this file.

This module should be largely standalone.  This should only depend on
scriptworker.exceptions and scriptworker.constants, or other standalone
modules, to avoid circular imports.

Attributes:
    log (logging.Logger): the log object for the module

"""
import asyncio
import logging
import os
import sys
from asyncio import AbstractEventLoop
from typing import Any, Awaitable, Callable, Dict, List, Match, NoReturn, Optional, Tuple
from urllib.parse import unquote

import jsonschema

from scriptworker.constants import STATUSES
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerException, ScriptWorkerTaskException, TaskVerificationError
from scriptworker.utils import load_json_or_yaml, match_url_regex, scriptworker_session

log = logging.getLogger(__name__)


def get_task(config: Dict[str, Any]) -> Dict[str, Any]:
    """Read the task.json from work_dir.

    Args:
        config (dict): the running config, to find work_dir.

    Returns:
        dict: the contents of task.json

    Raises:
        ScriptWorkerTaskException: on error.

    """
    path = os.path.join(config["work_dir"], "task.json")
    message = "Can't read task from {}!\n%(exc)s".format(path)
    contents = load_json_or_yaml(path, is_path=True, message=message)
    return contents


def validate_json_schema(data: Dict[str, Any], schema: Dict[str, Any], name: str = "task") -> None:
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
        validator = jsonschema.validators.validator_for(schema)
        jsonschema.validate(data, schema, validator, format_checker=validator.FORMAT_CHECKER)
    except jsonschema.exceptions.ValidationError as exc:
        raise ScriptWorkerTaskException("Can't validate {} schema!\n{}".format(name, str(exc)), exit_code=STATUSES["malformed-payload"])


def validate_task_schema(context: Any, schema_key: str = "schema_file") -> None:
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
    schema_keys = schema_key.split(".")
    for key in schema_keys:
        schema_path = schema_path[key]

    task_schema = load_json_or_yaml(schema_path, is_path=True)
    log.debug("Task is validated against this schema: {}".format(task_schema))

    try:
        validate_json_schema(context.task, task_schema)
    except ScriptWorkerTaskException as e:
        raise TaskVerificationError("Cannot validate task against schema. Task: {}.".format(context.task)) from e


def validate_artifact_url(valid_artifact_rules: Tuple[Any], valid_artifact_task_ids: List[str], url: str) -> str:
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

    def callback(match: Match[str]) -> Optional[str]:
        path_info = match.groupdict()
        # make sure we're pointing at a valid task ID
        if "taskId" in path_info and path_info["taskId"] not in valid_artifact_task_ids:
            return None
        if "filepath" not in path_info:
            return None
        return path_info["filepath"]

    filepath = match_url_regex(valid_artifact_rules, url, callback)
    if filepath is None:
        raise ScriptWorkerTaskException("Can't validate url {}".format(url), exit_code=STATUSES["malformed-payload"])
    return unquote(filepath).lstrip("/")


def sync_main(
    async_main: Callable[[Any], Awaitable[None]],
    config_path: Optional[str] = None,
    default_config: Optional[Dict[str, Any]] = None,
    should_validate_task: bool = True,
    loop_function: Callable[[], AbstractEventLoop] = asyncio.get_event_loop,
) -> None:
    """Entry point for scripts using scriptworker.

    This function sets up the basic needs for a script to run. More specifically:
        * it creates the scriptworker context and initializes it with the provided config
        * the path to the config file is either taken from `config_path` or from `sys.argv[1]`.
        * it verifies `sys.argv` doesn't have more arguments than the config path.
        * it creates the asyncio event loop so that `async_main` can run

    Args:
        async_main (function): The function to call once everything is set up
        config_path (str, optional): The path to the file to load the config from.
            Loads from ``sys.argv[1]`` if ``None``. Defaults to None.
        default_config (dict, optional): the default config to use for ``_init_context``.
            defaults to None.
        should_validate_task (bool, optional): whether we should validate the task
            schema. Defaults to True.
        loop_function (function, optional): the function to call to get the
            event loop; here for testing purposes. Defaults to
            ``asyncio.get_event_loop``.

    """
    context = _init_context(config_path, default_config)
    _init_logging(context)
    if should_validate_task:
        validate_task_schema(context)
    loop = loop_function()
    loop.run_until_complete(_handle_asyncio_loop(async_main, context))


def _init_context(config_path: Optional[str] = None, default_config: Optional[Dict[str, Any]] = None) -> Any:
    context = Context()  # type: Any

    # This prevents *script from overwriting json on disk
    context.write_json = lambda *args: None
    # call it for coverage
    context.write_json()  # type: ignore

    if config_path is None:
        if len(sys.argv) != 2:
            _usage()
        config_path = sys.argv[1]

    context.config = {} if default_config is None else default_config
    context.config.update(load_json_or_yaml(config_path, is_path=True))

    context.task = get_task(context.config)

    return context


def _usage() -> NoReturn:
    print("Usage: {} CONFIG_FILE".format(sys.argv[0]), file=sys.stderr)
    sys.exit(1)


def _init_logging(context: Any) -> None:
    logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG if context.config.get("verbose") else logging.INFO)
    logging.getLogger("taskcluster").setLevel(logging.WARNING)
    logging.getLogger("mohawk").setLevel(logging.INFO)


async def _handle_asyncio_loop(async_main: Callable[[Any], Awaitable[None]], context: Any) -> None:
    async with scriptworker_session() as session:
        context.session = session
        try:
            await async_main(context)
        except ScriptWorkerException as exc:
            log.exception("Failed to run async_main")
            sys.exit(exc.exit_code)
