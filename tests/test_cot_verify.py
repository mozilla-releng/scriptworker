#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.cot.verify"""
import json
import logging
import os
import tempfile
import time
from copy import deepcopy
from functools import partial
from unittest.mock import MagicMock

import aiohttp
import jsone
import pytest
from immutabledict import immutabledict

import scriptworker.context as swcontext
import scriptworker.cot.verify as cotverify
from scriptworker.artifacts import get_single_upstream_artifact_full_path
from scriptworker.exceptions import CoTError, DownloadError
from scriptworker.utils import load_json_or_yaml, makedirs, read_from_file

from . import create_async, noop_async, noop_sync, touch

log = logging.getLogger(__name__)

# constants helpers and fixtures {{{1
VALID_WORKER_IMPLS = ("docker-worker", "generic-worker", "scriptworker", "taskcluster-worker")


COTV2_DIR = os.path.join(os.path.dirname(__file__), "data", "cotv2")
COTV4_DIR = os.path.join(os.path.dirname(__file__), "data", "cotv4")
ED25519_DIR = os.path.join(os.path.dirname(__file__), "data", "ed25519")


def write_artifact(context, task_id, path, contents):
    path = get_single_upstream_artifact_full_path(context, task_id, path)
    os.makedirs(os.path.dirname(path))
    with open(path, "w") as f:
        f.write(contents)


async def die_async(*args, **kwargs):
    raise CoTError("x")


def die_sync(*args, **kwargs):
    raise CoTError("x")


@pytest.fixture(scope="function")
def chain(rw_context):
    yield _craft_chain(rw_context, scopes=["project:releng:signing:cert:nightly-signing", "ignoreme"])


@pytest.fixture(scope="function")
def try_chain(rw_context):
    yield _craft_chain(rw_context, scopes=["project:releng:signing:cert:dep-signing", "ignoreme"])


@pytest.fixture(scope="function")
def mobile_chain(mobile_rw_context):
    chain = _craft_chain(
        mobile_rw_context,
        scopes=["project:mobile:reference-browser:releng:signing:cert:release-signing", "ignoreme"],
        source_url="https://github.com/mozilla-mobile/reference-browser/raw/somerevision/.taskcluster.yml",
    )
    chain.context.config["github_oauth_token"] = "fakegithubtoken"
    chain.context.task["payload"]["env"] = {"MOBILE_HEAD_REPOSITORY": "https://github.com/mozilla-mobile/reference-browser"}
    yield chain


@pytest.fixture(scope="function")
def mobile_chain_pull_request(mobile_rw_context):
    chain = _craft_chain(
        mobile_rw_context,
        scopes=["project:mobile:reference-browser:releng:signing:cert:dep-signing", "ignoreme"],
        source_url="https://github.com/JohanLorenzo/reference-browser/raw/somerevision/.taskcluster.yml",
    )
    chain.context.config["github_oauth_token"] = "fakegithubtoken"
    chain.context.task["payload"]["env"] = {"MOBILE_HEAD_REPOSITORY": "https://github.com/JohanLorenzo/reference-browser"}
    yield chain


@pytest.fixture(scope="function")
def vpn_chain(vpn_private_rw_context):
    chain = _craft_chain(
        vpn_private_rw_context,
        scopes=["project:mozillavpn:releng:signing:cert:release-signing", "ignoreme"],
        source_url="https://github.com/mozilla-foobar/private-repo/raw/somerevision/.taskcluster.yml",
    )
    chain.context.config["github_oauth_token"] = "fakegithubtoken"
    chain.context.task["payload"]["env"] = {"MOZILLAVPN_HEAD_REPOSITORY": "https://github.com/mozilla-mobile/mozilla-vpn-client"}
    yield chain


def _craft_chain(context, scopes, source_url="https://hg.mozilla.org/mozilla-central"):
    context.config["scriptworker_provisioners"] = [context.config["provisioner_id"]]
    context.config["scriptworker_worker_types"] = [context.config["worker_type"]]
    context.task = {
        "created": {"relative-datestamp": "0 seconds"},
        "scopes": scopes,
        "dependencies": ["decision_task_id"],
        "provisionerId": context.config["provisioner_id"],
        "schedulerId": "schedulerId",
        "workerType": context.config["worker_type"],
        "taskGroupId": "decision_task_id",
        "payload": {"image": None},
        "metadata": {"source": source_url, "owner": "foo@example.tld"},
    }
    # decision_task_id
    return cotverify.ChainOfTrust(context, "signing", task_id="my_task_id")


@pytest.fixture(scope="function")
def build_link(chain):
    yield _craft_build_link(chain)


@pytest.fixture(scope="function")
def mobile_build_link(chain):
    link = _craft_build_link(chain, source_url="https://github.com/mozilla-mobile/reference-browser/raw/somerevision/.taskcluster.yml")
    link.task["payload"]["env"]["MOBILE_HEAD_REPOSITORY"] = "https://github.com/mozilla-mobile/reference-browser"

    yield link


def _craft_build_link(chain, source_url="https://hg.mozilla.org/mozilla-central"):
    link = cotverify.LinkOfTrust(chain.context, "build", "build_task_id")
    link.cot = {"taskId": "build_task_id", "environment": {"imageArtifactHash": "sha256:built_docker_image_sha"}}
    link.task = {
        "taskGroupId": "decision_task_id",
        "schedulerId": "scheduler_id",
        "provisionerId": "provisioner",
        "workerType": "workerType",
        "created": {"relative-datestamp": "0 seconds"},
        "scopes": [],
        "dependencies": ["some_task_id"],
        "metadata": {"source": source_url, "owner": "foo@example.tld"},
        "payload": {
            "artifacts": {"foo": {"sha256": "foo_sha", "expires": "blah"}, "bar": {"sha256": "bar_sha"}},
            "image": {"type": "task-image", "taskId": "docker_image_task_id", "path": "path/image"},
            "env": {"HG_STORE_PATH": "foo"},
        },
        "extra": {"chainOfTrust": {"inputs": {"docker-image": "docker_image_task_id"}}, "parent": "decision_task_id"},
    }
    return link


@pytest.fixture(scope="function")
def decision_link(chain):
    yield _craft_decision_link(chain, tasks_for="hg-push")


@pytest.fixture(scope="function")
def cron_link(chain):
    yield _craft_decision_link(chain, tasks_for="cron")


@pytest.fixture(scope="function")
def github_action_link(mobile_chain):
    link = cotverify.LinkOfTrust(mobile_chain.context, "action", "action_task_id")
    with open(os.path.join(COTV4_DIR, "action_github.json")) as fh:
        link.task = json.load(fh)
    yield link


@pytest.fixture(scope="function")
def mobile_github_release_link(mobile_chain):
    decision_link = _craft_decision_link(
        mobile_chain, tasks_for="github-releases", source_url="https://github.com/mozilla-mobile/reference-browser/raw/v9000.0.1/.taskcluster.yml"
    )
    decision_link.task["payload"]["env"] = {
        "MOBILE_HEAD_BRANCH": "releases/v9000.0",
        "MOBILE_HEAD_REPOSITORY": "https://github.com/mozilla-mobile/reference-browser",
        "MOBILE_HEAD_REV": "v9000.0.1",
    }
    yield decision_link


@pytest.fixture(scope="function")
def mobile_cron_link(mobile_chain):
    decision_link = _craft_decision_link(
        mobile_chain, tasks_for="cron", source_url="https://github.com/mozilla-mobile/reference-browser/raw/somerevision/.taskcluster.yml"
    )
    decision_link.task["payload"]["env"] = {
        "MOBILE_HEAD_BRANCH": "master",
        "MOBILE_HEAD_REPOSITORY": "https://github.com/mozilla-mobile/reference-browser",
        "MOBILE_HEAD_REV": "somerevision",
        "MOBILE_PUSH_DATE_TIME": "2019-02-01T12:00:00.000Z",
    }
    decision_link.task["extra"] = {"cron": '{"task_id":"cron-task-id"}'}
    yield decision_link


@pytest.fixture(scope="function")
def mobile_github_pull_request_link(mobile_chain):
    decision_link = _craft_decision_link(
        mobile_chain, tasks_for="github-pull-request", source_url="https://github.com/JohanLorenzo/reference-browser/raw/somerevision/.taskcluster.yml"
    )
    decision_link.task["payload"]["env"] = {
        "MOBILE_BASE_REF": "main",
        "MOBILE_BASE_REPOSITORY": "https://github.com/mozilla-mobile/firefox-android",
        "MOBILE_BASE_REV": "baserev",
        "MOBILE_HEAD_REF": "some-branch",
        "MOBILE_HEAD_REPOSITORY": "https://github.com/JohanLorenzo/reference-browser",
        "MOBILE_HEAD_REV": "somerevision",
        "MOBILE_PULL_REQUEST_NUMBER": "1234",
        "MOBILE_PUSH_DATE_TIME": "2019-02-01T12:00:00Z",
    }
    yield decision_link


@pytest.fixture(scope="function")
def mobile_github_push_link(mobile_chain):
    decision_link = _craft_decision_link(
        mobile_chain, tasks_for="github-push", source_url="https://github.com/mozilla-mobile/reference-browser/raw/somerevision/.taskcluster.yml"
    )
    decision_link.task["payload"]["env"] = {
        "MOBILE_BASE_REV": "somebaserevision",
        "MOBILE_HEAD_BRANCH": "refs/heads/some-branch",
        "MOBILE_HEAD_REPOSITORY": "https://github.com/mozilla-mobile/reference-browser",
        "MOBILE_HEAD_REV": "somerevision",
        "MOBILE_PUSH_DATE_TIME": "1549022400",
    }
    yield decision_link


def _craft_decision_link(chain, *, tasks_for, source_url="https://hg.mozilla.org/mozilla-central"):
    link = cotverify.LinkOfTrust(chain.context, "decision", "decision_task_id")
    link.cot = {"taskId": "decision_task_id", "environment": {"imageHash": "sha256:decision_image_sha"}}
    link.task = {
        "taskGroupId": "decision_task_id",
        "schedulerId": "scheduler_id",
        "provisionerId": "provisioner_id",
        "created": "2018-01-01T12:00:00.000Z",
        "workerType": "workerType",
        "dependencies": [],
        "scopes": [],
        "metadata": {"source": source_url, "owner": "foo@example.tld"},
        "payload": {"image": "blah"},
        "extra": {"cron": "{}", "tasks_for": tasks_for},
    }
    return link


@pytest.fixture(scope="function")
def action_link(chain):
    link = cotverify.LinkOfTrust(chain.context, "action", "action_task_id")
    link.cot = {"taskId": "action_task_id", "environment": {"imageHash": "sha256:decision_image_sha"}}
    link.task = {
        "taskGroupId": "decision_task_id",
        "schedulerId": "scheduler_id",
        "provisionerId": "provisioner_id",
        "created": "2018-01-01T12:00:00.000Z",
        "workerType": "workerType",
        "dependencies": [],
        "scopes": ["assume:repo:foo:action:bar"],
        "metadata": {"source": "https://hg.mozilla.org/mozilla-central"},
        "payload": {"env": {"ACTION_CALLBACK": ""}, "image": "blah"},
        "extra": {"action": {"context": {}}, "parent": "decision_task_id", "tasks_for": "action"},
    }
    yield link


@pytest.fixture(scope="function")
def docker_image_link(chain):
    link = cotverify.LinkOfTrust(chain.context, "docker-image", "docker_image_task_id")
    link.cot = {
        "taskId": "docker_image_task_id",
        "artifacts": {"path/image": {"sha256": "built_docker_image_sha"}},
        "environment": {"imageHash": "sha256:docker_image_sha"},
    }
    link.task = {
        "taskGroupId": "decision_task_id",
        "schedulerId": "scheduler_id",
        "provisionerId": "provisioner_id",
        "workerType": "workerType",
        "scopes": [],
        "metadata": {"source": "https://hg.mozilla.org/mozilla-central"},
        "payload": {"image": "blah", "env": {"HEAD_REF": "x"}, "command": ["/bin/bash", "-c", "/home/worker/bin/build_image.sh"]},
        "extra": {},
    }
    yield link


