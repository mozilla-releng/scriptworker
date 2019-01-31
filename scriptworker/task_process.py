import asyncio
import logging
from asyncio.subprocess import Process

log = logging.getLogger(__name__)


class TaskProcess:
    def __init__(self, process: Process):
        self.process = process
        self.stopped_due_to_worker_shutdown = False

    async def worker_shutdown_stop(self):
        self.stopped_due_to_worker_shutdown = True
        await self._stop()

    async def exceeded_timeout_stop(self):
        await self._stop()

    async def _stop(self):
        """Stops the current task process. Starts with SIGTERM, gives the process 1 second to terminate, then kills it

        """
        try:
            self.process.terminate()
            await asyncio.sleep(1)
            self.process.kill()
        except ProcessLookupError:
            return
