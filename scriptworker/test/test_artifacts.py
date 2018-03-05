import arrow
import gzip
import json
import operator
import os
import mimetypes
import mock
import pytest
import tempfile

from scriptworker.artifacts import get_expiration_arrow, guess_content_type_and_encoding, upload_artifacts, \
    create_artifact, get_artifact_url, download_artifacts, compress_artifact_if_supported, \
    _force_mimetypes_to_plain_text, _craft_artifact_put_headers, get_upstream_artifacts_full_paths_per_task_id, \
    get_and_check_single_upstream_artifact_full_path, get_single_upstream_artifact_full_path, \
    get_optional_artifacts_per_task_id
from scriptworker.exceptions import ScriptWorkerRetryException, ScriptWorkerTaskException


from . import touch, rw_context, event_loop, fake_session, fake_session_500, successful_queue


@pytest.yield_fixture(scope='function')
def context(rw_context):
    now = arrow.utcnow()
    rw_context.config['reclaim_interval'] = 0.001
    rw_context.config['task_max_timeout'] = .1
    rw_context.config['task_script'] = ('bash', '-c', '>&2 echo bar && echo foo && exit 1')
    rw_context.claim_task = {
        'credentials': {'a': 'b'},
        'status': {'taskId': 'taskId'},
        'task': {
            'expires': now.replace(days=2).isoformat(),
            'dependencies': ['dependency1', 'dependency2'],
            'taskGroupId': 'dependency0',
        },
        'runId': 'runId',
    }
    yield rw_context


@pytest.mark.parametrize("extension", ('foo.log', 'bar.asc'))
def test_force_mimetypes_to_plain_text(extension):
    # Function is not called explicitly here, because it should have occured at import time
    assert mimetypes.guess_type(extension)[0] == 'text/plain'


MIME_TYPES = {
    '/foo/bar/test.txt': ('text/plain', None),
    '/tmp/blah.tgz': ('application/x-tar', 'gzip'),
    '~/Firefox.dmg': ('application/x-apple-diskimage', None),
    '/foo/bar/blah.log': ('text/plain', None),
    '/foo/bar/chainOfTrust.asc': ('text/plain', None),
    '/totally/unknown': ('application/binary', None),
}


# guess_content_type {{{1
@pytest.mark.parametrize("mime_types", [(k, v) for k, v in sorted(MIME_TYPES.items())])
def test_guess_content_type(mime_types):
    path, (mimetype, encoding) = mime_types
    assert guess_content_type_and_encoding(path) == (mimetype, encoding)


# get_expiration_arrow {{{1
def test_expiration_arrow(context):

    # make sure time differences don't screw up the test
    expiration = get_expiration_arrow(context)
    assert expiration.isoformat() == context.task['expires']


# upload_artifacts {{{1
def test_upload_artifacts(context, event_loop):
    args = []
    os.makedirs(os.path.join(context.config['artifact_dir'], 'public'))
    paths = [
        os.path.join(context.config['artifact_dir'], 'one'),
        os.path.join(context.config['artifact_dir'], 'public/two'),
    ]
    for path in paths:
        touch(path)

    async def foo(_, path, **kwargs):
        args.append(path)

    with mock.patch('scriptworker.artifacts.create_artifact', new=foo):
        event_loop.run_until_complete(
            upload_artifacts(context)
        )

    assert sorted(args) == sorted(paths)

@pytest.mark.parametrize('filename, original_content, expected_content_type, expected_encoding', (
    ('file.txt', 'Foo bar', 'text/plain', 'gzip'),
    ('file.log',  '12:00:00 Foo bar', 'text/plain', 'gzip'),
    ('file.json', json.dumps({'foo': 'bar'}), 'application/json', 'gzip'),
    ('file.html', '<html><h1>foo</h1>bar</html>', 'text/html', 'gzip'),
    ('file.xml',  '<foo>bar</foo>', 'text/xml', 'gzip'),
    ('file.unknown',  'Unknown foo bar', 'application/binary', None),
))
def test_compress_artifact_if_supported(filename, original_content, expected_content_type, expected_encoding):
    with tempfile.TemporaryDirectory() as temp_dir:
        absolute_path = os.path.join(temp_dir, filename)
        with open(absolute_path, 'w') as f:
            f.write(original_content)

        old_number_of_files = _get_number_of_children_in_directory(temp_dir)

        content_type, encoding = compress_artifact_if_supported(absolute_path)
        assert content_type, encoding == (expected_content_type, expected_encoding)
        # compress_artifact_if_supported() should replace the existing file
        assert _get_number_of_children_in_directory(temp_dir) == old_number_of_files

        open_function = gzip.open if expected_encoding == 'gzip' else open
        with open_function(absolute_path, 'rt') as f:
            assert f.read() == original_content


