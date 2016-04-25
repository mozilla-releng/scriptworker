import asyncio
import pytest


@pytest.yield_fixture
def loop():
    # Set-up
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop

    # Clean-up
    loop.close()
