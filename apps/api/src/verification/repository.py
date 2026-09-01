"""The execution record a verification pass produces.

An execution exists before it is verified, and the verdict is written onto it.
That ordering matters: a `BLOCKED` execution has to be a *row*, not an absence.
"We could not verify this, and here is which layer stopped it" is an answer;
a missing record is indistinguishable from a request that never arrived.

Phase 5 writes the two states verification itself decides:

```text
VERIFYING  -> BLOCKED      a layer failed; error_json names it; no prose, ever
           -> EXPLAINING   every layer passed; the numbers may now be phrased
```

`EXPLAINING` is where this phase stops on purpose. The next state is
`COMPLETED`, and reaching it means generating text -- which is Phase 7's job and
nobody else's. Writing `COMPLETED` here would claim an answer exists when the
only thing that exists is permission to write one.

`response_source` stays `NULL` throughout, which is the persisted form of "no
text was generated". A blocked execution with a `response_source` would be a
contradiction the database can be asked about.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from evidence.models import Evidence
from evidence.repository import save_evidence
from runtime.schema import agent_executions

from .verifier import VerificationReport

__all__ = [
    "StoredExecution",
    "finish_execution",
    "open_execution",
    "read_execution",
    "record_verification",
]


@dataclass(frozen=True)
class StoredExecution:
    """What an execution looks like once verification has had its say."""

    id: UUID
    merchant_id: str
    period_from: date | None
    period_to: date | None
    status: str
    response_source: str | None
    error: dict[str, Any] | None

    @property
    def blocked(self) -> bool:
        return self.status == "BLOCKED"


async def open_execution(
    conn: AsyncConnection,
    *,
    execution_id: UUID,
    user_id: UUID,
    merchant_id: str,
    question: str,
    period_from: date | None = None,
    period_to: date | None = None,
) -> None:
    """Record the execution before anything is verified.

    The period is optional because an agent execution does not have one yet: it
    is written when planning resolves the intent. A placeholder window would be
    a date range nobody asked for, sitting in the audit row for every execution
    that never got as far as choosing one.
    """
    await conn.execute(
        agent_executions.insert().values(
            id=execution_id,
            user_id=user_id,
            merchant_id=merchant_id,
            input=question,
            period_from=period_from,
            period_to=period_to,
            status="VERIFYING",
        )
    )


async def record_verification(
    conn: AsyncConnection,
    execution_id: UUID,
    report: VerificationReport,
    rows: tuple[Evidence, ...],
) -> tuple[str, dict[str, Any] | None]:
    """Store the evidence a passing report earns, and say what state follows.

    A blocked execution stores **no evidence**. That is not tidiness: a stored
    row is something the API will serve and the provenance drawer will walk, and
    serving the support for a number that failed verification is how an
    unverified figure reaches a reader with a citation attached to it.

    It writes no status of its own, because two things move an execution between
    states -- this and the orchestrator's state machine -- and only one of them
    may own the column. Returning the verdict instead of writing it is what
    keeps the state machine the single writer.
    """
    if report.passed:
        await save_evidence(conn, execution_id, rows)
        return report.status, None
    return report.status, {
        "code": "VERIFICATION_FAILED",
        "message": f"verification stopped at layer {report.blocked_at}",
        "detail": {"blocked_at": report.blocked_at, "failures": list(report.failures)},
    }


async def finish_execution(
    conn: AsyncConnection,
    execution_id: UUID,
    report: VerificationReport,
    rows: tuple[Evidence, ...],
) -> str:
    """:func:`record_verification`, plus the status write, for a standalone run.

    Used by ``scripts/verify.py``, which exercises the trust layer with no
    planner and no state machine above it. Inside an agent execution the
    orchestrator does the status write itself.
    """
    status, error = await record_verification(conn, execution_id, report, rows)
    await conn.execute(
        update(agent_executions)
        .where(agent_executions.c.id == execution_id)
        .values(status=status, error_json=error)
    )
    return status


async def read_execution(conn: AsyncConnection, execution_id: UUID) -> StoredExecution | None:
    row = (
        await conn.execute(select(agent_executions).where(agent_executions.c.id == execution_id))
    ).one_or_none()
    if row is None:
        return None
    return StoredExecution(
        id=row.id,
        merchant_id=row.merchant_id,
        period_from=row.period_from,
        period_to=row.period_to,
        status=row.status,
        response_source=row.response_source,
        error=row.error_json,
    )
