"""Run the golden window through the tool contract and print what it produced.

Phase 2 ran the engine from here directly, with a note that Phase 3 would move
it behind ``finance.reconciliation``. It has. What is left is a thin CLI: build
a context, call ``tool.run``, print. The ordering that matters -- validate,
scope, execute, verify, then evidence -- now lives in ``tools/base.py``, where
every tool gets it rather than every caller re-implementing it.

Run: ``python scripts/task.py reconcile``
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

#: The golden analysis window (docs/08-seed-data.md).
DEFAULT_MERCHANT = "M123"
DEFAULT_FROM = date(2026, 8, 1)
DEFAULT_TO = date(2026, 8, 24)


async def main() -> int:
    # A fresh execution id per invocation. The run id is a function of the
    # execution, not of the clock, so determinism is preserved -- and a second
    # CLI run is genuinely a second execution, which appends a new immutable
    # run rather than colliding with the first.
    execution_id = f"cli-{uuid.uuid4().hex}"
    tool = REGISTRY.resolve("finance.reconciliation")
    period = Period(**{"from": DEFAULT_FROM, "to": DEFAULT_TO})

    async with connection() as conn:
        run = await tool.run(
            {"merchant_id": DEFAULT_MERCHANT, "period": {"from": DEFAULT_FROM, "to": DEFAULT_TO}},
            ToolContext(
                merchant_id=DEFAULT_MERCHANT,
                period=period,
                execution_id=execution_id,
                conn=conn,
            ),
        )

    out = run.output
    assert isinstance(out, ReconciliationOutput)
    print(f"run                {out.run_id}")
    print(f"period             {out.period.from_} -> {out.period.to}")
    print(f"bank window        {out.bank_period.from_} -> {out.bank_period.to}")
    print(f"ledger / bank      {out.ledger_count} / {out.bank_count}")
    print(f"matched pairs      {out.matched_pairs_count}")
    print(f"  clean            {out.matched_clean_count}")
    print(f"  with exception   {out.matched_with_exception_count}")
    print(f"unmatched ledger   {out.unmatched_ledger_count}")
    print(f"unmatched bank     {out.unmatched_bank_count}")
    print(f"clean match rate   {out.clean_match_rate_ratio}")
    print(f"exceptions         {out.exception_count}")
    for category, count in out.exception_breakdown.items():
        print(f"  {category:<20} {count}")
    print(f"unresolved         {out.unresolved_exception_value_paise} paise")
    print(f"checks passed      {len(run.verification.checks)}")
    print(f"evidence rows      {len(run.evidence)}")
    for item in run.evidence:
        print(f"  {item.metric_id:<34} {item.value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
