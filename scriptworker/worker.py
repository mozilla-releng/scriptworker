#!/usr/bin/env python
"""Scriptworker worker functions.

Attributes:
    log (logging.Logger): the log object for the module.

"""
import aiohttp
import arrow
import asyncio
import logging
import os
import sys
import signal
import socket
import typing

from scriptworker.artifacts import upload_artifacts
from scriptworker.config import get_context_from_cmdln
from scriptworker.constants import STATUSES
from scriptworker.cot.generate import generate_cot
from scriptworker.cot.verify import ChainOfTrust, verify_chain_of_trust
from scriptworker.exceptions import ScriptWorkerException, WorkerShutdownDuringTask
from scriptworker.task import claim_work, complete_task, prepare_to_run_task, \
    reclaim_task, run_task, worst_level
from scriptworker.utils import cleanup, filepaths_in_dir, get_results_and_future_exceptions

log = logging.getLogger(__name__)


# do_run_task {{{1
async def do_run_task(task_context, run_cancellable):
    """Run the task logic.

    Returns the integer status of the task.

    args:
        task_context (scriptworker.context.TaskContext): the task context.
        run_cancellable (typing.Callable): wraps future such that it'll cancel upon worker shutdown

    Raises:
        Exception: on unexpected exception.

    Returns:
        int: exit status

    """
    status = 0
    artifacts_paths = None
    shutdown = False
    try:
        if task_context.config['verify_chain_of_trust']:
            chain = ChainOfTrust(task_context, task_context.config['cot_job_type'])
            await run_cancellable(verify_chain_of_trust(chain))
        status = await run_task(task_context)
        generate_cot(task_context)
    except (asyncio.CancelledError, WorkerShutdownDuringTask):
        status = worst_level(status, STATUSES['worker-shutdown'])
        log.error("CoT cancelled asynchronously")
        shutdown = True
    except ScriptWorkerException as e:
        status = worst_level(status, e.exit_code)
        log.error("Hit ScriptWorkerException: {}".format(e))
    except Exception as e:
        log.exception("SCRIPTWORKER_UNEXPECTED_EXCEPTION task {}".format(e))
        status = STATUSES['internal-error']
    finally:
        if shutdown:
            shutdown_artifact_paths = [
                os.path.join('public', 'logs', log_file) for log_file in
                ['chain_of_trust.log', 'live_backing.log']
            ]
            artifacts_paths = [
                path for path in shutdown_artifact_paths if
                os.path.isfile(os.path.join(task_context.artifact_dir, path))
            ]
        else:
            artifacts_paths = filepaths_in_dir(task_context.artifact_dir)
        status = worst_level(status, await do_upload(task_context, artifacts_paths))
        await complete_task(task_context, status)
        task_context.reclaim_fut.cancel()
    return status


# do_upload {{{1
async def do_upload(task_context, files):
    """Upload artifacts and return status.

    Returns the integer status of the upload.

    args:
        task_context (scriptworker.context.TaskContext): the task context.
        files (list of str): list of files to be uploaded as artifacts

    Raises:
        Exception: on unexpected exception.

    Returns:
        int: exit status

    """
    status = 0
    try:
        await upload_artifacts(task_context, files)
    except ScriptWorkerException as e:
        status = worst_level(status, e.exit_code)
        log.error("Hit ScriptWorkerException: {}".format(e))
    except aiohttp.ClientError as e:
        status = worst_level(status, STATUSES['intermittent-task'])
        log.error("Hit aiohttp error: {}".format(e))
    except Exception as e:
        log.exception("SCRIPTWORKER_UNEXPECTED_EXCEPTION upload {}".format(e))
        raise
    return status


