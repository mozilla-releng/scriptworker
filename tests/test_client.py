#!/usr/bin/env python
# coding=utf-8
"""Test scriptworker.client
"""
import arrow
import asyncio
import glob
import mock
import os
import pytest
from scriptworker.exceptions import ScriptWorkerTaskException
import scriptworker.client as client


@pytest.fixture(scope='function')
def config(tmpdir_factory):
    temp_dir = tmpdir_factory.mktemp("work_dir", numbered=True)
    work_dir = os.path.join(str(temp_dir), "work")
    os.makedirs(work_dir)
    return {
        'work_dir': work_dir,
        'log_dir': os.path.join(str(temp_dir), "log"),
        'artifact_dir': os.path.join(str(temp_dir), "artifact"),
        'provisioner_id': 'provisioner_id',
        'scheduler_id': 'scheduler_id',
        'worker_type': 'worker_type',
    }


class TestClient(object):
    def test_get_missing_task(self, config):
        with pytest.raises(ScriptWorkerTaskException):
            client.get_task(config)
