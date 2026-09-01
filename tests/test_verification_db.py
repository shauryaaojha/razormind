"""The trust layer over the real fixture: the Phase 5 exit criteria.

Everything here runs the actual v1 tools against Postgres and then does one of
three things to the result: nothing, break a number, or break a citation. The
first must pass all five layers; the other two must be blocked, by the *named*
layer, with no evidence stored and no prose anywhere.

Mutating the published evidence rather than the tool is deliberate. A test that
patched `finance.revenue_analysis` to return a wrong figure would prove the
patch worked; what needs proving is that the verifier does not take a tool's
word for anything, including a tool whose own `verify()` passed.
"""

import uuid
from dataclasses import replace
from datetime import date

import httpx
import pytest
from sqlalchemy import func, select

from evidence.models import Evidence
from evidence.repository import load_evidence
from main import API_PREFIX, create_app
from provenance.builder import source_records, walk
from runtime.db import connection
from runtime.schema import evidence as evidence_table
from runtime.schema import transactions
from tools.base import Period, ToolContext
from tools.catalog import REGISTRY
from tools.finance.reconciliation import ReconciliationOutput
from verification.repository import finish_execution, open_execution, read_execution
from verification.sources import DatabaseSources, SourceRecord
from verification.verifier import LAYERS, ToolOutcome, verify_execution

pytestmark = pytest.mark.db

MERCHANT = "M123"
ANALYST = uuid.UUID("22222222-2222-4222-8222-222222222222")
CURRENT = Period(**{"from": date(2026, 8, 1), "to": date(2026, 8, 24)})
PRIOR = Period(**{"from": date(2026, 7, 1), "to": date(2026, 7, 24)})

ANALYSIS_TOOLS = (
    "finance.revenue_analysis",
    "payments.failure_analysis",
    "finance.refund_analysis",
    "risk.chargeback_analysis",
)

NET_CHANGE_RATIO = "finance.revenue_analysis/1.0/net_revenue_change_ratio/2026-08-01_2026-08-24"
GROSS = "finance.revenue_analysis/1.0/gross_payments_paise/2026-08-01_2026-08-24"
NET = "finance.revenue_analysis/1.0/net_revenue_paise/2026-08-01_2026-08-24"


@pytest.fixture
async def client() -> httpx.AsyncClient:  # type: ignore[misc]
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


async def run_every_tool(execution_id: uuid.UUID) -> list[ToolOutcome]:
    """Every v1 tool over the golden window, under one execution."""
    window = {"from": CURRENT.from_, "to": CURRENT.to}
    comparison = {"from": PRIOR.from_, "to": PRIOR.to}
    async with connection() as conn:
        ctx = ToolContext(
            merchant_id=MERCHANT,
            period=CURRENT,
            execution_id=str(execution_id),
            conn=conn,
        )
        reconciliation = REGISTRY.resolve("finance.reconciliation")
        reconciled = await reconciliation.run({"merchant_id": MERCHANT, "period": window}, ctx)
        run_out = reconciled.output
        assert isinstance(run_out, ReconciliationOutput)

        outcomes = [
            ToolOutcome(
                tool_name=reconciliation.name,
                tool_version=reconciliation.version,
                output=reconciled.output,
                evidence=reconciled.evidence,
            )
        ]
        request = {
            "merchant_id": MERCHANT,
            "period": window,
            "comparison_period": comparison,
            "run_id": run_out.run_id,
        }
        for name in ANALYSIS_TOOLS:
            tool = REGISTRY.resolve(name)
            run = await tool.run(request, ctx)
            outcomes.append(
                ToolOutcome(
                    tool_name=tool.name,
                    tool_version=tool.version,
                    output=run.output,
                    evidence=run.evidence,
                )
            )
    return outcomes


def rewrite(outcomes: list[ToolOutcome], evidence_id: str, **changes: object) -> list[ToolOutcome]:
    """Replace one published row, leaving everything else exactly as the tool built it."""
    rebuilt: list[ToolOutcome] = []
    for outcome in outcomes:
        rows = tuple(
            Evidence.model_construct(**{**row.__dict__, **changes})
            if row.id == evidence_id
            else row
            for row in outcome.evidence
        )
        rebuilt.append(replace(outcome, evidence=rows))
    return rebuilt


async def persist(outcomes: list[ToolOutcome], execution_id: uuid.UUID) -> str:
    async with connection() as conn:
        await open_execution(
            conn,
            execution_id=execution_id,
            user_id=ANALYST,
            merchant_id=MERCHANT,
            period_from=CURRENT.from_,
            period_to=CURRENT.to,
            question="Why did net revenue fall?",
        )
        report = await verify_execution(outcomes, DatabaseSources(conn))
        rows = tuple(row for outcome in outcomes for row in outcome.evidence)
        status = await finish_execution(conn, execution_id, report, rows)
    return status


# --------------------------------------------------------------------------
# the sound execution
# --------------------------------------------------------------------------


async def test_the_golden_execution_passes_all_five_layers() -> None:
    outcomes = await run_every_tool(uuid.uuid4())
    async with connection() as conn:
        report = await verify_execution(outcomes, DatabaseSources(conn))
    assert report.passed, report.failures
    assert [layer.layer for layer in report.layers] == list(LAYERS)
    assert report.status == "EXPLAINING"


async def test_every_layer_does_real_work_on_the_real_fixture() -> None:
    """A layer with no checks would pass on any input, including a broken one."""
    outcomes = await run_every_tool(uuid.uuid4())
    async with connection() as conn:
        report = await verify_execution(outcomes, DatabaseSources(conn))
    ran = {layer.layer: len(layer.checks) for layer in report.layers}
    assert all(count > 0 for count in ran.values()), ran
    # The consistency layer is the one with the fewest, and it must still be
    # comparing the three declared equivalences plus the shared ids.
    assert ran["CONSISTENCY"] >= 3


async def test_the_leaves_re_fold_from_the_records_themselves() -> None:
    """Layer 5 re-sums the column over the cited ids; nothing consults the tool."""
    outcomes = await run_every_tool(uuid.uuid4())
    async with connection() as conn:
        report = await verify_execution(outcomes, DatabaseSources(conn))
        source = report.layers[-1]
        gross = next(row for outcome in outcomes for row in outcome.evidence if row.id == GROSS)
        resolved = await DatabaseSources(conn).resolve(
            "transactions", "ATTEMPT_DATE", gross.source_record_ids
        )
    assert any("re_folds_from_its_records" in check for check in source.checks)
    assert sum(record.amount_paise for record in resolved.values()) == gross.value


# --------------------------------------------------------------------------
# layer 4: a number its own formula does not produce
# --------------------------------------------------------------------------


async def test_a_mutated_number_is_caught_by_layer_four() -> None:
    outcomes = await run_every_tool(uuid.uuid4())
    original = next(row for outcome in outcomes for row in outcome.evidence if row.id == NET)
    # One paise. Every operand still agrees with its cited row, the bridge's own
    # verify() already passed, and nothing but the re-evaluation notices.
    broken = rewrite(outcomes, NET, value=original.value + 1)
    async with connection() as conn:
        report = await verify_execution(broken, DatabaseSources(conn))
    assert report.blocked_at == "FORMULA"
    assert any("reproduces_its_own_formula" in failure for failure in report.failures)


async def test_layers_after_the_failure_do_not_run() -> None:
    outcomes = await run_every_tool(uuid.uuid4())
    original = next(row for outcome in outcomes for row in outcome.evidence if row.id == NET)
    broken = rewrite(outcomes, NET, value=original.value + 1)
    async with connection() as conn:
        report = await verify_execution(broken, DatabaseSources(conn))
    assert [layer.layer for layer in report.layers] == ["TYPE", "RANGE", "CONSISTENCY", "FORMULA"]


# --------------------------------------------------------------------------
# layer 5: a record outside the period
# --------------------------------------------------------------------------


async def test_a_record_outside_the_period_is_caught_by_layer_five() -> None:
    """A July capture cited by an August total. The number is unchanged."""
    outcomes = await run_every_tool(uuid.uuid4())
    gross = next(row for outcome in outcomes for row in outcome.evidence if row.id == GROSS)

    async with connection() as conn:
        stray = (
            await conn.execute(
                select(transactions.c.id)
                .where(
                    transactions.c.merchant_id == MERCHANT,
                    transactions.c.status == "CAPTURED",
                    transactions.c.attempted_at < date(2026, 7, 24),
                )
                .order_by(transactions.c.id)
                .limit(1)
            )
        ).one()
        broken = rewrite(
            outcomes,
            GROSS,
            source_record_ids=[*gross.source_record_ids, stray.id],
        )
        report = await verify_execution(broken, DatabaseSources(conn))

    assert report.blocked_at == "SOURCE"
    assert any("inside_the_period" in failure for failure in report.failures)
    assert any(stray.id in failure for failure in report.failures)


async def test_a_record_that_does_not_exist_is_caught_by_layer_five() -> None:
    outcomes = await run_every_tool(uuid.uuid4())
    gross = next(row for outcome in outcomes for row in outcome.evidence if row.id == GROSS)
    broken = rewrite(
        outcomes, GROSS, source_record_ids=[*gross.source_record_ids, "TXN_DOES_NOT_EXIST"]
    )
    async with connection() as conn:
        report = await verify_execution(broken, DatabaseSources(conn))
    assert report.blocked_at == "SOURCE"
    assert any("cited_records_exist" in failure for failure in report.failures)


async def test_the_anchor_is_the_scoping_the_tool_declared() -> None:
    """A refund raised after the window still belongs to its parent's window (D-31)."""
    async with connection() as conn:
        outcomes = await run_every_tool(uuid.uuid4())
        refunds_row = next(
            row
            for outcome in outcomes
            for row in outcome.evidence
            if row.metric_id == "refunds_paise" and row.period_from == "2026-08-01"
        )
        resolved = await DatabaseSources(conn).resolve(
            "refunds", "PARENT_ATTEMPT_DATE", refunds_row.source_record_ids
        )
    assert resolved
    assert all(
        isinstance(record, SourceRecord) and date(2026, 8, 1) <= record.anchor < date(2026, 8, 24)
        for record in resolved.values()
    )


