import asyncio
import logging
import os
import signal
from asyncio.subprocess import Process

log = logging.getLogger(__name__)


class TaskProcess:
    def __init__(self, process: Process):
        self.process = process
        self.stopped_due_to_worker_shutdown = False

    async def worker_shutdown_stop(self):
        self.stopped_due_to_worker_shutdown = True
        await self.stop()

    async def stop(self):
        """Stops the current task process. Starts with SIGTERM, gives the process 1 second to terminate, then kills it

        """
        # negate pid so that signals apply to process group
        pgid = -self.process.pid
        try:
            os.kill(pgid, signal.SIGTERM)
            await asyncio.sleep(1)
            os.kill(pgid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            return
