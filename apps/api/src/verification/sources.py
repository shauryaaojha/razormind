"""Resolving the records a piece of evidence cites.

Layer 5 asks two questions of every cited id: does this record exist, and does
it fall inside the window the evidence claims. Neither can be answered without
knowing *which date* selects the record, and that is not a property of the
record's type.

Four scoping rules are in play, all four deliberate, and a verifier that
assumed one date for everything would reject a correct row for three of them:

* a payment belongs to the window it was **attempted** in, because a failure
  has no capture instant (``ATTEMPT_DATE``);
* the reconciliation ledger is captures, scoped by **capture** date, because a
  settlement is due against a capture (``CAPTURE_DATE``);
* a refund or chargeback belongs to the window of the payment it reverses, not
  the window it was raised in -- one of this fixture's refunds is raised in the
  following month (``PARENT_ATTEMPT_DATE``, D-31);
* a settlement line lands in the bank window, which is the capture window
  shifted by the settlement cycle (``VALUE_DATE``, D-18).

So the evidence says which rule it used, in ``Aggregation.scoped_by``, and this
module answers accordingly (D-37). That makes layer 5 a check on the scoping the tool
*declared* rather than on a scoping the verifier assumed -- and a tool that
declares one rule and applies another is caught, which is the whole point.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from sqlalchemy import Table, select
from sqlalchemy.ext.asyncio import AsyncConnection

from evidence.models import Anchor
from runtime.calendar import ist_date
from runtime.money import Paise
from runtime.schema import chargebacks, refunds, settlements, transactions

__all__ = [
    "DatabaseSources",
    "SourceRecord",
    "SourceResolver",
    "StaticSources",
    "UnknownRecordSetError",
]


class UnknownRecordSetError(LookupError):
    """An evidence row names a record set nothing knows how to resolve.

    Raised rather than returning "no records found", which would render as
    "every cited record is missing" and send a reader looking for deleted rows.
    """


@dataclass(frozen=True)
class SourceRecord:
    """One resolved record: where it sits in time, and what it is worth.

    ``anchor`` is the date the *declared* scoping rule selects it by, not any
    single column -- for a refund it is the parent payment's attempt date.
    """

    id: str
    anchor: date
    amount_paise: Paise
    fee_paise: Paise


class SourceResolver(Protocol):
    """What layer 5 needs from the world below it."""

    async def resolve(
        self, over: str, scoped_by: Anchor, record_ids: Sequence[str]
    ) -> Mapping[str, SourceRecord]:
        """The cited records that exist. Missing ids are simply absent."""
        ...


#: ``over`` values whose cited ids are ledger **transaction** ids rather than
#: ids in the named table. A reconciliation metric cites the ledger record,
#: because that is the row a reader can actually open; the match and exception
#: rows are the reasoning about it, not the thing being counted.
_LEDGER_RECORD_SETS = frozenset({"reconciliation_matches", "reconciliation_exceptions"})

_MOVEMENT_TABLES: Mapping[str, Table] = {"refunds": refunds, "chargebacks": chargebacks}


class DatabaseSources:
    """Resolves against the tables the tools read."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def resolve(
        self, over: str, scoped_by: Anchor, record_ids: Sequence[str]
    ) -> Mapping[str, SourceRecord]:
        if not record_ids:
            return {}
        ids = list(dict.fromkeys(record_ids))
        if scoped_by in ("ATTEMPT_DATE", "CAPTURE_DATE"):
            return await self._transactions(over, scoped_by, ids)
        if scoped_by == "PARENT_ATTEMPT_DATE":
            return await self._movements(over, ids)
        return await self._settlements(over, ids)

    async def _transactions(
        self, over: str, scoped_by: Anchor, ids: list[str]
    ) -> Mapping[str, SourceRecord]:
        if over != "transactions" and over not in _LEDGER_RECORD_SETS:
            raise UnknownRecordSetError(
                f"{scoped_by} scoping does not apply to {over!r}; it selects transactions"
            )
        column = (
            transactions.c.attempted_at
            if scoped_by == "ATTEMPT_DATE"
            else transactions.c.captured_at
        )
        rows = (
            await self._conn.execute(
                select(
                    transactions.c.id,
                    column.label("anchor_at"),
                    transactions.c.amount_paise,
                    transactions.c.fee_paise,
                ).where(transactions.c.id.in_(ids))
            )
        ).all()
        return {
            row.id: SourceRecord(
                id=row.id,
                anchor=_ist(row.anchor_at),
                amount_paise=row.amount_paise,
                fee_paise=row.fee_paise,
            )
            for row in rows
            if row.anchor_at is not None
        }

    async def _movements(self, over: str, ids: list[str]) -> Mapping[str, SourceRecord]:
        table = _MOVEMENT_TABLES.get(over)
        if table is None:
            raise UnknownRecordSetError(
                f"PARENT_ATTEMPT_DATE scoping does not apply to {over!r}; "
                f"it selects one of {sorted(_MOVEMENT_TABLES)}"
            )
        rows = (
            await self._conn.execute(
                select(
                    table.c.id,
                    table.c.amount_paise,
                    transactions.c.attempted_at,
                )
                .select_from(table.join(transactions, table.c.transaction_id == transactions.c.id))
                .where(table.c.id.in_(ids))
            )
        ).all()
        return {
            row.id: SourceRecord(
                id=row.id,
                anchor=_ist(row.attempted_at),
                amount_paise=row.amount_paise,
                fee_paise=0,
            )
            for row in rows
        }

    async def _settlements(self, over: str, ids: list[str]) -> Mapping[str, SourceRecord]:
        if over != "settlements":
            raise UnknownRecordSetError(
                f"VALUE_DATE scoping does not apply to {over!r}; it selects settlements"
            )
        rows = (
            await self._conn.execute(
                select(
                    settlements.c.id,
                    settlements.c.value_date,
                    settlements.c.amount_paise,
                    settlements.c.fee_paise,
                ).where(settlements.c.id.in_(ids))
            )
        ).all()
        return {
            row.id: SourceRecord(
                id=row.id,
                anchor=row.value_date,
                amount_paise=row.amount_paise,
                fee_paise=row.fee_paise,
            )
            for row in rows
        }


class StaticSources:
    """An in-memory resolver, for tests that have no database.

    It answers from a fixed set of records rather than pretending everything
    exists: a resolver that resolved every id would make layer 5 pass by
    construction, which is the one thing a test of layer 5 must not do.
    """

    def __init__(self, records: Mapping[str, SourceRecord]) -> None:
        self._records = dict(records)

    async def resolve(
        self, over: str, scoped_by: Anchor, record_ids: Sequence[str]
    ) -> Mapping[str, SourceRecord]:
        del over, scoped_by
        return {
            record_id: self._records[record_id]
            for record_id in record_ids
            if record_id in self._records
        }


def _ist(moment: datetime) -> date:
    return ist_date(moment)
