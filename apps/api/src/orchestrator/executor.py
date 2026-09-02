"""Running a validated plan, layer by layer, concurrently within a layer.

docs/05-agent-runtime.md#execution. Three rules do all the work:

* **A node's failure skips its dependents and leaves its siblings alone.** The
  four analyses depend on reconciliation and on nothing else, so a dead failure
  tool costs exactly one metric group and not the answer.
* **A skipped or failed node yields nothing.** No substituted value, no
  estimate, no interpolation, no zero (Invariant 6). "We could not compute this"
  and "this is zero" are different facts and must render differently.
* **`finance.reconciliation` is required.** Every other tool reads the
  reconciled set, so proceeding without it produces numbers of unknown
  provenance -- and, concretely, a gross that includes a duplicated capture
  (D-32).

**Each node gets its own database connection.** Not a micro-optimisation: an
asyncpg connection cannot serve two queries at once, so nodes sharing one would
either serialise (defeating the concurrency this exists for) or corrupt each
other's protocol state. Layer boundaries are also transaction boundaries, which
is what makes the reconciliation run visible to the analyses that read it.

A timeout is a node failure, not a hang. Per node and for the run as a whole,
because a plan that hangs forever is worse than one that fails: the second has
an error code.
"""

import asyncio
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from evidence.models import Evidence
from plan.models import ExecutionPlan, PlanNode
from runtime.db import connection
from runtime.schema import tool_executions
from tools.base import Period, ToolContext, ToolError
from tools.registry import ToolRegistry
from verification.models import VerificationError

from .events import EventLog

__all__ = [
    "NODE_TIMEOUT_SECONDS",
    "RUN_TIMEOUT_SECONDS",
    "ExecutionOutcome",
    "NodeResult",
    "execute_plan",
]

#: Per node, and for the run. Both generous enough that hitting one means
#: something is wrong rather than slow.
NODE_TIMEOUT_SECONDS = 30
RUN_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class NodeResult:
    """What one node did, whether or not it worked."""

    node_id: str
    tool: str
    version: str
    status: str  # SUCCEEDED | FAILED | SKIPPED
    output: BaseModel | None = None
    evidence: tuple[Evidence, ...] = ()
    error: dict[str, Any] | None = None
    duration_ms: int = 0

    @property
    def succeeded(self) -> bool:
        return self.status == "SUCCEEDED"


@dataclass
class ExecutionOutcome:
    """The whole run: what succeeded, what did not, and what is therefore missing."""

    results: list[NodeResult] = field(default_factory=list)
    #: Set when a *required* node failed. The run cannot continue.
    fatal: NodeResult | None = None

    @property
    def succeeded(self) -> tuple[NodeResult, ...]:
        return tuple(result for result in self.results if result.succeeded)

    @property
    def unavailable(self) -> tuple[NodeResult, ...]:
        """Nodes that produced nothing, and are to be reported as unavailable."""
        return tuple(result for result in self.results if not result.succeeded)

    @property
    def partial(self) -> bool:
        return bool(self.unavailable) and self.fatal is None

    def limitations(self) -> list[str]:
        """What this answer does not cover, said out loud (Invariant 6)."""
        return [
            f"{result.tool} did not run ({result.status.lower()}"
            + (f": {result.error['code']}" if result.error else "")
            + "); every metric it publishes is unavailable, not zero."
            for result in self.unavailable
        ]


