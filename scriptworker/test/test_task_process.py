import pytest
from mock import MagicMock, call
from scriptworker.task_process import TaskProcess


@pytest.mark.asyncio
async def test_stop_increasing_severity():
    process = MagicMock()
    task_process = TaskProcess(process)
    await task_process.stop()
    assert process.method_calls == [call.terminate(), call.kill()]


@pytest.mark.asyncio
async def test_stop_handle_process_lookup_error():
    process = MagicMock()
    process.terminate.side_effect = ProcessLookupError
    task_process = TaskProcess(process)
    await task_process.stop()


@pytest.mark.asyncio
async def test_set_killed_due_to_worker_shutdown():
    task_process = TaskProcess(MagicMock())
    assert task_process.killed_due_to_worker_shutdown is False
    await task_process.worker_shutdown()
    assert task_process.killed_due_to_worker_shutdown is True
