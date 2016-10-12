#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.cot
"""
import logging
import os
import pytest
from scriptworker.constants import DEFAULT_CONFIG
from scriptworker.context import Context
from scriptworker.exceptions import ScriptWorkerException
import scriptworker.cot as cot
import scriptworker.gpg as sgpg
from . import ARTIFACT_SHAS, tmpdir

assert tmpdir  # silence pyflakes

log = logging.getLogger(__name__)


# constants helpers and fixtures {{{1
ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "data", "artifacts")


@pytest.yield_fixture(scope='function')
def context(tmpdir):
    GPG_HOME = os.path.join(os.path.dirname(__file__), "data", "gpg")
    context_ = Context()
    context_.config = {
        "artifact_dir": ARTIFACT_DIR,
        "work_dir": os.path.join(tmpdir, "work"),
        "log_dir": os.path.join(tmpdir, "log"),

        "chain_of_trust_hash_algorithm": "sha256",
        "cot_schema_path": DEFAULT_CONFIG['cot_schema_path'],
        "gpg_home": GPG_HOME,
        "gpg_encoding": 'utf-8',
        "gpg_options": None,
        "gpg_path": os.environ.get("GPG_PATH", None),
        "gpg_public_keyring": "%(gpg_home)s/pubring.gpg",
        "gpg_secret_keyring": "%(gpg_home)s/secring.gpg",
        "gpg_use_agent": None,
        "sign_chain_of_trust": True,

        "worker_id": "worker_id",
        "worker_type": "worker_type",
    }
    context_.claim_task = {
        "runId": 2,
        "status": {
            "taskId": "taskId",
        },
        "task": {
            'dependencies': [],
            "payload": {},
            "scopes": ["foo"],
            "taskGroupId": "taskGroupId",
            "workerType": "workerType",
        },
        "workerGroup": "worker_group",
        "credentials": {'c': 'd'},
    }
    yield context_


def expected_cot_body(context_, artifacts):
    return {
        'artifacts': artifacts,
        'chainOfTrustVersion': 1,
        'runId': context_.claim_task['runId'],
        'task': context_.task,
        'taskId': context_.claim_task['status']['taskId'],
        'workerGroup': context_.claim_task['workerGroup'],
        'workerId': context_.config['worker_id'],
        'workerType': context_.config['worker_type'],
        'environment': {}
    }


@pytest.fixture(scope='function')
def artifacts():
    artifacts = {}
    for k, v in ARTIFACT_SHAS.items():
        artifacts[k] = {"sha256": v}
    return artifacts


# tests {{{1
def test_get_cot_artifacts(artifacts, context):
    value = cot.get_cot_artifacts(context)
    assert value == artifacts


def test_generate_cot_body(artifacts, context):
    assert cot.generate_cot_body(context) == expected_cot_body(context, artifacts)


def test_generate_cot_body_exception(artifacts, context):
    del context.config['worker_type']
    with pytest.raises(ScriptWorkerException):
        cot.generate_cot_body(context)


def test_generate_cot(artifacts, context):
    path = os.path.join(context.config['work_dir'], "foo")
    signed_body = cot.generate_cot(context, path=path)
    with open(path, "r") as fh:
        assert fh.read() == signed_body
    body = sgpg.get_body(sgpg.GPG(context), signed_body)
    log.info(body)
    assert body.rstrip() == cot.format_json(cot.generate_cot_body(context))


def test_generate_cot_unsigned(artifacts, context):
    context.config['sign_chain_of_trust'] = False
    path = os.path.join(context.config['work_dir'], "foo")
    body = cot.generate_cot(context, path=path)
    assert body == cot.format_json(cot.generate_cot_body(context))


def test_generate_cot_exception(artifacts, context):
    context.config['cot_schema_path'] = os.path.join(context.config['work_dir'], "not_a_file")
    with pytest.raises(ScriptWorkerException):
        cot.generate_cot(context)