async def execute_plan(
    plan: ExecutionPlan,
    *,
    registry: ToolRegistry,
    execution_id: UUID,
    log: EventLog,
    log_conn: AsyncConnection,
    node_timeout: int = NODE_TIMEOUT_SECONDS,
    run_timeout: int = RUN_TIMEOUT_SECONDS,
) -> ExecutionOutcome:
    """Run the DAG. Never raises for a tool failure -- that is an outcome, not an error."""
    outcome = ExecutionOutcome()
    produced: dict[str, BaseModel] = {}
    started = time.monotonic()

    for tier, layer in enumerate(plan.topological_layers()):
        runnable, skipped = _split(layer, outcome)
        for node in skipped:
            result = _skipped(node, outcome)
            outcome.results.append(result)
            await log.append(
                log_conn,
                "node.finished",
                {
                    "node": node.id,
                    "tool": node.tool,
                    "status": "SKIPPED",
                    "layer": tier,
                    # Which dead dependency cost this node. Without it a skipped
                    # node in the trace is an unexplained gap, and the reader is
                    # left to infer the edge that killed it from the shape.
                    "code": None if result.error is None else result.error["code"],
                    "blocked_by": (
                        [] if result.error is None else result.error["detail"]["blocked_by"]
                    ),
                },
            )

        if not runnable:
            continue
        if time.monotonic() - started > run_timeout:
            for node in runnable:
                outcome.results.append(_timed_out(node, "RUN_TIMEOUT"))
            break

        for node in runnable:
            await log.append(
                log_conn,
                "node.started",
                {
                    "node": node.id,
                    "tool": node.tool,
                    "version": node.version,
                    "depends_on": list(node.depends_on),
                    "required": node.required,
                    # Everything in one tier starts on the same event and runs
                    # at once. Saying which tier is what lets a watcher see the
                    # concurrency the plan exists to express, rather than four
                    # tools that happen to finish close together.
                    "layer": tier,
                },
            )
        # The layer runs at once. This is the concurrency the plan exists to
        # express: the four analyses share a dependency and nothing else.
        results = await asyncio.gather(
            *(
                _run_node(node, plan, registry, execution_id, produced, node_timeout)
                for node in runnable
            )
        )
        for result in results:
            outcome.results.append(result)
            if result.output is not None:
                produced[result.node_id] = result.output
            await _record(log_conn, execution_id, plan, result)
            await log.append(
                log_conn,
                "node.finished",
                {
                    "node": result.node_id,
                    "tool": result.tool,
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                    "layer": tier,
                    # What was computed, and deliberately never what it
                    # computed. These rows have not been verified -- that is the
                    # next stage -- and a trace carrying their values would put
                    # unverified figures on screen in the same typeface as
                    # verified ones, which is the thing Invariant 4 forbids at
                    # the end of a run and has no reason to permit in the middle
                    # of one. Names and a count are enough to watch the work
                    # happen; the numbers arrive once they have been checked.
                    "metrics": sorted({row.metric_id for row in result.evidence}),
                    "evidence_rows": len(result.evidence),
                    "code": None if result.error is None else result.error["code"],
                },
            )
            if not result.succeeded and _node(plan, result.node_id).required:
                outcome.fatal = result
                return outcome
    return outcome


# --------------------------------------------------------------------------


def _split(
    layer: Sequence[PlanNode], outcome: ExecutionOutcome
) -> tuple[list[PlanNode], list[PlanNode]]:
    """Nodes whose dependencies all succeeded, and those whose did not."""
    done = {result.node_id: result for result in outcome.results}
    runnable: list[PlanNode] = []
    skipped: list[PlanNode] = []
    for node in layer:
        blocked = [
            required
            for required in node.depends_on
            if required in done and not done[required].succeeded
        ]
        (skipped if blocked else runnable).append(node)
    return runnable, skipped


def _skipped(node: PlanNode, outcome: ExecutionOutcome) -> NodeResult:
    done = {result.node_id: result for result in outcome.results}
    blocking = sorted(
        required
        for required in node.depends_on
        if required in done and not done[required].succeeded
    )
    return NodeResult(
        node_id=node.id,
        tool=node.tool,
        version=node.version,
        status="SKIPPED",
        error={
            "code": "DEPENDENCY_UNAVAILABLE",
            "message": f"depends on {', '.join(blocking)}, which did not produce a result",
            "detail": {"blocked_by": blocking},
        },
    )


def _timed_out(node: PlanNode, code: str) -> NodeResult:
    return NodeResult(
        node_id=node.id,
        tool=node.tool,
        version=node.version,
        status="FAILED",
        error={"code": code, "message": "the run exceeded its time budget", "detail": {}},
    )


def _node(plan: ExecutionPlan, node_id: str) -> PlanNode:
    node = plan.node(node_id)
    assert node is not None  # the results only ever name nodes from this plan
    return node


