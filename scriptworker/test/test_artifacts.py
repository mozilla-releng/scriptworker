import arrow
import os
import mock
import pytest

from scriptworker.artifacts import get_expiration_arrow, guess_content_type_and_encoding, upload_artifacts, \
    create_artifact, get_artifact_url, download_artifacts
from scriptworker.exceptions import ScriptWorkerRetryException


from . import touch, rw_context, event_loop, fake_session, fake_session_500, successful_queue


# TODO avoid copying this fixture
@pytest.yield_fixture(scope='function')
def context(rw_context):
    rw_context.config['artifact_expiration_hours'] = 1
    rw_context.config['reclaim_interval'] = 0.001
    rw_context.config['task_max_timeout'] = .1
    rw_context.config['task_script'] = ('bash', '-c', '>&2 echo bar && echo foo && exit 1')
    rw_context.claim_task = {
        'credentials': {'a': 'b'},
        'status': {'taskId': 'taskId'},
        'task': {'dependencies': ['dependency1', 'dependency2'], 'taskGroupId': 'dependency0'},
        'runId': 'runId',
    }
    yield rw_context


MIME_TYPES = {
    "/foo/bar/test.txt": "text/plain",
    "/tmp/blah.tgz": "application/x-tar",
    "~/Firefox.dmg": "application/x-apple-diskimage",
    "/foo/bar/blah.log": "text/plain",
    "/totally/unknown": "application/binary",
}


# get_expiration_arrow {{{1
def test_expiration_arrow(context):
    now = arrow.utcnow()

    # make sure time differences don't screw up the test
    with mock.patch.object(arrow, 'utcnow') as p:
        p.return_value = now
        expiration = get_expiration_arrow(context)
        diff = expiration.timestamp - now.timestamp
        assert diff == 3600


# guess_content_type {{{1
@pytest.mark.parametrize("mime_types", [(k, v) for k, v in sorted(MIME_TYPES.items())])
def test_guess_content_type(mime_types):
    path, mimetype = mime_types
    assert guess_content_type_and_encoding(path)[0] == mimetype


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


# get_artifact_url {{{1
def test_get_artifact_url():

    def makeRoute(*args, **kwargs):
        return "rel/path"

    context = mock.MagicMock()
    context.queue = mock.MagicMock()
    context.queue.options = {'baseUrl': 'https://netloc/'}
    context.queue.makeRoute = makeRoute
    assert get_artifact_url(context, "x", "y") == "https://netloc/v1/rel/path"


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
