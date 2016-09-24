#!/usr/bin/env python
"""Scripts running in scriptworker will use functions in this file.

This module should be largely standalone.  This should only depend on
scriptworker.exceptions and scriptworker.constants, or other standalone
modules, to avoid circular imports.
"""
import json
import jsonschema
import os
import re
from urllib.parse import urlparse, unquote

from scriptworker.constants import DEFAULT_CONFIG, STATUSES
from scriptworker.exceptions import ScriptWorkerTaskException


def get_task(config):
    """Read the task.json from work_dir.

    Args:
        config (dict): the running config, to find work_dir.

    Returns:
        dict: the contents of task.json

    Raises:
        ScriptWorkerTaskException: on error.
    """
    try:
        path = os.path.join(config['work_dir'], "task.json")
        with open(path, "r") as fh:
            contents = json.load(fh)
            return contents
    except (OSError, ValueError) as exc:
        raise ScriptWorkerTaskException(
            "Can't read task from {}!\n{}".format(path, str(exc)),
            exit_code=STATUSES['internal-error']
        )


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


def validate_artifact_url(config, url):
    """Ensure a URL fits in given scheme, netloc, and path restrictions.

    If `valid_artifact_schemes`, `valid_artifact_netlocs`, and/or
    `valid_artifact_path_regexes` are defined in `config` but are `None`,
    skip that check.

    If any are missing from `config`, fall back to the values in
    `DEFAULT_CONFIG`.

    If `valid_artifact_path_regexes` is not None, the url path should
    match one.  Each regex should define a `filepath`, which is what we'll
    return.

    Otherwise, if we pass all checks, return the unmodified path.

    If we fail any checks, raise a ScriptWorkerTaskException with
    `malformed-payload`.

    Args:
        config (dict): the running config.
        url (str): the url of the artifact.

    Returns:
        str: the `filepath` of the path regex.

    Raises:
        ScriptWorkerTaskException: on failure to validate.
    """
    messages = []
    validate_config = {}
    for key in (
        'valid_artifact_schemes', 'valid_artifact_netlocs',
        'valid_artifact_path_regexes', 'valid_artifact_task_ids',
    ):
        if key in config:
            validate_config[key] = config[key]
        else:
            validate_config[key] = DEFAULT_CONFIG[key]
    parts = urlparse(url)
    path = unquote(parts.path)
    return_value = path
    # scheme whitelisted?
    if validate_config['valid_artifact_schemes'] is not None and \
            parts.scheme not in validate_config['valid_artifact_schemes']:
        messages.append('Invalid scheme: {}!'.format(parts.scheme))
    # netloc whitelisted?
    if validate_config['valid_artifact_netlocs'] is not None and \
            parts.netloc not in validate_config['valid_artifact_netlocs']:
        messages.append('Invalid netloc: {}!'.format(parts.netloc))
    # check the paths
    for regex in validate_config.get('valid_artifact_path_regexes') or []:
        m = re.search(regex, path)
        if m is None:
            continue
        path_info = m.groupdict()
        # make sure we're pointing at a valid task ID
        if 'taskId' in path_info and \
                path_info['taskId'] not in validate_config['valid_artifact_task_ids']:
            messages.append('Invalid taskId: {}!'.format(path_info['taskId']))
            break
        if 'filepath' not in path_info:
            messages.append('Invalid regex {}!'.format(regex))
            break
        return_value = path_info['filepath']
        break
    else:
        if validate_config.get('valid_artifact_path_regexes'):
            messages.append('Invalid path: {}!'.format(path))

    if messages:
        raise ScriptWorkerTaskException(
            "Can't validate url {}\n{}".format(url, messages),
            exit_code=STATUSES['malformed-payload']
        )
    return return_value.lstrip('/')
