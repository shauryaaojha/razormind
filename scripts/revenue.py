"""The golden revenue bridge, end to end, through the tool contract.

Reconciles the analysis window first, then feeds that run into
``finance.revenue_analysis`` -- which is the real dependency order, not a
convenience: the run is what identifies the duplicated ledger row that must
come out of gross, and what bounds how much of the answer the bank confirmed.

Both tools run under one execution id, because they are one analysis.

Run: ``python scripts/task.py revenue``
"""

import asyncio
import sys
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from runtime.db import connection  # noqa: E402
from tools.base import Period, ToolContext  # noqa: E402
from tools.catalog import REGISTRY  # noqa: E402
from tools.finance.reconciliation import ReconciliationOutput  # noqa: E402
from tools.finance.revenue import RevenueAnalysisOutput  # noqa: E402

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


async def main() -> int:
    execution_id = f"cli-{uuid.uuid4().hex}"
    reconciliation = REGISTRY.resolve("finance.reconciliation")
    revenue = REGISTRY.resolve("finance.revenue_analysis")

    async with connection() as conn:
        reconciled = await reconciliation.run(
            {"merchant_id": MERCHANT, "period": {"from": CURRENT.from_, "to": CURRENT.to}},
            ToolContext(
                merchant_id=MERCHANT,
                period=CURRENT,
                execution_id=execution_id,
                conn=conn,
            ),
        )
        run_out = reconciled.output
        assert isinstance(run_out, ReconciliationOutput)

        analysed = await revenue.run(
            {
                "merchant_id": MERCHANT,
                "period": {"from": CURRENT.from_, "to": CURRENT.to},
                "comparison_period": {"from": PRIOR.from_, "to": PRIOR.to},
                "run_id": run_out.run_id,
            },
            ToolContext(
                merchant_id=MERCHANT,
                period=CURRENT,
                execution_id=execution_id,
                conn=conn,
                reconciliation_run_id=run_out.run_id,
            ),
        )

    out = analysed.output
    assert isinstance(out, RevenueAnalysisOutput)

    print(f"{'':<24}{'prior':>16}{'current':>16}")
    for label, attribute_name in (
        ("attempts", "attempt_count"),
        ("captures", "capture_count"),
    ):
        print(
            f"{label:<24}"
            f"{getattr(out.prior, attribute_name):>16}"
            f"{getattr(out.current, attribute_name):>16}"
        )
    print(
        f"{'success rate':<24}{out.prior.success_rate_ratio:>16}{out.current.success_rate_ratio:>16}"
    )
    for label, attribute_name in (
        ("attempted value", "attempted_value_paise"),
        ("gross payments", "gross_payments_paise"),
        ("refunds", "refunds_paise"),
        ("fees", "fees_paise"),
        ("chargebacks", "chargebacks_paise"),
        ("net revenue", "net_revenue_paise"),
    ):
        print(
            f"{label:<24}"
            f"{rupees(getattr(out.prior, attribute_name)):>16}"
            f"{rupees(getattr(out.current, attribute_name)):>16}"
        )

    print()
    print(
        f"net change         {rupees(out.net_revenue_change_paise)}  ({out.net_revenue_change_ratio})"
    )
    print("attribution")
    for term in out.attribution:
        share = term.share_of_change_ratio or "n/a"
        print(f"  {term.driver:<18} {rupees(term.effect_paise):>16}   {share:>10}")
    print(f"  {'rounding residual':<18} {out.rounding_residual_paise:>16} paise")
    print()
    print(
        f"unresolved         {rupees(out.unresolved_exception_value_paise)} "
        f"(+/- {out.confidence_band_ratio} of net revenue)"
    )
    print(f"checks passed      {len(analysed.verification.checks)}")
    print(f"evidence rows      {len(analysed.evidence)}")
    print("limitations")
    for limitation in out.limitations:
        print(f"  - {limitation}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
