#!/usr/bin/env python
# coding=utf-8
"""Scriptworker production CoT verification tests."""
import json
import logging
import os
import re
import tempfile
from unittest.mock import patch

import pytest
from asyncio_extras.contextmanager import async_contextmanager
from taskcluster.aio import Index, Queue, Secrets

import scriptworker.log as swlog
import scriptworker.utils as utils
from scriptworker import github
from scriptworker.config import apply_product_config, get_unfrozen_copy, read_worker_creds
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.context import Context
from scriptworker.cot.verify import ChainOfTrust, verify_chain_of_trust

log = logging.getLogger(__name__)

# constants helpers and fixtures {{{1
pytestmark = [pytest.mark.skipif(os.environ.get("NO_TESTS_OVER_WIRE"), reason="NO_TESTS_OVER_WIRE: skipping production CoT verification test")]
_CACHE = {}


@pytest.fixture(scope="session", autouse=True)
async def mock_memoized_func():
    # Memoize_ttl causes an issue with pytest-asyncio, so we copy the behavior to an in-memory cache
    async def fetch(*args, **kwargs):
        key = (args, tuple(kwargs.items()))
        if key not in _CACHE:
            _CACHE[key] = await github._fetch_github_branch_commits_data_helper(*args, **kwargs)
        return _CACHE[key]

    with patch("scriptworker.github._fetch_github_branch_commits_data", fetch):
        yield


def read_integration_creds():
    return read_worker_creds(key="integration_credentials")


async def build_config(override, basedir):
    config = get_unfrozen_copy(DEFAULT_CONFIG)
    config.update(
        {
            "log_dir": os.path.join(basedir, "log"),
            "artifact_dir": os.path.join(basedir, "artifact"),
            "task_log_dir": os.path.join(basedir, "artifact", "public", "logs"),
            "work_dir": os.path.join(basedir, "work"),
            "ed25519_private_key_path": "",
            "github_oauth_token": await _get_github_token(),
        }
    )
    del config["credentials"]
    if isinstance(override, dict):
        config.update(override)
    with open(os.path.join(basedir, "config.json"), "w") as fh:
        json.dump(config, fh, indent=2, sort_keys=True)
    config = apply_product_config(config)
    # Avoid creating a `...` directory
    for k, v in config.items():
        if v == "...":
            raise Exception(f"Let's not keep any '...' config values. {k} is {v}!")
    return config


async def _get_github_token():
    if os.environ.get("SCRIPTWORKER_GITHUB_TOKEN"):
        return os.environ["SCRIPTWORKER_GITHUB_TOKEN"]
    token = read_worker_creds(key="scriptworker_github_token")
    if token:
        return read_worker_creds(key="scriptworker_github_token")
    try:
        root_url = os.environ["TASKCLUSTER_PROXY_URL"]
    except KeyError as e:
        raise KeyError("You must provide `TASKCLUSTER_PROXY_URL` to run these tests") from e

    secrets = Secrets({"rootUrl": root_url})
    secret = await secrets.get("repo:github.com/mozilla-releng/scriptworker:github")
    return secret["secret"]["token"]


@async_contextmanager
async def get_context(config_override=None):
    context = Context()
    with tempfile.TemporaryDirectory() as tmp:
        context.config = await build_config(config_override, basedir=tmp)
        credentials = read_integration_creds()
        swlog.update_logging_config(context)
        utils.cleanup(context)
        async with utils.scriptworker_session() as session:
            context.session = session
            context.credentials = credentials
            yield context