def _get_number_of_children_in_directory(directory):
    return len([name for name in os.listdir(directory)])

# create_artifact {{{1
def test_create_artifact(context, fake_session, successful_queue, event_loop):
    path = os.path.join(context.config['artifact_dir'], "one.txt")
    touch(path)
    context.session = fake_session
    expires = arrow.utcnow().isoformat()
    context.temp_queue = successful_queue
    event_loop.run_until_complete(
        create_artifact(context, path, "public/env/one.txt", content_type='text/plain', content_encoding=None, expires=expires)
    )
    assert successful_queue.info == [
        "createArtifact", ('taskId', 'runId', "public/env/one.txt", {
            "storageType": "s3",
            "expires": expires,
            "contentType": "text/plain",
        }), {}
    ]

    # TODO: Assert the content of the PUT request is valid. This can easily be done once MagicMock supports async
    # context managers. See http://bugs.python.org/issue26467 and https://github.com/Martiusweb/asynctest/issues/29.
    context.session.close()


def test_create_artifact_retry(context, fake_session_500, successful_queue,
                               event_loop):
    path = os.path.join(context.config['artifact_dir'], "one.log")
    touch(path)
    context.session = fake_session_500
    expires = arrow.utcnow().isoformat()
    with pytest.raises(ScriptWorkerRetryException):
        context.temp_queue = successful_queue
        event_loop.run_until_complete(
            create_artifact(context, path, "public/env/one.log", content_type='text/plain', content_encoding=None, expires=expires)
        )
    context.session.close()


def test_craft_artifact_put_headers():
    assert _craft_artifact_put_headers('text/plain') == {'Content-Type': 'text/plain'}
    assert _craft_artifact_put_headers('text/plain', encoding=None) == {'Content-Type': 'text/plain'}
    assert _craft_artifact_put_headers('text/plain', 'gzip') == {'Content-Type': 'text/plain', 'Content-Encoding': 'gzip'}


# get_artifact_url {{{1
@pytest.mark.parametrize("path", ("public/rel/path", "private/foo"))
def test_get_artifact_url(path):

    expected = "https://netloc/v1/{}".format(path)

    def buildUrl(*args, **kwargs):
        if path.startswith('public/'):
            return expected

    def buildSignedUrl(*args, **kwargs):
        if not path.startswith('public/'):
            return expected

    context = mock.MagicMock()
    context.queue = mock.MagicMock()
    context.queue.options = {'baseUrl': 'https://netloc/'}
    context.queue.buildUrl = buildUrl
    context.queue.buildSignedUrl = buildSignedUrl
    assert get_artifact_url(context, "x", path) == expected


# download_artifacts {{{1
def test_download_artifacts(context, event_loop):
    urls = []
    paths = []

    expected_urls = [
        "https://queue.taskcluster.net/v1/task/dependency1/artifacts/foo/bar",
        "https://queue.taskcluster.net/v1/task/dependency2/artifacts/baz",
    ]
    expected_paths = [
        os.path.join(context.config['work_dir'], "foo", "bar"),
        os.path.join(context.config['work_dir'], "baz"),
    ]

    async def foo(_, url, path, **kwargs):
        urls.append(url)
        paths.append(path)

    result = event_loop.run_until_complete(
        download_artifacts(context, expected_urls, download_func=foo)
    )

    assert sorted(result) == sorted(expected_paths)
    assert sorted(paths) == sorted(expected_paths)
    assert sorted(urls) == sorted(expected_urls)


