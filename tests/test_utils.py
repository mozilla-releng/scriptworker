#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.utils
"""
import mock
import os
import pytest
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerException, ScriptWorkerRetryException
import scriptworker.utils as utils
from . import fake_session, fake_session_500

assert (fake_session, fake_session_500)  # silence flake8

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

retry_count = {}


@pytest.fixture(scope='function')
def datestring():
    """Datestring constant.
    """
    return "2016-04-16T03:46:24.958Z"


async def fail_first(*args, **kwargs):
    global retry_count
    retry_count['fail_first'] += 1
    if retry_count['fail_first'] < 2:
        raise ScriptWorkerRetryException("first")
    return "yay"


async def always_fail(*args, **kwargs):
    global retry_count
    retry_count['always_fail'] += 1
    raise ScriptWorkerException("fail")


async def fake_sleep(*args, **kwargs):
    pass


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

    @pytest.mark.asyncio
    async def test_request(self, context, fake_session):
        context.session = fake_session
        result = await utils.request(context, "url")
        assert result == '{}'
        context.session.close()

    @pytest.mark.asyncio
    async def test_request_retry(self, context, fake_session_500):
        context.session = fake_session_500
        with pytest.raises(ScriptWorkerRetryException):
            await utils.request(context, "url")
        context.session.close()

    @pytest.mark.asyncio
    async def test_request_exception(self, context, fake_session_500):
        context.session = fake_session_500
        with pytest.raises(ScriptWorkerException):
            await utils.request(context, "url", retry=())
        context.session.close()

    @pytest.mark.asyncio
    async def test_retry_request(self, context, fake_session):
        context.session = fake_session
        result = await utils.retry_request(context, "url")
        assert result == '{}'
        context.session.close()

    @pytest.mark.asyncio
    async def test_retry_async_fail_first(self):
        global retry_count
        retry_count['fail_first'] = 0
        status = await utils.retry_async(fail_first)
        assert status == "yay"
        assert retry_count['fail_first'] == 2

    @pytest.mark.asyncio
    async def test_retry_async_always_fail(self):
        global retry_count
        retry_count['always_fail'] = 0
        with mock.patch('asyncio.sleep', new=fake_sleep):
            with pytest.raises(ScriptWorkerException):
                status = await utils.retry_async(always_fail)
                assert status is None
        assert retry_count['always_fail'] == 5
