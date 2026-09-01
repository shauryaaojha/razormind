"""One question in, one execution out. The pipeline, and nothing else.

```text
PENDING -> PLANNING   parse the question into an intent, or ask one back
        -> VALIDATING eleven gates; nothing has run yet
        -> EXECUTING  the DAG, concurrent within each layer
        -> VERIFYING  the five trust layers over everything published
        -> EXPLAINING verified; the numbers may now be phrased (Phase 7)
```

This module contains no domain logic at all, which is the test of whether the
phases before it did their jobs. It parses, plans, validates, executes,
verifies, and moves a state machine. It computes nothing, decides nothing about
money, and would not notice if a tool were replaced.

**Every exit is a state, and every state is a row.** `NEEDS_CLARIFICATION`,
`REJECTED`, `FAILED` and `BLOCKED` are answers -- each with a code, each
persisted, each carrying no prose. The only path to `COMPLETED` runs through
`EXPLAINING`, and reaching it means every published number survived
verification.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from intent.models import Clarification, Intent
from intent.parser import IntentParseError, parse_intent
from llm.provider import LLMProvider
from plan.models import ExecutionPlan, Role
from runtime.db import connection
from tools.catalog import REGISTRY
from tools.registry import ToolRegistry
from validation.plan_validator import Rejection, ValidationOutcome, validate_plan
from validation.policy import load_policy
from verification.repository import open_execution, record_verification
from verification.sources import DatabaseSources
from verification.verifier import ToolOutcome, VerificationReport, verify_execution

from .events import EventLog
from .executor import ExecutionOutcome, execute_plan
from .planner import PlanningError, build_plan
from .state import StateMachine

__all__ = ["AgentRun", "answer"]


@dataclass(frozen=True)
class AgentRun:
    """Everything an execution produced, whatever state it ended in."""

    execution_id: UUID
    status: str
    intent: Intent | None = None
    plan: ExecutionPlan | None = None
    clarification: Clarification | None = None
    rejection: Rejection | None = None
    outcome: ExecutionOutcome | None = None
    report: VerificationReport | None = None
    error: dict[str, Any] | None = None
    events: tuple[Any, ...] = ()

    @property
    def verified(self) -> bool:
        return self.status == "EXPLAINING"


async def answer(
    question: str,
    *,
    merchant_id: str,
    user_id: UUID,
    provider: LLMProvider,
    today: date,
    threshold: Decimal,
    role: Role = "ANALYST",
    registry: ToolRegistry = REGISTRY,
    execution_id: UUID | None = None,
) -> AgentRun:
    """Run one question all the way to a verified state, or to the state that stopped it."""
    identifier = execution_id or uuid4()
    log = EventLog(identifier)

    async with connection() as conn:
        await open_execution(
            conn,
            execution_id=identifier,
            user_id=user_id,
            merchant_id=merchant_id,
            question=question,
        )
        await log.append(conn, "execution.created", {"question": question})
        machine = StateMachine(identifier, log)

        # ---- PLANNING ------------------------------------------------------
        await machine.to(conn, "PLANNING")
        try:
            parsed = await parse_intent(
                question,
                provider=provider,
                merchant_id=merchant_id,
                today=today,
                threshold=threshold,
            )
        except IntentParseError as error:
            return await _fail(
                conn, machine, log, identifier, error.code, error.message, error.detail
            )

        if parsed.clarification is not None:
            await log.append(
                conn,
                "clarification.requested",
                {
                    "question": parsed.clarification.question,
                    "reason": parsed.clarification.reason,
                },
            )
            await machine.to(conn, "NEEDS_CLARIFICATION")
            return AgentRun(
                execution_id=identifier,
                status=machine.state,
                clarification=parsed.clarification,
                events=log.recorded,
            )

        intent = parsed.intent
        assert intent is not None  # a ParseOutcome carries exactly one of the two
        try:
            plan = build_plan(intent)
        except PlanningError as error:
            return await _fail(conn, machine, log, identifier, error.code, error.message, {})

        await log.append(
            conn,
            "plan.built",
            {"intent": plan.intent, "nodes": [node.id for node in plan.nodes]},
        )
        await machine.to(
            conn,
            "VALIDATING",
            intent_json=intent.model_dump(mode="json", by_alias=True),
            plan_json=plan.model_dump(mode="json", by_alias=True),
            period_from=plan.period.from_,
            period_to=plan.period.to,
        )

        # ---- VALIDATING ----------------------------------------------------
        policy = await load_policy(conn, merchant_id, role)
        validation = validate_plan(plan, policy, registry)
        if not validation.approved:
            return await _reject(conn, machine, log, identifier, intent, plan, validation)

    # ---- EXECUTING ---------------------------------------------------------
    # A fresh connection per stage: the tools open their own, and holding the
    # planning transaction open across a 120-second DAG would pin a pool slot
    # for the whole run.
    async with connection() as conn:
        await machine.to(conn, "EXECUTING")
        outcome = await execute_plan(
            plan, registry=registry, execution_id=identifier, log=log, log_conn=conn
        )
        if outcome.fatal is not None:
            # Reconciliation. Every other tool reads the reconciled set, so
            # there is nothing honest left to compute (D-32).
            return await _fail(
                conn,
                machine,
                log,
                identifier,
                "REQUIRED_TOOL_FAILED",
                f"{outcome.fatal.tool} is required and did not produce a result",
                {"node": outcome.fatal.node_id, "error": outcome.fatal.error},
                intent=intent,
                plan=plan,
                outcome=outcome,
            )
        if outcome.partial:
            await machine.to(
                conn, "PARTIAL", {"unavailable": [r.tool for r in outcome.unavailable]}
            )

    # ---- VERIFYING ---------------------------------------------------------
    async with connection() as conn:
        await machine.to(conn, "VERIFYING")
        outcomes = [
            ToolOutcome(
                tool_name=result.tool,
                tool_version=result.version,
                output=result.output,
                evidence=result.evidence,
            )
            for result in outcome.succeeded
            if result.output is not None
        ]
        report = await verify_execution(outcomes, DatabaseSources(conn))
        rows = tuple(row for tool in outcomes for row in tool.evidence)
        status, verdict = await record_verification(conn, identifier, report, rows)

        await log.append(
            conn,
            "verification.finished",
            {
                "passed": report.passed,
                "blocked_at": report.blocked_at,
                "checks": len(report.checks),
            },
        )
        await machine.to(conn, status, error_json=verdict)
        await log.append(conn, "execution.finished", {"status": machine.state})

    return AgentRun(
        execution_id=identifier,
        status=machine.state,
        intent=intent,
        plan=plan,
        outcome=outcome,
        report=report,
        error=verdict,
        events=log.recorded,
    )


# --------------------------------------------------------------------------


async def _fail(
    conn: Any,
    machine: StateMachine,
    log: EventLog,
    identifier: UUID,
    code: str,
    message: str,
    detail: dict[str, Any],
    **carried: Any,
) -> AgentRun:
    error = {"code": code, "message": message, "detail": detail}
    await machine.to(conn, "FAILED", error_json=error)
    await log.append(conn, "execution.finished", {"status": "FAILED", "code": code})
    return AgentRun(
        execution_id=identifier,
        status=machine.state,
        error=error,
        events=log.recorded,
        **carried,
    )


async def _reject(
    conn: Any,
    machine: StateMachine,
    log: EventLog,
    identifier: UUID,
    intent: Intent,
    plan: ExecutionPlan,
    validation: ValidationOutcome,
) -> AgentRun:
    """A structured rejection, and **nothing executed**."""
    rejection = validation.first
    assert rejection is not None  # the caller checked `approved`
    await log.append(
        conn, "plan.rejected", {"codes": list(validation.codes), "code": rejection.code}
    )
    await machine.to(conn, "REJECTED", error_json=rejection.as_error())
    await log.append(conn, "execution.finished", {"status": "REJECTED"})
    return AgentRun(
        execution_id=identifier,
        status=machine.state,
        intent=intent,
        plan=plan,
        rejection=rejection,
        error=rejection.as_error(),
        events=log.recorded,
    )