def get_cot(task_defn, task_id="task_id"):
    return {
        "artifacts": {"path/to/artifact": {"sha256": "abcd1234"}},
        "chainOfTrustVersion": 1,
        "environment": {},
        "task": task_defn,
        "runId": 0,
        "taskId": task_id,
        "workerGroup": "...",
        "workerId": "...",
    }


async def cot_load_url(context, url, path, parent_path=None, **kwargs):
    if path.endswith("taskcluster.yml"):
        return load_json_or_yaml(os.path.join(parent_path, ".taskcluster.yml"), is_path=True, file_type="yaml")
    elif path.endswith("projects.yml"):
        return load_json_or_yaml(os.path.join(parent_path, "projects.yml"), is_path=True, file_type="yaml")


cotv2_load_url = partial(cot_load_url, parent_path=COTV2_DIR)
cotv4_load_url = partial(cot_load_url, parent_path=COTV4_DIR)


def cot_load(string, is_path=False, parent_dir=None, **kwargs):
    if is_path:
        if string.endswith("parameters.yml"):
            return load_json_or_yaml(os.path.join(parent_dir, "parameters.yml"), is_path=True, file_type="yaml")
        elif string.endswith("actions.json"):
            return load_json_or_yaml(os.path.join(parent_dir, "actions.json"), is_path=True)
    else:
        return load_json_or_yaml(string)


cotv2_load = partial(cot_load, parent_dir=COTV2_DIR)
cotv4_load = partial(cot_load, parent_dir=COTV4_DIR)


async def cot_pushlog(_, parent_dir=None):
    return load_json_or_yaml(os.path.join(parent_dir, "pushlog.json"), is_path=True)


cotv2_pushlog = partial(cot_pushlog, parent_dir=COTV2_DIR)
cotv4_pushlog = partial(cot_pushlog, parent_dir=COTV4_DIR)


# dependent_task_ids {{{1
def test_dependent_task_ids(chain):
    ids = ["one", "TWO", "thr33", "vier"]
    for i in ids:
        link = cotverify.LinkOfTrust(chain.context, "build", i)
        chain.links.append(link)
    assert sorted(chain.dependent_task_ids()) == sorted(ids)


# get_all_links_in_chain {{{1
@pytest.mark.asyncio
async def test_get_all_links_in_chain(chain, decision_link, build_link):
    # standard test
    chain.links = [build_link, decision_link]
    assert set(chain.get_all_links_in_chain()) == set([chain, decision_link, build_link])

    # decision task test
    chain.task_type = "decision"
    chain.task_id = decision_link.task_id
    chain.links = [build_link, decision_link]
    assert set(chain.get_all_links_in_chain()) == set([decision_link, build_link])


# is_try {{{1
@pytest.mark.asyncio
@pytest.mark.parametrize("bools,expected", (([False, False], False), ([False, True], True)))
async def test_chain_is_try_or_pull_request(chain, bools, expected):
    for b in bools:
        m = MagicMock()
        m.is_try_or_pull_request = create_async(b)
        chain.links.append(m)
    assert await chain.is_try_or_pull_request() == expected


# get_link {{{1
@pytest.mark.parametrize("ids,req,raises", ((("one", "two", "three"), "one", False), (("one", "one", "two"), "one", True), (("one", "two"), "three", True)))
def test_get_link(chain, ids, req, raises):
    for i in ids:
        link = cotverify.LinkOfTrust(chain.context, "build", i)
        chain.links.append(link)
    if raises:
        with pytest.raises(CoTError):
            chain.get_link(req)
    else:
        chain.get_link(req)


# link.task {{{1
@pytest.mark.asyncio
async def test_link_task(chain):
    link = cotverify.LinkOfTrust(chain.context, "build", "one")
    link.task = chain.task
    assert not await link.is_try_or_pull_request()
    assert link.worker_impl == "scriptworker"
    with pytest.raises(CoTError):
        link.task = {}


# link.cot {{{1
def test_link_cot(chain):
    link = cotverify.LinkOfTrust(chain.context, "build", "task_id")
    cot = get_cot(chain.task, task_id=link.task_id)
    link.cot = cot
    assert link.cot == cot
    with pytest.raises(CoTError):
        link.cot = {}
    # mismatched taskId should raise
    link2 = cotverify.LinkOfTrust(chain.context, "build", "different_task_id")
    with pytest.raises(CoTError):
        link2.cot = cot


# raise_on_errors {{{1
@pytest.mark.parametrize("errors,raises", (([], False), (["foo"], True)))
def test_raise_on_errors(errors, raises):
    if raises:
        with pytest.raises(CoTError):
            cotverify.raise_on_errors(errors)
    else:
        cotverify.raise_on_errors(errors)


# guess_worker_impl {{{1
@pytest.mark.parametrize(
    "task,expected,raises",
    (
        ({"payload": {}, "provisionerId": "", "workerType": "", "scopes": []}, None, True),
        ({"payload": {"image": "x"}, "provisionerId": "", "workerType": "", "scopes": ["docker-worker:"]}, "docker-worker", False),
        ({"payload": {}, "provisionerId": "test-dummy-provisioner", "workerType": "test-dummy-myname", "scopes": ["x"]}, "scriptworker", False),
        ({"payload": {}, "provisionerId": "scriptworker-prov-v1", "workerType": "signing-linux-v1", "scopes": ["x"]}, "scriptworker", False),
        ({"payload": {"mounts": [], "osGroups": []}, "provisionerId": "", "workerType": "", "scopes": []}, "generic-worker", False),
        ({"payload": {"image": "x"}, "provisionerId": "test-dummy-provisioner", "workerType": "", "scopes": []}, None, True),
        ({"payload": {"image": "x", "osGroups": []}, "provisionerId": "", "workerType": "", "scopes": []}, None, True),
        ({"payload": {}, "provisionerId": "", "workerType": "", "scopes": [], "tags": {"worker-implementation": "generic-worker"}}, "generic-worker", False),
        (
            {
                "payload": {"image": "x"},
                "provisionerId": "",
                "workerType": "",
                "scopes": ["docker-worker:"],
                "tags": {"worker-implementation": "generic-worker"},
            },
            None,
            True,
        ),
    ),
)
def test_guess_worker_impl(chain, task, expected, raises):
    link = MagicMock()
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
    assert isinstance(result, immutabledict)
    for key, value in result.items():
        assert key in VALID_WORKER_IMPLS
        assert callable(value)


# guess_task_type {{{1
def test_guess_task_type():
    for name in cotverify.get_valid_task_types().keys():
        with pytest.raises(CoTError):
            cotverify.guess_task_type("foo:bar:baz:{}0".format(name), {})
        assert name == cotverify.guess_task_type("foo:bar:baz:{}".format(name), {})
    # Special cased `parent` name
    assert cotverify.guess_task_type("foo:bar:baz:parent", {"payload": {}}) == "decision"
    assert cotverify.guess_task_type("foo:bar:baz:parent", {"payload": {}, "extra": {"action": {}}}) == "action"


# check_interactive_docker_worker {{{1
@pytest.mark.parametrize(
    "task,raises",
    (
        ({"payload": {"features": {}, "env": {}}}, False),
        ({"payload": {"features": {"interactive": True}, "env": {}}}, True),
        ({"payload": {"features": {}, "env": {"TASKCLUSTER_INTERACTIVE": "x"}}}, True),
        ({}, True),
    ),
)
def test_check_interactive_docker_worker(task, raises):
    link = MagicMock()
    link.name = "foo"
    link.task = task
    if raises:
        with pytest.raises(CoTError):
            cotverify.check_interactive_docker_worker(link)
    else:
        cotverify.check_interactive_docker_worker(link)


# check_interactive_generic_worker {{{1
@pytest.mark.parametrize(
    "task,raises",
    (
        ({"payload": {}, "scopes": []}, False),
        ({"payload": {"rdpInfo": {"foo": "bar"}}, "scopes": []}, True),
        ({"payload": {}, "scopes": ["foo", "generic-worker:allow-rdp:foo:bar"]}, True),
        ({}, True),
    ),
)
def test_check_interactive_generic_worker(task, raises):
    link = MagicMock()
    link.name = "foo"
    link.task = task
    if raises:
        with pytest.raises(CoTError):
            cotverify.check_interactive_generic_worker(link)
    else:
        cotverify.check_interactive_generic_worker(link)


# verify_docker_image_sha {{{1
def test_verify_docker_image_sha(chain, build_link, decision_link, docker_image_link):
    chain.links = [build_link, decision_link, docker_image_link]
    for link in chain.links:
        cotverify.verify_docker_image_sha(chain, link)
    # cover action == decision case
    decision_link.task_type = "action"
    cotverify.verify_docker_image_sha(chain, decision_link)


def test_verify_docker_image_sha_wrong_built_sha(chain, build_link, decision_link, docker_image_link):
    chain.links = [build_link, decision_link, docker_image_link]
    docker_image_link.cot["artifacts"]["path/image"]["sha256"] = "wrong_sha"
    with pytest.raises(CoTError):
        cotverify.verify_docker_image_sha(chain, build_link)


def test_verify_docker_image_sha_missing(chain, build_link, decision_link, docker_image_link):
    chain.links = [build_link, decision_link, docker_image_link]
    # missing built sha
    docker_image_link.cot["artifacts"]["path/image"]["sha256"] = None
    with pytest.raises(CoTError):
        cotverify.verify_docker_image_sha(chain, build_link)


def test_verify_docker_image_sha_wrong_task_id(chain, build_link, decision_link, docker_image_link):
    chain.links = [build_link, decision_link, docker_image_link]
    # wrong task id
    build_link.task["extra"]["chainOfTrust"]["inputs"]["docker-image"] = "wrong_task_id"
    with pytest.raises(CoTError):
        cotverify.verify_docker_image_sha(chain, build_link)


@pytest.mark.parametrize("prebuilt_any,raises", ((False, True), (True, False)))
def test_verify_docker_image_sha_wrong_task_type(chain, build_link, decision_link, prebuilt_any, raises):
    chain.links = [build_link, decision_link]
    # non-dict
    build_link.task["payload"]["image"] = "string"
    if prebuilt_any:
        chain.context.config["prebuilt_docker_image_task_types"] = "any"
    if raises:
        with pytest.raises(CoTError):
            cotverify.verify_docker_image_sha(chain, build_link)
    else:
        cotverify.verify_docker_image_sha(chain, build_link)


def test_verify_docker_image_sha_indexed_image(mobile_chain, decision_link):
    """
    Indexed image are not allowed with restricted scopes.
    """
    chain = mobile_chain
    decision_link.task["payload"]["image"] = {
        "namespace": "trust-domain.v2.taskgraph-try.latest.taskgraph.decision-image",
        "path": "public/image.tar.zst",
        "type": "indexed-image",
    }
    with pytest.raises(CoTError):
        cotverify.verify_docker_image_sha(chain, decision_link)


def test_verify_docker_image_sha_indexed_image_pr(mobile_chain_pull_request, decision_link):
    """
    Indexed image are allowed with no restricted scopes.
    """
    chain = mobile_chain_pull_request
    decision_link.task["payload"]["image"] = {
        "namespace": "trust-domain.v2.taskgraph-try.latest.taskgraph.decision-image",
        "path": "public/image.tar.zst",
        "type": "indexed-image",
    }
    cotverify.verify_docker_image_sha(chain, decision_link)


def test_verify_docker_image_sha_unknown_image_type(mobile_chain, decision_link):
    """
    Unknown image types are not allowed.
    """
    chain = mobile_chain
    decision_link.task["payload"]["image"] = {"type": "spooky-image"}
    with pytest.raises(CoTError):
        cotverify.verify_docker_image_sha(chain, decision_link)


def test_verify_docker_image_sha_unknown_image_type_pr(mobile_chain_pull_request, decision_link):
    """
    Unknown image type are not allowed, even for github PRs.
    """
    chain = mobile_chain_pull_request
    decision_link.task["payload"]["image"] = {"type": "spooky-image"}
    with pytest.raises(CoTError):
        cotverify.verify_docker_image_sha(chain, decision_link)


def test_verify_docker_image_sha_indexed_build(try_chain, decision_link, build_link):
    """
    For hg based projects, non-decision/docker-image type tasks can't use indexed images.
    """
    chain = try_chain
    build_link.task["payload"]["image"] = {
        "namespace": "trust-domain.v2.taskgraph-try.latest.taskgraph.decision-image",
        "path": "public/image.tar.zst",
        "type": "indexed-image",
    }
    with pytest.raises(CoTError):
        cotverify.verify_docker_image_sha(chain, build_link)