def test_get_upstream_artifacts_full_paths_per_task_id(context):
    artifacts_to_succeed = [{
        'paths': ['public/file_a'],
        'taskId': 'dependency1',
        'taskType': 'signing',
    }, {
        'paths': ['public/file_b'],
        'taskId': 'dependency2',
        'taskType': 'signing',
    }]

    context.task['payload'] = {
        'upstreamArtifacts': [{
            'paths': ['public/failed_optional_file1'],
            'taskId': 'failedDependency1',
            'taskType': 'signing',
            'optional': True
        }, {
            'paths': ['public/failed_optional_file2', 'public/failed_optional_file3'],
            'taskId': 'failedDependency2',
            'taskType': 'signing',
            'optional': True
        }],
    }

    context.task['payload']['upstreamArtifacts'].extend(artifacts_to_succeed)
    for artifact in artifacts_to_succeed:
        folder = os.path.join(context.config['work_dir'], 'cot', artifact['taskId'])
        os.makedirs(os.path.join(folder, 'public'))
        touch(os.path.join(folder, artifact['paths'][0]))

    succeeded_artifacts, failed_artifacts = get_upstream_artifacts_full_paths_per_task_id(context)

    assert succeeded_artifacts == {
        'dependency1': [os.path.join(context.config['work_dir'], 'cot', 'dependency1', 'public', 'file_a')],
        'dependency2': [os.path.join(context.config['work_dir'], 'cot', 'dependency2', 'public', 'file_b')],
    }
    assert failed_artifacts == {
        'failedDependency1': ['public/failed_optional_file1'],
        'failedDependency2': ['public/failed_optional_file2', 'public/failed_optional_file3'],
    }


def test_fail_get_upstream_artifacts_full_paths_per_task_id(context):
    context.task['payload'] = {
        'upstreamArtifacts': [{
            'paths': ['public/failed_mandatory_file'],
            'taskId': 'failedDependency',
            'taskType': 'signing',
        }]
    }
    with pytest.raises(ScriptWorkerTaskException):
        get_upstream_artifacts_full_paths_per_task_id(context)


def test_get_and_check_single_upstream_artifact_full_path(context):
    folder = os.path.join(context.config['work_dir'], 'cot', 'dependency1')
    os.makedirs(os.path.join(folder, 'public'))
    touch(os.path.join(folder, 'public/file_a'))

    assert get_and_check_single_upstream_artifact_full_path(context, 'dependency1', 'public/file_a') == \
        os.path.join(context.config['work_dir'], 'cot', 'dependency1', 'public', 'file_a')

    with pytest.raises(ScriptWorkerTaskException):
        get_and_check_single_upstream_artifact_full_path(context, 'dependency1', 'public/non_existing_file')

    with pytest.raises(ScriptWorkerTaskException):
        get_and_check_single_upstream_artifact_full_path(context, 'non-existing-dep', 'public/file_a')


def test_get_single_upstream_artifact_full_path(context):
    folder = os.path.join(context.config['work_dir'], 'cot', 'dependency1')

    assert get_single_upstream_artifact_full_path(context, 'dependency1', 'public/file_a') == \
        os.path.join(context.config['work_dir'], 'cot', 'dependency1', 'public', 'file_a')

    assert get_single_upstream_artifact_full_path(context, 'dependency1', 'public/non_existing_file') == \
        os.path.join(context.config['work_dir'], 'cot', 'dependency1', 'public', 'non_existing_file')

    assert get_single_upstream_artifact_full_path(context, 'non-existing-dep', 'public/file_a') == \
        os.path.join(context.config['work_dir'], 'cot', 'non-existing-dep', 'public', 'file_a')


@pytest.mark.parametrize('upstream_artifacts, expected', ((
    [{}], {},
), (
    [{'taskId': 'someTaskId', 'paths': ['mandatory_artifact_1']}], {},
), (
    [{'taskId': 'someTaskId', 'paths': ['optional_artifact_1'], 'optional': True}],
    {'someTaskId': ['optional_artifact_1']},
), (
    [{'taskId': 'someTaskId', 'paths': ['optional_artifact_1', 'optional_artifact_2'], 'optional': True}],
    {'someTaskId': ['optional_artifact_1', 'optional_artifact_2']},
), (
    [
        {'taskId': 'someTaskId', 'paths': ['optional_artifact_1'], 'optional': True},
        {'taskId': 'someOtherTaskId', 'paths': ['optional_artifact_2'], 'optional': True},
        {'taskId': 'anotherOtherTaskId', 'paths': ['mandatory_artifact_1']},
    ],
    {'someTaskId': ['optional_artifact_1'], 'someOtherTaskId': ['optional_artifact_2']},
), (
    [
        {'taskId': 'taskIdGivenThreeTimes', 'paths': ['optional_artifact_1'], 'optional': True},
        {'taskId': 'taskIdGivenThreeTimes', 'paths': ['mandatory_artifact_1']},
        {'taskId': 'taskIdGivenThreeTimes', 'paths': ['optional_artifact_2'], 'optional': True},
    ],
    {'taskIdGivenThreeTimes': ['optional_artifact_1', 'optional_artifact_2']},
)))
def test_get_optional_artifacts_per_task_id(upstream_artifacts, expected):
    assert get_optional_artifacts_per_task_id(upstream_artifacts) == expected
