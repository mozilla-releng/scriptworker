#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.utils
"""
import asyncio
import mock
import os
import pytest
import re
import shutil
import tempfile
from scriptworker.exceptions import DownloadError, ScriptWorkerException, ScriptWorkerRetryException
import scriptworker.utils as utils
from . import (
    FakeResponse,
    event_loop,
    fake_session,
    fake_session_500,
    noop_async,
    tmpdir,
    touch,
)
from . import rw_context as context

assert event_loop, tmpdir  # silence flake8
assert context  # silence flake8
assert fake_session, fake_session_500  # silence flake8

# constants helpers and fixtures {{{1
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


# to_unicode {{{1
@pytest.mark.parametrize("text", [v for _, v in sorted(text.items())])
def test_text_to_unicode(text):
    assert text == utils.to_unicode(text)
    assert text == utils.to_unicode(text.encode('utf-8'))


@pytest.mark.parametrize("non_text", [v for _, v in sorted(non_text.items())])
def test_nontext_to_unicode(non_text):
    assert non_text == utils.to_unicode(non_text)


# datestring_to_timestamp {{{1
def test_datestring_to_timestamp(datestring):
    assert utils.datestring_to_timestamp(datestring) == 1460778384


# cleanup {{{1
def test_cleanup(context):
    for name in 'work_dir', 'artifact_dir', 'task_log_dir':
        path = context.config[name]
        open(os.path.join(path, 'tempfile'), "w").close()
        assert os.path.exists(os.path.join(path, "tempfile"))
    utils.cleanup(context)
    for name in 'work_dir', 'artifact_dir':
        path = context.config[name]
        assert os.path.exists(path)
        assert not os.path.exists(os.path.join(path, "tempfile"))
    # 2nd pass
    utils.rm(context.config['work_dir'])
    utils.cleanup(context)


# request and retry_request {{{1
def test_request(context, fake_session, event_loop):
    context.session = fake_session
    result = event_loop.run_until_complete(
        utils.request(context, "url")
    )
    assert result == '{}'
    context.session.close()


def test_request_json(context, fake_session, event_loop):
    context.session = fake_session
    result = event_loop.run_until_complete(
        utils.request(context, "url", return_type="json")
    )
    assert result == {}
    context.session.close()


def test_request_response(context, fake_session, event_loop):
    context.session = fake_session
    result = event_loop.run_until_complete(
        utils.request(context, "url", return_type="response")
    )
    assert isinstance(result, FakeResponse)
    context.session.close()


def test_request_retry(context, fake_session_500, event_loop):
    context.session = fake_session_500
    with pytest.raises(ScriptWorkerRetryException):
        event_loop.run_until_complete(
            utils.request(context, "url")
        )
    context.session.close()


def test_request_exception(context, fake_session_500, event_loop):
    context.session = fake_session_500
    with pytest.raises(ScriptWorkerException):
        event_loop.run_until_complete(
            utils.request(context, "url", retry=())
        )
    context.session.close()


def test_retry_request(context, fake_session, event_loop):
    context.session = fake_session
    result = event_loop.run_until_complete(
        utils.retry_request(context, "url")
    )
    assert result == '{}'
    context.session.close()


# calculate_sleep_time {{{1
@pytest.mark.parametrize("attempt", (-1, 0))
def test_calculate_no_sleep_time(attempt):
    assert utils.calculate_sleep_time(attempt) == 0


@pytest.mark.parametrize("attempt,kwargs,min_expected,max_expected", ((
1, {"delay_factor": 5.0, "randomization_factor": 0, "max_delay": 15}, 5.0, 5.0
), (
2, {"delay_factor": 5.0, "randomization_factor": .25, "max_delay": 15}, 10.0, 12.5
), (
3, {"delay_factor": 5.0, "randomization_factor": .25, "max_delay": 10}, 10.0, 10.0
)))
def test_calculate_sleep_time(attempt, kwargs, min_expected, max_expected):
    assert min_expected <= utils.calculate_sleep_time(attempt, **kwargs) <= max_expected


# retry_async {{{1
def test_retry_async_fail_first(event_loop):
    global retry_count
    retry_count['fail_first'] = 0
    status = event_loop.run_until_complete(
        utils.retry_async(fail_first, sleeptime_kwargs={'delay_factor': 0})
    )
    assert status == "yay"
    assert retry_count['fail_first'] == 2


def test_retry_async_always_fail(event_loop):
    global retry_count
    retry_count['always_fail'] = 0
    with mock.patch('asyncio.sleep', new=fake_sleep):
        with pytest.raises(ScriptWorkerException):
            status = event_loop.run_until_complete(
                utils.retry_async(always_fail, sleeptime_kwargs={'delay_factor': 0})
            )
            assert status is None
    assert retry_count['always_fail'] == 5


# create_temp_creds {{{1
def test_create_temp_creds():
    with mock.patch.object(utils, 'createTemporaryCredentials') as p:
        p.return_value = {
            "one": b"one",
            "two": "two",
        }
        creds = utils.create_temp_creds('clientId', 'accessToken', 'start', 'expires')
        assert p.called_once_with(
            'clientId', 'accessToken', 'start', 'expires',
            ['assume:project:taskcluster:worker-test-scopes', ], name=None
        )
        assert creds == {"one": "one", "two": "two"}


# raise_future_exceptions {{{1
@pytest.mark.parametrize("exc", (IOError, SyntaxError, None))
def test_raise_future_exceptions(event_loop, exc):

    async def one():
        if exc is not None:
            raise exc("foo")

    async def two():
        pass

    tasks = [asyncio.ensure_future(one()), asyncio.ensure_future(two())]
    if exc is not None:
        with pytest.raises(exc):
            event_loop.run_until_complete(
                utils.raise_future_exceptions(tasks)
            )
    else:
        event_loop.run_until_complete(
            utils.raise_future_exceptions(tasks)
        )


def test_raise_future_exceptions_noop(event_loop):
    event_loop.run_until_complete(
        utils.raise_future_exceptions([])
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", (IOError, SyntaxError, None))
async def test_get_results_and_future_exceptions(exc):
    async def one():
        if exc is None:
            return 'passed1'
        else:
            raise exc('failed')

    async def two():
        return 'passed2'

    tasks = [asyncio.ensure_future(one()), asyncio.ensure_future(two())]

    passed_results, error_results = await utils.get_results_and_future_exceptions(tasks)
    if exc is None:
        assert passed_results == ['passed1', 'passed2']
        assert error_results == []
    else:
        assert passed_results == ['passed2']
        assert [str(error) for error in error_results] == [str(exc('failed'))]


# filepaths_in_dir {{{1
def test_filepaths_in_dir(tmpdir):
    filepaths = sorted([
        "asdfasdf/lwekrjweoi/lsldkfjs",
        "lkdsjf/werew/sdlkfds",
        "lsdkjf/sdlkfds",
        "lkdlkf/lsldkfjs",
    ])
    for path in filepaths:
        parent_dir = os.path.join(tmpdir, os.path.dirname(path))
        os.makedirs(parent_dir)
        touch(os.path.join(tmpdir, path))
    assert sorted(utils.filepaths_in_dir(tmpdir)) == filepaths


# get_hash {{{1
def test_get_hash():
    path = os.path.join(os.path.dirname(__file__), "data", "azure.xml")
    sha = utils.get_hash(path, hash_alg="sha256")
    assert sha == "584818280d7908da33c810a25ffb838b1e7cec1547abd50c859521229942c5a5"


# makedirs {{{1
def test_makedirs_empty():
    utils.makedirs(None)


def test_makedirs_existing_file():
    path = os.path.join(os.path.dirname(__file__), "data", "azure.xml")
    with pytest.raises(ScriptWorkerException):
        utils.makedirs(path)


def test_makedirs_existing_dir():
    path = os.path.join(os.path.dirname(__file__))
    utils.makedirs(path)


# rm {{{1
def test_rm_empty():
    utils.rm(None)


def test_rm_file():
    _, tmp = tempfile.mkstemp()
    assert os.path.exists(tmp)
    utils.rm(tmp)
    assert not os.path.exists(tmp)


def test_rm_dir():
    tmp = tempfile.mkdtemp()
    assert os.path.exists(tmp)
    utils.rm(tmp)
    assert not os.path.exists(tmp)


# download_file {{{1
def test_download_file(context, fake_session, tmpdir, event_loop):
    path = os.path.join(tmpdir, "foo")
    event_loop.run_until_complete(
        utils.download_file(context, "url", path, session=fake_session)
    )
    with open(path, "r") as fh:
        contents = fh.read()
    assert contents == "asdfasdf"


def test_download_file_exception(context, fake_session_500, tmpdir, event_loop):
    path = os.path.join(tmpdir, "foo")
    with pytest.raises(DownloadError):
        event_loop.run_until_complete(
            utils.download_file(context, "url", path, session=fake_session_500)
        )


# format_json {{{1
def test_format_json():
    expected = '\n'.join([
        '{',
        '  "a": 1,',
        '  "b": [',
        '    4,',
        '    3,',
        '    2',
        '  ],',
        '  "c": {',
        '    "d": 5',
        '  }',
        '}'
    ])
    assert utils.format_json({'c': {'d': 5}, 'a': 1, 'b': [4, 3, 2]}) == expected



# load_json_or_yaml {{{1
@pytest.mark.parametrize("string,is_path,exception,raises,result", ((
    os.path.join(os.path.dirname(__file__), 'data', 'bad.json'),
    True, None, False, {"credentials": ["blah"]}
), (
    '{"a": "b"}', False, None, False, {"a": "b"}
), (
    '{"a": "b}', False, None, False, None
), (
    '{"a": "b}', False, ScriptWorkerException, True, None
)))
def test_load_json_or_yaml(string, is_path, exception, raises, result):
    if raises:
        with pytest.raises(exception):
            utils.load_json_or_yaml(string, is_path=is_path, exception=exception)
    else:
        for file_type in ("json", "yaml"):
            assert result == utils.load_json_or_yaml(
                string, is_path=is_path, exception=exception, file_type=file_type
            )

# load_json_or_yaml_from_url {{{1
@pytest.mark.asyncio
@pytest.mark.parametrize("overwrite,file_type", ((
    True, "json"
), (
    False, "json"
), (
    True, "yaml"
), (
    False, "yaml"
)))
async def test_load_json_or_yaml_from_url(context, mocker, overwrite, file_type, tmpdir):
    mocker.patch.object(utils, 'retry_async', new=noop_async)
    path = os.path.join(tmpdir, "bad.{}".format(file_type))
    shutil.copyfile(
        os.path.join(os.path.dirname(__file__), 'data', 'bad.json'),
        path
    )
    assert await utils.load_json_or_yaml_from_url(
        context, "", path, overwrite=overwrite
    ) == {"credentials": ["blah"]}


# get_loggable_url {{{1
@pytest.mark.parametrize("url,expected",((
    "https://foo/bar", "https://foo/bar"
), (
    "https://foo/bar?bewit=foobar", "https://foo/bar?<snip>"
), (
    "https://bar/baz?AWSAccessKeyId=foobar", "https://bar/baz?<snip>"
)))
def test_get_loggable_url(url, expected):
    assert utils.get_loggable_url(url) == expected


# match_url_path_callback {{{1
@pytest.mark.parametrize("path", (
    "/mozilla-central", "/mozilla-central/foo/bar", "/mozilla-central/"
))
def test_match_url_path_callback(path):
    regex = re.compile("^/(?P<path>mozilla-(central|unified))(/|$)")
    m = regex.match(path)
    assert utils.match_url_path_callback(m) == "mozilla-central"


# match_url_regex {{{1
def test_match_url_regex():
    rules =  ({
        'schemes': ['bad_scheme'],
    }, {
        'schemes': ['https'],
        'netlocs': ['bad_netloc'],
    }, {
        'schemes': ['https'],
        'netlocs': ['hg.mozilla.org'],
        'path_regexes': [
            "^bad_regex$",
        ],
    }, {
        'schemes': ['https'],
        'netlocs': ['hg.mozilla.org'],
        'path_regexes': [
            "^.*$",
            "^/(?P<path>mozilla-(central|unified))(/|$)",
        ],
    })

    def cb(m):
        import logging
        log = logging.getLogger()
        log.error(m)
        path_info = m.groupdict()
        if 'path' in path_info:
            return path_info['path']

    assert utils.match_url_regex(rules, "https://hg.mozilla.org/mozilla-central", cb) == "mozilla-central"
    assert utils.match_url_regex((), "https://hg.mozilla.org/mozilla-central", cb) is None


# add_enumerable_item_to_dict {{{1
@pytest.mark.parametrize("dict_, key, item, expected", ((
    {}, 'non_existing_key', 'an_item', {'non_existing_key': ['an_item']}
), (
    {}, 'non_existing_key', ['a', 'list'], {'non_existing_key': ['a', 'list']}
), (
    {}, 'non_existing_key', ('a', 'tuple', 'to', 'become', 'a', 'list'), {'non_existing_key': ['a', 'tuple', 'to', 'become', 'a', 'list']}
), (
    {'existing_key': []}, 'existing_key', 'an_item', {'existing_key': ['an_item']}
), (
    {'existing_key': ['an_item']}, 'existing_key', 'a_second_item', {'existing_key': ['an_item', 'a_second_item']}
), (
    {'existing_key': ['an_item']}, 'existing_key', ['some', 'new', 'items'], {'existing_key': ['an_item', 'some', 'new', 'items']}
)))
def test_add_enumerable_item_to_dict(dict_, key, item, expected):
    utils.add_enumerable_item_to_dict(dict_, key, item)
    assert dict_ == expected


# remove_empty_keys {{{1
@pytest.mark.parametrize("orig,expected", ((
    {'a': None, 'b': '', 'c': {}, 'd': [], 'e': 'null'},
    {'b': ''}
), (
    {'a': {'b': None, 'c': ''}, 'd': [{}, '']},
    {'a': {'c': ''}, 'd': ['']}
)))
def test_remove_empty_keys(orig, expected):
    assert utils.remove_empty_keys(orig) == expected