# find_sorted_task_dependencies{{{1
@pytest.mark.parametrize(
    "task,expected,task_type",
    (
        (
            # Make sure we don't follow other_task_id on a decision task
            {"taskGroupId": "other_task_id", "extra": {}, "payload": {}},
            [("decision:parent", "other_task_id")],
            "decision",
        ),
        ({"taskGroupId": "decision_task_id", "extra": {}, "payload": {}}, [("build:parent", "decision_task_id")], "build"),
        ({"taskGroupId": "decision_task_id", "extra": {"parent": "action_task_id"}, "payload": {}}, [("build:parent", "action_task_id")], "build"),
        (
            {"taskGroupId": "decision_task_id", "extra": {"chainOfTrust": {"inputs": {"docker-image": "docker_image_task_id"}}}, "payload": {}},
            [("build:parent", "decision_task_id"), ("build:docker-image", "docker_image_task_id")],
            "build",
        ),
        (
            {
                "taskGroupId": "decision_task_id",
                "extra": {"chainOfTrust": {"inputs": {"docker-image": "docker_image_task_id"}}},
                "payload": {"upstreamArtifacts": [{"taskId": "blah_task_id", "taskType": "blah"}, {"taskId": "blah_task_id", "taskType": "blah"}]},
            },
            [
                ("build:parent", "decision_task_id"),
                ("build:blah", "blah_task_id"),
                ("build:blah", "blah_task_id"),  # Duplicates aren't deleted
                ("build:docker-image", "docker_image_task_id"),
            ],
            "build",
        ),
        (
            # PushAPK-like definitions
            {
                "taskGroupId": "decision_task_id",
                "extra": {},
                "payload": {
                    "upstreamArtifacts": [
                        {"taskId": "platform_0_signing_task_id", "taskType": "signing"},
                        {"taskId": "platform_1_signing_task_id", "taskType": "signing"},
                        {"taskId": "platform_2_signing_task_id", "taskType": "signing"},
                    ]
                },
            },
            [
                ("pushapk:parent", "decision_task_id"),
                ("pushapk:signing", "platform_0_signing_task_id"),
                ("pushapk:signing", "platform_1_signing_task_id"),
                ("pushapk:signing", "platform_2_signing_task_id"),
            ],
            "pushapk",
        ),
    ),
)
def test_find_sorted_task_dependencies(task, expected, task_type):
    assert expected == cotverify.find_sorted_task_dependencies(task, task_type, "task_id")


# build_task_dependencies {{{1
@pytest.mark.asyncio
async def test_build_task_dependencies(chain, mocker):
    async def fake_task(task_id):
        if task_id == "die":
            raise CoTError("dying")
        else:
            return {
                "taskGroupId": "decision_task_id",
                "provisionerId": "",
                "schedulerId": "",
                "workerType": "",
                "scopes": [],
                "payload": {"image": "x"},
                "metadata": {},
            }

    async def fake_task_defn(queue, task_id, **kwargs):
        return await fake_task(task_id)

    def fake_find(task, name, _):
        if name.endswith("decision"):
            return []
        return [("build:decision", "decision_task_id"), ("build:a", "already_exists"), ("build:docker-image", "die")]

    already_exists = MagicMock()
    already_exists.task_id = "already_exists"
    chain.links = [already_exists]

    chain.context.queue = MagicMock()
    chain.context.queue.task = fake_task

    mocker.patch.object(cotverify, "find_sorted_task_dependencies", new=fake_find)
    mocker.patch.object(cotverify, "retry_get_task_definition", new=fake_task_defn)
    with pytest.raises(CoTError):
        length = chain.context.config["max_chain_length"]
        await cotverify.build_task_dependencies(
            chain,
            {},
            # range(0, length) gives `max_chain_length` parts, but we're
            # measuring colons which are at `max_chain_length - 1`.
            # To go over, we have to add 2.
            ":".join([str(x) for x in range(0, length + 2)]),
            "task_id",
        )
    with pytest.raises(CoTError):
        await cotverify.build_task_dependencies(chain, {}, "build", "task_id")


# download_cot {{{1
@pytest.mark.parametrize(
    "upstream_artifacts, raises, download_artifacts_mock, verify_sig",
    (
        ([{"taskId": "task_id", "paths": ["path1", "path2"]}], True, die_async, False),
        ([{"taskId": "task_id", "paths": ["path1", "path2"]}, {"taskId": "task_id", "paths": ["failed_path"], "optional": True}], True, die_async, False),
        ([{"taskId": "task_id", "paths": ["path1", "path2"]}], False, None, True),
        ([{"taskId": "task_id", "paths": ["path1", "path2"]}], False, None, False),
        ([], False, None, False),
    ),
)
@pytest.mark.asyncio
async def test_download_cot(chain, mocker, upstream_artifacts, raises, download_artifacts_mock, verify_sig):
    async def down(_, urls, **kwargs):
        return ["x"]

    def fake_artifact_url(_x, _y, path):
        return path

    if download_artifacts_mock is None:
        download_artifacts_mock = down

    def sha(*args, **kwargs):
        return "sha"

    m = MagicMock()
    m.task_id = "task_id"
    m.cot_dir = "y"
    chain.links = [m]
    chain.context.config["verify_cot_signature"] = verify_sig
    mocker.patch.object(cotverify, "get_artifact_url", new=fake_artifact_url)
    if raises:
        mocker.patch.object(cotverify, "download_artifacts", new=download_artifacts_mock)
        with pytest.raises(CoTError):
            await cotverify.download_cot(chain)
    else:
        mocker.patch.object(cotverify, "download_artifacts", new=download_artifacts_mock)
        mocker.patch.object(cotverify, "get_hash", new=sha)
        await cotverify.download_cot(chain)


# download_cot_artifact {{{1
@pytest.mark.parametrize("path,sha,raises", (("one", "sha", False), ("one", "bad_sha", True), ("bad", "bad_sha", True), ("missing", "bad_sha", True)))
@pytest.mark.asyncio
async def test_download_cot_artifact(chain, path, sha, raises, mocker):
    def fake_get_hash(*args, **kwargs):
        return sha

    link = MagicMock()
    link.task_id = "task_id"
    link.name = "name"
    link.cot_dir = "cot_dir"
    link.cot = {"taskId": "task_id", "artifacts": {"one": {"sha256": "sha"}, "bad": {"illegal": "bad_sha"}}}
    chain.links = [link]
    mocker.patch.object(cotverify, "get_artifact_url", new=noop_sync)
    mocker.patch.object(cotverify, "download_artifacts", new=noop_async)
    mocker.patch.object(cotverify, "get_hash", new=fake_get_hash)
    if raises:
        with pytest.raises(CoTError):
            await cotverify.download_cot_artifact(chain, "task_id", path)
    else:
        await cotverify.download_cot_artifact(chain, "task_id", path)


@pytest.mark.asyncio
async def test_download_cot_artifact_no_downloaded_cot(chain, mocker):
    link = MagicMock()
    link.task_id = "task_id"
    link.cot = None
    chain.links = [link]
    await cotverify.download_cot_artifact(chain, "task_id", "path")


# download_cot_artifacts {{{1
@pytest.mark.parametrize(
    "upstreamArtifacts,raises",
    (
        ([{"taskId": "task_id", "paths": ["path1", "path2"]}, {"taskId": "task_id", "paths": ["path3", "failed_path"], "optional": True}], True),
        ([{"taskId": "task_id", "paths": ["path1", "path2"]}, {"taskId": "task_id", "paths": ["path3", "failed_path"], "optional": True}], False),
        ([{"taskId": "task_id", "paths": ["path1", "path2"]}, {"taskId": "task_id", "paths": ["path3"], "optional": True}], False),
    ),
)
@pytest.mark.asyncio
async def test_download_cot_artifacts(chain, raises, mocker, upstreamArtifacts):
    async def fake_download(x, y, path):
        if path == "failed_path":
            raise DownloadError("")
        return path

    chain.task["payload"]["upstreamArtifacts"] = upstreamArtifacts
    if raises:
        mocker.patch.object(cotverify, "download_cot_artifact", new=die_async)
        with pytest.raises(CoTError):
            await cotverify.download_cot_artifacts(chain)
    else:
        mocker.patch.object(cotverify, "download_cot_artifact", new=fake_download)
        result = await cotverify.download_cot_artifacts(chain)
        assert sorted(result) == ["path1", "path2", "path3"]


# download_cot_artifacts {{{1
@pytest.mark.parametrize(
    "upstreamArtifacts,expected,artifact_prefix",
    (
        ([{"taskId": "task_id", "paths": ["*"]}], ["foo", "bar", "baz", "live.log", "test.log"], None),
        ([{"taskId": "task_id", "paths": ["*.log"]}], ["live.log", "test.log"], None),
        ([{"taskId": "task_id", "paths": ["public/*"]}], ["public/foo", "public/bar", "public/baz", "public/live.log", "public/test.log"], "public"),
        ([{"taskId": "task_id", "paths": ["public/*.log"]}], ["public/live.log", "public/test.log"], "public"),
    ),
)
@pytest.mark.asyncio
async def test_download_cot_artifacts_wildcard(chain, mocker, upstreamArtifacts, expected, artifact_prefix):
    async def fake_download(x, y, path):
        return path

    async def fake_artifacts(*args, **kwargs):
        artifacts = []
        for name in ("foo", "bar", "baz", "live.log", "test.log"):
            if artifact_prefix:
                artifact_name = f"{artifact_prefix}/{name}"
            else:
                artifact_name = name

            artifacts.append(
                {
                    "storageType": "s3",
                    "name": artifact_name,
                    "expires": "2025-03-01T16:04:04.463Z",
                    "contentType": "text/plain",
                }
            )

        return {"artifacts": artifacts}

    chain.task["payload"]["upstreamArtifacts"] = upstreamArtifacts
    mocker.patch.object(cotverify, "download_cot_artifact", new=fake_download)
    mocker.patch.object(cotverify, "retry_list_latest_artifacts", new=fake_artifacts)
    result = await cotverify.download_cot_artifacts(chain)
    assert sorted(result) == sorted(expected)


# is_artifact_optional {{{1
@pytest.mark.parametrize(
    "upstream_artifacts, task_id, path, expected",
    (
        ([{"taskId": "id1", "paths": ["id1_path1", "id1_path2"]}], "id1", "id1_path1", False),
        ([{"taskId": "id1", "paths": ["id1_path1", "id1_path2"], "optional": True}], "id1", "id1_path1", True),
        ([{"taskId": "id1", "paths": ["id1_path1"], "optional": True}, {"taskId": "id1", "paths": ["id1_path2"]}], "id1", "id1_path1", True),
        ([{"taskId": "id1", "paths": ["id1_path1"], "optional": True}, {"taskId": "id1", "paths": ["id1_path2"]}], "id1", "id1_path2", False),
    ),
)
def test_is_artifact_optional(chain, upstream_artifacts, task_id, path, expected):
    chain.task["payload"]["upstreamArtifacts"] = upstream_artifacts
    assert cotverify.is_artifact_optional(chain, task_id, path) == expected


@pytest.mark.parametrize(
    "upstream_artifacts,expected",
    (
        (None, {"decision_task_id": ["public/actions.json", "public/parameters.yml", "public/task-graph.json"]}),
        (
            [{"taskId": "id1", "paths": ["id1_path1", "id1_path2"]}, {"taskId": "id2", "paths": ["id2_path1", "id2_path2"]}],
            {
                "decision_task_id": ["public/actions.json", "public/parameters.yml", "public/task-graph.json"],
                "id1": ["id1_path1", "id1_path2"],
                "id2": ["id2_path1", "id2_path2"],
            },
        ),
        (
            # same, but with duplicate paths
            [
                {"taskId": "id1", "paths": ["id1_path1", "id1_path2"]},
                {"taskId": "id2", "paths": ["id2_path1", "id2_path2"]},
                {"taskId": "id1", "paths": ["id1_path1", "id1_path2"]},
            ],
            {
                "decision_task_id": ["public/actions.json", "public/parameters.yml", "public/task-graph.json"],
                "id1": ["id1_path1", "id1_path2"],
                "id2": ["id2_path1", "id2_path2"],
            },
        ),
    ),
)
@pytest.mark.asyncio
async def test_get_all_artifacts_per_task_id(chain, decision_link, build_link, upstream_artifacts, expected, docker_image_link, mocker):
    chain.links = [decision_link, build_link, docker_image_link]
    assert expected == cotverify.get_all_artifacts_per_task_id(chain, upstream_artifacts)


