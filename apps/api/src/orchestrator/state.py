"""The nine-state machine, with the transitions written down.

docs/05-agent-runtime.md#state-machine, which fixes
[C-12](../../../../docs/00-corrections.md): the original omitted validation and
explanation despite both being first-class stages, and named `PARTIAL` and
`BLOCKED` with no transitions into or out of them.

```text
PENDING -> PLANNING -> NEEDS_CLARIFICATION            (terminal, resumable)
                    -> VALIDATING -> REJECTED         (terminal)
                                  -> EXECUTING -> FAILED
                                               -> PARTIAL --\\
                                               -> VERIFYING <+
                                                             -> BLOCKED
                                                             -> EXPLAINING
                                                                -> COMPLETED
```

An illegal transition **raises**. It is not a data problem to be logged and
worked around: a run that reached `COMPLETED` from `BLOCKED` has produced prose
for numbers that failed verification, and the only safe response is to stop
before the row is written.

`PARTIAL` goes on to verification rather than terminating, which is the
degradation the demo turns on: with the failure tool dead, reconciliation and
revenue still produce a verified, honest answer that says what is missing.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncConnection

from runtime.schema import agent_executions

from .events import EventLog

__all__ = ["TERMINAL", "TRANSITIONS", "ExecutionState", "IllegalTransitionError", "StateMachine"]

type ExecutionState = str

TRANSITIONS: dict[str, frozenset[str]] = {
    "PENDING": frozenset({"PLANNING", "FAILED"}),
    "PLANNING": frozenset({"VALIDATING", "NEEDS_CLARIFICATION", "FAILED"}),
    "NEEDS_CLARIFICATION": frozenset(),
    "VALIDATING": frozenset({"EXECUTING", "REJECTED", "FAILED"}),
    "REJECTED": frozenset(),
    "EXECUTING": frozenset({"VERIFYING", "PARTIAL", "FAILED"}),
    "PARTIAL": frozenset({"VERIFYING", "FAILED"}),
    "VERIFYING": frozenset({"EXPLAINING", "BLOCKED", "FAILED"}),
    "BLOCKED": frozenset(),
    "EXPLAINING": frozenset({"COMPLETED", "FAILED"}),
    "COMPLETED": frozenset(),
    "FAILED": frozenset(),
}

#: States nothing leaves. Every one of them is an answer of some kind, including
#: the two that carry no numbers.
TERMINAL: frozenset[str] = frozenset(state for state, onward in TRANSITIONS.items() if not onward)


class IllegalTransitionError(RuntimeError):
    """A move the state machine does not allow."""

    def __init__(self, current: str, requested: str) -> None:
        self.current = current
        self.requested = requested
        allowed = sorted(TRANSITIONS.get(current, frozenset()))
        super().__init__(
            f"cannot move from {current} to {requested}; "
            f"{current} allows {allowed or 'nothing -- it is terminal'}"
        )


@dataclass
class StateMachine:
    """One execution's state, the row that holds it, and the log beside it."""

    execution_id: UUID
    log: EventLog
    state: str = "PENDING"

    async def to(
        self,
        conn: AsyncConnection,
        requested: str,
        payload: dict[str, Any] | None = None,
        **columns: Any,
    ) -> None:
        """Move, write the row, append the event. In that order, or not at all.

        The event is appended *after* the row is updated so the log never claims
        a transition the execution did not take. Both happen inside the caller's
        transaction, so a failure between them rolls back together.
        """
        if requested not in TRANSITIONS:
            raise IllegalTransitionError(self.state, requested)
        if requested not in TRANSITIONS[self.state]:
            raise IllegalTransitionError(self.state, requested)

        previous, self.state = self.state, requested
        await conn.execute(
            update(agent_executions)
            .where(agent_executions.c.id == self.execution_id)
            .values(status=requested, **columns)
        )
        await self.log.append(
            conn, "state.changed", {"from": previous, "to": requested, **(payload or {})}
        )

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL
