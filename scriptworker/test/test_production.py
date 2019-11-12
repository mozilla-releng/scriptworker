#!/usr/bin/env python
# coding=utf-8
"""Scriptworker production CoT verification tests.
"""
import aiohttp
from asyncio_extras.contextmanager import async_contextmanager
import json
import logging
import os
import pytest
import re

import tempfile
from scriptworker.config import (
    apply_product_config,
    get_unfrozen_copy,
    read_worker_creds,
)
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.context import Context
from scriptworker.cot.verify import ChainOfTrust, verify_chain_of_trust
import scriptworker.log as swlog
import scriptworker.utils as utils
from taskcluster.aio import Index, Queue

log = logging.getLogger(__name__)

# constants helpers and fixtures {{{1
pytestmark = [
    pytest.mark.skipif(os.environ.get("NO_TESTS_OVER_WIRE"), reason="NO_TESTS_OVER_WIRE: skipping production CoT verification test")
]


def read_integration_creds():
    return read_worker_creds(key="integration_credentials")


def build_config(override, basedir):
    config = get_unfrozen_copy(DEFAULT_CONFIG)
    config.update({
        'log_dir': os.path.join(basedir, "log"),
        'base_artifact_dir': os.path.join(basedir, "artifact"),
        'task_log_dir_template': os.path.join(basedir, "artifact", "public", "logs"),
        'base_work_dir': os.path.join(basedir, "work"),
    })
    del(config['credentials'])
    if isinstance(override, dict):
        config.update(override)
    with open(os.path.join(basedir, "config.json"), "w") as fh:
        json.dump(config, fh, indent=2, sort_keys=True)
    config = apply_product_config(config)
    return config


@async_contextmanager
async def get_context(config_override=None):
    context = Context()
    with tempfile.TemporaryDirectory() as tmp:
        context.config = build_config(config_override, basedir=tmp)
        credentials = read_integration_creds()
        swlog.update_logging_config(context)
        utils.cleanup(context)
        async with aiohttp.ClientSession() as session:
            context.session = session
            context.credentials = credentials
            yield context


# verify_cot {{{1
@pytest.mark.parametrize("branch_context", ({
    "name": "mozilla-central nightly desktop",
    "taskcluster_root_url": "https://taskcluster.net",
    "index": "gecko.v2.mozilla-central.latest.firefox.decision-nightly-desktop",
    "task_label_to_task_type": {
        "balrog-.*-nightly/opt": "balrog",
        "beetmover-repackage-.*-nightly/opt": "beetmover",
    },
    "cot_product": "firefox",
}, {
    "name": "mozilla-esr68 nightly android",
    "taskcluster_root_url": "https://taskcluster.net",
    "index": "gecko.v2.mozilla-esr68.latest.firefox.decision-nightly-android",
    "task_label_to_task_type": {
        "push-apk/opt": "pushapk",
    },
    "cot_product": "firefox",
}, {
    "name": "mozilla-central nightly android",
    "taskcluster_root_url": "https://taskcluster.net",
    "index": "gecko.v2.mozilla-central.latest.firefox.decision-nightly-android",
    "task_label_to_task_type": {
        "push-apk/opt": "pushapk",
    },
    "cot_product": "firefox",
}, {
    "name": "mozilla-central win64 en-US repackage signing",
    "taskcluster_root_url": "https://taskcluster.net",
    "index": "gecko.v2.mozilla-central.shippable.latest.firefox.win64-shippable-repackage-signing",
    "task_type": "signing",
    "cot_product": "firefox",
}, {
    "name": "mozilla-beta win64 en-US repackage signing",
    "taskcluster_root_url": "https://taskcluster.net",
    "index": "gecko.v2.mozilla-beta.shippable.latest.firefox.win64-shippable-repackage-signing",
    "task_type": "signing",
    "cot_product": "firefox",
}, {
    "name": "mozilla-release win64 en-US repackage signing",
    "taskcluster_root_url": "https://taskcluster.net",
    "index": "gecko.v2.mozilla-release.shippable.latest.firefox.win64-shippable-repackage-signing",
    "task_type": "signing",
    "cot_product": "firefox",
}, {
    "name": "mozilla-esr68 win64 en-US repackage signing",
    "taskcluster_root_url": "https://taskcluster.net",
    "index": "gecko.v2.mozilla-esr68.shippable.latest.firefox.win64-shippable-repackage-signing",
    "task_type": "signing",
    "cot_product": "firefox",
}, {
    "name": "fenix nightly",
    "taskcluster_root_url": "https://taskcluster.net",
    "index": "project.mobile.fenix.v2.nightly.latest",
    "task_type": "build",
    "cot_product": "mobile",
}, {
    "name": "fenix master raptor aarch64",
    "taskcluster_root_url": "https://taskcluster.net",
    "index": "project.mobile.fenix.v2.branch.master.latest.raptor.aarch64",
    "task_type": "build",
    "cot_product": "mobile",
}, {
    "name": "reference-browser nightly",
    "taskcluster_root_url": "https://taskcluster.net",
    "index": "project.mobile.reference-browser.v2.nightly.latest",
    "task_type": "signing",
    "cot_product": "mobile",
}, {
    "name": "reference-browser master raptor aarch64",
    "taskcluster_root_url": "https://taskcluster.net",
    "index": "project.mobile.reference-browser.v2.branch.master.latest.raptor.aarch64",
    "task_type": "build",
    "cot_product": "mobile",
}))
# We were testing "project.mobile.focus.signed-nightly.nightly.latest" but that repo is
# currently failing due to a force-push.
@pytest.mark.asyncio
async def test_verify_production_cot(branch_context):
    index = Index(options={'rootUrl': branch_context['taskcluster_root_url']})
    queue = Queue(options={'rootUrl': branch_context['taskcluster_root_url']})

    async def get_task_id_from_index(index_path):
        res = await index.findTask(index_path)
        return res['taskId']

    async def get_completed_task_info_from_labels(decision_task_id, label_to_task_type):
        label_to_taskid = await queue.getLatestArtifact(
            decision_task_id, "public/label-to-taskid.json"
        )
        task_info = {}
        for re_label, task_type in label_to_task_type.items():
            r = re.compile(re_label)
            for label, task_id in label_to_taskid.items():
                if r.match(label):
                    status = await queue.status(task_id)
                    # only run verify_cot against tasks with completed deps.
                    if status['status']['state'] in ('completed', 'running', 'pending', 'failed'):
                        task_info[task_id] = task_type
                        break
            else:
                log.warning(
                    "Not running verify_cot against {} {} because there are no elegible completed tasks".format(
                        decision_task_id, task_type
                    )
                )
        return task_info

    async def verify_cot(name, task_id, task_type):
        log.info("Verifying {} {} {}...".format(name, task_id, task_type))
        context.task = await queue.task(task_id)
        cot = ChainOfTrust(context, task_type, task_id=task_id)
        await verify_chain_of_trust(cot)

    async with get_context({'cot_product': branch_context['cot_product']}) as context:
        context.queue = queue
        task_id = await get_task_id_from_index(branch_context['index'])
        assert task_id, "{}: Can't get task_id from index {}!".format(
            branch_context['name'], branch_context['index']
        )
        if branch_context.get('task_label_to_task_type'):
            task_info = await get_completed_task_info_from_labels(
                task_id, branch_context['task_label_to_task_type']
            )
            for task_id, task_type in task_info.items():
                name = "{} {}".format(branch_context['name'], task_type)
                await verify_cot(name, task_id, task_type)
        else:
            await verify_cot(branch_context['name'], task_id, branch_context['task_type'])
