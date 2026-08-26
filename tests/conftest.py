"""Shared test setup.

The database engine is cached per process (`runtime.db.get_engine`), which is
right for a single-worker API but wrong across tests: pytest gives each test its
own event loop, and an asyncpg pool bound to a loop that has since closed fails
on teardown with "Event loop is closed" rather than on anything to do with the
test. Disposing it after each test keeps the failure surface honest.
"""

from collections.abc import AsyncIterator

import pytest

from runtime.db import get_engine


@pytest.fixture(autouse=True)
async def reset_database_engine() -> AsyncIterator[None]:
    yield
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
        get_engine.cache_clear()
