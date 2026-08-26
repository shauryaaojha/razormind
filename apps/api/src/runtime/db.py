"""Database access. One engine per process, sessions per request.

SQLAlchemy **Core**, not the ORM: reconciliation is only reproducible if every
query carries an explicit ``ORDER BY`` with a unique tiebreaker, and an ORM's
identity map hides exactly the thing that has to stay visible.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from config.settings import get_settings

__all__ = ["acting_as", "connection", "get_engine"]


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


@asynccontextmanager
async def connection() -> AsyncIterator[AsyncConnection]:
    """A connection with a transaction open."""
    engine = get_engine()
    async with engine.begin() as conn:
        yield conn


async def acting_as(conn: AsyncConnection, user_id: str) -> None:
    """Bind a connection to a user, so row-level security applies to it.

    Sets the GUC that ``razormind_current_user_id()`` reads. On Supabase the
    same function reads ``auth.uid()`` from the forwarded JWT, so the policies
    themselves are identical in both environments -- see migration 0001.

    ``SET ROLE`` matters as much as the identity: the table owner is exempt
    from row-level security by default, so a connection that stays the owner
    would have policies that are decorative.
    """
    await conn.execute(text("SET ROLE razormind_app"))
    await conn.execute(text("SELECT set_config('razormind.user_id', :uid, true)"), {"uid": user_id})
