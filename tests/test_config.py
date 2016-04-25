#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.config
"""
from copy import deepcopy
import pytest
import scriptworker.config as config


@pytest.fixture(scope='function')
def test_config():
    return deepcopy(config.DEFAULT_CONFIG)


class TestConfig(object):
    def test_nontext_to_unicode(self):
        d = {'a': [1, 2, 3]}
        config.list_to_tuple(d)
        assert d == {'a': (1, 2, 3)}

    def test_invalid_key(self, test_config):
        test_config['invalid_key_for_testing'] = 1
        messages = config.check_config(test_config, "test_path")
        assert "Unknown key" in "\n".join(messages)

    def test_invalid_type(self, test_config):
        test_config['log_dir'] = tuple(test_config['log_dir'])
        messages = config.check_config(test_config, "test_path")
        assert "log_dir: type" in "\n".join(messages)

    def test_valid_config(self, test_config):
        for key, value in test_config.items():
            if value == "...":
                test_config[key] = "filled_in"
        messages = config.check_config(test_config, "test_path")
        assert messages == []
