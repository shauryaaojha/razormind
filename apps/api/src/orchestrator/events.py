"""The append-only event log. This table *is* the audit trail.

docs/05-agent-runtime.md: every state transition appends a row, and Phase 8's
SSE stream and Phase 9's history view are both replays of it. That is the design
constraint worth stating plainly -- history and live are not two renderings of
an execution, they are the same rendering of the same rows, so a trace that
looks right live cannot look different an hour later.

``seq`` is monotonic per execution and assigned in process, not by the database.
Two nodes finishing at once would otherwise race on ``max(seq) + 1`` and one of
them would take the other's number; the unique constraint would catch it, but as
a crash rather than as an ordering. A single asyncio lock per execution is
sufficient and correct here because the API runs a single uvicorn worker by
design (D-12) and an execution lives entirely inside one process.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncConnection

from runtime.schema import execution_events

__all__ = ["EVENT_KINDS", "EventLog", "RecordedEvent"]

#: Every kind of thing that can be logged. Closed, because a consumer that
#: cannot enumerate the events cannot render them.
EVENT_KINDS: tuple[str, ...] = (
    "execution.created",
    "state.changed",
    "plan.built",
    "plan.rejected",
    "clarification.requested",
    "node.started",
    "node.finished",
    "verification.finished",
    # Where the answer came from, how many attempts it took, and why the
    # template was used if it was. The one event a reader consults to decide
    # how much of the wording to trust.
    "explanation.grounded",
    "execution.finished",
)


@dataclass(frozen=True)
class RecordedEvent:
    seq: int
    kind: str
    payload: dict[str, Any]


@dataclass
class EventLog:
    """One execution's events, in order.

    ``on_event`` is how a live SSE subscriber sees a stage before the stage
    commits. It is a plain callback rather than an import of the broadcaster so
    that this module -- which every execution depends on -- stays ignorant of
    delivery, and so the dependency runs one way when the broadcaster is
    replaced by a message bus (D-12).
    """

    execution_id: UUID
    on_event: Callable[[UUID, RecordedEvent], None] | None = None
    _next: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _recorded: list[RecordedEvent] = field(default_factory=list)

    @property
    def recorded(self) -> tuple[RecordedEvent, ...]:
        return tuple(self._recorded)

    async def append(
        self, conn: AsyncConnection, kind: str, payload: dict[str, Any] | None = None
    ) -> RecordedEvent:
        """Write one event. Refuses a kind nobody declared."""
        if kind not in EVENT_KINDS:
            raise ValueError(f"{kind!r} is not one of the declared event kinds")
        async with self._lock:
            seq = self._next
            self._next += 1
        event = RecordedEvent(seq=seq, kind=kind, payload=payload or {})
        await conn.execute(
            execution_events.insert().values(
                id=uuid4(),
                execution_id=self.execution_id,
                seq=event.seq,
                kind=event.kind,
                payload_json=event.payload,
            )
        )
        self._recorded.append(event)
        if self.on_event is not None:
            # After the INSERT, so nothing is announced that was not written,
            # and before the commit, so a ninety-second DAG is not a
            # ninety-second silence.
            self.on_event(self.execution_id, event)
        return event
