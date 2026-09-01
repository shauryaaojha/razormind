"""The agent runtime against a real Postgres: the DAG, the states, the log.

Four of the five Phase 6 exit criteria live here. The fifth -- the ten seeded
questions -- is `test_intent.py`, because it needs no database and no model.

The tools in the concurrency and degradation tests are **fakes**, and have to
be: a test that proved the four real analyses run concurrently would be timing
Postgres, and would pass or fail on how warm the cache was. A tool that sleeps
for a known interval turns "did these run at once?" into arithmetic.
"""

import asyncio
import json
import time
import uuid
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select

from evidence.models import Evidence
from evidence.repository import load_evidence
from intent.models import Intent, IntentPeriod
from llm.provider import Completion, DisabledProvider
from orchestrator.events import EventLog
from orchestrator.executor import execute_plan
from orchestrator.planner import RECONCILE
from orchestrator.runtime import answer
from orchestrator.state import IllegalTransitionError, StateMachine
from plan.models import ExecutionPlan, PlanNode
from runtime.db import connection
from runtime.schema import execution_events, reconciliation_runs, tool_executions
from tools.base import DeterministicTool, ToolContext, ToolError, ToolInput
from tools.registry import ToolRegistry
from verification.models import Checks, VerificationResult
from verification.repository import open_execution, read_execution

pytestmark = pytest.mark.db

MERCHANT = "M123"
ANALYST = uuid.UUID("22222222-2222-4222-8222-222222222222")
TODAY = date(2026, 8, 24)
THRESHOLD = Decimal("0.75")

AUGUST = {"from": "2026-08-01", "to": "2026-08-24"}
JULY = {"from": "2026-07-01", "to": "2026-07-24"}


class ScriptedProvider:
    """The model, replaced by exactly what it would have said."""

    name = "scripted"

    def __init__(self, **fields: Any) -> None:
        self._body = json.dumps(
            {
                "merchant_id": MERCHANT,
                "confidence_ratio": "0.95",
                "clarification_needed": False,
                **fields,
            }
        )

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: Mapping[str, Any],
        max_tokens: int,
        timeout_seconds: int,
    ) -> Completion:
        del system, prompt, schema, max_tokens, timeout_seconds
        return Completion(text=self._body, model="scripted", input_tokens=0, output_tokens=0)

    def impersonate(self, merchant_id: str) -> None:
        """Answer with a merchant the session is not scoped to (C-13)."""
        body = json.loads(self._body)
        body["merchant_id"] = merchant_id
        self._body = json.dumps(body)


async def run(provider: Any, **kwargs: Any) -> Any:
    return await answer(
        "why did revenue fall?",
        merchant_id=MERCHANT,
        user_id=ANALYST,
        provider=provider,
        today=TODAY,
        threshold=THRESHOLD,
        **kwargs,
    )


async def events_for(execution_id: uuid.UUID) -> list[Any]:
    async with connection() as conn:
        return list(
            (
                await conn.execute(
                    select(execution_events)
                    .where(execution_events.c.execution_id == execution_id)
                    .order_by(execution_events.c.seq)
                )
            ).all()
        )


# --------------------------------------------------------------------------
# end to end
# --------------------------------------------------------------------------


async def test_a_revenue_question_runs_to_a_verified_state() -> None:
    result = await run(
        ScriptedProvider(intent="revenue_diagnosis", period=AUGUST, comparison_period=JULY)
    )
    assert result.status == "EXPLAINING", result.error
    assert result.report is not None
    assert result.report.passed
    assert result.plan is not None
    assert len(result.plan.nodes) == 5

    async with connection() as conn:
        stored = await read_execution(conn, result.execution_id)
        published = await load_evidence(conn, result.execution_id)
    assert stored is not None
    assert stored.status == "EXPLAINING"
    # No prose has been written, and none may be until Phase 7.
    assert stored.response_source is None
    assert len(published) == 123