# verify_cot {{{1
VERIFY_COT_BRANCH_CONTEXTS = (
    {
        "name": "mozilla-central nightly desktop",
        "taskcluster_root_url": "https://firefox-ci-tc.services.mozilla.com/",
        "index": "gecko.v2.mozilla-central.shippable.latest.firefox.win64-shippable-repackage-signing",
        "task_type": "signing",
        "cot_product": "firefox",
    },
    {
        "name": "mozilla-central win64 en-US repackage signing",
        "taskcluster_root_url": "https://firefox-ci-tc.services.mozilla.com/",
        "index": "gecko.v2.mozilla-central.shippable.latest.firefox.win64-shippable-repackage-signing",
        "task_type": "signing",
        "cot_product": "firefox",
    },
    {
        "name": "mozilla-beta win64 en-US repackage signing",
        "taskcluster_root_url": "https://firefox-ci-tc.services.mozilla.com/",
        "index": "gecko.v2.mozilla-beta.shippable.latest.firefox.win64-shippable-repackage-signing",
        "task_type": "signing",
        "cot_product": "firefox",
    },
    {
        "name": "mozilla-release win64 en-US repackage signing",
        "taskcluster_root_url": "https://firefox-ci-tc.services.mozilla.com/",
        "index": "gecko.v2.mozilla-release.shippable.latest.firefox.win64-shippable-repackage-signing",
        "task_type": "signing",
        "cot_product": "firefox",
    },
    {
        "name": "focus nightly",
        "taskcluster_root_url": "https://firefox-ci-tc.services.mozilla.com/",
        "index": "gecko.v2.mozilla-central.latest.mobile.focus-nightly",
        "task_type": "signing",
        "cot_product": "firefox",
    },
    {
        "name": "focus beta",
        "taskcluster_root_url": "https://firefox-ci-tc.services.mozilla.com/",
        "index": "gecko.v2.mozilla-beta.latest.mobile.focus-beta",
        "task_type": "signing",
        "cot_product": "firefox",
    },
    {
        "name": "fenix nightly",
        "taskcluster_root_url": "https://firefox-ci-tc.services.mozilla.com/",
        "index": "gecko.v2.mozilla-central.latest.mobile.fenix-nightly",
        "task_type": "signing",
        "cot_product": "firefox",
    },
    {
        "name": "fenix beta",
        "taskcluster_root_url": "https://firefox-ci-tc.services.mozilla.com/",
        "index": "gecko.v2.mozilla-beta.latest.mobile.fenix-beta",
        "task_type": "signing",
        "cot_product": "firefox",
    },
    {
        "name": "reference-browser nightly",
        "taskcluster_root_url": "https://firefox-ci-tc.services.mozilla.com/",
        "index": "mobile.v2.reference-browser.nightly.latest.arm64-v8a",
        "task_type": "signing",
        "cot_product": "mobile",
    },
    {
        "name": "reference-browser master raptor aarch64",
        "taskcluster_root_url": "https://firefox-ci-tc.services.mozilla.com/",
        "index": "mobile.v2.reference-browser.raptor.latest.arm64-v8a",
        "task_type": "signing",
        "cot_product": "mobile",
        "check_task": False,  # These tasks run on level t workers.
    },
    {
        "name": "adhoc-signing-decision",
        "taskcluster_root_url": "https://firefox-ci-tc.services.mozilla.com/",
        "index": "adhoc.v2.adhoc-signing.latest.taskgraph.decision",
        "task_type": "decision",
        "cot_product": "adhoc",
    },
    {
        "name": "app-services",
        "taskcluster_root_url": "https://firefox-ci-tc.services.mozilla.com/",
        "index": "app-services.cache.level-3.docker-images.v2.linux.latest",
        "task_type": "docker-image",
        "cot_product": "app-services",
    },
)


def idfn(obj):
    return obj["name"]


@pytest.mark.parametrize("branch_context", VERIFY_COT_BRANCH_CONTEXTS, ids=idfn)
@pytest.mark.asyncio
async def test_verify_production_cot(branch_context):
    index = Index(options={"rootUrl": branch_context["taskcluster_root_url"]})
    queue = Queue(options={"rootUrl": branch_context["taskcluster_root_url"]})

    async def get_task_id_from_index(index_path):
        res = await index.findTask(index_path)
        return res["taskId"]

    async def get_completed_task_info_from_labels(decision_task_id, label_to_task_type):
        label_to_taskid = await queue.getLatestArtifact(decision_task_id, "public/label-to-taskid.json")
        task_info = {}
        for re_label, task_type in label_to_task_type.items():
            r = re.compile(re_label)
            for label, task_id in label_to_taskid.items():
                if r.match(label):
                    status = await queue.status(task_id)
                    # only run verify_cot against tasks with completed deps.
                    if status["status"]["state"] in ("completed", "running", "pending", "failed"):
                        task_info[task_id] = task_type
                        break
            else:
                log.warning("Not running verify_cot against {} {} because there are no elegible completed tasks".format(decision_task_id, task_type))
        return task_info

    async def verify_cot(name, task_id, task_type, check_task=True):
        log.info("Verifying {} {} {}...".format(name, task_id, task_type))
        context.task = await queue.task(task_id)
        cot = ChainOfTrust(context, task_type, task_id=task_id)
        await verify_chain_of_trust(cot, check_task=check_task)

    async with get_context({"cot_product": branch_context["cot_product"], "verify_cot_signature": True}) as context:
        context.queue = queue
        task_id = await get_task_id_from_index(branch_context["index"])
        assert task_id, "{}: Can't get task_id from index {}!".format(branch_context["name"], branch_context["index"])
        if branch_context.get("task_label_to_task_type"):
            task_info = await get_completed_task_info_from_labels(task_id, branch_context["task_label_to_task_type"])
            assert "check_task" not in branch_context, "{}: Can't disable check_task.".format(
                branch_context["name"],
            )
            for task_id, task_type in task_info.items():
                name = "{} {}".format(branch_context["name"], task_type)
                await verify_cot(name, task_id, task_type)
        else:
            await verify_cot(
                branch_context["name"],
                task_id,
                branch_context["task_type"],
                branch_context.get("check_task", True),
            )
