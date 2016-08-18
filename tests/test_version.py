#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Test scriptworker/version.py
"""
import json
import os
import scriptworker.version as swversion
import pytest
import tempfile

# constants helpers and fixtures {{{1
LEGAL_VERSIONS = (
    ('0.1.0', (0, 1, 0)),
    ('1.2.3', (1, 2, 3)),
    ('4.1.5', (4, 1, 5)),
    ('9.2.0-alpha', (9, 2, 0, "alpha")),
)
ILLEGAL_LENGTH_VERSIONS = (
    (0, ),
    (0, 1),
    (0, 1, 0, 'alpha', 'beta'),
)


@pytest.fixture(scope='function')
def fake_version_tuple():
    return ("version!!!", "tuple!!!")


@pytest.fixture(scope='function')
def fake_version_string():
    return "version string!!!"


# tests {{{1
@pytest.mark.parametrize("version_tuple", LEGAL_VERSIONS)
def test_legal_version(version_tuple):
    """test_version | version tuple -> version string
    """
    assert swversion.get_version_string(version_tuple[1]) == version_tuple[0]


def test_illegal_three_version():
    """test_version | Raise if a 3-len tuple has a non-digit
    """
    with pytest.raises(TypeError):
        swversion.get_version_string(('one', 'two', 'three'))


def test_four_version():
    """test_version | 3 digit + string tuple -> version string
    """
    assert swversion.get_version_string((0, 1, 0, 'alpha')) == '0.1.0-alpha'


@pytest.mark.parametrize("version_tuple", ILLEGAL_LENGTH_VERSIONS)
def test_illegal_len_version(version_tuple):
    """test_version | Raise if len(version) not in (3, 4)
    """
    with pytest.raises(Exception):
        swversion.get_version_string(version_tuple)


def test_write_version(mocker, fake_version_tuple, fake_version_string):
    mocker.patch.object(swversion, '__version__', new=fake_version_tuple)
    mocker.patch.object(swversion, '__version_string__', new=fake_version_string)
    _, path = tempfile.mkstemp()
    swversion.write_version(path=path)
    with open(path) as fh:
        contents = json.load(fh)
    assert contents == {'version': list(fake_version_tuple), 'version_string': fake_version_string}
    os.remove(path)
