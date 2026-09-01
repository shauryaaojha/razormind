"""Every v1 tool over the golden window, and the agreements between them.

This is the deterministic half of the demo: the numbers an explainer would be
allowed to phrase, with nothing generated and nothing inferred. It runs all
five tools under one execution id, prints what each published, and then checks
the cross-tool equivalences the vocabulary declares -- because two tools
computing the same quantity and disagreeing is a defect that only shows up when
something puts them side by side.

Run: ``python scripts/task.py diagnose``
"""

import asyncio
import sys
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from evidence.vocabulary import EQUIVALENCES  # noqa: E402
from runtime.db import connection  # noqa: E402
from tools.base import Period, ToolContext  # noqa: E402
from tools.catalog import REGISTRY  # noqa: E402
from tools.finance.reconciliation import ReconciliationOutput  # noqa: E402
from tools.finance.refunds import RefundAnalysisOutput  # noqa: E402
from tools.finance.revenue import RevenueAnalysisOutput  # noqa: E402
from tools.payments.failure import FailureAnalysisOutput  # noqa: E402
from tools.risk.chargebacks import ChargebackAnalysisOutput  # noqa: E402

MERCHANT = "M123"
CURRENT = Period(**{"from": date(2026, 8, 1), "to": date(2026, 8, 24)})
PRIOR = Period(**{"from": date(2026, 7, 1), "to": date(2026, 7, 24)})


def rupees(paise: int) -> str:
    """Indian digit grouping: lakh and crore, not thousands."""
    sign = "-" if paise < 0 else ""
    whole, fraction = divmod(abs(paise), 100)
    text = str(whole)
    if len(text) > 3:
        head, tail = text[:-3], text[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        text = ",".join([*groups, tail])
    return f"{sign}Rs {text}.{fraction:02d}"


def percent(ratio_text: str) -> str:
    return f"{float(ratio_text) * 100:.2f}%"


async def main() -> int:
    execution_id = f"cli-{uuid.uuid4().hex}"
    window = {"from": CURRENT.from_, "to": CURRENT.to}
    comparison = {"from": PRIOR.from_, "to": PRIOR.to}

    async with connection() as conn:
        ctx = ToolContext(
            merchant_id=MERCHANT, period=CURRENT, execution_id=execution_id, conn=conn
        )
        reconciled = await REGISTRY.resolve("finance.reconciliation").run(
            {"merchant_id": MERCHANT, "period": window}, ctx
        )
        run_out = reconciled.output
        assert isinstance(run_out, ReconciliationOutput)

        request = {
            "merchant_id": MERCHANT,
            "period": window,
            "comparison_period": comparison,
            "run_id": run_out.run_id,
        }
        revenue = await REGISTRY.resolve("finance.revenue_analysis").run(request, ctx)
        failure = await REGISTRY.resolve("payments.failure_analysis").run(request, ctx)
        refunds = await REGISTRY.resolve("finance.refund_analysis").run(request, ctx)
        chargebacks = await REGISTRY.resolve("risk.chargeback_analysis").run(request, ctx)

    money = revenue.output
    rates = failure.output
    returns = refunds.output
    disputes = chargebacks.output
    assert isinstance(money, RevenueAnalysisOutput)
    assert isinstance(rates, FailureAnalysisOutput)
    assert isinstance(returns, RefundAnalysisOutput)
    assert isinstance(disputes, ChargebackAnalysisOutput)

    print(f"run                {run_out.run_id}")
    print(f"clean match rate   {percent(run_out.clean_match_rate_ratio)}")
    print()

    print("revenue".upper())
    print(f"{'':<22}{'prior':>16}{'current':>16}")
    for label, field in (
        ("gross payments", "gross_payments_paise"),
        ("refunds", "refunds_paise"),
        ("fees", "fees_paise"),
        ("chargebacks", "chargebacks_paise"),
        ("net revenue", "net_revenue_paise"),
    ):
        print(
            f"{label:<22}"
            f"{rupees(getattr(money.prior, field)):>16}"
            f"{rupees(getattr(money.current, field)):>16}"
        )
    print(
        f"{'net change':<22}{rupees(money.net_revenue_change_paise):>16}"
        f"  ({money.net_revenue_change_ratio})"
    )
    for term in money.attribution:
        print(f"  {term.driver:<20}{rupees(term.effect_paise):>16}")
    print(f"  {'rounding residual':<20}{money.rounding_residual_paise:>16} paise")
    print()

    print("success rates".upper())
    print(f"{'':<22}{'prior':>12}{'current':>12}{'change':>10}")
    print(
        f"{'blended':<22}"
        f"{percent(rates.prior.success_rate_ratio):>12}"
        f"{percent(rates.current.success_rate_ratio):>12}"
        f"{rates.success_rate_pp_change + ' pp':>10}"
    )
    prior_rails = {entry.method: entry for entry in rates.prior_by_method}
    for entry in rates.by_method:
        before = prior_rails.get(entry.method)
        print(
            f"  {entry.method:<20}"
            f"{percent(before.success_rate_ratio) if before else 'n/a':>12}"
            f"{percent(entry.success_rate_ratio):>12}"
            f"{(entry.success_rate_pp_change or 'n/a') + ' pp':>10}"
        )
    print(
        f"{'technical declines':<22}"
        f"{percent(rates.prior.technical_decline_ratio):>12}"
        f"{percent(rates.current.technical_decline_ratio):>12}"
        f"{rates.technical_decline_pp_change + ' pp':>10}"
    )
    print(
        f"{'business declines':<22}"
        f"{percent(rates.prior.business_decline_ratio):>12}"
        f"{percent(rates.current.business_decline_ratio):>12}"
        f"{rates.business_decline_pp_change + ' pp':>10}"
    )
    print()

    for title, output, change in (
        ("refunds", returns, returns.refund_value_change_paise),
        ("chargebacks", disputes, disputes.chargeback_value_change_paise),
    ):
        print(title.upper())
        print(
            f"{'value':<22}{rupees(output.prior.value_paise):>16}"
            f"{rupees(output.current.value_paise):>16}"
        )
        print(
            f"{'rate of gross':<22}{percent(output.prior.rate_ratio):>16}"
            f"{percent(output.current.rate_ratio):>16}"
        )
        print(f"{'change':<22}{rupees(change):>16}")
        for reason in output.current.by_reason:
            print(f"  {reason.reason:<20}{rupees(reason.value_paise):>16}  ({reason.count})")
        print()

    # ---- the checks nothing else would run ----
    published: dict[tuple[str, str], set[object]] = {}
    for row in (
        *reconciled.evidence,
        *revenue.evidence,
        *failure.evidence,
        *refunds.evidence,
        *chargebacks.evidence,
    ):
        published.setdefault((row.metric_id, row.period_from), set()).add(row.value)

    print("CROSS-TOOL CONSISTENCY")
    period = CURRENT.from_.isoformat()
    failures = 0
    for left, right in EQUIVALENCES:
        left_values = published.get((left, period), set())
        right_values = published.get((right, period), set())
        agree = bool(left_values) and left_values == right_values
        failures += 0 if agree else 1
        marker = "ok " if agree else "FAIL"
        print(f"  {marker} {left} == {right}   {left_values or '-'} / {right_values or '-'}")

    checks = sum(
        len(run.verification.checks) for run in (reconciled, revenue, failure, refunds, chargebacks)
    )
    evidence = sum(
        len(run.evidence) for run in (reconciled, revenue, failure, refunds, chargebacks)
    )
    print()
    print(f"checks passed      {checks}")
    print(f"evidence rows      {evidence}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
