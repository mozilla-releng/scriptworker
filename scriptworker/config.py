#!/usr/bin/env python
"""Config for scriptworker

Attributes:
    log (logging.Logger): the log object for the module.
    CREDS_FILES (tuple): an ordered list of files to look for taskcluster
        credentials, if they aren't in the config file or environment.
"""
import argparse
from copy import deepcopy
from frozendict import frozendict
import json
import logging
import os
import sys

from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.client import validate_json_schema
from scriptworker.context import Context
from scriptworker.log import update_logging_config

log = logging.getLogger(__name__)

CREDS_FILES = (
    os.path.join(os.getcwd(), 'secrets.json'),
    os.path.join(os.environ.get('HOME', '/etc/'), '.scriptworker'),
)


# freeze_values {{{1
def freeze_values(dictionary):
    """Convert a dictionary's list values into tuples, and dicts into frozendicts.

    This won't recurse; it's best for relatively flat data structures.

    Args:
        dictionary (dict): the dictionary to modify in-place.
    """
    for key, value in dictionary.items():
        if isinstance(value, list):
            dictionary[key] = tuple(value)
        elif isinstance(value, dict):
            dictionary[key] = frozendict(value)


# read_worker_creds {{{1
def read_worker_creds(key="credentials"):
    """Get credentials from CREDS_FILES or the environment.

    This looks at the CREDS_FILES in order, and falls back to the environment.

    Args:
        key (str, optional): each CREDS_FILE is a json dict.  This key's value
            contains the credentials.  Defaults to 'credentials'.

    Returns:
        dict: the credentials found. None if no credentials found.
    """
    for path in CREDS_FILES:
        if not os.path.exists(path):
            continue
        with open(path, "r") as fh:
            try:
                contents = json.load(fh)
                return contents[key]
            except (json.decoder.JSONDecodeError, KeyError):
                pass
    else:
        if key == "credentials" and os.environ.get("TASKCLUSTER_ACCESS_TOKEN") and \
                os.environ.get("TASKCLUSTER_CLIENT_ID"):
            credentials = {
                "accessToken": os.environ["TASKCLUSTER_ACCESS_TOKEN"],
                "clientId": os.environ["TASKCLUSTER_CLIENT_ID"],
            }
            if os.environ.get("TASKCLUSTER_CERTIFICATE"):
                credentials['certificate'] = os.environ['TASKCLUSTER_CERTIFICATE']
            return credentials


# check_config {{{1
def check_config(config, path):
    """Validate the config against DEFAULT_CONFIG.

    Any unknown keys or wrong types will add error messages.

    Args:
        config (dict): the running config.
        path (str): the path to the config file, used in error messages.

    Returns:
        list: the error messages found when validating the config.
    """
    messages = []
    for key, value in config.items():
        if key not in DEFAULT_CONFIG:
            messages.append("Unknown key {} in {}!".format(key, path))
            continue
        if DEFAULT_CONFIG[key] is not None:
            value_type = type(value)
            default_type = type(DEFAULT_CONFIG[key])
            if value_type != default_type:
                messages.append(
                    "{} {}: type {} is not {}!".format(path, key, value_type, default_type)
                )
        if value in ("...", b"..."):
            messages.append("{} {} needs to be defined!".format(path, key))
        if key in ("gpg_public_keyring", "gpg_secret_keyring") and not value.startswith('%(gpg_home)s/'):
            messages.append("{} needs to start with %(gpg_home)s/ to be portable!")
    return messages


# _get_json_from_mandatory_file {{{1
def _get_json_from_mandatory_file(path, function_name):
    if not os.path.exists(path):
        print("{} doesn't exist! Exiting {}()...".format(path, function_name),
              file=sys.stderr)
        print("Exiting...", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# create_config {{{1
def create_config(config_path="scriptworker.json"):
    """Create a config from DEFAULT_CONFIG, arguments, and config file.

    Then validate it and freeze it.

    Args:
        config_path (str, optional): the path to the config file.  Defaults to
            "scriptworker.json"

    Returns:
        tuple: (config frozendict, credentials dict)

    Raises:
        SystemExit: on failure
    """
    secrets = _get_json_from_mandatory_file(config_path, "create_config")
    config = dict(deepcopy(DEFAULT_CONFIG))
    if not secrets.get("credentials"):
        secrets['credentials'] = read_worker_creds()
    freeze_values(secrets)
    config.update(secrets)
    messages = check_config(config, config_path)
    if messages:
        print('\n'.join(messages), file=sys.stderr)
        print("Exiting...", file=sys.stderr)
        sys.exit(1)
    credentials = frozendict(secrets['credentials'])
    del(config['credentials'])
    config = frozendict(config)
    return config, credentials


# create_cot_config {{{1
def create_cot_config(context, cot_config_path=None):
    """Create a Chain of Trust config from context.config['cot_config'] file.

    Then validate it via the schema file, and freeze it.

    Args:
        context (scriptworker.context.Context): the scriptworker context.

    Returns:
        frozendict: the Chain of Trust config.

    Raises:
        SystemExit: on failure
    """
    cot_config_path = cot_config_path or context.config['cot_config_path']
    cot_config = _get_json_from_mandatory_file(cot_config_path, "create_cot_config")
    with open(context.config['cot_config_schema_path'], "r") as fh:
        schema = json.load(fh)
    validate_json_schema(cot_config, schema, name="cot_config")
    freeze_values(cot_config)
    cot_config = frozendict(cot_config)
    return cot_config


# get_context_from_cmdln {{{1
def get_context_from_cmdln(args, desc="Run scriptworker"):
    """Create a Context object from args.

    This was originally part of main(), but we use it in
    `scriptworker.gpg.create_initial_gpg_homedirs` too.

    Args:
        args (list): the commandline args.  Generally sys.argv

    Returns:
        tuple: `scriptworker.context.Context` with populated config, and
            credentials frozendict
    """
    context = Context()
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument(
        "config_path", type=str, nargs="?", default="scriptworker.json",
        help="the path to the config file"
    )
    parser.add_argument(
        "cot_config_path", type=str, nargs="?",
        help="the path to the chain of trust config file"
    )
    parsed_args = parser.parse_args(args)
    context.config, credentials = create_config(config_path=parsed_args.config_path)
    update_logging_config(context)
    context.cot_config = create_cot_config(context, cot_config_path=parsed_args.cot_config_path)
    return context, credentials
