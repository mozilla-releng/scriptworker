#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.config
"""
from copy import deepcopy
from frozendict import frozendict
import json
import mock
import os
import pytest
import scriptworker.config as config
from scriptworker.constants import DEFAULT_CONFIG


# constants helpers and fixtures {{{1
ENV_CREDS_PARAMS = ((
    {
        'TASKCLUSTER_ACCESS_TOKEN': 'x',
        'TASKCLUSTER_CLIENT_ID': 'y',
    }, {
        "accessToken": 'x',
        "clientId": 'y',
    }
), (
    {
        'TASKCLUSTER_ACCESS_TOKEN': 'x',
        'TASKCLUSTER_CLIENT_ID': 'y',
        'TASKCLUSTER_CERTIFICATE': 'z',
    }, {
        "accessToken": 'x',
        "clientId": 'y',
        "certificate": 'z',
    }
))


@pytest.fixture(scope='function')
def t_config():
    return dict(deepcopy(DEFAULT_CONFIG))


@pytest.fixture(scope='function')
def t_env():
    env = {}
    for key, value in os.environ.items():
        if not key.startswith('TASKCLUSTER_'):
            env[key] = value
    return env


# freeze_values {{{1
def test_freeze_values():
    d = {'a': [1, 2, 3], 'b': {'c': 'd'}}
    config.freeze_values(d)
    assert d == {'a': (1, 2, 3), 'b': frozendict({'c': 'd'})}


# check_config {{{1
def test_check_config_invalid_key(t_config):
    t_config['invalid_key_for_testing'] = 1
    messages = config.check_config(t_config, "test_path")
    assert "Unknown key" in "\n".join(messages)


def test_check_config_invalid_type(t_config):
    t_config['log_dir'] = tuple(t_config['log_dir'])
    messages = config.check_config(t_config, "test_path")
    assert "log_dir: type" in "\n".join(messages)


def test_check_config_bad_keyring(t_config):
    t_config['gpg_secret_keyring'] = 'foo{}'.format(t_config['gpg_secret_keyring'])
    messages = config.check_config(t_config, "test_path")
    assert "needs to start with %(gpg_home)s/" in "\n".join(messages)


def test_check_config_good(t_config):
    for key, value in t_config.items():
        if value == "...":
            t_config[key] = "filled_in"
    messages = config.check_config(t_config, "test_path")
    assert messages == []


# create_config {{{1
def test_create_config_missing_file():
    with pytest.raises(SystemExit):
        config.create_config(config_path="this_file_does_not_exist.json")


def test_create_config_bad_config():
    path = os.path.join(os.path.dirname(__file__), "data", "bad.json")
    with pytest.raises(SystemExit):
        config.create_config(config_path=path)


def test_create_config_good(t_config):
    path = os.path.join(os.path.dirname(__file__), "data", "good.json")
    with open(path, "r") as fh:
        contents = json.load(fh)
    t_config.update(contents)
    test_creds = t_config['credentials']
    del(t_config['credentials'])
    generated_config, generated_creds = config.create_config(config_path=path)
    assert generated_config == t_config
    assert generated_creds == test_creds
    assert isinstance(generated_config, frozendict)
    assert isinstance(generated_creds, frozendict)


# create_cot_config {{{1
def test_create_cot_config(t_config):
    context = mock.MagicMock()
    context.config = t_config
    context.config['cot_config_path'] = os.path.join(
        os.path.dirname(__file__), "data", "cot_config.json"
    )
    context.config['cot_config_schema_path'] = os.path.join(
        os.path.dirname(__file__), "data", "cot_config_schema.json"
    )
    assert config.create_cot_config(context) == frozendict({"foo": "bar"})


def test_create_cot_config_exception(t_config):
    context = mock.MagicMock()
    context.config = t_config
    with pytest.raises(SystemExit):
        config.create_cot_config(context)


# credentials {{{1
def test_bad_worker_creds():
    path = os.path.join(os.path.dirname(__file__), "data", "good.json")
    with mock.patch.object(config, 'CREDS_FILES', new=(path, )):
        assert config.read_worker_creds(key="nonexistent_key") is None


def test_no_creds_in_config():
    fake_creds = {"foo": "bar"}

    def fake_read(*args, **kwargs):
        return deepcopy(fake_creds)

    path = os.path.join(os.path.dirname(__file__), "data", "no_creds.json")
    with mock.patch.object(config, 'read_worker_creds', new=fake_read):
        _, creds = config.create_config(config_path=path)
    assert creds == fake_creds


def test_missing_creds(t_env):
    with mock.patch.object(config, 'CREDS_FILES', new=['this_file_does_not_exist']):
        with mock.patch.object(os, 'environ', new=t_env):
            assert config.read_worker_creds() is None


@pytest.mark.parametrize("params", ENV_CREDS_PARAMS)
def test_environ_creds(params, t_env):
    t_env.update(params[0])
    with mock.patch.object(config, 'CREDS_FILES', new=['this_file_does_not_exist']):
        with mock.patch.object(os, 'environ', new=t_env):
            assert config.read_worker_creds() == params[1]


# get_context_from_cmdln {{{1
def test_get_context_from_cmdln(t_config):
    path = os.path.join(os.path.dirname(__file__), "data", "good.json")
    c = deepcopy(dict(DEFAULT_CONFIG))
    with open(path) as fh:
        c.update(json.load(fh))
    expected_creds = frozendict(c['credentials'])
    del(c['credentials'])
    expected_config = frozendict(c)

    def noop(*args, **kwargs):
        pass

    with mock.patch.object(config, "create_cot_config", new=noop):
        context, credentials = config.get_context_from_cmdln([path])
        assert credentials == expected_creds
        assert context.config == expected_config


@pytest.mark.parametrize("args", ([
    "1", "2", "3", "4"
], [
    "x", os.path.join(os.path.dirname(__file__), "data", "bad.json")
], []))
def test_get_context_from_cmdln_exception(args):
    with pytest.raises(SystemExit):
        config.get_context_from_cmdln(args)