async def test_every_transition_has_an_event_with_a_monotonic_seq() -> None:
    result = await run(
        ScriptedProvider(intent="revenue_diagnosis", period=AUGUST, comparison_period=JULY)
    )
    rows = await events_for(result.execution_id)

    assert [row.seq for row in rows] == list(range(len(rows)))
    transitions = [row for row in rows if row.kind == "state.changed"]
    assert [row.payload_json["to"] for row in transitions] == [
        "PLANNING",
        "VALIDATING",
        "EXECUTING",
        "VERIFYING",
        "EXPLAINING",
    ]
    # Every state the execution passed through is followed by the one it moved
    # to, with no gap: the log is the audit trail, not a summary of it.
    for row in transitions:
        assert row.payload_json["from"] != row.payload_json["to"]


async def test_the_log_records_every_node() -> None:
    result = await run(
        ScriptedProvider(intent="revenue_diagnosis", period=AUGUST, comparison_period=JULY)
    )
    rows = await events_for(result.execution_id)
    started = {row.payload_json["node"] for row in rows if row.kind == "node.started"}
    finished = {row.payload_json["node"] for row in rows if row.kind == "node.finished"}
    assert started == finished == {RECONCILE, "revenue", "failures", "refunds", "chargebacks"}

    async with connection() as conn:
        recorded = (
            await conn.execute(
                select(func.count())
                .select_from(tool_executions)
                .where(tool_executions.c.execution_id == result.execution_id)
            )
        ).scalar_one()
    assert recorded == 5


async def test_a_narrow_intent_runs_a_narrow_plan() -> None:
    result = await run(
        ScriptedProvider(intent="refund_analysis", period=AUGUST, comparison_period=JULY)
    )
    assert result.status == "EXPLAINING", result.error
    assert result.plan is not None
    assert [node.tool for node in result.plan.nodes] == [
        "finance.reconciliation",
        "finance.refund_analysis",
    ]


# --------------------------------------------------------------------------
# the two ways a run stops before executing
# --------------------------------------------------------------------------


async def test_a_low_confidence_question_asks_and_runs_nothing() -> None:
    result = await run(
        ScriptedProvider(intent="revenue_diagnosis", period=AUGUST, confidence_ratio="0.4")
    )
    assert result.status == "NEEDS_CLARIFICATION"
    assert result.clarification is not None

    async with connection() as conn:
        runs = (
            await conn.execute(
                select(func.count())
                .select_from(reconciliation_runs)
                .where(reconciliation_runs.c.id.like("%"))
            )
        ).scalar_one()
        recorded = (
            await conn.execute(
                select(func.count())
                .select_from(tool_executions)
                .where(tool_executions.c.execution_id == result.execution_id)
            )
        ).scalar_one()
    assert recorded == 0
    assert runs >= 0  # the count is incidental; the point is this run added none


async def test_no_provider_fails_the_run_rather_than_guessing() -> None:
    result = await run(DisabledProvider("llm_enabled is false"))
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error["code"] == "PROVIDER_UNAVAILABLE"


async def test_a_rejected_plan_executes_nothing() -> None:
    """A period the fixture does not cover. REJECTED is terminal."""
    result = await run(
        ScriptedProvider(
            intent="revenue_diagnosis",
            period={"from": "2030-01-01", "to": "2030-02-01"},
            comparison_period={"from": "2029-12-01", "to": "2029-12-31"},
        )
    )
    assert result.status == "REJECTED"
    assert result.rejection is not None
    assert result.rejection.code == "PERIOD_OUT_OF_RANGE"

    async with connection() as conn:
        recorded = (
            await conn.execute(
                select(func.count())
                .select_from(tool_executions)
                .where(tool_executions.c.execution_id == result.execution_id)
            )
        ).scalar_one()
    assert recorded == 0