async def _run_node(
    node: PlanNode,
    plan: ExecutionPlan,
    registry: ToolRegistry,
    execution_id: UUID,
    produced: Mapping[str, BaseModel],
    budget_seconds: int,
) -> NodeResult:
    """One tool call, on its own connection, inside its own budget."""
    started = time.monotonic()
    try:
        raw = _resolve_inputs(node, produced)
    except LookupError as error:
        return NodeResult(
            node_id=node.id,
            tool=node.tool,
            version=node.version,
            status="FAILED",
            error={"code": "UNRESOLVED_INPUT_REFERENCE", "message": str(error), "detail": {}},
            duration_ms=_elapsed(started),
        )

    try:
        async with asyncio.timeout(budget_seconds), connection() as conn:
            tool = registry.resolve(node.tool, node.version)
            ctx = ToolContext(
                merchant_id=plan.merchant_id,
                period=Period(**{"from": plan.period.from_, "to": plan.period.to}),
                execution_id=str(execution_id),
                conn=conn,
            )
            run = await tool.run(raw, ctx)
    except TimeoutError:
        return NodeResult(
            node_id=node.id,
            tool=node.tool,
            version=node.version,
            status="FAILED",
            error={
                "code": "TOOL_TIMEOUT",
                "message": f"{node.tool} did not finish in {budget_seconds}s",
                "detail": {},
            },
            duration_ms=_elapsed(started),
        )
    except ToolError as error:
        return NodeResult(
            node_id=node.id,
            tool=node.tool,
            version=node.version,
            status="FAILED",
            error={"code": error.code, "message": error.message, "detail": error.detail},
            duration_ms=_elapsed(started),
        )
    except VerificationError as error:
        # The tool's *own* invariants failed. Distinct from the trust layer's
        # verification, which runs later over every tool at once, and reported
        # separately so "this tool contradicted itself" is not confused with
        # "two tools disagreed".
        return NodeResult(
            node_id=node.id,
            tool=node.tool,
            version=node.version,
            status="FAILED",
            error={
                "code": "TOOL_SELF_VERIFICATION_FAILED",
                "message": str(error),
                "detail": {"failures": list(error.failures)},
            },
            duration_ms=_elapsed(started),
        )

    return NodeResult(
        node_id=node.id,
        tool=node.tool,
        version=node.version,
        status="SUCCEEDED",
        output=run.output,
        evidence=run.evidence,
        duration_ms=_elapsed(started),
    )


def _resolve_inputs(node: PlanNode, produced: Mapping[str, BaseModel]) -> dict[str, Any]:
    """Fill the referenced inputs from the outputs that already exist."""
    raw = dict(node.inputs)
    for name, reference in node.references.items():
        upstream = produced.get(reference.from_node)
        if upstream is None:
            raise LookupError(f"{node.id}.{name} reads from {reference}, which produced nothing")
        if not hasattr(upstream, reference.field):
            raise LookupError(f"{reference.from_node} has no field {reference.field!r}")
        raw[name] = getattr(upstream, reference.field)
    return raw


async def _record(
    conn: AsyncConnection, execution_id: UUID, plan: ExecutionPlan, result: NodeResult
) -> None:
    """One ``tool_executions`` row per node, written before the next layer starts."""
    node = _node(plan, result.node_id)
    await conn.execute(
        tool_executions.insert().values(
            id=uuid4(),
            execution_id=execution_id,
            tool_name=result.tool,
            tool_version=result.version,
            input_json=_jsonable(node.inputs),
            output_json=(None if result.output is None else result.output.model_dump(mode="json")),
            status=result.status,
            error_json=result.error,
            started_at=_now(),
            finished_at=_now(),
            duration_ms=result.duration_ms,
        )
    )


def _jsonable(inputs: Mapping[str, Any]) -> dict[str, Any]:
    from datetime import date, datetime

    def convert(value: Any) -> Any:
        if isinstance(value, datetime | date):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        return value

    return {key: convert(value) for key, value in inputs.items()}


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)


def _elapsed(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
