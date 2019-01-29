import asyncio
import logging
from asyncio.subprocess import Process

log = logging.getLogger(__name__)


class TaskProcess:
    def __init__(self, process: Process):
        self.process = process
        self.killed_due_to_worker_shutdown = False

    async def worker_shutdown(self):
        self.killed_due_to_worker_shutdown = True
        await self.stop()

    async def stop(self):
        """Stops the current task process. Starts with SIGTERM, gives the process 1 second to terminate, then kills it

        """
        pid = self.process.pid
        log.info("Killing process tree for pid {}".format(pid))
        try:
            self.process.terminate()
            await asyncio.sleep(1)
            self.process.kill()
        except ProcessLookupError:
            return
