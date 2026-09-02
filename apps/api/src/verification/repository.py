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

`response_source` stays `NULL` through verification, which is the persisted
form of "no text was generated". Phase 7 writes it, together with the answer
itself, and a database constraint keeps the two in step in both directions: a
blocked execution with a `response_source` -- or with prose -- would be a
contradiction the database can be asked about.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
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
    "find_by_client_request",
    "finish_execution",
    "list_executions",
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
    #: The generated answer, and the claims grounding checked it against. Both
    #: are ``None`` until an execution reaches ``COMPLETED``, and both stay
    #: ``None`` forever on one that did not.
    answer: str | None = None
    claims: list[dict[str, Any]] = field(default_factory=list)
    grounding_attempts: int = 0
    #: What was asked, and when. Carried so the history list needs one query
    #: rather than one per row.
    question: str = ""
    created_at: datetime | None = None

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
    client_request_id: str | None = None,
    period_from: date | None = None,
    period_to: date | None = None,
    status: str = "PENDING",
) -> None:
    """Record the execution before anything else happens.

    The period is optional because an agent execution does not have one yet: it
    is written when planning resolves the intent. A placeholder window would be
    a date range nobody asked for, sitting in the audit row for every execution
    that never got as far as choosing one.

    The row lands as ``PENDING``, which is what a client polling one millisecond
    after ``202 Accepted`` is entitled to see. ``client_request_id`` is the
    idempotency key: the unique constraint on ``(merchant_id,
    client_request_id)`` is what makes a retried chat message return the
    original run rather than start a second one.
    """
    await conn.execute(
        agent_executions.insert().values(
            id=execution_id,
            user_id=user_id,
            merchant_id=merchant_id,
            input=question,
            client_request_id=client_request_id,
            period_from=period_from,
            period_to=period_to,
            status=status,
        )
    )


async def find_by_client_request(
    conn: AsyncConnection, merchant_id: str, client_request_id: str
) -> StoredExecution | None:
    """The execution a replayed idempotency key already produced."""
    row = (
        await conn.execute(
            select(agent_executions).where(
                agent_executions.c.merchant_id == merchant_id,
                agent_executions.c.client_request_id == client_request_id,
            )
        )
    ).one_or_none()
    return None if row is None else _stored(row)


async def list_executions(
    conn: AsyncConnection,
    merchant_id: str,
    *,
    status: str | None = None,
    limit: int = 50,
    cursor: datetime | None = None,
) -> list[StoredExecution]:
    """Newest first, keyset-paginated on ``created_at``.

    Keyset rather than OFFSET: executions are inserted while somebody is
    paging, and an offset would show a row twice or skip one. The cursor is the
    last row's ``created_at``, which is monotonic per merchant in practice and
    tie-broken by id.
    """
    query = select(agent_executions).where(agent_executions.c.merchant_id == merchant_id)
    if status is not None:
        query = query.where(agent_executions.c.status == status)
    if cursor is not None:
        query = query.where(agent_executions.c.created_at < cursor)
    query = query.order_by(
        agent_executions.c.created_at.desc(), agent_executions.c.id.desc()
    ).limit(limit)
    return [_stored(row) for row in (await conn.execute(query)).all()]


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
    return None if row is None else _stored(row)


def _stored(row: Any) -> StoredExecution:
    return StoredExecution(
        id=row.id,
        merchant_id=row.merchant_id,
        period_from=row.period_from,
        period_to=row.period_to,
        status=row.status,
        response_source=row.response_source,
        error=row.error_json,
        answer=row.answer_text,
        claims=list(row.claims_json or []),
        grounding_attempts=row.grounding_attempts,
        question=row.input,
        created_at=row.created_at,
    )
