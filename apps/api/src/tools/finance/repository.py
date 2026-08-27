"""Loading what the revenue bridge needs, and reading a reconciliation run.

Every query carries an explicit ``ORDER BY id``. The bridge sorts its inputs
anyway, but a query without a stable order is the kind of thing that works for
a year and then changes after a vacuum; ordering at the source means the two
layers agree rather than one silently compensating for the other.

Window bounds are computed in IST and pushed into SQL as aware timestamps. The
alternative -- ``attempted_at::date`` -- would compare a UTC calendar date
against an IST window, and a payment at 20:00 UTC on 1 August is 01:30 IST on
the 2nd (C-10).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncConnection

from runtime.calendar import IST
from runtime.money import Paise
from runtime.schema import (
    chargebacks,
    reconciliation_exceptions,
    reconciliation_runs,
    refunds,
    transactions,
)

from .bridge import MovementRecord, PaymentRecord

__all__ = [
    "RunFacts",
    "load_chargebacks",
    "load_payments",
    "load_refunds",
    "load_run_facts",
]


@dataclass(frozen=True)
class RunFacts:
    """What a completed reconciliation run tells the revenue analysis.

    Two things, and they are different in kind. ``duplicate_transaction_ids``
    changes the numbers -- a duplicated ledger row is not revenue and must come
    out of gross. ``unresolved_paise`` does not change any number; it bounds
    how much of the answer the bank has confirmed, and is reported as a band
    rather than netted into anything (Invariant 7).
    """

    run_id: str
    merchant_id: str
    period_from: date
    period_to: date
    duplicate_transaction_ids: frozenset[str]
    unresolved_paise: Paise


def _window_bounds(period_from: date, period_to: date) -> tuple[datetime, datetime]:
    """The half-open IST window, as aware instants."""
    return (
        datetime.combine(period_from, time.min, tzinfo=IST),
        datetime.combine(period_to, time.min, tzinfo=IST),
    )


async def load_payments(
    conn: AsyncConnection, merchant_id: str, period_from: date, period_to: date
) -> list[PaymentRecord]:
    """Every attempt in the window -- successes and failures alike.

    Failures are the point. Scoping on ``captured_at`` would drop them all,
    because a failure has no capture instant, and the success rate would then
    read 100% for every period ever analysed.
    """
    opens, closes = _window_bounds(period_from, period_to)
    query = (
        select(
            transactions.c.id,
            transactions.c.method,
            transactions.c.instrument,
            transactions.c.status,
            transactions.c.decline_type,
            transactions.c.amount_paise,
            transactions.c.fee_paise,
            transactions.c.attempted_at,
            transactions.c.captured_at,
        )
        .where(
            transactions.c.merchant_id == merchant_id,
            transactions.c.attempted_at >= opens,
            transactions.c.attempted_at < closes,
        )
        .order_by(transactions.c.id)
    )
    rows = (await conn.execute(query)).all()
    return [
        PaymentRecord(
            id=row.id,
            method=row.method,
            instrument=row.instrument,
            status=row.status,
            decline_type=row.decline_type,
            amount_paise=row.amount_paise,
            fee_paise=row.fee_paise,
            attempted_at=row.attempted_at,
            captured_at=row.captured_at,
        )
        for row in rows
    ]


async def load_refunds(
    conn: AsyncConnection, merchant_id: str, transaction_ids: Sequence[str]
) -> list[MovementRecord]:
    """Refunds against the given payments, whenever they were raised.

    Scoped by parent, never by the refund's own date: a refund belongs to the
    window of the payment it reverses (see ``bridge.py``).
    """
    return await _load_movements(conn, refunds, merchant_id, transaction_ids)


async def load_chargebacks(
    conn: AsyncConnection, merchant_id: str, transaction_ids: Sequence[str]
) -> list[MovementRecord]:
    return await _load_movements(conn, chargebacks, merchant_id, transaction_ids)


async def _load_movements(
    conn: AsyncConnection, table: Table, merchant_id: str, transaction_ids: Sequence[str]
) -> list[MovementRecord]:
    """Refunds and chargebacks are the same shape, so they share one loader."""
    if not transaction_ids:
        return []
    columns = table.c
    query = (
        select(
            columns.id,
            columns.transaction_id,
            columns.amount_paise,
            columns.reason,
        )
        .where(
            columns.merchant_id == merchant_id,
            columns.transaction_id.in_(list(transaction_ids)),
        )
        .order_by(columns.id)
    )
    rows = (await conn.execute(query)).all()
    return [
        MovementRecord(
            id=row.id,
            transaction_id=row.transaction_id,
            amount_paise=row.amount_paise,
            reason=row.reason,
        )
        for row in rows
    ]


async def load_run_facts(conn: AsyncConnection, run_id: str) -> RunFacts | None:
    """The run, or ``None`` if there is no such run.

    ``None`` rather than a raise: whether a missing run is an error depends on
    the caller, and the tool that knows turns it into a ``ToolError`` with a
    code a client can switch on.
    """
    run = (
        await conn.execute(select(reconciliation_runs).where(reconciliation_runs.c.id == run_id))
    ).one_or_none()
    if run is None:
        return None

    exception_rows = (
        await conn.execute(
            select(
                reconciliation_exceptions.c.category,
                reconciliation_exceptions.c.transaction_id,
                reconciliation_exceptions.c.amount_paise,
            )
            .where(
                reconciliation_exceptions.c.run_id == run_id,
                reconciliation_exceptions.c.side == "LEDGER",
            )
            .order_by(reconciliation_exceptions.c.id)
        )
    ).all()

    duplicates = frozenset(
        row.transaction_id
        for row in exception_rows
        if row.category == "POSSIBLE_DUPLICATE" and row.transaction_id is not None
    )
    unresolved = sum(row.amount_paise for row in exception_rows if row.category == "NO_COUNTERPART")

    return RunFacts(
        run_id=run.id,
        merchant_id=run.merchant_id,
        period_from=run.period_from,
        period_to=run.period_to,
        duplicate_transaction_ids=duplicates,
        unresolved_paise=unresolved,
    )