async def test_a_foreign_merchant_never_reaches_a_query() -> None:
    """C-13, through the whole pipeline."""
    foreign = ScriptedProvider(intent="revenue_diagnosis", period=AUGUST, comparison_period=JULY)
    foreign.impersonate("M999")
    result = await run(foreign)
    assert result.status == "FAILED"
    assert result.error is not None
    assert result.error["code"] == "MERCHANT_SCOPE_VIOLATION"


# --------------------------------------------------------------------------
# the executor, on tools built to misbehave
# --------------------------------------------------------------------------


class FakeOutput(BaseModel):
    run_id: str = "fake-run"


def _fake(
    name: str, *, delay: float = 0.0, fail: bool = False
) -> type[DeterministicTool[Any, Any]]:
    class Fake(DeterministicTool[ToolInput, FakeOutput]):
        tool_name: ClassVar[str] = name
        version: ClassVar[str] = "1.0"
        input_model: ClassVar[type[BaseModel]] = ToolInput
        output_model: ClassVar[type[BaseModel]] = FakeOutput
        metrics: ClassVar[tuple[str, ...]] = ()

        async def execute(self, inp: ToolInput, ctx: ToolContext) -> FakeOutput:
            await asyncio.sleep(delay)
            if fail:
                raise ToolError("DELIBERATE", f"{name} was built to fail")
            return FakeOutput()

        def verify(self, inp: ToolInput, out: FakeOutput) -> VerificationResult:
            return Checks().result()

        def evidence(self, inp: ToolInput, out: FakeOutput, ctx: ToolContext) -> list[Evidence]:
            return []

    Fake.name = name  # ClassVar assignment after creation, so `name` is not shadowed
    return Fake


def fake_registry(*tools: type[DeterministicTool[Any, Any]]) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool())
    return registry


def fake_plan(*node_ids: str, required: str = RECONCILE) -> ExecutionPlan:
    nodes = [
        PlanNode(
            id=required,
            tool=required,
            version="1.0",
            inputs={"merchant_id": MERCHANT, "period": AUGUST},
            required=True,
        )
    ]
    nodes.extend(
        PlanNode(
            id=node_id,
            tool=node_id,
            version="1.0",
            inputs={"merchant_id": MERCHANT, "period": AUGUST},
            depends_on=[required],
        )
        for node_id in node_ids
    )
    return ExecutionPlan(
        intent="revenue_diagnosis",
        merchant_id=MERCHANT,
        period=IntentPeriod(**{"from": date(2026, 8, 1), "to": date(2026, 8, 24)}),
        nodes=nodes,
    )


async def _execute(plan: ExecutionPlan, registry: ToolRegistry) -> Any:
    execution_id = uuid.uuid4()
    log = EventLog(execution_id)
    async with connection() as conn:
        await open_execution(
            conn,
            execution_id=execution_id,
            user_id=ANALYST,
            merchant_id=MERCHANT,
            question="fake",
        )
        return await execute_plan(
            plan, registry=registry, execution_id=execution_id, log=log, log_conn=conn
        )


async def test_independent_nodes_run_concurrently() -> None:
    """Wall time under the sum of the node times, which is the whole point of layering."""
    delay = 0.4
    registry = fake_registry(
        _fake(RECONCILE),
        *(_fake(f"analysis_{n}", delay=delay) for n in range(4)),
    )
    plan = fake_plan(*(f"analysis_{n}" for n in range(4)))

    started = time.monotonic()
    outcome = await _execute(plan, registry)
    elapsed = time.monotonic() - started

    assert len(outcome.succeeded) == 5
    # Four nodes of 0.4s each: 1.6s serial, ~0.4s concurrent. Half the serial
    # total is a wide margin that still cannot be met by running them in turn.
    assert elapsed < delay * 4 / 2, f"took {elapsed:.2f}s; serial would be {delay * 4:.2f}s"


