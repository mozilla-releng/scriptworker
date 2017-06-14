#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.cot.verify
"""
import asyncio
from copy import deepcopy
from frozendict import frozendict
import json
import logging
import mock
import os
import pytest
import tempfile
from taskcluster.exceptions import TaskclusterFailure
import scriptworker.cot.verify as cotverify
from scriptworker.exceptions import CoTError, ScriptWorkerGPGException
from scriptworker.utils import makedirs
from . import noop_async, noop_sync, rw_context, tmpdir, touch

assert rw_context, tmpdir  # silence pyflakes

log = logging.getLogger(__name__)

# constants helpers and fixtures {{{1
VALID_WORKER_IMPLS = (
    'docker-worker',
    'generic-worker',
    'scriptworker',
    'taskcluster-worker',
)


async def die_async(*args, **kwargs):
    raise CoTError("x")


@pytest.yield_fixture(scope='function')
def chain(rw_context):
    rw_context.config['scriptworker_provisioners'] = [rw_context.config['provisioner_id']]
    rw_context.config['scriptworker_worker_types'] = [rw_context.config['worker_type']]
    rw_context.config['docker_image_allowlists'] = {
        "decision": ["sha256:decision_image_sha"],
        "docker-image": ["sha256:docker_image_sha"],
    }
    rw_context.task = {
        'scopes': ['project:releng:signing:cert:nightly-signing', 'ignoreme'],
        'dependencies': ['decision_task_id'],
        'provisionerId': rw_context.config['provisioner_id'],
        'schedulerId': 'schedulerId',
        'workerType': rw_context.config['worker_type'],
        'taskGroupId': 'decision_task_id',
        'payload': {
            'image': None,
        },
        'metadata': {
            'source': 'https://hg.mozilla.org/mozilla-central/foo'
        },
    }
    # decision_task_id
    chain_ = cotverify.ChainOfTrust(
        rw_context, 'signing', task_id='my_task_id'
    )
    yield chain_


@pytest.yield_fixture(scope='function')
def build_link(chain):
    link = cotverify.LinkOfTrust(chain.context, 'build', 'build_task_id')
    link.cot = {
        'environment': {
            'imageArtifactHash': "sha256:built_docker_image_sha",
        },
    }
    link.task = {
        'taskGroupId': 'decision_task_id',
        'schedulerId': 'scheduler_id',
        'provisionerId': 'provisioner',
        'workerType': 'workerType',
        'scopes': [],
        'dependencies': ['some_task_id'],
        'metadata': {
            'source': 'https://hg.mozilla.org/mozilla-central',
        },
        'payload': {
            'artifacts': {
                'foo': {
                    'sha256': "foo_sha",
                    'expires': "blah",
                },
                'bar': {
                    'sha256': "bar_sha",
                },
            },
            'image': {
                'taskId': 'docker_image_task_id',
                'path': 'path/image',
            },
            'env': {
                'HG_STORE_PATH': 'foo',
            },
        },
        'extra': {
            'chainOfTrust': {
                'inputs': {
                    'docker-image': 'docker_image_task_id',
                },
            },
        },
    }
    yield link


@pytest.yield_fixture(scope='function')
def decision_link(chain):
    link = cotverify.LinkOfTrust(chain.context, 'decision', 'decision_task_id')
    link.cot = {
        'environment': {
            'imageHash': "sha256:decision_image_sha",
        },
    }
    link.task = {
        'taskGroupId': 'decision_task_id',
        'schedulerId': 'scheduler_id',
        'provisionerId': 'provisioner_id',
        'workerType': 'workerType',
        'scopes': [],
        'metadata': {
            'source': 'https://hg.mozilla.org/mozilla-central',
        },
        'payload': {
            'image': "blah",
        },
        'extra': {},
    }
    yield link


@pytest.yield_fixture(scope='function')
def docker_image_link(chain):
    link = cotverify.LinkOfTrust(chain.context, 'docker-image', 'docker_image_task_id')
    link.cot = {
        'artifacts': {
            'path/image': {
                'sha256': 'built_docker_image_sha',
            },
        },
        'environment': {
            'imageHash': "sha256:docker_image_sha",
        },
    }
    link.task = {
        'taskGroupId': 'decision_task_id',
        'schedulerId': 'scheduler_id',
        'provisionerId': 'provisioner_id',
        'workerType': 'workerType',
        'scopes': [],
        'metadata': {
            'source': 'https://hg.mozilla.org/mozilla-central',
        },
        'payload': {
            'image': "blah",
            'env': {
                "HEAD_REF": "x",
            },
            'command': ["/bin/bash", "-c", "/home/worker/bin/build_image.sh"],
        },
        'extra': {},
    }
    yield link


# dependent_task_ids {{{1
def test_dependent_task_ids(chain):
    ids = ["one", "TWO", "thr33", "vier"]
    for i in ids:
        l = cotverify.LinkOfTrust(chain.context, 'build', i)
        chain.links.append(l)
    assert sorted(chain.dependent_task_ids()) == sorted(ids)


# is_try {{{1
@pytest.mark.parametrize("bools,expected", (([False, False], False), ([False, True], True)))
def test_chain_is_try(chain, bools, expected):
    for b in bools:
        m = mock.MagicMock()
        m.is_try = b
        chain.links.append(m)
    assert chain.is_try() == expected


@pytest.mark.parametrize("task", (
    {'payload': {'env': {'GECKO_HEAD_REPOSITORY': "https://hg.mozilla.org/try/blahblah"}}, 'metadata': {}, 'schedulerId': "x"},
    {'payload': {'env': {'GECKO_HEAD_REPOSITORY': "https://hg.mozilla.org/mozilla-central", "MH_BRANCH": "try"}}, 'metadata': {}, "schedulerId": "x"},
    {'payload': {}, 'metadata': {'source': 'http://hg.mozilla.org/try'}, 'schedulerId': "x"},
    {'payload': {}, 'metadata': {}, 'schedulerId': "gecko-level-1"},
))
def test_is_try(task):
    assert cotverify.is_try(task)


# get_link {{{1
@pytest.mark.parametrize("ids,req,raises", ((
    ("one", "two", "three"), "one", False
), (
    ("one", "one", "two"), "one", True
), (
    ("one", "two"), "three", True
)))
def test_get_link(chain, ids, req, raises):
    for i in ids:
        l = cotverify.LinkOfTrust(chain.context, 'build', i)
        chain.links.append(l)
    if raises:
        with pytest.raises(CoTError):
            chain.get_link(req)
    else:
        chain.get_link(req)


# link.task {{{1
def test_link_task(chain):
    link = cotverify.LinkOfTrust(chain.context, 'build', "one")
    link.task = chain.task
    assert not link.is_try
    assert link.worker_impl == 'scriptworker'
    with pytest.raises(CoTError):
        link.task = {}


# link.cot {{{1
def test_link_cot(chain):
    link = cotverify.LinkOfTrust(chain.context, 'build', "one")
    link.cot = chain.task
    assert link.cot == chain.task
    with pytest.raises(CoTError):
        link.cot = {}


# raise_on_errors {{{1
@pytest.mark.parametrize("errors,raises", (([], False,), (["foo"], True)))
def test_raise_on_errors(errors, raises):
    if raises:
        with pytest.raises(CoTError):
            cotverify.raise_on_errors(errors)
    else:
        cotverify.raise_on_errors(errors)


# guess_worker_impl {{{1
@pytest.mark.parametrize("task,expected,raises", ((
    {'payload': {}, 'provisionerId': '', 'workerType': '', 'scopes': []},
    None, True
), (
    {'payload': {'image': 'x'}, 'provisionerId': '', 'workerType': '', 'scopes': ['docker-worker:']},
    'docker-worker', False
), (
    {'payload': {}, 'provisionerId': 'test-dummy-provisioner', 'workerType': 'test-dummy-myname', 'scopes': ["x"]},
    'scriptworker', False
), (
    {'payload': {'mounts': [], 'osGroups': []}, 'provisionerId': '', 'workerType': '', 'scopes': []},
    'generic-worker', False
), (
    {'payload': {'image': 'x'}, 'provisionerId': 'test-dummy-provisioner', 'workerType': '', 'scopes': []},
    None, True
), (
    {'payload': {'image': 'x', 'osGroups': []}, 'provisionerId': '', 'workerType': '', 'scopes': []},
    None, True
)))
def test_guess_worker_impl(chain, task, expected, raises):
    link = mock.MagicMock()
    link.task = task
    link.name = "foo"
    link.context = chain.context
    if raises:
        with pytest.raises(CoTError):
            cotverify.guess_worker_impl(link)
    else:
        assert expected == cotverify.guess_worker_impl(link)


# get_valid_worker_impls {{{1
def test_get_valid_worker_impls():
    result = cotverify.get_valid_worker_impls()
    assert isinstance(result, frozendict)
    for key, value in result.items():
        assert key in VALID_WORKER_IMPLS
        assert callable(value)


# get_task_type {{{1
def test_get_task_type():
    for name in cotverify.get_valid_task_types().keys():
        with pytest.raises(CoTError):
            cotverify.guess_task_type("foo:bar:baz:{}0".format(name))
        assert name == cotverify.guess_task_type("foo:bar:baz:{}".format(name))


# check_interactive_docker_worker {{{1
@pytest.mark.parametrize("task,has_errors", ((
    {'payload': {'features': {}, 'env': {}, }}, False
), (
    {'payload': {'features': {'interactive': True}, 'env': {}, }}, True
), (
    {'payload': {'features': {}, 'env': {'TASKCLUSTER_INTERACTIVE': "x"}, }}, True
), (
    {}, True
)))
def test_check_interactive_docker_worker(task, has_errors):
    link = mock.MagicMock()
    link.name = "foo"
    link.task = task
    result = cotverify.check_interactive_docker_worker(link)
    if has_errors:
        assert len(result) >= 1
    else:
        assert result == []


# verify_docker_image_sha {{{1
def test_verify_docker_image_sha(chain, build_link, decision_link, docker_image_link):
    chain.links = [build_link, decision_link, docker_image_link]
    for link in chain.links:
        cotverify.verify_docker_image_sha(chain, link)


def test_verify_docker_image_sha_wrong_built_sha(chain, build_link, decision_link, docker_image_link):
    chain.links = [build_link, decision_link, docker_image_link]
    docker_image_link.cot['artifacts']['path/image']['sha256'] = "wrong_sha"
    with pytest.raises(CoTError):
        cotverify.verify_docker_image_sha(chain, build_link)


def test_verify_docker_image_sha_missing(chain, build_link, decision_link, docker_image_link):
    chain.links = [build_link, decision_link, docker_image_link]
    # missing built sha
    docker_image_link.cot['artifacts']['path/image']['sha256'] = None
    with pytest.raises(CoTError):
        cotverify.verify_docker_image_sha(chain, build_link)


def test_verify_docker_image_sha_wrong_task_id(chain, build_link, decision_link, docker_image_link):
    chain.links = [build_link, decision_link, docker_image_link]
    # wrong task id
    build_link.task['extra']['chainOfTrust']['inputs']['docker-image'] = "wrong_task_id"
    with pytest.raises(CoTError):
        cotverify.verify_docker_image_sha(chain, build_link)


def test_verify_docker_image_sha_bad_allowlist(chain, build_link, decision_link, docker_image_link):
    chain.links = [build_link, decision_link, docker_image_link]
    # wrong docker hub sha
    decision_link.cot['environment']['imageHash'] = "sha256:not_allowlisted"
    with pytest.raises(CoTError):
        cotverify.verify_docker_image_sha(chain, decision_link)


@pytest.mark.parametrize("task,expected", ((
    {'taskGroupId': 'task_id', 'extra': {}, 'payload': {}},
    []
), (
    {'taskGroupId': 'decision_task_id', 'extra': {}, 'payload': {}},
    [('build:decision', 'decision_task_id')]
), (
    {
        'taskGroupId': 'decision_task_id',
        'extra': {
            'chainOfTrust': {'inputs': {'docker-image': 'docker_image_task_id'}}
        },
        'payload': {},
    }, [
        ('build:decision', 'decision_task_id'),
        ('build:docker-image', 'docker_image_task_id'),
    ]
), (
    {
        'taskGroupId': 'decision_task_id',
        'extra': {
            'chainOfTrust': {'inputs': {'docker-image': 'docker_image_task_id'}}
        },
        'payload': {
            'upstreamArtifacts': [{
                'taskId': "blah_task_id",
                'taskType': "blah",
            }, {
                'taskId': "blah_task_id",
                'taskType': "blah",
            }],
        },
    }, [
        ('build:decision', 'decision_task_id'),
        ('build:blah', 'blah_task_id'),
        ('build:blah', 'blah_task_id'),     # Duplicates aren't deleted
        ('build:docker-image', 'docker_image_task_id'),
    ]
), (
    # PushAPK-like definitions
    {
        'taskGroupId': 'decision_task_id',
        'extra': {},
        'payload': {
            'upstreamArtifacts': [{
                'taskId': 'platform_0_signing_task_id',
                'taskType': 'signing',
            }, {
                'taskId': 'platform_1_signing_task_id',
                'taskType': 'signing',
            }, {
                'taskId': 'platform_2_signing_task_id',
                'taskType': 'signing',
            }],
        },
    }, [
        ('build:decision', 'decision_task_id'),
        ('build:signing', 'platform_0_signing_task_id'),
        ('build:signing', 'platform_1_signing_task_id'),
        ('build:signing', 'platform_2_signing_task_id'),
    ]
)))
def test_find_sorted_task_dependencies(task, expected):
    assert expected == cotverify.find_sorted_task_dependencies(task, 'build', 'task_id')


# build_task_dependencies {{{1
@pytest.mark.asyncio
async def test_build_task_dependencies(chain, mocker, event_loop):

    async def fake_task(task_id):
        if task_id == 'die':
            raise TaskclusterFailure("dying")
        else:
            return {
                'taskGroupId': 'decision_task_id',
                'provisionerId': '',
                'schedulerId': '',
                'workerType': '',
                'scopes': [],
                'payload': {
                    'image': "x",
                },
                'metadata': {},
            }

    def fake_find(task, name, _):
        if name.endswith('decision'):
            return []
        return [
            ('build:decision', 'decision_task_id'),
            ('build:a', 'already_exists'),
            ('build:docker-image', 'die'),
        ]

    already_exists = mock.MagicMock()
    already_exists.task_id = 'already_exists'
    chain.links = [already_exists]

    chain.context.queue = mock.MagicMock()
    chain.context.queue.task = fake_task

    mocker.patch.object(cotverify, 'find_sorted_task_dependencies', new=fake_find)
    with pytest.raises(CoTError):
        await cotverify.build_task_dependencies(chain, {}, 'too:many:colons:in:this:name:z', 'task_id')
    with pytest.raises(CoTError):
        await cotverify.build_task_dependencies(chain, {}, 'build', 'task_id')


# download_cot {{{1
@pytest.mark.parametrize("raises", (True, False))
@pytest.mark.asyncio
async def test_download_cot(chain, mocker, raises, event_loop):
    async def down(*args, **kwargs):
        return ['x']

    def sha(*args, **kwargs):
        return "sha"

    m = mock.MagicMock()
    m.task_id = "x"
    m.cot_dir = "y"
    chain.links = [m]
    mocker.patch.object(cotverify, 'get_artifact_url', new=noop_sync)
    if raises:
        mocker.patch.object(cotverify, 'download_artifacts', new=die_async)
        with pytest.raises(CoTError):
            await cotverify.download_cot(chain)
    else:
        mocker.patch.object(cotverify, 'download_artifacts', new=down)
        mocker.patch.object(cotverify, 'get_hash', new=sha)
        await cotverify.download_cot(chain)


# download_cot_artifact {{{1
@pytest.mark.parametrize("path,sha,raises", ((
    "one", "sha", False
), (
    "one", "bad_sha", True
), (
    "bad", "bad_sha", True
), (
    "missing", "bad_sha", True
)))
@pytest.mark.asyncio
async def test_download_cot_artifact(chain, path, sha, raises, mocker, event_loop):

    def fake_get_hash(*args, **kwargs):
        return sha

    link = mock.MagicMock()
    link.task_id = 'task_id'
    link.name = 'name'
    link.cot_dir = 'cot_dir'
    link.cot = {
        'artifacts': {
            'one': {
                'sha256': 'sha',
            },
            'bad': {
                'illegal': 'bad_sha',
            },
        }
    }
    chain.links = [link]
    mocker.patch.object(cotverify, 'get_artifact_url', new=noop_sync)
    mocker.patch.object(cotverify, 'download_artifacts', new=noop_async)
    mocker.patch.object(cotverify, 'get_hash', new=fake_get_hash)
    if raises:
        with pytest.raises(CoTError):
            await cotverify.download_cot_artifact(chain, 'task_id', path)
    else:
        await cotverify.download_cot_artifact(chain, 'task_id', path)


# download_cot_artifacts {{{1
@pytest.mark.parametrize("raises", (True, False))
@pytest.mark.asyncio
async def test_download_cot_artifacts(chain, raises, mocker, event_loop):

    async def fake_download(x, y, path):
        return path

    artifact_dict = {'task_id': ['path1', 'path2']}
    if raises:
        mocker.patch.object(cotverify, 'download_cot_artifact', new=die_async)
        with pytest.raises(CoTError):
            await cotverify.download_cot_artifacts(chain, artifact_dict)
    else:
        mocker.patch.object(cotverify, 'download_cot_artifact', new=fake_download)
        result = await cotverify.download_cot_artifacts(chain, artifact_dict)
        assert sorted(result) == ['path1', 'path2']


# download_firefox_cot_artifacts {{{1
@pytest.mark.parametrize("upstream_artifacts,expected", ((
    None, {'decision_task_id': ['public/task-graph.json']}
), (
    [{
        "taskId": "id1",
        "paths": ["id1_path1", "id1_path2"],
    }, {
        "taskId": "id2",
        "paths": ["id2_path1", "id2_path2"],
    }],
    {
        'decision_task_id': ['public/task-graph.json'],
        'id1': ['id1_path1', 'id1_path2'],
        'id2': ['id2_path1', 'id2_path2'],
    }
)))
@pytest.mark.asyncio
async def test_download_firefox_cot_artifacts(chain, decision_link, build_link,
                                              upstream_artifacts, expected,
                                              docker_image_link, mocker, event_loop):

    async def fake_download(_, result):
        return result

    chain.links = [decision_link, build_link, docker_image_link]
    if upstream_artifacts is not None:
        chain.task['payload']['upstreamArtifacts'] = upstream_artifacts
    mocker.patch.object(cotverify, 'download_cot_artifacts', new=fake_download)
    assert expected == await cotverify.download_firefox_cot_artifacts(chain)


# verify_cot_signatures {{{1
def test_verify_cot_signatures_no_file(chain, build_link, mocker):
    chain.links = [build_link]
    mocker.patch.object(cotverify, 'GPG', new=noop_sync)
    with pytest.raises(CoTError):
        cotverify.verify_cot_signatures(chain)


def test_verify_cot_signatures_bad_sig(chain, build_link, mocker):

    def die(*args, **kwargs):
        raise ScriptWorkerGPGException("x")

    path = os.path.join(build_link.cot_dir, 'public/chainOfTrust.json.asc')
    makedirs(os.path.dirname(path))
    touch(path)
    chain.links = [build_link]
    mocker.patch.object(cotverify, 'GPG', new=noop_sync)
    mocker.patch.object(cotverify, 'get_body', new=die)
    with pytest.raises(CoTError):
        cotverify.verify_cot_signatures(chain)


def test_verify_cot_signatures(chain, build_link, mocker):

    def fake_body(*args, **kwargs):
        return '{}'

    build_link._cot = None
    unsigned_path = os.path.join(build_link.cot_dir, 'public/chainOfTrust.json.asc')
    path = os.path.join(build_link.cot_dir, 'chainOfTrust.json')
    makedirs(os.path.dirname(unsigned_path))
    touch(unsigned_path)
    chain.links = [build_link]
    mocker.patch.object(cotverify, 'GPG', new=noop_sync)
    mocker.patch.object(cotverify, 'get_body', new=fake_body)
    cotverify.verify_cot_signatures(chain)
    assert os.path.exists(path)
    with open(path, "r") as fh:
        assert json.load(fh) == {}

@pytest.mark.parametrize('payload, expected', (
    ({}, {}),
    (
        {
            'artifacts': {
                'public/build': {
                    'path': 'public/build',
                    'expires': '2018-06-13T14:06:47.295419Z',
                    'type': 'directory',
                },
            },
        },
        {
            'artifacts': {
                'public/build': {
                    'path': 'public/build',
                    'type': 'directory',
                },
            },
        },
    ), (
        {
            'artifacts': [{
                'path': 'public/build',
                'expires': '2018-06-13T14:06:47.295419Z',
                'type': 'directory',
                'name': 'public/build'
            }],
        },
        {
            'artifacts': [{
                'path': 'public/build',
                'type': 'directory',
                'name': 'public/build'
            }],
        },
    ),
))
def test_take_expires_out_from_artifacts_in_payload(payload, expected):
    assert cotverify._take_expires_out_from_artifacts_in_payload(payload) == expected


def test_wrong_take_expires_out_from_artifacts_in_payload():
    with pytest.raises(CoTError):
        cotverify._take_expires_out_from_artifacts_in_payload({
            'artifacts': 0,
        })


# verify_link_in_task_graph {{{1
def test_verify_link_in_task_graph(chain, decision_link, build_link):
    chain.links = [decision_link, build_link]
    decision_link.task_graph = {
        build_link.task_id: {
            'task': deepcopy(build_link.task)
        },
        chain.task_id: {
            'task': deepcopy(chain.task)
        }
    }
    cotverify.verify_link_in_task_graph(chain, decision_link, build_link)


@pytest.mark.parametrize("zero_deps", (True, False))
def test_verify_link_in_task_graph_fuzzy_match(chain, decision_link, build_link, zero_deps):
    chain.links = [decision_link, build_link]
    task_defn1 = deepcopy(build_link.task)
    task_defn2 = deepcopy(chain.task)
    if zero_deps:
        build_link.task['dependencies'] = []
        chain.task['dependencies'] = []
    decision_link.task_graph = {
        'bogus-task-id': {
            'task': task_defn1
        },
        'bogus-task-id2': {
            'task': task_defn2
        }
    }
    cotverify.verify_link_in_task_graph(chain, decision_link, build_link)


def test_verify_link_in_task_graph_exception(chain, decision_link, build_link):
    chain.links = [decision_link, build_link]
    bad_task = deepcopy(build_link.task)
    bad_task['dependencies'].append("foo")
    bad_task['x'] = 'y'
    build_link.task['x'] = 'z'
    decision_link.task_graph = {
        build_link.task_id: {
            'task': bad_task
        },
        chain.task_id: {
            'task': deepcopy(chain.task)
        },
    }
    with pytest.raises(CoTError):
        cotverify.verify_link_in_task_graph(chain, decision_link, build_link)


def test_verify_link_in_task_graph_fuzzy_match_exception(chain, decision_link, build_link):
    chain.links = [decision_link, build_link]
    bad_task = deepcopy(build_link.task)
    bad_task['dependencies'].append("foo")
    bad_task['x'] = 'y'
    build_link.task['x'] = 'z'
    decision_link.task_graph = {
        'bogus-task-id': {
            'task': bad_task
        },
        'bogus-task-id2': {
            'task': deepcopy(chain.task)
        },
    }
    with pytest.raises(CoTError):
        cotverify.verify_link_in_task_graph(chain, decision_link, build_link)


# verify_firefox_decision_command {{{1
@pytest.mark.parametrize("command,raises", ((
    [
        '/home/worker/bin/run-task',
        '--vcs-checkout=foo',
        '--',
        'bash',
        '-cx',
        'cd foo && ln -s x y && ./mach --foo taskgraph decision --bar --baz',
    ], False
), (
    [
        '/bad/worker/bin/run-task',
        '--vcs-checkout=foo',
        '--',
        'bash',
        '-cx',
        'cd foo && ln -s x y && ./mach --foo taskgraph decision --bar --baz',
    ], True
), (
    [
        '/home/worker/bin/run-task',
        '--bad-option=foo',
        '--',
        'bash',
        '-cx',
        'cd foo && ln -s x y && ./mach --foo taskgraph decision --bar --baz',
    ], True
), (
    [
        '/home/worker/bin/run-task',
        '--bad-option=foo',
        '--',
        'bash',
        '-cx',
        'cd foo && -s x y && ./mach bad command',
    ], True
)))
def test_verify_firefox_decision_command(decision_link, command, raises):
    decision_link.task['payload']['command'] = command
    if raises:
        with pytest.raises(CoTError):
            cotverify.verify_firefox_decision_command(decision_link)
    else:
        cotverify.verify_firefox_decision_command(decision_link)


# verify_decision_task {{{1
@pytest.mark.asyncio
async def test_verify_decision_task(chain, decision_link, build_link, mocker):

    def task_graph(*args, **kwargs):
        return {
            build_link.task_id: {
                'task': deepcopy(build_link.task)
            },
            chain.task_id: {
                'task': deepcopy(chain.task)
            },
        }

    path = os.path.join(decision_link.cot_dir, "public", "task-graph.json")
    makedirs(os.path.dirname(path))
    touch(path)
    chain.links = [decision_link, build_link]
    decision_link.task['workerType'] = chain.context.config['valid_decision_worker_types'][0]
    mocker.patch.object(cotverify, 'load_json', new=task_graph)
    mocker.patch.object(cotverify, 'verify_firefox_decision_command', new=noop_sync)
    await cotverify.verify_decision_task(chain, decision_link)


@pytest.mark.asyncio
async def test_verify_decision_task_worker_type(chain, decision_link, build_link, mocker):

    def task_graph(*args, **kwargs):
        return {
            build_link.task_id: {
                'task': deepcopy(build_link.task)
            },
            chain.task_id: {
                'task': deepcopy(chain.task)
            },
        }

    path = os.path.join(decision_link.cot_dir, "public", "task-graph.json")
    makedirs(os.path.dirname(path))
    touch(path)
    chain.links = [decision_link, build_link]
    decision_link.task['workerType'] = 'bad-worker-type'
    mocker.patch.object(cotverify, 'load_json', new=task_graph)
    mocker.patch.object(cotverify, 'verify_firefox_decision_command', new=noop_sync)
    with pytest.raises(CoTError):
        await cotverify.verify_decision_task(chain, decision_link)


@pytest.mark.asyncio
async def test_verify_decision_task_missing_graph(chain, decision_link, build_link, mocker):
    chain.links = [decision_link, build_link]
    decision_link.task['workerType'] = chain.context.config['valid_decision_worker_types'][0]
    with pytest.raises(CoTError):
        await cotverify.verify_decision_task(chain, decision_link)


# verify_build_task {{{1
@pytest.mark.asyncio
async def test_verify_build_task(chain, build_link):
    await cotverify.verify_build_task(chain, build_link)


@pytest.mark.asyncio
async def test_verify_build_task_noop(chain, build_link):
    build_link.worker_impl = 'unknown'
    await cotverify.verify_build_task(chain, build_link)


# verify_docker_image_task {{{1
@pytest.mark.asyncio
async def test_verify_docker_image_task(chain, docker_image_link):
    docker_image_link.task['workerType'] = chain.context.config['valid_docker_image_worker_types'][0]
    await cotverify.verify_docker_image_task(chain, docker_image_link)


@pytest.mark.asyncio
async def test_verify_docker_image_task_worker_type(chain, docker_image_link):
    docker_image_link.task['workerType'] = 'bad-worker-type'
    with pytest.raises(CoTError):
        await cotverify.verify_docker_image_task(chain, docker_image_link)


@pytest.mark.asyncio
async def test_verify_docker_image_task_command(chain, docker_image_link):
    docker_image_link.task['workerType'] = chain.context.config['valid_docker_image_worker_types'][0]
    docker_image_link.task['payload']['command'] = ["illegal", "command!"]
    with pytest.raises(CoTError):
        await cotverify.verify_docker_image_task(chain, docker_image_link)


# verify_scriptworker_task {{{1
@pytest.mark.parametrize("func", ["verify_balrog_task", "verify_beetmover_task",
                                  "verify_pushapk_task", "verify_signing_task",
                                  "verify_scriptworker_task"])
@pytest.mark.asyncio
async def test_verify_scriptworker_task(chain, build_link, func):
    build_link.worker_impl = 'scriptworker'
    await getattr(cotverify, func)(chain, build_link)


@pytest.mark.parametrize("func", ["verify_balrog_task", "verify_beetmover_task",
                                  "verify_pushapk_task", "verify_signing_task",
                                  "verify_scriptworker_task"])
@pytest.mark.asyncio
async def test_verify_scriptworker_task_worker_impl(chain, build_link, func):
    build_link.worker_impl = 'bad_impl'
    with pytest.raises(CoTError):
        await getattr(cotverify, func)(chain, build_link)


# check_num_tasks {{{1
@pytest.mark.parametrize("num,raises", ((1, False), (2, False), (3, False), (0, True)))
def test_check_num_tasks(chain, num, raises):
    if raises:
        with pytest.raises(CoTError):
            cotverify.check_num_tasks(chain, {'decision': num})
    else:
        cotverify.check_num_tasks(chain, {'decision': num})


# verify_task_types {{{1
@pytest.mark.asyncio
async def test_verify_task_types(chain, decision_link, build_link, docker_image_link, mocker):
    chain.links = [decision_link, build_link, docker_image_link]
    for func in cotverify.get_valid_task_types().values():
        mocker.patch.object(cotverify, func.__name__, new=noop_async)
    expected = {'decision': 1, 'build': 1, 'docker-image': 1, 'signing': 1}
    assert expected == await cotverify.verify_task_types(chain)


# verify_docker_worker_task {{{1
@pytest.mark.asyncio
async def test_verify_docker_worker_task(mocker):
    mocker.patch.object(cotverify, 'check_interactive_docker_worker', new=noop_sync)
    mocker.patch.object(cotverify, 'verify_docker_image_sha', new=noop_sync)
    await cotverify.verify_docker_worker_task(mock.MagicMock(), mock.MagicMock())


# verify_generic_worker_task {{{1
@pytest.mark.asyncio
async def test_verify_generic_worker_task(mocker):
    await cotverify.verify_generic_worker_task(mock.MagicMock(), mock.MagicMock())


# verify_worker_impls {{{1
@pytest.mark.parametrize("raises", (True, False))
@pytest.mark.asyncio
async def test_verify_worker_impls(chain, decision_link, build_link,
                                   docker_image_link, raises, mocker):
    chain.links = [decision_link, build_link, docker_image_link]
    for func in cotverify.get_valid_worker_impls().values():
        mocker.patch.object(cotverify, func.__name__, new=noop_async)
    if raises:
        chain.worker_impl = 'docker-worker'
        with pytest.raises(CoTError):
            await cotverify.verify_worker_impls(chain)
    else:
        await cotverify.verify_worker_impls(chain)


# get_firefox_source_url {{{1
@pytest.mark.parametrize("task,expected", ((
    {
        'payload': {
            'env': {
                'GECKO_HEAD_REPOSITORY': 'https://example.com/blah',
            },
        },
        'metadata': {'source': 'https://example.com/blah/blah'}
    }, "https://example.com/blah/blah"
), (
    {
        'payload': {
            'env': {
                'GECKO_HEAD_REPOSITORY': 'https://example.com/blah/blah',
            },
        },
        'metadata': {'source': 'https://task/blah'}
    }, "https://example.com/blah/blah"
), (
    {
        'payload': {
            'env': {},
        },
        'metadata': {'source': 'https://example.com/blah'}
    }, "https://example.com/blah"
)))
def test_get_firefox_source_url(task, expected):
    obj = mock.MagicMock()
    obj.task = task
    assert expected == cotverify.get_firefox_source_url(obj)


# trace_back_to_firefox_tree {{{1
@pytest.mark.asyncio
async def test_trace_back_to_firefox_tree(chain, decision_link, build_link, docker_image_link):
    chain.links = [decision_link, build_link, docker_image_link]
    await cotverify.trace_back_to_firefox_tree(chain)


@pytest.mark.asyncio
async def test_trace_back_to_firefox_tree_bad_repo(chain):
    chain.task['metadata']['source'] = "https://hg.mozilla.org/try"
    with pytest.raises(CoTError):
        await cotverify.trace_back_to_firefox_tree(chain)


@pytest.mark.asyncio
async def test_trace_back_to_firefox_tree_bad_cot_product(chain):
    chain.context.config['cot_product'] = 'invalid-product!!!111'
    with pytest.raises(CoTError):
        await cotverify.trace_back_to_firefox_tree(chain)


@pytest.mark.asyncio
async def test_trace_back_to_firefox_tree_unknown_repo(chain, decision_link,
                                                       build_link, docker_image_link):
    docker_image_link.decision_task_id = 'other'
    docker_image_link.task['metadata']['source'] = "https://hg.mozilla.org/unknown/repo"
    chain.links = [decision_link, build_link, docker_image_link]
    with pytest.raises(CoTError):
        await cotverify.trace_back_to_firefox_tree(chain)


@pytest.mark.asyncio
async def test_trace_back_to_firefox_tree_docker_unknown_repo(chain, decision_link,
                                                              build_link, docker_image_link):
    build_link.task['metadata']['source'] = "https://hg.mozilla.org/unknown/repo"
    chain.links = [decision_link, build_link, docker_image_link]
    with pytest.raises(CoTError):
        await cotverify.trace_back_to_firefox_tree(chain)


@pytest.mark.asyncio
async def test_trace_back_to_firefox_tree_diff_repo(chain, decision_link,
                                                    build_link, docker_image_link):
    docker_image_link.decision_task_id = 'other'
    docker_image_link.task['metadata']['source'] = "https://hg.mozilla.org/releases/mozilla-aurora"
    chain.links = [decision_link, build_link, docker_image_link]
    await cotverify.trace_back_to_firefox_tree(chain)


# verify_chain_of_trust {{{1
@pytest.mark.parametrize("exc", (None, KeyError, CoTError))
@pytest.mark.asyncio
async def test_verify_chain_of_trust(chain, exc, mocker):

    async def maybe_die(*args):
        if exc is not None:
            raise exc("blah")

    for func in ('build_task_dependencies', 'download_cot', 'download_firefox_cot_artifacts',
                 'verify_task_types', 'verify_worker_impls'):
        mocker.patch.object(cotverify, func, new=noop_async)
    for func in ('verify_cot_signatures', 'check_num_tasks'):
        mocker.patch.object(cotverify, func, new=noop_sync)
    mocker.patch.object(cotverify, 'trace_back_to_firefox_tree', new=maybe_die)
    if exc:
        with pytest.raises(CoTError):
            await cotverify.verify_chain_of_trust(chain)
    else:
        await cotverify.verify_chain_of_trust(chain)


# verify_cot_cmdln {{{1
@pytest.mark.parametrize("args", (("x", "--task-type", "signing", "--cleanup"), ("x", "--task-type", "balrog")))
def test_verify_cot_cmdln(chain, args, tmpdir, mocker, event_loop):
    context = mock.MagicMock()
    context.queue = mock.MagicMock()
    context.queue.task = noop_async
    path = os.path.join(tmpdir, 'x')
    makedirs(path)

    def eloop():
        return event_loop

    def get_context():
        return context

    def mkdtemp():
        return path

    def cot(*args, **kwargs):
        m = mock.MagicMock()
        m.links = [mock.MagicMock()]
        m.dependent_task_ids = noop_sync
        return m

    mocker.patch.object(tempfile, 'mkdtemp', new=mkdtemp)
    mocker.patch.object(asyncio, 'get_event_loop', new=eloop)
    mocker.patch.object(cotverify, 'read_worker_creds', new=noop_sync)
    mocker.patch.object(cotverify, 'Context', new=get_context)
    mocker.patch.object(cotverify, 'ChainOfTrust', new=cot)
    mocker.patch.object(cotverify, 'verify_chain_of_trust', new=noop_async)

    cotverify.verify_cot_cmdln(args=args)