# verify_link_ed25519_cot_signature {{{1
@pytest.mark.parametrize(
    "unsigned_path, signature_path, verifying_key_paths, raises, verify_sigs",
    (
        (
            # Good
            os.path.join(ED25519_DIR, "foo.json"),
            os.path.join(ED25519_DIR, "foo.json.scriptworker.sig"),
            [os.path.join(ED25519_DIR, "scriptworker_public_key")],
            False,
            True,
        ),
        (
            # nonexistent unsigned_path
            os.path.join(ED25519_DIR, "NONEXISTENT_PATH"),
            os.path.join(ED25519_DIR, "foo.json.scriptworker.sig"),
            [os.path.join(ED25519_DIR, "scriptworker_public_key")],
            True,
            True,
        ),
        (
            # Bad verifying key
            os.path.join(ED25519_DIR, "foo.json"),
            os.path.join(ED25519_DIR, "foo.json.scriptworker.sig"),
            [os.path.join(ED25519_DIR, "docker-worker_public_key")],
            True,
            True,
        ),
        (
            # Bad+good verifying key
            os.path.join(ED25519_DIR, "foo.json"),
            os.path.join(ED25519_DIR, "foo.json.scriptworker.sig"),
            [os.path.join(ED25519_DIR, "docker-worker_public_key"), os.path.join(ED25519_DIR, "scriptworker_public_key")],
            False,
            True,
        ),
        (
            # Bad verifying key, but don't check sigs
            os.path.join(ED25519_DIR, "foo.json"),
            os.path.join(ED25519_DIR, "foo.json.scriptworker.sig"),
            [os.path.join(ED25519_DIR, "docker-worker_public_key")],
            False,
            False,
        ),
    ),
)
def test_verify_link_ed25519_cot_signature(chain, build_link, mocker, unsigned_path, signature_path, verifying_key_paths, raises, verify_sigs):
    chain.context.config["verify_cot_signature"] = verify_sigs
    chain.context.config["ed25519_public_keys"][build_link.worker_impl] = [read_from_file(path) for path in verifying_key_paths]
    build_link._cot = None
    build_link.task_id = None
    if raises:
        with pytest.raises(CoTError):
            cotverify.verify_link_ed25519_cot_signature(chain, build_link, unsigned_path, signature_path)
    else:
        contents = load_json_or_yaml(unsigned_path, is_path=True)
        cotverify.verify_link_ed25519_cot_signature(chain, build_link, unsigned_path, signature_path)
        assert build_link.cot == contents


# verify_cot_signatures {{{1
@pytest.mark.parametrize("ed25519_mock, raises", ((noop_sync, False), (die_sync, True)))
def test_verify_link_cot_signature_bad_sig(chain, mocker, build_link, ed25519_mock, raises):
    mocker.patch.object(cotverify, "verify_link_ed25519_cot_signature", new=ed25519_mock)
    chain.links = [build_link]
    if raises:
        with pytest.raises(CoTError):
            cotverify.verify_cot_signatures(chain)
    else:
        cotverify.verify_cot_signatures(chain)


# verify_link_in_task_graph {{{1
def test_verify_link_in_task_graph(chain, decision_link, build_link):
    chain.links = [decision_link, build_link]
    decision_link.task_graph = {build_link.task_id: {"task": deepcopy(build_link.task)}, chain.task_id: {"task": deepcopy(chain.task)}}
    build_link.task["created"] = "1970-01-01T01:00:00.000Z"
    chain.task["created"] = "1970-01-01T01:00:00.000Z"
    cotverify.verify_link_in_task_graph(chain, decision_link, build_link)
    build_link.task["dependencies"].append("decision_task_id")
    cotverify.verify_link_in_task_graph(chain, decision_link, build_link)


@pytest.mark.parametrize("in_chain", (True, False))
def test_verify_link_in_task_graph_exception(chain, decision_link, build_link, in_chain):
    chain.links = [decision_link, build_link]
    bad_task = deepcopy(build_link.task)
    build_link.task["created"] = "1970-01-01T01:00:00.000Z"
    build_link.task["dependencies"].append("foo")
    bad_task["x"] = "y"
    build_link.task["x"] = "z"
    decision_link.task_graph = {chain.task_id: {"task": deepcopy(chain.task)}}
    chain.task["created"] = "1970-01-01T01:00:00.000Z"
    if in_chain:
        decision_link.task_graph[build_link.task_id] = {"task": bad_task}
    with pytest.raises(CoTError):
        cotverify.verify_link_in_task_graph(chain, decision_link, build_link)


# get_pushlog_info {{{1
@pytest.mark.parametrize("pushes", (["push"], ["push1", "push2"]))
@pytest.mark.asyncio
async def test_get_pushlog_info(decision_link, pushes, mocker):
    async def fake_load(*args, **kwargs):
        return {"pushes": pushes}

    mocker.patch.object(cotverify, "load_json_or_yaml_from_url", new=fake_load)
    assert await cotverify.get_pushlog_info(decision_link) == {"pushes": pushes}


@pytest.mark.parametrize(
    "tasks_for, expected, raises",
    (
        (
            "hg-push",
            {
                "now": "2018-01-01T12:00:00.000Z",
                "ownTaskId": "decision_task_id",
                "push": {"base_revision": "baserev", "comment": " ", "owner": "some-user", "pushdate": 1500000000, "pushlog_id": 1, "revision": None},
                "repository": {"level": "1", "project": "mozilla-central", "url": None},
                "taskId": None,
                "tasks_for": "hg-push",
            },
            False,
        ),
        (
            "cron",
            {
                "cron": {},
                "now": "2018-01-01T12:00:00.000Z",
                "ownTaskId": "decision_task_id",
                "push": {"base_revision": "baserev", "comment": "", "owner": "cron", "pushdate": 1500000000, "pushlog_id": 1, "revision": None},
                "repository": {"level": "1", "project": "mozilla-central", "url": None},
                "taskId": None,
                "tasks_for": "cron",
            },
            False,
        ),
        (
            "action",
            {
                "now": "2018-01-01T12:00:00.000Z",
                "ownTaskId": "action_task_id",
                "parameters": {},
                "repository": {"level": "1", "project": "mozilla-central", "url": None},
                "task": None,
                "taskId": None,
                "tasks_for": "action",
            },
            False,
        ),
        ("unknown", False, True),
    ),
)
@pytest.mark.asyncio
async def test_populate_jsone_context_gecko_trees(mocker, chain, decision_link, action_link, cron_link, tasks_for, expected, raises):
    async def get_scm_level(*args, **kwargs):
        return "1"

    async def get_pushlog_info(*args, **kwargs):
        return {"pushes": {1: {"user": "some-user", "date": 1500000000, "changesets": [{"desc": " ", "parents": ["baserev"]}]}}}

    mocker.patch.object(cotverify, "get_scm_level", get_scm_level)
    mocker.patch.object(cotverify, "get_pushlog_info", get_pushlog_info)
    mocker.patch.object(cotverify, "load_json_or_yaml", return_value={})

    if tasks_for == "action":
        link = action_link
    elif tasks_for == "cron":
        link = cron_link
    else:
        link = decision_link

    if raises:
        with pytest.raises(CoTError, match="Unknown tasks_for"):
            await cotverify.populate_jsone_context(chain, link, link, tasks_for=tasks_for)
    else:
        context = await cotverify.populate_jsone_context(chain, link, link, tasks_for=tasks_for)
        del context["as_slugid"]
        assert context == expected


@pytest.mark.asyncio
async def test_populate_jsone_context_github_release(mocker, mobile_chain, mobile_github_release_link):
    github_repo_mock = MagicMock()

    async def get_release_mock(release_name, *args, **kwargs):
        assert release_name == "v9000.0.1"
        return {"author": {"login": "some-user"}, "published_at": "2019-02-01T12:00:00Z", "target_commitish": "releases/v9000"}

    github_repo_mock.get_release = get_release_mock
    github_repo_class_mock = mocker.patch.object(cotverify, "GitHubRepository", return_value=github_repo_mock)

    context = await cotverify.populate_jsone_context(mobile_chain, mobile_github_release_link, mobile_github_release_link, tasks_for="github-release")

    github_repo_class_mock.assert_called_once_with("mozilla-mobile", "reference-browser", "fakegithubtoken")
    del context["as_slugid"]
    assert context == {
        "event": {
            "action": "published",
            "repository": {
                "clone_url": "https://github.com/mozilla-mobile/reference-browser.git",
                "full_name": "mozilla-mobile/reference-browser",
                "html_url": "https://github.com/mozilla-mobile/reference-browser",
                "name": "reference-browser",
            },
            "release": {"tag_name": "v9000.0.1", "target_commitish": "releases/v9000", "published_at": "2019-02-01T12:00:00Z"},
            "sender": {"login": "some-user"},
        },
        "now": "2018-01-01T12:00:00.000Z",
        "ownTaskId": "decision_task_id",
        "taskId": None,
        "tasks_for": "github-release",
    }


@pytest.mark.parametrize("has_triggered_by", (True, False))
@pytest.mark.asyncio
async def test_populate_jsone_context_git_cron(mobile_chain, mobile_cron_link, has_triggered_by):
    if has_triggered_by:
        mobile_cron_link.task["payload"]["env"]["MOBILE_TRIGGERED_BY"] = "TaskclusterHook"

    context = await cotverify.populate_jsone_context(mobile_chain, mobile_cron_link, mobile_cron_link, tasks_for="cron")
    del context["as_slugid"]
    assert context == {
        "cron": {"task_id": "cron-task-id"},
        "event": {
            "repository": {
                "clone_url": "https://github.com/mozilla-mobile/reference-browser",
                "full_name": "mozilla-mobile/reference-browser",
                "html_url": "https://github.com/mozilla-mobile/reference-browser",
                "name": "reference-browser",
            },
            "release": {"published_at": "2019-02-01T12:00:00.000Z", "tag_name": "somerevision", "target_commitish": "master"},
            "sender": {"login": "TaskclusterHook"},
        },
        "now": "2018-01-01T12:00:00.000Z",
        "ownTaskId": "decision_task_id",
        "taskId": None,
        "tasks_for": "cron",
        "repository": {"url": "https://github.com/mozilla-mobile/reference-browser", "project": "reference-browser", "level": "3"},
        "push": {"branch": "master", "revision": "somerevision"},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "committer_login, committer_email, author_login, author_email",
    (
        ("some-user", "some-user@email.tld", "some-user", "some-user@email.tld"),
        ("some-user", "some-user@email.tld", "some-other-user", "other@email.tld"),
        ("web-flow", "noreply@github.com", "some-user", "some-user@email.tld"),
    ),
)
async def test_populate_jsone_context_github_push(mocker, mobile_chain, mobile_github_push_link, committer_login, committer_email, author_login, author_email):
    github_repo_mock = MagicMock()

    async def get_commit_mock(commit_hash, *args, **kwargs):
        assert commit_hash == "somerevision"
        return {
            "commit": {"author": {"email": author_email}, "committer": {"email": committer_email}},
            "committer": {"login": committer_login},
            "author": {"login": author_login},
        }

    github_repo_mock.get_commit = get_commit_mock
    github_repo_class_mock = mocker.patch.object(cotverify, "GitHubRepository", return_value=github_repo_mock)

    context = await cotverify.populate_jsone_context(mobile_chain, mobile_github_push_link, mobile_github_push_link, tasks_for="github-push")

    github_repo_class_mock.assert_called_once_with("mozilla-mobile", "reference-browser", "fakegithubtoken")
    del context["as_slugid"]
    assert context == {
        "event": {
            "before": "somebaserevision",
            "after": "somerevision",
            "pusher": {"email": "foo@example.tld"},
            "base_ref": None,
            "ref": "refs/heads/some-branch",
            "repository": {
                "full_name": "mozilla-mobile/reference-browser",
                "html_url": "https://github.com/mozilla-mobile/reference-browser",
                "name": "reference-browser",
                "pushed_at": "1549022400",
                "ssh_url": "git@github.com:mozilla-mobile/reference-browser.git",
            },
            "sender": {"login": "some-user"},
        },
        "now": "2018-01-01T12:00:00.000Z",
        "ownTaskId": "decision_task_id",
        "taskId": None,
        "tasks_for": "github-push",
    }


