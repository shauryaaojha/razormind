"""Every v1 tool over the golden window, then the five verification layers.

This is `diagnose` with the trust layer switched on. The tools run exactly as
before; the difference is that nothing they published is believed until the
layers have re-derived it:

```text
1. TYPE        the outputs are the shape they declared
2. RANGE       every value is inside the range its metric declares
3. CONSISTENCY the quantities two tools share agree, exactly
4. FORMULA     every derived metric is re-evaluated from its own expression
5. SOURCE      every cited record exists, is inside the period, and re-folds
```

The execution is persisted either way. A pass writes the evidence and leaves the
run in `EXPLAINING` -- verified, and waiting for something to phrase it. A
failure writes `BLOCKED`, names the layer, and stores **no evidence at all**,
because serving the support for a number that failed verification is exactly
how an unverified figure reaches a reader with a citation attached.

Run: ``python scripts/task.py verify``
"""

import asyncio
import sys
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from evidence.builder import EvidenceSet  # noqa: E402
from provenance.builder import ProvenanceNode, source_records, walk  # noqa: E402
from runtime.db import connection  # noqa: E402
from tools.base import Period, ToolContext  # noqa: E402
from tools.catalog import REGISTRY  # noqa: E402
from tools.finance.reconciliation import ReconciliationOutput  # noqa: E402
from verification.repository import finish_execution, open_execution  # noqa: E402
from verification.sources import DatabaseSources  # noqa: E402
from verification.verifier import LAYERS, ToolOutcome, verify_execution  # noqa: E402

MERCHANT = "M123"
#: The seeded analyst. Phase 6 takes this from the authenticated caller.
ANALYST = uuid.UUID("22222222-2222-4222-8222-222222222222")
CURRENT = Period(**{"from": date(2026, 8, 1), "to": date(2026, 8, 24)})
PRIOR = Period(**{"from": date(2026, 7, 1), "to": date(2026, 7, 24)})

QUESTION = "Why did net revenue fall between July and August?"

TOOLS = (
    "finance.revenue_analysis",
    "payments.failure_analysis",
    "finance.refund_analysis",
    "risk.chargeback_analysis",
)

HEADLINE = "finance.revenue_analysis/1.0/net_revenue_change_ratio/2026-08-01_2026-08-24"


async def main() -> int:
    execution_id = uuid.uuid4()
    window = {"from": CURRENT.from_, "to": CURRENT.to}
    comparison = {"from": PRIOR.from_, "to": PRIOR.to}

    async with connection() as conn:
        await open_execution(
            conn,
            execution_id=execution_id,
            user_id=ANALYST,
            merchant_id=MERCHANT,
            period_from=CURRENT.from_,
            period_to=CURRENT.to,
            question=QUESTION,
        )

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
        for name in TOOLS:
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

        report = await verify_execution(outcomes, DatabaseSources(conn))
        rows = tuple(row for outcome in outcomes for row in outcome.evidence)
        status = await finish_execution(conn, execution_id, report, rows)

    print(f"execution   {execution_id}")
    print(f"tools       {len(outcomes)}")
    print(f"evidence    {len(rows)} rows")
    print()

    print("VERIFICATION")
    for name in LAYERS:
        result = next((layer for layer in report.layers if layer.layer == name), None)
        if result is None:
            print(f"  --   {name:<12} not reached")
            continue
        mark = "ok  " if result.passed else "FAIL"
        print(f"  {mark} {name:<12} {len(result.checks)} checks")
        for failure in result.failures[:10]:
            print(f"       {failure}")
    print()
    print(f"status      {status}")

    if not report.passed:
        return 1

    published = EvidenceSet(rows)
    node = walk(published, HEADLINE)
    records = source_records(node)
    print()
    print("PROVENANCE")
    _render(node)
    print()
    print(f"reaches {len(records)} source record(s), e.g. {', '.join(records[:6])}")
    return 0


def _render(node: ProvenanceNode, indent: int = 2) -> None:
    """The chain, as the drawer would show it."""
    pad = " " * indent
    slice_of = f" [{node.dimension_value}]" if node.dimension_value else ""
    print(f"{pad}{node.metric_id}{slice_of} = {node.value}  ({node.period_from})")
    print(f"{pad}  {node.detail}")
    if node.is_leaf:
        print(f"{pad}  -> {len(node.source_record_ids)} record(s)")
        return
    for operand in node.operands:
        if operand.node is None:
            print(f"{pad}  {operand.name} = {operand.value}  (literal)")
        else:
            _render(operand.node, indent + 4)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