# --------------------------------------------------------------------------
# BLOCKED, and what it means for what is stored and served
# --------------------------------------------------------------------------


async def test_a_verified_execution_stores_its_evidence() -> None:
    execution_id = uuid.uuid4()
    outcomes = await run_every_tool(execution_id)
    status = await persist(outcomes, execution_id)
    assert status == "EXPLAINING"

    async with connection() as conn:
        stored = await load_evidence(conn, execution_id)
        published = sum(len(outcome.evidence) for outcome in outcomes)
    assert len(stored) == published
    assert stored.get(NET_CHANGE_RATIO) is not None


async def test_a_blocked_execution_stores_no_evidence_and_no_prose() -> None:
    """Invariant 4: verification failure blocks explanation entirely."""
    execution_id = uuid.uuid4()
    outcomes = await run_every_tool(execution_id)
    original = next(row for outcome in outcomes for row in outcome.evidence if row.id == NET)
    status = await persist(rewrite(outcomes, NET, value=original.value + 1), execution_id)
    assert status == "BLOCKED"

    async with connection() as conn:
        stored = await read_execution(conn, execution_id)
        rows = (
            await conn.execute(
                select(func.count())
                .select_from(evidence_table)
                .where(evidence_table.c.execution_id == execution_id)
            )
        ).scalar_one()
    assert stored is not None
    assert stored.blocked
    assert stored.response_source is None
    assert rows == 0
    assert stored.error is not None
    assert stored.error["detail"]["blocked_at"] == "FORMULA"


# --------------------------------------------------------------------------
# provenance, and the endpoint that serves it
# --------------------------------------------------------------------------


async def test_provenance_from_the_headline_reaches_real_transaction_ids() -> None:
    execution_id = uuid.uuid4()
    outcomes = await run_every_tool(execution_id)
    await persist(outcomes, execution_id)

    async with connection() as conn:
        published = await load_evidence(conn, execution_id)
        node = walk(published, NET_CHANGE_RATIO)
        reached = source_records(node)
        transaction_ids = [record for record in reached if record.startswith("TXN_")]
        existing = (
            await conn.execute(
                select(func.count())
                .select_from(transactions)
                .where(transactions.c.id.in_(transaction_ids))
            )
        ).scalar_one()

    assert node.metric_id == "net_revenue_change_ratio"
    assert node.detail == "(current - prior) / prior"
    # Both windows' net revenue, each decomposed into four leaves.
    assert len(reached) > 500
    assert transaction_ids
    assert existing == len(transaction_ids)


async def test_the_endpoint_serves_the_row_and_its_chain(client: httpx.AsyncClient) -> None:
    execution_id = uuid.uuid4()
    outcomes = await run_every_tool(execution_id)
    await persist(outcomes, execution_id)

    response = await client.get(
        f"{API_PREFIX}/executions/{execution_id}/evidence/{NET_CHANGE_RATIO}"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["metric_id"] == "net_revenue_change_ratio"
    # A ratio goes over the wire as a string, or JSON's float would eat it.
    assert body["value"] == "-0.175956"
    assert body["provenance"]["detail"] == "(current - prior) / prior"
    assert [operand["name"] for operand in body["provenance"]["operands"]] == ["current", "prior"]
    assert body["source_record_ids"]


async def test_a_dimensioned_row_is_addressable_in_a_url(client: httpx.AsyncClient) -> None:
    """The slice separator is `~`, so it survives the path (D-42)."""
    execution_id = uuid.uuid4()
    outcomes = await run_every_tool(execution_id)
    await persist(outcomes, execution_id)

    rail = "payments.failure_analysis/1.0/by_method.success_rate_ratio/2026-08-01_2026-08-24~UPI"
    response = await client.get(f"{API_PREFIX}/executions/{execution_id}/evidence/{rail}")
    assert response.status_code == 200
    body = response.json()
    assert body["dimension_value"] == "UPI"
    assert body["metric_id"] == "by_method.success_rate_ratio"


async def test_a_blocked_execution_serves_no_evidence(client: httpx.AsyncClient) -> None:
    execution_id = uuid.uuid4()
    outcomes = await run_every_tool(execution_id)
    original = next(row for outcome in outcomes for row in outcome.evidence if row.id == NET)
    await persist(rewrite(outcomes, NET, value=original.value + 1), execution_id)

    response = await client.get(
        f"{API_PREFIX}/executions/{execution_id}/evidence/{NET_CHANGE_RATIO}"
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"]["code"] == "EXECUTION_BLOCKED"

    summary = await client.get(f"{API_PREFIX}/executions/{execution_id}")
    assert summary.status_code == 200
    assert summary.json()["status"] == "BLOCKED"
    assert summary.json()["response_source"] is None


async def test_an_unknown_execution_is_a_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{API_PREFIX}/executions/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "EXECUTION_NOT_FOUND"