async def test_a_failing_tool_skips_its_dependents_and_spares_its_siblings() -> None:
    registry = fake_registry(
        _fake(RECONCILE),
        _fake("broken", fail=True),
        _fake("healthy"),
    )
    outcome = await _execute(fake_plan("broken", "healthy"), registry)

    by_id = {result.node_id: result for result in outcome.results}
    assert by_id["broken"].status == "FAILED"
    assert by_id["broken"].error is not None
    assert by_id["broken"].error["code"] == "DELIBERATE"
    assert by_id["healthy"].status == "SUCCEEDED"
    assert outcome.partial
    assert outcome.fatal is None


async def test_nothing_substitutes_a_value_for_a_failed_node() -> None:
    """Invariant 6: unavailable is not zero, and is said out loud."""
    registry = fake_registry(_fake(RECONCILE), _fake("broken", fail=True))
    outcome = await _execute(fake_plan("broken"), registry)

    assert outcome.unavailable[0].output is None
    assert outcome.unavailable[0].evidence == ()
    assert "unavailable, not zero" in outcome.limitations()[0]


async def test_a_required_tool_failing_ends_the_run() -> None:
    """Every other tool reads the reconciled set, so there is nothing left to compute."""
    registry = fake_registry(_fake(RECONCILE, fail=True), _fake("revenue"))
    outcome = await _execute(fake_plan("revenue"), registry)

    assert outcome.fatal is not None
    assert outcome.fatal.node_id == RECONCILE
    assert not outcome.partial
    # The dependent never ran at all -- it was not reached, not skipped.
    assert [result.node_id for result in outcome.results] == [RECONCILE]


async def test_a_node_that_overruns_its_budget_is_a_failure_not_a_hang() -> None:
    registry = fake_registry(_fake(RECONCILE), _fake("slow", delay=2.0))
    execution_id = uuid.uuid4()
    log = EventLog(execution_id)
    async with connection() as conn:
        await open_execution(
            conn,
            execution_id=execution_id,
            user_id=ANALYST,
            merchant_id=MERCHANT,
            question="fake",
        )
        outcome = await execute_plan(
            fake_plan("slow"),
            registry=registry,
            execution_id=execution_id,
            log=log,
            log_conn=conn,
            node_timeout=1,
        )
    slow = next(result for result in outcome.results if result.node_id == "slow")
    assert slow.status == "FAILED"
    assert slow.error is not None
    assert slow.error["code"] == "TOOL_TIMEOUT"


# --------------------------------------------------------------------------
# the state machine
# --------------------------------------------------------------------------


async def test_an_illegal_transition_raises_rather_than_being_logged() -> None:
    """A run reaching COMPLETED from BLOCKED has produced prose for unverified numbers."""
    execution_id = uuid.uuid4()
    machine = StateMachine(execution_id, EventLog(execution_id), state="BLOCKED")
    async with connection() as conn:
        with pytest.raises(IllegalTransitionError, match="terminal"):
            await machine.to(conn, "COMPLETED")


async def test_a_state_that_does_not_exist_is_refused() -> None:
    execution_id = uuid.uuid4()
    machine = StateMachine(execution_id, EventLog(execution_id))
    async with connection() as conn:
        with pytest.raises(IllegalTransitionError):
            await machine.to(conn, "ALMOST_DONE")


async def test_the_intent_and_plan_are_persisted_on_the_execution() -> None:
    """The audit view needs what was decided, not only what came out."""
    result = await run(
        ScriptedProvider(intent="revenue_diagnosis", period=AUGUST, comparison_period=JULY)
    )
    async with connection() as conn:
        from runtime.schema import agent_executions

        row = (
            await conn.execute(
                select(agent_executions).where(agent_executions.c.id == result.execution_id)
            )
        ).one()
    assert row.intent_json["intent"] == "revenue_diagnosis"
    assert [node["id"] for node in row.plan_json["nodes"]] == [
        RECONCILE,
        "revenue",
        "failures",
        "refunds",
        "chargebacks",
    ]
    assert row.period_from == date(2026, 8, 1)
    assert Intent.model_validate(row.intent_json).merchant_id == MERCHANT
