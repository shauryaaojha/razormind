"""Loading records for a period, and writing a run.

Every query here carries an explicit ``ORDER BY id``. That is not tidiness:
the engine sorts its inputs anyway, but a query without a stable order is the
kind of thing that works for a year and then changes after a vacuum. Ordering
at the source means the two layers agree rather than one silently compensating
for the other.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from runtime.calendar import bank_period
from runtime.schema import (
    reconciliation_exceptions,
    reconciliation_matches,
    reconciliation_runs,
    settlements,
    transactions,
)

from .models import BankRecord, LedgerRecord, ReconciliationResult

__all__ = [
    "load_bank_records",
    "load_ledger_records",
    "new_run_id",
    "write_run",
]


def new_run_id() -> str:
    return f"rec_{uuid.uuid4().hex[:20]}"


async def load_ledger_records(
    conn: AsyncConnection, merchant_id: str, period_from: date, period_to: date
) -> list[LedgerRecord]:
    """Captures whose **IST calendar date** falls in the half-open period.

    ``AT TIME ZONE 'Asia/Kolkata'``, never ``::date`` on the raw timestamp -- a
    capture at 20:00 UTC on the 1st is 01:30 IST on the 2nd and belongs to the
    2nd (C-10).
    """
    query = (
        select(
            transactions.c.id,
            transactions.c.merchant_id,
            transactions.c.external_ref,
            transactions.c.utr,
            transactions.c.instrument,
            transactions.c.amount_paise,
            transactions.c.fee_paise,
            transactions.c.captured_at,
            transactions.c.settlement_due_date,
        )
        .where(
            transactions.c.merchant_id == merchant_id,
            transactions.c.status == "CAPTURED",
            transactions.c.captured_at.is_not(None),
        )
        .order_by(transactions.c.id)
    )
    rows = (await conn.execute(query)).all()
    return [
        LedgerRecord(
            id=row.id,
            merchant_id=row.merchant_id,
            external_ref=row.external_ref,
            utr=row.utr,
            instrument=row.instrument,
            amount_paise=row.amount_paise,
            fee_paise=row.fee_paise,
            captured_at=row.captured_at,
            settlement_due_date=row.settlement_due_date,
        )
        for row in rows
        if row.settlement_due_date is not None
        and period_from <= _ist_date(row.captured_at) < period_to
    ]


def _ist_date(moment: object) -> date:
    from datetime import datetime

    from runtime.calendar import ist_date

    assert isinstance(moment, datetime)
    return ist_date(moment)


async def load_bank_records(
    conn: AsyncConnection, merchant_id: str, period_from: date, period_to: date
) -> list[BankRecord]:
    """Settlements in the *settlement* window for that capture window.

    The two sides carry different dates for the same payment, so scoping both
    to the same literal dates would compare two different cohorts and invent
    exceptions at the edges (D-18).
    """
    opens, closes = bank_period(period_from, period_to)
    query = (
        select(
            settlements.c.id,
            settlements.c.merchant_id,
            settlements.c.bank_ref,
            settlements.c.utr,
            settlements.c.amount_paise,
            settlements.c.fee_paise,
            settlements.c.value_date,
        )
        .where(
            settlements.c.merchant_id == merchant_id,
            settlements.c.value_date >= opens,
            settlements.c.value_date < closes,
        )
        .order_by(settlements.c.id)
    )
    rows = (await conn.execute(query)).all()
    return [
        BankRecord(
            id=row.id,
            merchant_id=row.merchant_id,
            bank_ref=row.bank_ref,
            utr=row.utr,
            amount_paise=row.amount_paise,
            fee_paise=row.fee_paise,
            value_date=row.value_date,
        )
        for row in rows
    ]


async def write_run(
    conn: AsyncConnection, result: ReconciliationResult, run_id: str | None = None
) -> str:
    """Persist a verified run. Immutable once written.

    Re-running a period creates a new row rather than updating the old one,
    which is what makes "which numbers did we see on the 24th?" answerable.
    """
    run_id = run_id or new_run_id()

    await conn.execute(
        reconciliation_runs.insert().values(
            id=run_id,
            merchant_id=result.merchant_id,
            period_from=result.period_from,
            period_to=result.period_to,
            ledger_count=result.ledger_count,
            bank_count=result.bank_count,
            matched_pairs=result.matched_pairs,
            matched_clean=result.matched_clean,
            matched_with_exception=result.matched_with_exception,
            unmatched_ledger=result.unmatched_ledger,
            unmatched_bank=result.unmatched_bank,
            clean_match_rate_ratio=result.clean_match_rate_ratio,
            status="COMPLETED",
        )
    )

    if result.matches:
        await conn.execute(
            reconciliation_matches.insert(),
            [
                {
                    "id": f"mat_{uuid.uuid4().hex[:20]}",
                    "run_id": run_id,
                    "transaction_id": match.transaction_id,
                    "settlement_id": match.settlement_id,
                    "rule": match.rule,
                    "confidence_ratio": match.confidence_ratio,
                    "reason": match.reason,
                    "amount_delta_paise": match.amount_delta_paise,
                    "lag_days": match.lag_days,
                }
                for match in result.matches
            ],
        )

    if result.exceptions:
        await conn.execute(
            reconciliation_exceptions.insert(),
            [
                {
                    "id": f"exc_{uuid.uuid4().hex[:20]}",
                    "run_id": run_id,
                    "category": exc.category,
                    "side": exc.side,
                    "transaction_id": exc.transaction_id,
                    "settlement_id": exc.settlement_id,
                    "amount_paise": exc.amount_paise,
                    "status": "OPEN",
                    "detail_json": exc.detail,
                }
                for exc in result.exceptions
            ],
        )

    return run_id
