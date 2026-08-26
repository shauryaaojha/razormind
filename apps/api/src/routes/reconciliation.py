"""Reconciliation read endpoints (docs/07-api.md#reconciliation).

The original spec's endpoints took no parameters, which cannot work for a
merchant- and period-scoped resource.

**Scoping.** `merchant_id` selects; row-level security *enforces*. Until Phase 8
wires Supabase JWTs, these routes connect as the owner role, so the policies are
present and tested (`tests/test_rls.py`) but not yet the thing standing between
a caller and another tenant's rows. That is a stated gap, not an oversight --
see the note in `routes/__init__.py`.
"""

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from runtime.db import connection
from runtime.schema import (
    reconciliation_exceptions,
    reconciliation_matches,
    reconciliation_runs,
    settlements,
    transactions,
)

__all__ = ["router"]

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"])

MAX_PAGE = 200


class Period(BaseModel):
    from_: date = Field(alias="from")
    to: date

    model_config = {"populate_by_name": True}


class RunSummary(BaseModel):
    """Ratios serialize as **strings** to survive JSON's float round-trip.

    Money stays an integer. Only ratios are strings (D-02).
    """

    run_id: str
    period: Period
    ledger_count: int
    bank_count: int
    matched_pairs_count: int
    matched_clean_count: int
    matched_with_exception_count: int
    unmatched_ledger_count: int
    unmatched_bank_count: int
    clean_match_rate_ratio: str
    exception_count: int
    exception_breakdown: dict[str, int]
    unresolved_exception_value_paise: int


