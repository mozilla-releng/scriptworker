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
def test_config():
    return deepcopy(config.DEFAULT_CONFIG)


# tests {{{1
def test_nontext_to_unicode():
    d = {'a': [1, 2, 3]}
    config.list_to_tuple(d)
    assert d == {'a': (1, 2, 3)}


def test_check_config_invalid_key(test_config):
    test_config['invalid_key_for_testing'] = 1
    messages = config.check_config(test_config, "test_path")
    assert "Unknown key" in "\n".join(messages)


def test_check_config_invalid_type(test_config):
    test_config['log_dir'] = tuple(test_config['log_dir'])
    messages = config.check_config(test_config, "test_path")
    assert "log_dir: type" in "\n".join(messages)


def test_check_config_good(test_config):
    for key, value in test_config.items():
        if value == "...":
            test_config[key] = "filled_in"
    messages = config.check_config(test_config, "test_path")
    assert messages == []


def test_create_config_missing_file():
    with pytest.raises(SystemExit):
        config.create_config("this_file_does_not_exist.json")


def test_create_config_bad_config():
    path = os.path.join(os.path.dirname(__file__), "data", "bad.json")
    with pytest.raises(SystemExit):
        config.create_config(path)


def test_create_config_good(test_config):
    path = os.path.join(os.path.dirname(__file__), "data", "good.json")
    with open(path, "r") as fh:
        contents = json.load(fh)
    test_config.update(contents)
    test_creds = test_config['credentials']
    del(test_config['credentials'])
    generated_config, generated_creds = config.create_config(path)
    assert generated_config == test_config
    assert generated_creds == test_creds
    assert isinstance(generated_config, frozendict)
    assert isinstance(generated_creds, frozendict)


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
        _, creds = config.create_config(path=path)
    assert creds == fake_creds


def test_missing_creds():
    with mock.patch.object(config, 'CREDS_FILES', new=['this_file_does_not_exist']):
        assert config.read_worker_creds() is None


@pytest.mark.parametrize("params", ENV_CREDS_PARAMS)
def test_environ_creds(params):
    env = deepcopy(os.environ)
    env.update(params[0])
    with mock.patch.object(config, 'CREDS_FILES', new=['this_file_does_not_exist']):
        with mock.patch.object(os, 'environ', new=env):
            assert config.read_worker_creds() == params[1]