# RunTasks {{{1
class RunTasks:
    """Manage processing of Taskcluster tasks.

    Attributes:
        futures (list): a list of ``asyncio.Future``s associated with the tasks
        is_cancelled (bool): whether the tasks have been cancelled by SIGTERM
        task_contexts (list of ``scriptworker.context.TaskContext``s): the contexts for the running tasks

    """

    def __init__(self):
        """Constructor."""
        self.futures = []
        self.is_cancelled = False
        self.task_contexts = []

    async def invoke(self, worker_context):
        """Claims and processes Taskcluster work.

        Args:
            worker_context (scriptworker.context.WorkerContext): context of worker

        Returns: list of status codes

        """
        try:
            # Note: claim_work(...) might not be safely interruptible! See
            # https://bugzilla.mozilla.org/show_bug.cgi?id=1524069
            tasks = await self._run_cancellable(claim_work(worker_context))
            if not tasks or not tasks.get('tasks', []):
                await self._run_cancellable(asyncio.sleep(worker_context.config['poll_interval']))
                return

            futures = []
            for task_num, task_defn in enumerate(tasks.get('tasks', [])):
                task_context = prepare_to_run_task(worker_context, task_defn, task_num=task_num)
                task_context.reclaim_fut = worker_context.event_loop.create_task(reclaim_task(task_context))
                self.task_contexts.append(task_context)
                futures.append(
                    asyncio.ensure_future(
                        do_run_task(task_context, self._run_cancellable)
                    )
                )
            results, errors = await get_results_and_future_exceptions(futures)
            unexpected_errors = [
                err for err in errors if not isinstance(err, asyncio.CancelledError)
            ]
            if unexpected_errors:
                for err in unexpected_errors:
                    log.exception(
                        "SCRIPTWORKER_UNEXPECTED_EXCEPTION RunTasks.invoke: {}".format(str(err)),
                        exc_info=(err.__class__, err, err.__traceback__)
                    )
                raise unexpected_errors[0]
            cleanup(worker_context)

            return results

        except asyncio.CancelledError:
            return

    async def _run_cancellable(self, coroutine: typing.Awaitable):
        future = asyncio.ensure_future(coroutine)
        # we can't assume this is the only cancellable future running;
        # we may be running `num_concurrent_tasks` concurrently
        self.futures.append(future)
        if self.is_cancelled:
            self._cancel_all_futures()
            return
        status = await future
        self.futures.remove(future)
        return status

    def _cancel_all_futures(self):
        for future in self.futures:
            future.cancel()

    async def cancel(self):
        """Cancel current work."""
        self.is_cancelled = True
        for task_context in self.task_contexts:
            if task_context.task_process:
                log.warning("Worker is shutting down, but a task is running. Terminating task")
                await task_context.task_process.worker_shutdown_stop()
        self._cancel_all_futures()


# run_tasks {{{1
async def run_tasks(worker_context):
    """Run any tasks returned by claimWork.

    Returns the integer status of the task that was run, or None if no task was
    run.

    args:
        worker_context (scriptworker.context.WorkerContext): the scriptworker context.

    Raises:
        Exception: on unexpected exception.

    Returns:
        list: exit statuses

    """
    running_tasks = RunTasks()
    worker_context.running_tasks = running_tasks
    statuses = await running_tasks.invoke(worker_context)
    worker_context.running_tasks = None
    return statuses


# async_main {{{1
async def async_main(worker_context, credentials):
    """Set up and run tasks for this iteration.

    http://docs.taskcluster.net/queue/worker-interaction/

    Args:
        worker_context (scriptworker.context.WorkerContext): the scriptworker context.
        credentials (dict): the worker taskcluster credentials

    """
    conn = aiohttp.TCPConnector(limit=worker_context.config['aiohttp_max_connections'])
    async with aiohttp.ClientSession(connector=conn) as session:
        worker_context.session = session
        worker_context.credentials = credentials
        await run_tasks(worker_context)


# main {{{1
def main(event_loop=None):
    """Scriptworker entry point: get everything set up, then enter the main loop.

    Args:
        event_loop (asyncio.BaseEventLoop, optional): the event loop to use.
            If None, use ``asyncio.get_event_loop()``. Defaults to None.

    """
    worker_context, credentials = get_context_from_cmdln(sys.argv[1:])
    log.info("Scriptworker starting up at {} UTC".format(arrow.utcnow().format()))
    log.info("Worker FQDN: {}".format(socket.getfqdn()))
    cleanup(worker_context)
    worker_context.event_loop = event_loop or asyncio.get_event_loop()

    done = False

    async def _handle_sigterm():
        log.info("SIGTERM received; shutting down")
        nonlocal done
        done = True
        if worker_context.running_tasks is not None:
            await worker_context.running_tasks.cancel()

    async def _handle_sigusr1():
        """Stop accepting new tasks."""
        log.info("SIGUSR1 received; no more tasks will be taken")
        nonlocal done
        done = True

    worker_context.event_loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.ensure_future(_handle_sigterm()))
    worker_context.event_loop.add_signal_handler(signal.SIGUSR1, lambda: asyncio.ensure_future(_handle_sigusr1()))

    while not done:
        try:
            worker_context.event_loop.run_until_complete(async_main(worker_context, credentials))
        except Exception:
            log.critical("Fatal exception", exc_info=1)
            raise
    else:
        log.info("Scriptworker stopped at {} UTC".format(arrow.utcnow().format()))
        log.info("Worker FQDN: {}".format(socket.getfqdn()))