@pytest.mark.asyncio
async def test_get_additional_git_action_jsone_context(github_action_link):
    jsone_context = await cotverify._get_additional_git_action_jsone_context(None, github_action_link)
    assert jsone_context == {
        "taskGroupId": "decision_task_id",
        "taskId": None,
        "input": {
            "build_number": 1,
            "do_not_optimize": [],
            "previous_graph_ids": [],
            "rebuild_kinds": [],
            "release_promotion_flavor": "build",
            "version": "",
            "xpi_name": "multipreffer",
        },
    }


@pytest.mark.parametrize(
    "extra_env,extra_repo_definition,expected_use_parent,latest_head_sha,tasks_for",
    (
        pytest.param({}, {"fork": True}, True, "somerevision", "github-pull-request", id="fork with different base repo"),
        pytest.param({}, {"fork": False}, False, "somerevision", "github-pull-request", id="no fork with different base repo"),
        pytest.param(
            {"MOBILE_BASE_REPOSITORY": "https://github.com/JohanLorenzo/reference-browser"},
            {"fork": True},
            False,
            "somerevision",
            "github-pull-request",
            id="fork with same base repo",
        ),
        pytest.param({}, {}, True, "someotherrevision", "github-pull-request", id="upstream task from different revision"),
        pytest.param({}, {"fork": True}, True, "somerevision", "github-pull-request-untrusted", id="fork with different base repo and untrusted PR"),
        pytest.param({}, {"fork": False}, False, "somerevision", "github-pull-request-untrusted", id="no fork with different base repo and untrusted PR"),
        pytest.param(
            {"MOBILE_BASE_REPOSITORY": "https://github.com/JohanLorenzo/reference-browser"},
            {"fork": True},
            False,
            "somerevision",
            "github-pull-request-untrusted",
            id="fork with same base repo and untrusted PR",
        ),
        pytest.param({}, {}, True, "someotherrevision", "github-pull-request-untrusted", id="upstream task from different revision and untrusted PR"),
    ),
)
@pytest.mark.asyncio
async def test_populate_jsone_context_github_pull_request(
    mocker, mobile_chain_pull_request, mobile_github_pull_request_link, extra_env, extra_repo_definition, expected_use_parent, latest_head_sha, tasks_for
):
    github_repo_mock = MagicMock()
    repo_definition = {"fork": True, "parent": {"name": "reference-browser", "owner": {"login": "mozilla-mobile"}}}
    repo_definition.update(extra_repo_definition)
    github_repo_mock.definition = repo_definition

    mobile_github_pull_request_link.task["extra"]["tasks_for"] = tasks_for
    mobile_github_pull_request_link.task["payload"]["env"].update(extra_env)

    async def get_pull_request_mock(pull_request_number, *args, **kwargs):
        assert pull_request_number == 1234
        return {
            "base": {
                "repo": {
                    "full_name": "mozilla-mobile/reference-browser",
                    "html_url": "https://github.com/mozilla-mobile/reference-browser",
                    "name": "reference-browser",
                }
            },
            "head": {
                "ref": "some-branch",
                "repo": {"html_url": "https://github.com/JohanLorenzo/reference-browser"},
                "sha": latest_head_sha,
                "user": {"login": "some-user"},
            },
            "html_url": "https://github.com/mozilla-mobile/reference-browser/pulls/1234",
            "number": 1234,
            "title": "Some PR title",
        }

    github_repo_mock.get_pull_request = get_pull_request_mock
    github_repo_class_mock = mocker.patch.object(cotverify, "GitHubRepository", return_value=github_repo_mock)

    context = await cotverify.populate_jsone_context(
        mobile_chain_pull_request, mobile_github_pull_request_link, mobile_github_pull_request_link, tasks_for=tasks_for
    )

    github_repo_class_mock.assert_any_call("JohanLorenzo", "reference-browser", "fakegithubtoken")

    if expected_use_parent:
        github_repo_class_mock.assert_any_call(owner="mozilla-mobile", repo_name="reference-browser", token="fakegithubtoken")
        assert len(github_repo_class_mock.call_args_list) == 2
    else:
        assert len(github_repo_class_mock.call_args_list) == 1

    del context["as_slugid"]
    assert context == {
        "event": {
            "action": "synchronize",
            "repository": {
                "full_name": "mozilla-mobile/reference-browser",
                "html_url": "https://github.com/mozilla-mobile/reference-browser",
                "name": "reference-browser",
            },
            "pull_request": {
                "base": {
                    "repo": {
                        "full_name": "mozilla-mobile/reference-browser",
                        "html_url": "https://github.com/mozilla-mobile/reference-browser",
                        "name": "reference-browser",
                    },
                    "sha": "baserev",
                },
                "head": {
                    "ref": "some-branch",
                    "sha": "somerevision",
                    "repo": {"html_url": "https://github.com/JohanLorenzo/reference-browser"},
                    "user": {"login": "some-user"},
                    "updated_at": "2019-02-01T12:00:00Z",
                },
                "title": "Some PR title",
                "number": 1234,
                "html_url": "https://github.com/mozilla-mobile/reference-browser/pulls/1234",
            },
            "sender": {"login": "some-user"},
        },
        "now": "2018-01-01T12:00:00.000Z",
        "ownTaskId": "decision_task_id",
        "taskId": None,
        "tasks_for": tasks_for,
    }


@pytest.mark.asyncio
async def test_populate_jsone_context_fail(mobile_chain, mobile_github_release_link):
    with pytest.raises(CoTError):
        await cotverify.populate_jsone_context(mobile_chain, mobile_github_release_link, mobile_github_release_link, tasks_for="bad-tasks-for")
    mobile_chain.context.config["cot_product_type"] = "bad-cot-product-type"
    with pytest.raises(CoTError):
        await cotverify.populate_jsone_context(mobile_chain, mobile_github_release_link, mobile_github_release_link, tasks_for="github-push")


@pytest.mark.asyncio
async def test_populate_jsone_context_github_action(mocker, mobile_chain, mobile_github_push_link, github_action_link):
    context = await cotverify.populate_jsone_context(mobile_chain, github_action_link, mobile_github_push_link, tasks_for="action")
    del context["as_slugid"]
    assert context == {
        "now": "2019-10-21T23:36:07.490Z",
        "ownTaskId": "action_task_id",
        "taskId": None,
        "tasks_for": "action",
        "taskGroupId": "decision_task_id",
        "input": {
            "build_number": 1,
            "do_not_optimize": [],
            "previous_graph_ids": [],
            "rebuild_kinds": [],
            "release_promotion_flavor": "build",
            "version": "",
            "xpi_name": "multipreffer",
        },
    }


# get_action_context_and_template {{{1
@pytest.mark.parametrize(
    "defn,expected",
    (
        ({"actionPerm": "generic"}, "generic"),
        ({"actionPerm": "foobar"}, "foobar"),
        ({"hookId": "blah/generic/"}, "generic"),
        ({}, "generic"),
        ({"hookId": "blah/foobar/", "hookPayload": {"decision": {"action": {"cb_name": "action!"}}}}, "action!"),
    ),
)
def test_get_action_perm(defn, expected):
    assert cotverify._get_action_perm(defn) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,task_id,path,decision_task_id,decision_path," "expected_template_path,expected_context_path",
    (
        (
            "action",
            "NdzxKw8bS5Sw5DRhoiM14w",
            os.path.join(COTV4_DIR, "action_retrigger.json"),
            "c5nn2xbNS9mJxeVC0uNElg",
            os.path.join(COTV4_DIR, "decision_try.json"),
            os.path.join(COTV4_DIR, "retrigger_template.json"),
            os.path.join(COTV4_DIR, "retrigger_context.json"),
        ),
    ),
)
async def test_get_action_context_and_template(
    chain, name, task_id, path, decision_task_id, decision_path, expected_template_path, expected_context_path, mocker
):
    chain.context.config["min_cot_version"] = 3
    link = cotverify.LinkOfTrust(chain.context, name, task_id)
    link.task = load_json_or_yaml(path, is_path=True)
    decision_link = cotverify.LinkOfTrust(chain.context, "decision", decision_task_id)
    decision_link.task = load_json_or_yaml(decision_path, is_path=True)

    mocker.patch.object(cotverify, "load_json_or_yaml_from_url", new=cotv4_load_url)
    mocker.patch.object(swcontext, "load_json_or_yaml_from_url", new=cotv4_load_url)
    mocker.patch.object(cotverify, "load_json_or_yaml", new=cotv4_load)
    mocker.patch.object(cotverify, "get_pushlog_info", new=cotv4_pushlog)

    chain.links = list(set([decision_link, link]))

    result = await cotverify.get_action_context_and_template(chain, link, decision_link)
    log.info("result:\n{}".format(result))
    with open(expected_template_path) as fh:
        fake_template = json.load(fh)
    assert result[1] == fake_template
    # can't easily compare a lambda
    if "as_slugid" in result[0]:
        del result[0]["as_slugid"]
    with open(expected_context_path) as fh:
        fake_context = json.load(fh)
    assert result[0] == fake_context


@pytest.mark.asyncio
async def test_broken_action_context_and_template(chain, mocker):
    def fake_get_action_from_actions_json(all_actions, callback_name):
        # We need to avoid raising CoTError in _get_action_from_actions_json,
        # so we can raise CoTError inside get_action_context_and_template.
        # History here:
        #   https://github.com/mozilla-releng/scriptworker/pull/286#discussion_r243445069
        for defn in all_actions:
            if defn.get("hookPayload", {}).get("decision", {}).get("action", {}).get("cb_name") == callback_name:
                hacked_defn = deepcopy(defn)
                hacked_defn["kind"] = "BROKEN BROKEN BROKEN"
                return hacked_defn

    chain.context.config["min_cot_version"] = 3
    link = cotverify.LinkOfTrust(chain.context, "action", "action_taskid")
    link.task = load_json_or_yaml(os.path.join(COTV4_DIR, "action_retrigger.json"), is_path=True)
    decision_link = cotverify.LinkOfTrust(chain.context, "decision", "decision_taskid")
    decision_link.task = load_json_or_yaml(os.path.join(COTV4_DIR, "decision_try.json"), is_path=True)
    mocker.patch.object(cotverify, "load_json_or_yaml_from_url", new=cotv4_load_url)
    mocker.patch.object(swcontext, "load_json_or_yaml_from_url", new=cotv4_load_url)
    mocker.patch.object(cotverify, "get_pushlog_info", new=cotv4_pushlog)
    mocker.patch.object(cotverify, "load_json_or_yaml", new=cotv4_load)
    mocker.patch.object(cotverify, "_get_action_from_actions_json", new=fake_get_action_from_actions_json)
    chain.links = list(set([decision_link, link]))

    with pytest.raises(CoTError, match="Unknown action kind .BROKEN BROKEN BROKEN"):
        await cotverify.get_action_context_and_template(chain, link, decision_link)


