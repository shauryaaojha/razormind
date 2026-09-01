"""Storing and reading back an execution's evidence.

Evidence is written once and never updated. That is what makes "which numbers
did we publish on the 24th, and what supported them?" answerable later: a row
that could be corrected in place would make every stored answer provisional.

The round trip is lossless by construction -- the rows go out through the same
serialisers the API uses and come back through the same model, so a value that
survives the database is a value that would have survived the wire. Ratios
travel as **strings** (D-02): JSON has one numeric type and it is a float, so a
scale-6 ratio written as a number would come back as the nearest binary double
and the byte-match in grounding check 3 would fail for reasons that have
nothing to do with the number being wrong.
"""

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from runtime.schema import evidence as evidence_table

from .builder import EvidenceSet
from .models import Evidence

__all__ = ["load_evidence", "read_evidence", "save_evidence"]


async def save_evidence(conn: AsyncConnection, execution_id: UUID, rows: Iterable[Evidence]) -> int:
    """Write every row for one execution. Returns how many were written."""
    payload = [_to_row(execution_id, row) for row in rows]
    if not payload:
        return 0
    await conn.execute(evidence_table.insert(), payload)
    return len(payload)


async def load_evidence(conn: AsyncConnection, execution_id: UUID) -> EvidenceSet:
    """Everything the execution published, as a walkable set."""
    rows = (
        await conn.execute(
            select(evidence_table)
            .where(evidence_table.c.execution_id == execution_id)
            .order_by(evidence_table.c.id)
        )
    ).all()
    return EvidenceSet(_from_row(row._mapping) for row in rows)


async def read_evidence(
    conn: AsyncConnection, execution_id: UUID, evidence_id: str
) -> Evidence | None:
    """One row, or ``None``."""
    row = (
        await conn.execute(
            select(evidence_table).where(
                evidence_table.c.execution_id == execution_id,
                evidence_table.c.id == evidence_id,
            )
        )
    ).one_or_none()
    return None if row is None else _from_row(row._mapping)


def _to_row(execution_id: UUID, row: Evidence) -> dict[str, Any]:
    serialised = row.model_dump(mode="json")
    return {
        "execution_id": execution_id,
        "id": row.id,
        "tool_name": row.tool_name,
        "tool_version": row.tool_version,
        "metric_id": row.metric_id,
        "unit": row.unit,
        "value_json": serialised["value"],
        "period_from": date.fromisoformat(row.period_from),
        "period_to": date.fromisoformat(row.period_to),
        "dimension_value": row.dimension_value,
        "formula_json": serialised["formula"],
        "aggregation_json": serialised["aggregation"],
        "inputs_json": serialised["inputs"],
        "source_record_ids": list(row.source_record_ids),
        "rules_applied": list(row.rules_applied),
        "verification_checks": list(row.verification_checks),
    }


def _from_row(mapping: Any) -> Evidence:
    stored = dict(mapping)
    return Evidence.model_validate(
        {
            "id": stored["id"],
            "execution_id": str(stored["execution_id"]),
            "tool_name": stored["tool_name"],
            "tool_version": stored["tool_version"],
            "metric_id": stored["metric_id"],
            "unit": stored["unit"],
            "value": stored["value_json"],
            "period_from": stored["period_from"].isoformat(),
            "period_to": stored["period_to"].isoformat(),
            "dimension_value": stored["dimension_value"],
            "formula": stored["formula_json"],
            "aggregation": stored["aggregation_json"],
            "inputs": stored["inputs_json"],
            "source_record_ids": _strings(stored["source_record_ids"]),
            "rules_applied": _strings(stored["rules_applied"]),
            "verification_checks": _strings(stored["verification_checks"]),
        }
    )


def _strings(value: Sequence[Any] | None) -> list[str]:
    return [str(item) for item in (value or [])]
