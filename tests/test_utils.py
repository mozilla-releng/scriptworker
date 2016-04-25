#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.utils
"""
import pytest
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
