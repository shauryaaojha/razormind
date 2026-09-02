"""Starting a run, and watching one happen.

docs/07-api.md#agent, which fixes
[C-14](../../../../docs/00-corrections.md): the original single blocking `POST`
could not drive a stage-by-stage UI, because there is nothing to render until
the whole thing is over. Here the POST reserves a row and returns, and the
client opens a stream.

```text
POST /agent/runs            202  { execution_id, status: "PENDING" }
GET  /agent/runs/{id}/events     text/event-stream, from seq 0 or Last-Event-ID
GET  /executions/{id}            the record, once it has one
```

**Replay then follow.** The stream reads `execution_events` from the requested
sequence -- the durable, append-only log -- and only then attaches to the live
broadcaster. Subscribing *before* the read is what closes the gap: an event
written between the two would otherwise reach nobody and appear as a hole. What
arrives on both paths is deduplicated by `seq`, which is monotonic per
execution, so `Last-Event-ID` resumes exactly where a dropped connection
stopped, with no gap and no repeat.

That the history page and the live chat are the same replay is the point rather
than a convenience: a trace that looked right while it ran cannot look different
an hour later, because there is only one thing to render.

**Identity is a stated gap.** docs/07-api.md specifies a forwarded Supabase JWT
and row-level security; there is no Supabase here yet, so the caller declares
itself with `X-RazorMind-User` and the merchant is *validated against*
`merchant_members` rather than trusted from the body (C-13). The check is real
and the tests hold it; what is missing is proof that the header is who it says
it is, which arrives with the JWT and changes this module in one function.
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from config.settings import get_settings
from llm.provider import get_provider
from orchestrator.events import RecordedEvent
from orchestrator.runtime import answer
from orchestrator.stream import EVENTS
from plan.models import ROLE_RANK, Role
from runtime.calendar import IST
from runtime.db import connection
from runtime.schema import execution_events, merchant_members
from verification.repository import find_by_client_request, open_execution, read_execution

__all__ = ["event_frames", "router"]

router = APIRouter(prefix="/agent", tags=["agent"])

#: Comment frames keep proxies from closing an idle stream. Fifteen seconds is
#: the doc's figure and comfortably inside the usual sixty-second idle timeout.
HEARTBEAT_SECONDS = 15.0

#: How the runtime's event kinds map onto the SSE ``event:`` field. The precise
#: kind travels in the payload as well; this is the coarse channel a client
#: subscribes to (docs/07-api.md).
CHANNELS: dict[str, str] = {
    "execution.created": "stage",
    "state.changed": "state",
    "intent.parsed": "stage",
    "plan.built": "stage",
    "plan.validated": "stage",
    "plan.rejected": "stage",
    "clarification.requested": "stage",
    "node.started": "tool",
    "node.finished": "tool",
    "verification.layer": "verification",
    "verification.finished": "verification",
    "explanation.grounded": "stage",
    "execution.finished": "state",
}

#: Nothing follows these, so a stream on one can close instead of idling.
TERMINAL_STATES = frozenset({"NEEDS_CLARIFICATION", "REJECTED", "BLOCKED", "COMPLETED", "FAILED"})


class RunRequest(BaseModel):
    """What a client asks for. ``merchant_id`` is checked, never trusted."""

    merchant_id: str = Field(min_length=1, max_length=32)
    message: str = Field(min_length=1, max_length=2000)
    #: An idempotency key. Replaying it returns the original execution rather
    #: than starting a second run: chat clients retry, and a finance
    #: investigation should not silently happen twice.
    client_request_id: str | None = Field(default=None, max_length=128)


class RunAccepted(BaseModel):
    execution_id: str
    status: str
    #: True when this request replayed an idempotency key. The client needs to
    #: know: it is watching a run that may already be finished.
    replayed: bool = False


def _error(
    code: str, message: str, status: int, detail: dict[str, Any] | None = None
) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


async def _membership(conn: AsyncConnection, user_id: UUID, merchant_id: str) -> Role:
    """The caller's role at this merchant, or a scope violation.

    Read from ``merchant_members`` rather than from the request. A body that
    could name its own merchant is not a tenancy boundary, it is a suggestion
    (C-13).
    """
    role = (
        await conn.execute(
            select(merchant_members.c.role).where(
                merchant_members.c.user_id == user_id,
                merchant_members.c.merchant_id == merchant_id,
            )
        )
    ).scalar_one_or_none()
    if role is None:
        raise _error(
            "MERCHANT_SCOPE_VIOLATION",
            f"This caller is not a member of {merchant_id}.",
            403,
            {"merchant_id": merchant_id},
        )
    if role not in ROLE_RANK:
        raise _error("INSUFFICIENT_PERMISSION", f"Unknown role {role!r}.", 403, {"role": role})
    resolved: Role = role
    return resolved


def _caller(header: str | None) -> UUID:
    try:
        return UUID(header or "")
    except ValueError as error:
        raise _error(
            "UNAUTHENTICATED",
            "X-RazorMind-User must carry the caller's user id until JWT auth lands.",
            401,
        ) from error


@router.post("/runs", response_model=RunAccepted, status_code=202)
async def start_run(
    request: RunRequest,
    x_razormind_user: Annotated[str | None, Header()] = None,
) -> RunAccepted:
    """Reserve an execution, start it in the background, and return its id.

    The row is inserted *before* returning, not by the background task: a
    client that polls the id it was just handed must find something there, and
    "202 Accepted, but ask again in a moment" is an API that leaks a race.
    """
    user_id = _caller(x_razormind_user)
    settings = get_settings()

    async with connection() as conn:
        role = await _membership(conn, user_id, request.merchant_id)
        if role == "VIEWER":
            raise _error(
                "INSUFFICIENT_PERMISSION",
                "A VIEWER may read an investigation but not run one.",
                403,
                {"role": role},
            )
        if request.client_request_id is not None:
            existing = await find_by_client_request(
                conn, request.merchant_id, request.client_request_id
            )
            if existing is not None:
                return RunAccepted(
                    execution_id=str(existing.id), status=existing.status, replayed=True
                )

        identifier = uuid4()
        try:
            await open_execution(
                conn,
                execution_id=identifier,
                user_id=user_id,
                merchant_id=request.merchant_id,
                question=request.message,
                client_request_id=request.client_request_id,
            )
        except IntegrityError as error:
            # Two identical requests in flight at once. The unique constraint
            # is the arbiter rather than the read above, which can only ever
            # have been a fast path.
            raise _error(
                "DUPLICATE_REQUEST",
                "That client_request_id is already running.",
                409,
                {"client_request_id": request.client_request_id},
            ) from error

    task = asyncio.create_task(
        _run(
            identifier,
            question=request.message,
            merchant_id=request.merchant_id,
            user_id=user_id,
            role=role,
            # The execution's own date, so "last month" resolves in the
            # calendar the money is booked in rather than the server's.
            today=datetime.now(tz=IST).date(),
            threshold=settings.intent_confidence_threshold,
        )
    )
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)

    return RunAccepted(execution_id=str(identifier), status="PENDING")


@router.get("/runs/{execution_id}/events")
async def stream_events(
    execution_id: UUID,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    from_seq: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    """Replay from the log, then follow the live broadcaster."""
    async with connection() as conn:
        stored = await read_execution(conn, execution_id)
    if stored is None:
        raise _error("EXECUTION_NOT_FOUND", f"No execution {execution_id}.", 404)

    start = _resume_from(last_event_id, from_seq)
    return StreamingResponse(
        event_frames(execution_id, start),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # nginx buffers text/event-stream by default, which turns a
            # progressive stream back into one burst at the end.
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------
# the stream
# --------------------------------------------------------------------------


async def event_frames(execution_id: UUID, start: int) -> AsyncIterator[str]:
    """Every event from ``start`` onward, exactly once, in order.

    Public because it is the thing worth testing: httpx's ASGI transport runs
    an app to completion and hands back the collected body, so a test that went
    through it could prove the frames were right and never that they arrived
    while the run was still going -- which is the entire point of C-14.

    Nothing here polls for a disconnect. The ASGI server cancels this generator
    when the client goes away, which is both earlier and more reliable than
    asking; a hand-rolled check would be a second, worse copy of a mechanism
    that already exists.
    """
    async with EVENTS.subscribe(execution_id) as queue:
        # Subscribe first, then read. The other order loses whatever is written
        # in between, and a stream with a hole in it is worse than one that
        # repeats.
        async with connection() as conn:
            replayed = await _replay(conn, execution_id, start)
            stored = await read_execution(conn, execution_id)

        emitted = start - 1
        for event in replayed:
            emitted = event.seq
            yield _frame(event)

        if stored is not None and stored.status in TERMINAL_STATES:
            # Finished before anyone watched. The replay was the whole story.
            return

        while True:
            try:
                async with asyncio.timeout(HEARTBEAT_SECONDS):
                    live = await queue.get()
            except TimeoutError:
                # A comment frame. Proxies close an idle connection, and an
                # execution can legitimately spend a minute inside one node.
                yield ": heartbeat\n\n"
                continue
            if live is None:
                return
            if live.seq <= emitted:
                # Already delivered by the replay. Deduplicating on seq is what
                # makes "subscribe then read" safe.
                continue
            emitted = live.seq
            yield _frame(live)
            if live.kind == "execution.finished":
                return


async def _replay(conn: AsyncConnection, execution_id: UUID, start: int) -> list[RecordedEvent]:
    rows = (
        await conn.execute(
            select(execution_events)
            .where(
                execution_events.c.execution_id == execution_id,
                execution_events.c.seq >= start,
            )
            .order_by(execution_events.c.seq)
        )
    ).all()
    return [
        RecordedEvent(seq=row.seq, kind=row.kind, payload=dict(row.payload_json or {}))
        for row in rows
    ]


def _frame(event: RecordedEvent) -> str:
    """One SSE frame. ``id:`` is the sequence, which is what resumes a stream."""
    body = json.dumps(
        {"seq": event.seq, "kind": event.kind, **event.payload},
        separators=(",", ":"),
        default=str,
    )
    channel = CHANNELS.get(event.kind, "stage")
    return f"id: {event.seq}\nevent: {channel}\ndata: {body}\n\n"


def _resume_from(last_event_id: str | None, from_seq: int) -> int:
    """``Last-Event-ID`` wins over the query parameter; it is the browser's own.

    A malformed header is treated as absent rather than as an error: the
    browser sends it automatically on reconnect, and refusing the reconnect
    would be a worse outcome than replaying from the start.
    """
    if last_event_id is not None:
        try:
            return int(last_event_id) + 1
        except ValueError:
            return from_seq
    return from_seq


# --------------------------------------------------------------------------
# the background run
# --------------------------------------------------------------------------

#: Strong references to running tasks. Without this the event loop is the only
#: holder and a run can be garbage-collected mid-flight.
_RUNNING: set[asyncio.Task[None]] = set()


async def _run(execution_id: UUID, **kwargs: Any) -> None:
    """Drive one execution, and always close its stream.

    Failures are swallowed here on purpose: the runtime writes every terminal
    state to the row itself, so an exception escaping into the task would add
    nothing a client can see and would print a traceback nobody is reading.
    What must not be skipped is the close, or every subscriber waits out its
    heartbeat forever.
    """
    try:
        with contextlib.suppress(Exception):
            await answer(
                kwargs.pop("question"),
                execution_id=execution_id,
                reserved=True,
                provider=get_provider(),
                on_event=EVENTS.publish,
                **kwargs,
            )
    finally:
        EVENTS.close(execution_id)
