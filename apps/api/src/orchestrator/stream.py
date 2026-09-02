"""Live delivery of events that are already durable.

The SSE endpoint has two sources and needs both. `execution_events` is the
truth -- append-only, monotonically sequenced, and the reason a finished run and
a live one render identically. But a stage's rows are not *visible* until the
stage's transaction commits, and a client watching a ninety-second DAG through
one commit boundary sees nothing for ninety seconds and then everything at once.

So a subscriber replays from the table and then follows this broadcaster, which
`EventLog` publishes to as each event is written. Deduplication is by ``seq``,
which is monotonic per execution, so an event arriving on both paths is emitted
once and a gap in the middle is impossible.

**This is in-process, and that is a design constraint rather than a shortcut**
(D-12). One uvicorn worker, executions and subscribers in the same memory. The
trigger to change it is written down: a second worker, or executions needing to
survive a restart. When that day comes this module becomes a Redis pub/sub
adapter and nothing above it changes, because the durable log already exists.

One consequence worth stating: an event is published here after its INSERT but
before the stage commits, so a subscriber can in principle see an event whose
transaction later rolls back. Every stage in the runtime either commits or ends
the run, so the window is real but empty -- and the alternative, waiting for the
commit, is the thing this exists to avoid.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from uuid import UUID

from .events import RecordedEvent

__all__ = ["EVENTS", "Broadcaster"]

#: How many events a slow subscriber may fall behind before it is dropped. An
#: execution publishes tens of events, so reaching this means the consumer is
#: gone rather than busy, and holding the producer for it would stall the run.
QUEUE_LIMIT = 256


@dataclass
class Broadcaster:
    """Fan-out of one execution's events to whoever is watching it."""

    _subscribers: dict[UUID, list[asyncio.Queue[RecordedEvent | None]]] = field(
        default_factory=dict
    )

    def publish(self, execution_id: UUID, event: RecordedEvent) -> None:
        """Hand an event to every current subscriber. Never blocks, never raises.

        A full queue drops the event for that one subscriber rather than
        applying back-pressure to the execution. The subscriber notices,
        because the next ``seq`` it sees will have skipped -- and the durable
        log is one reconnect away.
        """
        for queue in self._subscribers.get(execution_id, []):
            if queue.qsize() < QUEUE_LIMIT:
                queue.put_nowait(event)

    def close(self, execution_id: UUID) -> None:
        """Signal every subscriber that the execution is over."""
        for queue in self._subscribers.get(execution_id, []):
            queue.put_nowait(None)

    @asynccontextmanager
    async def subscribe(
        self, execution_id: UUID
    ) -> AsyncIterator[asyncio.Queue[RecordedEvent | None]]:
        """A queue of this execution's events, removed on exit.

        Subscribing *before* the replay read is the caller's job and is what
        closes the gap: an event written between the read and the subscribe
        would otherwise be delivered to nobody and appear as a hole in a stream
        that is supposed to have none.
        """
        queue: asyncio.Queue[RecordedEvent | None] = asyncio.Queue()
        self._subscribers.setdefault(execution_id, []).append(queue)
        try:
            yield queue
        finally:
            watchers = self._subscribers.get(execution_id, [])
            if queue in watchers:
                watchers.remove(queue)
            if not watchers:
                self._subscribers.pop(execution_id, None)

    def watching(self, execution_id: UUID) -> int:
        return len(self._subscribers.get(execution_id, []))


#: The process-wide instance. A module-level singleton for the same reason the
#: engine is one: there is exactly one process, and a per-request broadcaster
#: would fan out to nobody.
EVENTS = Broadcaster()
