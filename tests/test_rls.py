"""Row-level security, proven against a real Postgres.

Phase 1 exit criterion: "a user in merchant B reading merchant A's transactions
gets zero rows". Not zero rows because the query said so -- zero rows because
the database refused, with the application's own filter deliberately absent
from every statement below.

These tests need the database, so they are marked ``db`` and excluded from the
default run. ``python scripts/task.py dbtest`` runs them inside the compose
network.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from runtime.db import acting_as

pytestmark = pytest.mark.db

OWNER = "11111111-1111-4111-8111-111111111111"
OUTSIDER = "99999999-9999-4999-8999-999999999999"

#: The role the API connects as. Deliberately not the table owner: an owner is
#: exempt from RLS by default, so testing as one would prove nothing.
APP_ROLE = "razormind_app"

SCOPED_TABLES = (
    "transactions",
    "settlements",
    "refunds",
    "chargebacks",
)


def _database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://razormind:razormind@db:5432/razormind"
    )


@pytest.fixture
async def connection() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(_database_url())
    async with engine.connect() as conn:
        yield conn
    await engine.dispose()


async def _act_as(conn: AsyncConnection, user_id: str | None) -> None:
    """Bind the session to a user, through the same helper the API uses.

    Deliberately `runtime.db.acting_as` rather than an equivalent written here:
    a test that proves a hand-rolled twin works proves nothing about the code
    that ships.
    """
    await acting_as(conn, user_id if user_id is not None else "")


async def _count(conn: AsyncConnection, table: str) -> int:
    # No merchant filter anywhere in this statement. That is the point.
    result = await conn.execute(text(f"SELECT count(*) FROM {table}"))
    return int(result.scalar_one())


async def test_a_member_sees_their_own_merchants_rows(connection: AsyncConnection) -> None:
    await _act_as(connection, OWNER)
    assert await _count(connection, "transactions") > 0


@pytest.mark.parametrize("table", SCOPED_TABLES)
async def test_an_outsider_sees_nothing(connection: AsyncConnection, table: str) -> None:
    """The user belongs to a different merchant entirely."""
    await _act_as(connection, OUTSIDER)
    assert await _count(connection, table) == 0


@pytest.mark.parametrize("table", SCOPED_TABLES)
async def test_an_unauthenticated_session_sees_nothing(
    connection: AsyncConnection, table: str
) -> None:
    """No identity means no rows -- never "all rows"."""
    await _act_as(connection, None)
    assert await _count(connection, table) == 0


async def test_the_policy_survives_an_explicit_wrong_merchant_filter(
    connection: AsyncConnection,
) -> None:
    """An application bug that scopes to the wrong merchant still returns nothing.

    This is the failure RLS exists for: not a missing filter, but a *wrong*
    one. `merchant_id` comes from the session, never the model (D-09), and
    this is what happens when that rule is violated in code.
    """
    await _act_as(connection, OUTSIDER)
    result = await connection.execute(
        text("SELECT count(*) FROM transactions WHERE merchant_id = 'M123'")
    )
    assert int(result.scalar_one()) == 0


async def test_a_member_cannot_see_another_users_membership(
    connection: AsyncConnection,
) -> None:
    await _act_as(connection, OUTSIDER)
    result = await connection.execute(text("SELECT count(*) FROM merchant_members"))
    assert int(result.scalar_one()) == 1  # only their own row


async def test_the_seed_actually_loaded(connection: AsyncConnection) -> None:
    """Guards against a vacuously green suite.

    Zero rows everywhere passes every isolation test above for entirely the
    wrong reason. The expected counts come from the generated ground truth
    rather than being written here, so a regenerated fixture cannot leave this
    test asserting a number nothing produces any more.
    """
    import json

    truth = json.loads(
        (
            Path(__file__).resolve().parents[1] / "data" / "seed" / "golden" / "ground_truth.json"
        ).read_text(encoding="utf-8")
    )
    await _act_as(connection, OWNER)
    assert await _count(connection, "transactions") == truth["transaction_count"]
    assert await _count(connection, "settlements") == truth["settlement_count"]
