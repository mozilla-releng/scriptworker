import os
import signal

import pytest
from mock import MagicMock, call
from scriptworker.task_process import TaskProcess


@pytest.mark.asyncio
async def test_stop_pid_group_increasing_severity(mocker):
    process = MagicMock(pid=1)
    task_process = TaskProcess(process)

    mock_kill = mocker.patch.object(os, 'kill')
    await task_process.stop()
    assert mock_kill.mock_calls == [call(-1, signal.SIGTERM), call(-1, signal.SIGKILL)]


@pytest.mark.asyncio
async def test_stop_catch_os_error(monkeypatch):
    def mock_kill(_, __):
        raise OSError()

    process = MagicMock()
    task_process = TaskProcess(process)

    monkeypatch.setattr(os, 'kill', mock_kill)
    await task_process.stop()


@pytest.mark.asyncio
async def test_stop_handle_process_lookup_error():
    process = MagicMock()
    process.terminate.side_effect = ProcessLookupError
    task_process = TaskProcess(process)
    await task_process.stop()


@pytest.mark.asyncio
async def test_set_killed_due_to_worker_shutdown():
    task_process = TaskProcess(MagicMock())
    assert task_process.stopped_due_to_worker_shutdown is False
    await task_process.worker_shutdown_stop()
    assert task_process.stopped_due_to_worker_shutdown is True