# verify_parent_task_definition {{{1
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,task_id,path,decision_task_id,decision_path,parent_path",
    (
        (
            "decision",
            "VQU9QMO4Teq7zr91FhBusg",
            os.path.join(COTV2_DIR, "decision_hg-push.json"),
            "VQU9QMO4Teq7zr91FhBusg",
            os.path.join(COTV2_DIR, "decision_hg-push.json"),
            COTV2_DIR,
        ),
        (
            "action",
            "LpCJV9wUQHSAm5SHyW4Olw",
            os.path.join(COTV4_DIR, "action_relpro.json"),
            "VQU9QMO4Teq7zr91FhBusg",
            os.path.join(COTV2_DIR, "decision_hg-push.json"),
            COTV4_DIR,
        ),
        (
            "decision",
            "D4euZNyCRtuBci-fnsfn7A",
            os.path.join(COTV2_DIR, "cron.json"),
            "D4euZNyCRtuBci-fnsfn7A",
            os.path.join(COTV2_DIR, "cron.json"),
            COTV2_DIR,
        ),
    ),
)
async def test_verify_parent_task_definition(chain, name, task_id, path, decision_task_id, decision_path, parent_path, mocker):
    link = cotverify.LinkOfTrust(chain.context, name, task_id)
    link.task = load_json_or_yaml(path, is_path=True)
    if task_id == decision_task_id:
        decision_link = link
    else:
        decision_link = cotverify.LinkOfTrust(chain.context, "decision", decision_task_id)
        decision_link.task = load_json_or_yaml(decision_path, is_path=True)

    mocker.patch.object(cotverify, "load_json_or_yaml_from_url", new=partial(cot_load_url, parent_path=parent_path))
    mocker.patch.object(swcontext, "load_json_or_yaml_from_url", new=partial(cot_load_url, parent_path=parent_path))
    mocker.patch.object(cotverify, "load_json_or_yaml", new=partial(cot_load, parent_dir=parent_path))
    mocker.patch.object(cotverify, "get_pushlog_info", new=partial(cot_pushlog, parent_dir=parent_path))

    chain.links = list(set([decision_link, link]))
    await cotverify.verify_parent_task_definition(chain, link)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,task_id,path,decision_task_id,decision_path",
    (
        (
            "decision",
            "VUTfOIPFQWaGHf7sIbgTEg",
            os.path.join(COTV4_DIR, "decision_github_private.json"),
            "VUTfOIPFQWaGHf7sIbgTEg",
            os.path.join(COTV4_DIR, "decision_github_private.json"),
        ),
    ),
)
async def test_verify_parent_task_definition_vpn(vpn_chain, name, task_id, path, decision_task_id, decision_path, mocker):
    link = cotverify.LinkOfTrust(vpn_chain.context, name, task_id)
    link.task = load_json_or_yaml(path, is_path=True)
    if task_id == decision_task_id:
        decision_link = link
    else:
        decision_link = cotverify.LinkOfTrust(vpn_chain.context, "decision", decision_task_id)
        decision_link.task = load_json_or_yaml(decision_path, is_path=True)

    class MockedGitHubRepository(object):
        def __init__(self, *args, **kwargs):
            pass

        async def get_commit(self, commit):
            assert commit == "330ea928b42ff2403fc99cd3e596d13294fe8775"
            # Return minimal information necessary for jsone rebuild
            return {
                "author": {"login": "Callek"},
                "commit": {"author": {"email": "Callek@gmail.com"}, "committer": {"email": "Callek@gmail.com"}},
                "committer": {"login": "Callek"},
            }

    async def mocked_load_url(context, url, path, parent_path=COTV4_DIR, **kwargs):
        if path.endswith("taskcluster.yml"):
            assert kwargs.get("auth")
            assert isinstance(kwargs["auth"], aiohttp.BasicAuth)
            assert kwargs["auth"].login == "fakegithubtoken"
            return load_json_or_yaml(os.path.join(parent_path, "private_github_.taskcluster.yml"), is_path=True, file_type="yaml")
        raise NotImplementedError()

    mocker.patch.object(cotverify, "load_json_or_yaml_from_url", new=mocked_load_url)
    mocker.patch.object(swcontext, "load_json_or_yaml_from_url", new=cotv4_load_url)
    mocker.patch.object(cotverify, "load_json_or_yaml", new=cotv4_load)
    mocker.patch.object(cotverify, "get_pushlog_info", new=cotv4_pushlog)
    mocker.patch.object(cotverify, "GitHubRepository", new=MockedGitHubRepository)

    vpn_chain.links = list(set([decision_link, link]))
    await cotverify.verify_parent_task_definition(vpn_chain, link)


def test_build_taskcluster_yml_url_unknown_server(decision_link):
    decision_link.task["payload"]["env"] = {"GECKO_HEAD_REPOSITORY": "https://unknown.server/fake-mozilla-central"}
    with pytest.raises(CoTError):
        cotverify.build_taskcluster_yml_url(decision_link)


@pytest.mark.asyncio
@pytest.mark.parametrize("use_auth", (None, True))
@pytest.mark.parametrize(
    "source_repo,revision,expected_url",
    (
        (
            "ssh://github.com/mozilla-mobile/mozilla-vpn-client",
            "330ea928b42ff2403fc99cd3e596d13294fe8775",
            "https://raw.githubusercontent.com/mozilla-mobile/mozilla-vpn-client/330ea928b42ff2403fc99cd3e596d13294fe8775/.taskcluster.yml",
        ),
        (
            "git@github.com:mozilla-mobile/mozilla-vpn-client",
            "330ea928b42ff2403fc99cd3e596d13294fe8775",
            "https://raw.githubusercontent.com/mozilla-mobile/mozilla-vpn-client/330ea928b42ff2403fc99cd3e596d13294fe8775/.taskcluster.yml",
        ),
        (
            "https://hg.mozilla.org/ci/taskgraph-try",
            "a9afa8aa11cf1431d4e6ef06c2a08d19e271c6ea",
            "https://hg.mozilla.org/ci/taskgraph-try/raw-file/a9afa8aa11cf1431d4e6ef06c2a08d19e271c6ea/.taskcluster.yml",
        ),
    ),
)
async def test_get_in_tree_template_auth_morphing(vpn_chain, mocker, use_auth, source_repo, revision, expected_url):
    name = "decision"
    task_id = "VUTfOIPFQWaGHf7sIbgTEg"
    if not use_auth:
        del vpn_chain.context.config["github_oauth_token"]
    link = cotverify.LinkOfTrust(vpn_chain.context, name, task_id)

    async def mocked_load_url(context, url, path, parent_path=COTV2_DIR, **kwargs):
        assert url == expected_url
        if use_auth and "github.com" in source_repo:
            assert kwargs.get("auth")
            assert isinstance(kwargs["auth"], aiohttp.BasicAuth)
            assert kwargs["auth"].login == "fakegithubtoken"
            return "some_template"
        else:
            assert not kwargs.get("auth")
            return "some_template_no_auth"

    mocker.patch.object(cotverify, "load_json_or_yaml_from_url", new=mocked_load_url)
    mocker.patch.object(cotverify, "get_repo", new=lambda x, y: source_repo)
    mocker.patch.object(cotverify, "get_revision", new=lambda x, y: revision)

    await cotverify.get_in_tree_template(link)


@pytest.mark.asyncio
async def test_no_match_in_actions_json(chain):
    """
    Searching for nonexistent action callback name in actions.json causes a
    chain-of-trust failure.
    """
    task_id = "NdzxKw8bS5Sw5DRhoiM14w"
    decision_task_id = "c5nn2xbNS9mJxeVC0uNElg"

    chain.context.config["min_cot_version"] = 3
    link = cotverify.LinkOfTrust(chain.context, "action", task_id)
    link.task = {
        "taskGroupId": decision_task_id,
        "provisionerId": "test-provisioner",
        "schedulerId": "tutorial-scheduler",
        "workerType": "docker-worker",
        "scopes": [],
        "payload": {"image": "test-image", "env": {"ACTION_CALLBACK": "non-existent"}},
        "metadata": {},
    }

    decision_link = cotverify.LinkOfTrust(chain.context, "decision", decision_task_id)
    write_artifact(
        chain.context,
        decision_task_id,
        "public/actions.json",
        json.dumps(
            {
                "actions": [
                    {"name": "act", "kind": "hook", "hookPayload": {"decision": {"action": {"cb_name": "act-callback"}}}},
                ]
            }
        ),
    )

    chain.links = list(set([decision_link, link]))
    with pytest.raises(CoTError, match="No action with .* callback found."):
        await cotverify.get_action_context_and_template(chain, link, decision_link)


@pytest.mark.asyncio
async def test_unknown_action_kind(chain):
    """
    Unknown action kinds cause chain-of-trust failure.
    """
    task_id = "NdzxKw8bS5Sw5DRhoiM14w"
    decision_task_id = "c5nn2xbNS9mJxeVC0uNElg"

    chain.context.config["min_cot_version"] = 3
    link = cotverify.LinkOfTrust(chain.context, "action", task_id)
    link.task = {
        "taskGroupId": decision_task_id,
        "provisionerId": "test-provisioner",
        "schedulerId": "tutorial-scheduler",
        "workerType": "docker-worker",
        "scopes": [],
        "payload": {"image": "test-image", "env": {"ACTION_CALLBACK": "act-callback"}},
        "metadata": {},
    }

    decision_link = cotverify.LinkOfTrust(chain.context, "decision", decision_task_id)
    write_artifact(
        chain.context,
        decision_task_id,
        "public/actions.json",
        json.dumps(
            {
                "actions": [
                    {"name": "magic", "kind": "task", "hookPayload": {"decision": {"action": {"cb_name": "act-callback"}}}},
                    {"name": "act", "kind": "hook", "hookPayload": {"decision": {"action": {"cb_name": "act-callback"}}}},
                ]
            }
        ),
    )

    chain.links = list(set([decision_link, link]))
    with pytest.raises(CoTError, match="Unknown action kind"):
        await cotverify.get_action_context_and_template(chain, link, decision_link)


@pytest.mark.asyncio
async def test_verify_parent_task_definition_bad_project(chain, mocker):
    link = cotverify.LinkOfTrust(chain.context, "decision", "VQU9QMO4Teq7zr91FhBusg")
    link.task = load_json_or_yaml(os.path.join(COTV2_DIR, "decision_hg-push.json"), is_path=True)

    def fake_url(*args):
        return "https://fake_server"

    mocker.patch.object(cotverify, "load_json_or_yaml_from_url", new=cotv2_load_url)
    mocker.patch.object(swcontext, "load_json_or_yaml_from_url", new=cotv2_load_url)
    mocker.patch.object(cotverify, "load_json_or_yaml", new=cotv2_load)
    mocker.patch.object(cotverify, "get_pushlog_info", new=cotv2_pushlog)
    mocker.patch.object(cotverify, "get_source_url", new=fake_url)

    chain.links = [link]
    with pytest.raises(CoTError):
        await cotverify.verify_parent_task_definition(chain, link)


@pytest.mark.asyncio
async def test_verify_parent_task_definition_bad_comment(chain, mocker):
    link = cotverify.LinkOfTrust(chain.context, "decision", "VQU9QMO4Teq7zr91FhBusg")
    link.task = load_json_or_yaml(os.path.join(COTV2_DIR, "decision_hg-push.json"), is_path=True)
    link.task["payload"]["env"]["GECKO_COMMIT_MSG"] = "invalid comment"

    mocker.patch.object(cotverify, "load_json_or_yaml_from_url", new=cotv2_load_url)
    mocker.patch.object(swcontext, "load_json_or_yaml_from_url", new=cotv2_load_url)
    mocker.patch.object(cotverify, "load_json_or_yaml", new=cotv2_load)
    mocker.patch.object(cotverify, "get_pushlog_info", new=cotv2_pushlog)

    chain.links = [link]
    with pytest.raises(CoTError):
        await cotverify.verify_parent_task_definition(chain, link)


@pytest.mark.asyncio
async def test_verify_parent_task_definition_failed_jsone(chain, mocker):
    link = cotverify.LinkOfTrust(chain.context, "decision", "VQU9QMO4Teq7zr91FhBusg")
    link.task = load_json_or_yaml(os.path.join(COTV2_DIR, "decision_hg-push.json"), is_path=True)

    def die(*args):
        raise jsone.JSONTemplateError("foo")

    mocker.patch.object(cotverify, "load_json_or_yaml_from_url", new=cotv2_load_url)
    mocker.patch.object(swcontext, "load_json_or_yaml_from_url", new=cotv2_load_url)
    mocker.patch.object(cotverify, "load_json_or_yaml", new=cotv2_load)
    mocker.patch.object(cotverify, "get_pushlog_info", new=cotv2_pushlog)
    mocker.patch.object(jsone, "render", new=die)

    chain.links = [link]
    with pytest.raises(CoTError):
        await cotverify.verify_parent_task_definition(chain, link)