class RunPage(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None = None


class ExceptionItem(BaseModel):
    id: str
    category: str
    side: str
    transaction_id: str | None
    settlement_id: str | None
    amount_paise: int
    currency: str = "INR"
    status: str
    detail: dict[str, Any]


class ExceptionPage(BaseModel):
    items: list[ExceptionItem]
    next_cursor: str | None = None


class MatchRecord(BaseModel):
    """One pairing plus both source records -- what the provenance drawer opens onto."""

    id: str
    run_id: str
    rule: str
    confidence_ratio: str
    reason: str
    amount_delta_paise: int
    lag_days: int
    transaction: dict[str, Any]
    settlement: dict[str, Any]


def _error(code: str, message: str, status: int) -> HTTPException:
    """The one error shape, everywhere. Clients switch on `code`, never `message`."""
    return HTTPException(
        status_code=status,
        detail={"error": {"code": code, "message": message, "detail": {}}},
    )


@router.get("/runs", response_model=RunPage)
async def list_runs(
    merchant_id: Annotated[str, Query(min_length=1, max_length=32)],
    period_from: Annotated[date | None, Query(alias="from")] = None,
    period_to: Annotated[date | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
) -> RunPage:
    if period_from is not None and period_to is not None and period_from >= period_to:
        raise _error("INVALID_PERIOD", "Period start must precede period end.", 422)

    query = (
        select(reconciliation_runs)
        .where(reconciliation_runs.c.merchant_id == merchant_id)
        .order_by(
            reconciliation_runs.c.period_from.desc(),
            # A unique tiebreaker, so two runs over the same period never
            # swap places between requests.
            reconciliation_runs.c.id.desc(),
        )
        .limit(limit)
    )
    if period_from is not None:
        query = query.where(reconciliation_runs.c.period_to > period_from)
    if period_to is not None:
        query = query.where(reconciliation_runs.c.period_from < period_to)

    async with connection() as conn:
        runs = (await conn.execute(query)).all()
        summaries = []
        for run in runs:
            breakdown_rows = (
                await conn.execute(
                    select(
                        reconciliation_exceptions.c.category,
                        reconciliation_exceptions.c.amount_paise,
                    ).where(
                        reconciliation_exceptions.c.run_id == run.id,
                        # Ledger-side only. Counting the bank side in the same
                        # total would count one discrepancy twice (D-20).
                        reconciliation_exceptions.c.side == "LEDGER",
                    )
                )
            ).all()
            breakdown: dict[str, int] = {}
            unresolved = 0
            for row in breakdown_rows:
                breakdown[row.category] = breakdown.get(row.category, 0) + 1
                if row.category == "NO_COUNTERPART":
                    unresolved += row.amount_paise
            summaries.append(
                RunSummary(
                    run_id=run.id,
                    period=Period(**{"from": run.period_from, "to": run.period_to}),
                    ledger_count=run.ledger_count,
                    bank_count=run.bank_count,
                    matched_pairs_count=run.matched_pairs,
                    matched_clean_count=run.matched_clean,
                    matched_with_exception_count=run.matched_with_exception,
                    unmatched_ledger_count=run.unmatched_ledger,
                    unmatched_bank_count=run.unmatched_bank,
                    clean_match_rate_ratio=f"{run.clean_match_rate_ratio:.6f}",
                    exception_count=len(breakdown_rows),
                    exception_breakdown=dict(sorted(breakdown.items())),
                    unresolved_exception_value_paise=unresolved,
                )
            )
    return RunPage(items=summaries)


@router.get("/runs/{run_id}/exceptions", response_model=ExceptionPage)
async def list_exceptions(
    run_id: str,
    category: str | None = None,
    side: Literal["LEDGER", "BANK"] | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 50,
    cursor: str | None = None,
) -> ExceptionPage:
    query = (
        select(reconciliation_exceptions)
        .where(reconciliation_exceptions.c.run_id == run_id)
        .order_by(reconciliation_exceptions.c.id)
        .limit(limit + 1)
    )
    if category is not None:
        query = query.where(reconciliation_exceptions.c.category == category)
    if side is not None:
        query = query.where(reconciliation_exceptions.c.side == side)
    if cursor is not None:
        query = query.where(reconciliation_exceptions.c.id > cursor)

    async with connection() as conn:
        if not await _run_exists(conn, run_id):
            raise _error("RUN_NOT_FOUND", f"No reconciliation run {run_id}.", 404)
        rows = (await conn.execute(query)).all()

    has_more = len(rows) > limit
    page = rows[:limit]
    return ExceptionPage(
        items=[
            ExceptionItem(
                id=row.id,
                category=row.category,
                side=row.side,
                transaction_id=row.transaction_id,
                settlement_id=row.settlement_id,
                amount_paise=row.amount_paise,
                status=row.status,
                detail=row.detail_json,
            )
            for row in page
        ],
        next_cursor=page[-1].id if has_more and page else None,
    )


@router.get("/runs/{run_id}/matches/{match_id}", response_model=MatchRecord)
async def get_match(run_id: str, match_id: str) -> MatchRecord:
    async with connection() as conn:
        row = (
            await conn.execute(
                select(reconciliation_matches).where(
                    reconciliation_matches.c.run_id == run_id,
                    reconciliation_matches.c.id == match_id,
                )
            )
        ).one_or_none()
        if row is None:
            raise _error("MATCH_NOT_FOUND", f"No match {match_id} in run {run_id}.", 404)

        transaction = (
            await conn.execute(select(transactions).where(transactions.c.id == row.transaction_id))
        ).one()
        settlement = (
            await conn.execute(select(settlements).where(settlements.c.id == row.settlement_id))
        ).one()

    return MatchRecord(
        id=row.id,
        run_id=row.run_id,
        rule=row.rule,
        confidence_ratio=f"{row.confidence_ratio:.6f}",
        reason=row.reason,
        amount_delta_paise=row.amount_delta_paise,
        lag_days=row.lag_days,
        transaction=_jsonable(transaction._mapping),
        settlement=_jsonable(settlement._mapping),
    )


async def _run_exists(conn: Any, run_id: str) -> bool:
    found = (
        await conn.execute(
            select(reconciliation_runs.c.id).where(reconciliation_runs.c.id == run_id)
        )
    ).one_or_none()
    return found is not None


def _jsonable(mapping: Any) -> dict[str, Any]:
    """Dates and datetimes as ISO-8601; money stays an integer."""
    from datetime import datetime

    rendered: dict[str, Any] = {}
    for key, value in dict(mapping).items():
        if isinstance(value, datetime | date):
            rendered[key] = value.isoformat()
        else:
            rendered[key] = value
    return rendered
