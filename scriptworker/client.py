#!/usr/bin/env python
"""Scripts running in scriptworker will use functions in this file.

This module should be largely standalone.  This should only depend on
scriptworker.exceptions and scriptworker.constants, or other standalone
modules, to avoid circular imports.

"""
import jsonschema
import os

from scriptworker.constants import STATUSES
from scriptworker.exceptions import ScriptWorkerTaskException
from scriptworker.utils import load_json, match_url_regex


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
    contents = load_json(path, is_path=True, message=message)
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
    return filepath.lstrip('/')