@pytest.mark.asyncio
async def test_verify_parent_task_definition_failed_diff(chain, mocker):
    link = cotverify.LinkOfTrust(chain.context, "decision", "VQU9QMO4Teq7zr91FhBusg")
    link.task = load_json_or_yaml(os.path.join(COTV2_DIR, "decision_hg-push.json"), is_path=True)
    link.task["illegal"] = "boom"

    mocker.patch.object(cotverify, "load_json_or_yaml_from_url", new=cotv2_load_url)
    mocker.patch.object(swcontext, "load_json_or_yaml_from_url", new=cotv2_load_url)
    mocker.patch.object(cotverify, "load_json_or_yaml", new=cotv2_load)
    mocker.patch.object(cotverify, "get_pushlog_info", new=cotv2_pushlog)

    chain.links = [link]
    with pytest.raises(CoTError):
        await cotverify.verify_parent_task_definition(chain, link)


@pytest.mark.asyncio
async def test_verify_parent_task_definition_failed_tasks_for(chain, mocker):
    link = cotverify.LinkOfTrust(chain.context, "decision", "VQU9QMO4Teq7zr91FhBusg")
    link.task = load_json_or_yaml(os.path.join(COTV2_DIR, "decision_hg-push.json"), is_path=True)
    link.task["extra"]["tasks_for"] = "illegal"

    mocker.patch.object(cotverify, "load_json_or_yaml_from_url", new=cotv2_load_url)
    mocker.patch.object(swcontext, "load_json_or_yaml_from_url", new=cotv2_load_url)
    mocker.patch.object(cotverify, "load_json_or_yaml", new=cotv2_load)
    mocker.patch.object(cotverify, "get_pushlog_info", new=cotv2_pushlog)

    chain.links = [link]
    with pytest.raises(CoTError):
        await cotverify.verify_parent_task_definition(chain, link)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "push_comment,task_comment,raises",
    (
        ("foo bar baz", " ", False),
        ("try: a b c", "try: a b c", False),
        ("blah blah blah blah try: a b c", "try: a b c", False),
        ("blah blah blah blah\nlbah blha try: [a] b c\nblah blah", "try: [a] b c", False),
        ("asdfsadfsad", "", True),
    ),
)
async def test_get_additional_hg_push_jsone_context(chain, mocker, push_comment, task_comment, raises):
    async def fake_pushlog(*args):
        return {"pushes": {"123": {"user": "myuser", "date": "mydate", "changesets": [{"desc": push_comment, "parents": ["baserev"]}]}}}

    def fake_commit_msg(*args):
        return task_comment

    mocker.patch.object(cotverify, "get_revision", return_value="myrev")
    mocker.patch.object(cotverify, "get_pushlog_info", new=fake_pushlog)
    mocker.patch.object(cotverify, "get_commit_message", new=fake_commit_msg)

    if raises:
        with pytest.raises(CoTError):
            await cotverify._get_additional_hg_push_jsone_context(chain, chain)
    else:
        expected = {
            "push": {"base_revision": "baserev", "revision": "myrev", "comment": task_comment, "owner": "myuser", "pushlog_id": "123", "pushdate": "mydate"}
        }
        assert expected == await cotverify._get_additional_hg_push_jsone_context(chain, chain)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "push_comment", ("foo bar baz", "try: a b c", "blah blah blah blah try: a b c", "blah blah blah blah\nlbah blha try: [a] b c\nblah blah")
)
async def test_get_additional_hg_cron_jsone_context(cron_link, mocker, push_comment):
    chain = cron_link

    async def fake_pushlog(*args):
        return {"pushes": {"123": {"user": "myuser", "date": "mydate", "changesets": [{"desc": push_comment, "parents": ["baserev"]}]}}}

    def fake_commit_msg(*args):
        return push_comment

    mocker.patch.object(cotverify, "get_revision", return_value="myrev")
    mocker.patch.object(cotverify, "get_pushlog_info", new=fake_pushlog)
    mocker.patch.object(cotverify, "get_commit_message", new=fake_commit_msg)

    expected = {
        "cron": {},
        "push": {"base_revision": "baserev", "revision": "myrev", "comment": "", "owner": "cron", "pushlog_id": "123", "pushdate": "mydate"},
    }
    assert expected == await cotverify._get_additional_hg_cron_jsone_context(chain, chain)


# check_and_update_action_task_group_id {{{1
@pytest.mark.parametrize(
    "rebuilt_gid,runtime_gid,action_taskid,decision_taskid,raises",
    (
        ("decision", "decision", "action", "decision", False),
        ("action", "decision", "action", "decision", False),
        ("other", "other", "action", "decision", True),
        ("other", "decision", "action", "decision", True),
    ),
)
def test_check_and_update_action_task_group_id(rebuilt_gid, runtime_gid, action_taskid, decision_taskid, raises):
    rebuilt_definition = {"tasks": [{"payload": {"env": {"ACTION_TASK_GROUP_ID": rebuilt_gid}}}]}
    runtime_definition = {"payload": {"env": {"ACTION_TASK_GROUP_ID": runtime_gid}}}
    parent_link = MagicMock()
    parent_link.task_id = action_taskid
    parent_link.task = runtime_definition
    decision_link = MagicMock()
    decision_link.task_id = decision_taskid
    if raises:
        with pytest.raises(CoTError):
            cotverify.check_and_update_action_task_group_id(parent_link, decision_link, rebuilt_definition)
    else:
        cotverify.check_and_update_action_task_group_id(parent_link, decision_link, rebuilt_definition)
        assert rebuilt_definition["tasks"][0] == runtime_definition


# verify_parent_task {{{1
@pytest.mark.asyncio
@pytest.mark.parametrize("defn_fn,raises", ((noop_async, False), (die_async, True)))
async def test_verify_parent_task(chain, action_link, cron_link, decision_link, build_link, mocker, defn_fn, raises):
    for parent_link in (action_link, cron_link, decision_link):
        build_link.decision_task_id = parent_link.decision_task_id
        build_link.parent_task_id = parent_link.task_id

        build_task = deepcopy(build_link.task)
        chain_task = deepcopy(chain.task)
        build_link.task["created"] = "1970-01-01T01:00:00.000Z"
        chain.task["created"] = "1970-01-01T01:00:00.000Z"

        def task_graph(*args, **kwargs):
            return {build_link.task_id: {"task": deepcopy(build_task)}, chain.task_id: {"task": deepcopy(chain_task)}}

        paths = [os.path.join(parent_link.cot_dir, "public", "task-graph.json"), os.path.join(decision_link.cot_dir, "public", "parameters.yml")]
        for path in paths:
            makedirs(os.path.dirname(path))
            touch(path)
        chain.links = [parent_link, build_link]
        parent_link.task["provisionerId"] = chain.context.config["valid_decision_worker_pools"][0].split("/")[0]
        parent_link.task["workerType"] = chain.context.config["valid_decision_worker_pools"][0].split("/")[1]
        mocker.patch.object(cotverify, "load_json_or_yaml", new=task_graph)
        mocker.patch.object(cotverify, "verify_parent_task_definition", new=defn_fn)
        if raises:
            with pytest.raises(CoTError):
                await cotverify.verify_parent_task(chain, parent_link)
        else:
            await cotverify.verify_parent_task(chain, parent_link)
            # Deal with chain == link scenario
            orig_chain_task = chain.task
            chain.task = parent_link.task
            chain.links = []
            await cotverify.verify_parent_task(chain, chain)
            chain.task = orig_chain_task


@pytest.mark.asyncio
async def test_verify_parent_task_worker_type(chain, decision_link, build_link, mocker):
    def task_graph(*args, **kwargs):
        return {build_link.task_id: {"task": deepcopy(build_link.task)}, chain.task_id: {"task": deepcopy(chain.task)}}

    path = os.path.join(decision_link.cot_dir, "public", "task-graph.json")
    makedirs(os.path.dirname(path))
    touch(path)
    chain.links = [decision_link, build_link]
    decision_link.task["workerType"] = "bad-worker-type"
    mocker.patch.object(cotverify, "load_json_or_yaml", new=task_graph)
    mocker.patch.object(cotverify, "verify_parent_task_definition", new=noop_async)
    with pytest.raises(CoTError):
        await cotverify.verify_parent_task(chain, decision_link)


@pytest.mark.asyncio
async def test_verify_parent_task_missing_graph(chain, decision_link, build_link, mocker):
    chain.links = [decision_link, build_link]
    decision_link.task["provisionerId"] = chain.context.config["valid_decision_worker_pools"][0].split("/")[0]
    decision_link.task["workerType"] = chain.context.config["valid_decision_worker_pools"][0].split("/")[1]
    with pytest.raises(CoTError):
        await cotverify.verify_parent_task(chain, decision_link)


# verify_build_task {{{1
@pytest.mark.asyncio
async def test_verify_build_task(chain, build_link):
    await cotverify.verify_build_task(chain, build_link)


@pytest.mark.asyncio
async def test_verify_build_task_noop(chain, build_link):
    build_link.worker_impl = "unknown"
    await cotverify.verify_build_task(chain, build_link)


# verify_partials_task {{{1
@pytest.mark.asyncio
async def test_verify_partials_task(chain, build_link):
    await cotverify.verify_partials_task(chain, build_link)


@pytest.mark.asyncio
async def test_verify_partials_task_noop(chain, build_link):
    build_link.worker_impl = "unknown"
    await cotverify.verify_partials_task(chain, build_link)


# verify_docker_image_task {{{1
@pytest.mark.asyncio
async def test_verify_docker_image_task(chain, docker_image_link):
    docker_image_link.task["provisionerId"] = chain.context.config["valid_docker_image_worker_pools"][0].split("/")[0]
    docker_image_link.task["workerType"] = chain.context.config["valid_docker_image_worker_pools"][0].split("/")[1]
    await cotverify.verify_docker_image_task(chain, docker_image_link)


@pytest.mark.asyncio
async def test_verify_docker_image_task_worker_type(chain, docker_image_link):
    docker_image_link.task["workerType"] = "bad-worker-type"
    with pytest.raises(CoTError):
        await cotverify.verify_docker_image_task(chain, docker_image_link)


# verify_scriptworker_task {{{1
@pytest.mark.parametrize("func", ["verify_partials_task", "verify_scriptworker_task"])
@pytest.mark.asyncio
async def test_verify_scriptworker_task(chain, build_link, func):
    build_link.worker_impl = "scriptworker"
    await getattr(cotverify, func)(chain, build_link)


@pytest.mark.parametrize("func", ["verify_scriptworker_task"])
@pytest.mark.asyncio
async def test_verify_scriptworker_task_worker_impl(chain, build_link, func):
    build_link.worker_impl = "bad_impl"
    with pytest.raises(CoTError):
        await getattr(cotverify, func)(chain, build_link)


# verify_task_types {{{1
@pytest.mark.asyncio
async def test_verify_task_types(chain, decision_link, build_link, docker_image_link, mocker):
    chain.links = [decision_link, build_link, docker_image_link]
    for func in cotverify.get_valid_task_types().values():
        mocker.patch.object(cotverify, func.__name__, new=noop_async)
    expected = {"decision": 1, "build": 1, "docker-image": 1, "signing": 1}
    assert expected == await cotverify.verify_task_types(chain)


# verify_docker_worker_task {{{1
@pytest.mark.asyncio
async def test_verify_docker_worker_task(mocker):
    chain = MagicMock()
    link = MagicMock()
    check = MagicMock()
    mocker.patch.object(cotverify, "check_interactive_docker_worker", new=check.method1)
    mocker.patch.object(cotverify, "verify_docker_image_sha", new=check.method2)
    await cotverify.verify_docker_worker_task(chain, chain)
    check.method1.assert_called_once_with(chain)
    check.method2.assert_not_called()
    await cotverify.verify_docker_worker_task(chain, link)
    check.method1.assert_called_with(link)
    check.method2.assert_called_once_with(chain, link)


# verify_generic_worker_task {{{1
@pytest.mark.asyncio
async def test_verify_generic_worker_task(mocker):
    chain = MagicMock()
    link = MagicMock()
    check = MagicMock()
    mocker.patch.object(cotverify, "check_interactive_generic_worker", new=check.method1)
    await cotverify.verify_generic_worker_task(chain, chain)
    check.method1.assert_called_once_with(chain)
    await cotverify.verify_generic_worker_task(chain, link)
    check.method1.assert_called_with(link)


# verify_worker_impls {{{1
@pytest.mark.asyncio
async def test_verify_worker_impls(chain, decision_link, build_link, docker_image_link, mocker):
    chain.links = [decision_link, build_link, docker_image_link]
    for func in cotverify.get_valid_worker_impls().values():
        mocker.patch.object(cotverify, func.__name__, new=noop_async)
    await cotverify.verify_worker_impls(chain)


