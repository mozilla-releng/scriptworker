#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.utils
"""
import aiohttp
import asyncio
import json
import mock
import os
import pytest
from scriptworker.context import Context
import scriptworker.utils as utils

# from https://github.com/SecurityInnovation/PGPy/blob/develop/tests/test_01_types.py
text = {
    # some basic utf-8 test strings - these should all pass
    'english': u'The quick brown fox jumped over the lazy dog',
    # this hiragana pangram comes from http://www.columbia.edu/~fdc/utf8/
    'hiragana': u'いろはにほへど　ちりぬるを\n'
                u'わがよたれぞ　つねならむ\n'
                u'うゐのおくやま　けふこえて\n'
                u'あさきゆめみじ　ゑひもせず',

    'poo': u'Hello, \U0001F4A9!',
}

non_text = {
    'None': None,
    'dict': {'a': 1, 2: 3},
    'cyrillic': u'грызть гранит науки'.encode('iso8859_5'),
    'cp865': u'Mit luftpudefartøj er fyldt med ål'.encode('cp865'),
}


@pytest.fixture(scope='function')
def datestring():
    """Datestring constant.
    """
    return "2016-04-16T03:46:24.958Z"


@pytest.fixture(scope='function')
def context(tmpdir_factory):
    temp_dir = tmpdir_factory.mktemp("context", numbered=True)
    path = str(temp_dir)
    context = Context()
    context.config = {
        'log_dir': os.path.join(path, 'log'),
        'artifact_dir': os.path.join(path, 'artifact'),
        'work_dir': os.path.join(path, 'work'),
    }
    return context


class FakeResponse(aiohttp.client_reqrep.ClientResponse):
    """Integration tests allow us to test everything's hooked up to aiohttp
    correctly.  When we don't want to actually hit an external url, have
    the aiohttp session's _request method return a FakeResponse.
    """
    def __init__(self, *args, status=200, payload=None, **kwargs):
        super(FakeResponse, self).__init__(*args, **kwargs)
        self._connection = mock.MagicMock()
        self._payload = payload or {}
        self.status = status
        self.headers = {'content-type': 'application/json'}
        self._loop = mock.MagicMock()

    @asyncio.coroutine
    def text(self, *args, **kwargs):
        return json.dumps(self._payload)

    @asyncio.coroutine
    def json(self, *args, **kwargs):
        return self._payload

    @asyncio.coroutine
    def release(self):
        return


@pytest.fixture(scope='function')
def fake_session():
    @asyncio.coroutine
    def _fake_request(method, url, *args, **kwargs):
        return FakeResponse(method, url)

    session = aiohttp.ClientSession()
    session._request = _fake_request
    return session


class TestUtils(object):
    @pytest.mark.parametrize("text", [v for _, v in sorted(text.items())])
    def test_text_to_unicode(self, text):
        assert text == utils.to_unicode(text)
        assert text == utils.to_unicode(text.encode('utf-8'))

    @pytest.mark.parametrize("non_text", [v for _, v in sorted(non_text.items())])
    def test_nontext_to_unicode(self, non_text):
        assert non_text == utils.to_unicode(non_text)

    def test_datestring_to_timestamp(self, datestring):
        assert utils.datestring_to_timestamp(datestring) == 1460803584.0

    def test_cleanup(self, context):
        for name in 'work_dir', 'artifact_dir':
            path = context.config[name]
            os.makedirs(path)
            open(os.path.join(path, 'tempfile'), "w").close()
            assert os.path.exists(os.path.join(path, "tempfile"))
        utils.cleanup(context)
        for name in 'work_dir', 'artifact_dir':
            path = context.config[name]
            assert os.path.exists(path)
            assert not os.path.exists(os.path.join(path, "tempfile"))

    def test_close_asyncio_loop(self, event_loop):
        assert not event_loop.is_closed()
        utils.close_asyncio_loop()
        assert event_loop.is_closed()

    def test_request(self, context, fake_session, event_loop):
        context.session = fake_session

        result = event_loop.run_until_complete(utils.request(context, "url"))
        assert result == '{}'