# get_source_url {{{1
@pytest.mark.parametrize(
    "task,expected,source_env_prefix,raises",
    (
        (
            {"payload": {"env": {"GECKO_HEAD_REPOSITORY": "https://example.com/blah"}}, "metadata": {"source": "https://example.com/blah/blah"}},
            "https://example.com/blah/blah",
            "GECKO",
            False,
        ),
        ({"payload": {"env": {"GECKO_HEAD_REPOSITORY": "https://example.com/blah/blah"}}, "metadata": {"source": "https://task/blah"}}, None, "GECKO", True),
        ({"payload": {"env": {}}, "metadata": {"source": "https://example.com/blah"}}, "https://example.com/blah", "GECKO", False),
        (
            {
                "payload": {"env": {"GECKO_HEAD_REPOSITORY": "https://example.com/blah/blah", "COMM_HEAD_REPOSITORY": "https://example.com/blah/comm"}},
                "metadata": {"source": "https://example.com/blah/comm"},
            },
            "https://example.com/blah/comm",
            "COMM",
            False,
        ),
        (
            {"payload": {"env": {"PVT_HEAD_REPOSITORY": "https://github.com/blah/blah.git"}}, "metadata": {"source": "https://github.com/blah/blah"}},
            "https://github.com/blah/blah",
            "PVT",
            False,
        ),
        (
            {"payload": {"env": {"PVT_HEAD_REPOSITORY": "git@github.com:blah/blah.git"}}, "metadata": {"source": "https://github.com/blah/blah"}},
            "https://github.com/blah/blah",
            "PVT",
            False,
        ),
    ),
)
def test_get_source_url(task, expected, source_env_prefix, raises):
    obj = MagicMock()
    obj.task = task
    obj.context.config = {"source_env_prefix": source_env_prefix}
    if raises:
        with pytest.raises(CoTError):
            cotverify.get_source_url(obj)
    else:
        assert expected == cotverify.get_source_url(obj)


# trace_back_to_tree {{{1
@pytest.mark.asyncio
async def test_trace_back_to_tree(chain, decision_link, build_link, docker_image_link):
    chain.links = [decision_link, build_link, docker_image_link]
    await cotverify.trace_back_to_tree(chain)


@pytest.mark.asyncio
async def test_trace_back_to_tree_bad_repo(chain):
    chain.task["metadata"]["source"] = "https://hg.mozilla.org/try"
    with pytest.raises(CoTError):
        await cotverify.trace_back_to_tree(chain)


@pytest.mark.asyncio
async def test_trace_back_to_tree_unknown_repo(chain, decision_link, build_link, docker_image_link):
    docker_image_link.decision_task_id = "other"
    docker_image_link.parent_task_id = "other"
    docker_image_link.task["metadata"]["source"] = "https://hg.mozilla.org/unknown/repo"
    chain.links = [decision_link, build_link, docker_image_link]
    with pytest.raises(CoTError):
        await cotverify.trace_back_to_tree(chain)


@pytest.mark.asyncio
async def test_trace_back_to_tree_docker_unknown_repo(chain, decision_link, build_link, docker_image_link):
    build_link.task["metadata"]["source"] = "https://hg.mozilla.org/unknown/repo"
    chain.links = [decision_link, build_link, docker_image_link]
    with pytest.raises(CoTError):
        await cotverify.trace_back_to_tree(chain)


@pytest.mark.asyncio
async def test_trace_back_to_tree_diff_repo(chain, decision_link, build_link, docker_image_link):
    docker_image_link.decision_task_id = "other"
    docker_image_link.parent_task_id = "other"
    docker_image_link.task["metadata"]["source"] = "https://hg.mozilla.org/releases/mozilla-beta"
    chain.links = [decision_link, build_link, docker_image_link]
    await cotverify.trace_back_to_tree(chain)


@pytest.mark.parametrize(
    "source_url, raises",
    (
        ("https://github.com/mozilla-mobile/reference-browser", False),
        ("https://github.com/JohanLorenzo/reference-browser", True),
        ("https://github.com/mitchhentges/reference-browser", True),
        ("https://github.com/MihaiTabara/reference-browser", True),
    ),
)
@pytest.mark.asyncio
async def test_trace_back_to_tree_mobile_staging_repos_dont_access_restricted_scopes(
    mobile_chain, mobile_github_release_link, mobile_build_link, source_url, raises, mocker
):
    (source_url, raises) = ("https://github.com/mozilla-mobile/reference-browser", False)
    mobile_github_release_link.task["metadata"]["source"] = source_url
    mobile_chain.links = [mobile_github_release_link, mobile_build_link]
    mocker.patch.object(mobile_chain, "is_try_or_pull_request", new=create_async(result=False))
    if raises:
        with pytest.raises(CoTError):
            await cotverify.trace_back_to_tree(mobile_chain)
    else:
        await cotverify.trace_back_to_tree(mobile_chain)


# AuditLogFormatter {{{1
@pytest.mark.parametrize("level,expected", ((logging.INFO, "foo"), (logging.DEBUG, " foo")))
def test_audit_log_formatter(level, expected):
    formatter = cotverify.AuditLogFormatter()
    record = logging.LogRecord("a", level, "", 1, "foo", [], None)
    assert formatter.format(record) == expected


# verify_chain_of_trust {{{1
@pytest.mark.parametrize("exc", (None, KeyError, TypeError, CoTError))
@pytest.mark.parametrize("check_task", (True, False))
@pytest.mark.asyncio
async def test_verify_chain_of_trust(chain, exc, check_task, mocker):
    async def maybe_die(*args):
        if exc is not None:
            raise exc("blah")

    for func in ("build_task_dependencies", "build_link", "download_cot", "download_cot_artifacts", "verify_task_types", "verify_worker_impls"):
        mocker.patch.object(cotverify, func, new=noop_async)
    mocker.patch.object(cotverify, "verify_cot_signatures", new=noop_sync)
    mocker.patch.object(cotverify, "trace_back_to_tree", new=maybe_die)
    if exc:
        with pytest.raises(CoTError):
            await cotverify.verify_chain_of_trust(chain, check_task=check_task)
    else:
        await cotverify.verify_chain_of_trust(chain, check_task=check_task)


# verify_cot_cmdln {{{1
@pytest.mark.parametrize("args", (("x", "--task-type", "signing", "--cleanup"), ("x", "--task-type", "balrog")))
@pytest.mark.parametrize("use_github_token", (False, True))
def test_verify_cot_cmdln(chain, args, tmpdir, mocker, event_loop, use_github_token, monkeypatch):
    if use_github_token:
        monkeypatch.setenv("SCRIPTWORKER_GITHUB_OAUTH_TOKEN", "sometoken")
    context = MagicMock()
    path = os.path.join(tmpdir, "x")
    makedirs(path)

    def get_context():
        return context

    def mkdtemp():
        return path

    def cot(*args, **kwargs):
        m = MagicMock()
        m.links = [MagicMock()]
        m.dependent_task_ids = noop_sync
        if use_github_token:
            assert context.config["github_oauth_token"] == "sometoken"
        return m

    mocker.patch.object(tempfile, "mkdtemp", new=mkdtemp)
    mocker.patch.object(cotverify, "read_worker_creds", new=noop_sync)
    mocker.patch.object(cotverify, "Context", new=get_context)
    mocker.patch.object(cotverify, "ChainOfTrust", new=cot)
    mocker.patch.object(cotverify, "retry_get_task_definition", new=noop_async)
    mocker.patch.object(cotverify, "verify_chain_of_trust", new=noop_async)

    cotverify.verify_cot_cmdln(args=args, event_loop=event_loop)


# create_test_workdir {{{1
@pytest.mark.asyncio
async def test_async_create_test_workdir(mocker, tmpdir):
    """``_async_create_test_workdir`` populates ``path`` with ``task.json`` and
    cot artifacts.

    """
    task_defn = {"payload": {"upstreamArtifacts": [{"taskId": "taskId1", "paths": ["public/build/one", "public/build/two"]}]}}

    async def fake_task(task_id):
        return task_defn

    queue = mocker.MagicMock()
    queue.task = fake_task
    mocker.patch.object(cotverify, "download_artifacts", new=noop_async)

    await cotverify._async_create_test_workdir("taskId", tmpdir, queue=queue)
    contents = load_json_or_yaml(os.path.join(tmpdir, "task.json"), is_path=True)
    assert contents == task_defn


@pytest.mark.parametrize("exists, overwrite, raises", ((True, True, False), (False, False, False), (False, True, False), (True, False, True)))
def test_create_test_workdir(mocker, event_loop, tmpdir, exists, overwrite, raises):
    """``create_test_workdir`` fails if ``path`` exists and ``--overwrite`` isn't
    passed. Otherwise we call ``_async_create_test_workdir`` with the appropriate
    args.

    """
    work_dir = os.path.join(tmpdir, "work")
    args = ["--path", work_dir, "taskId"]
    if overwrite:
        args.append("--overwrite")

    async def fake_create(*args):
        assert args == ("taskId", work_dir)

    mocker.patch.object(cotverify, "_async_create_test_workdir", new=fake_create)
    if exists:
        makedirs(work_dir)
    if raises:
        with pytest.raises(SystemExit):
            cotverify.create_test_workdir(args=args, event_loop=event_loop)
    else:
        cotverify.create_test_workdir(args=args, event_loop=event_loop)


@pytest.mark.parametrize(
    "project,level,raises", (("mozilla-central", "3", False), ("no-such-project", None, True), ("fenix", "3", False), ("vpn", "3", False), ("redo", None, True))
)
@pytest.mark.asyncio
async def test_get_scm_level(rw_context, project, level, raises):
    rw_context.projects = {
        "mozilla-central": {"access": "scm_level_3", "repo_type": "hg"},
        "fenix": {"branches": [{"name": "main", "level": 3}], "repo_type": "git"},
        "vpn": {"branches": [{"name": "master", "level": 3}], "default_branch": "master", "repo_type": "git"},
        "redo": {},
    }
    rw_context._projects_timestamp = time.time()

    if raises:
        with pytest.raises(Exception):
            await cotverify.get_scm_level(rw_context, project)
    else:
        assert await cotverify.get_scm_level(rw_context, project) == level


# tests for matching scopes with a partial match, implemented for xpi
@pytest.mark.parametrize(
    "scope, restricted_scopes, expected",
    (
        (
            "project:xpi:signing:cert:release-signing",
            ["project:xpi:ship-it:production", "project:xpi:signing:cert:release-signing"],
            "project:xpi:signing:cert:release-signing",
        ),
        ("project:xpi:signing:cert:release", ["project:xpi:ship-it:production", "project:xpi:signing:cert:release-signing"], ""),
        ("project:xpi:ship-it:production", ["project:xpi:ship-it:production"], "project:xpi:ship-it:production"),
        (
            "project:xpi:releng:github:project:mozilla-extensions/xpi-manifest",
            ["project:xpi:releng:github:project:mozilla-extensions/*"],
            "project:xpi:releng:github:project:mozilla-extensions/*",
        ),
        ("project:xpi:releng:github:project:mozilla-releng/xpi-manifest", ["project:xpi:releng:github:project:mozilla-extensions/*"], ""),
        ("project:xpi:ship-it:production", ["project:xpi:ship-it:*"], "project:xpi:ship-it:*"),
        ("project:xpi:ship-it:production", ["project:xpi:ship-it"], ""),
        ("project:xpi:ship-it:production", ["project:xpi:ship-it:staging"], ""),
        ("project:xpi:ship-it:*", ["project:xpi:ship-it:*"], "project:xpi:ship-it:*"),
        ("project:xpi:ship-it", ["*project:xpi:ship-it"], ""),
        ("project:xpi:ship-it:production", ["project:xpi:ship-it:production*", "project:xpi:ship-it:production"], "COTError"),
    ),
)
def test_scope_in_restricted_scopes(chain, scope, restricted_scopes, expected):
    if expected == "COTError":
        with pytest.raises(CoTError):
            chain.is_scope_in_restricted_scopes(scope, restricted_scopes)
    else:
        assert chain.is_scope_in_restricted_scopes(scope, restricted_scopes) is expected
