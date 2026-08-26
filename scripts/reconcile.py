"""Run a reconciliation against the database and persist it.

This orchestration sits in a script rather than in a package because it is the
one thing that spans planes: it loads records, reconciles, verifies, and only
then writes. Phase 3 moves it behind the `finance.reconciliation` tool
contract; until the tool base class exists, putting it in `reconciliation/`
would mean that package importing `verification/`, which the layer contract
forbids for good reason -- the engine must not be able to decide whether its
own output is trustworthy.

Run: ``python scripts/task.py reconcile``
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from sqlalchemy.ext.asyncio import AsyncConnection  # noqa: E402

from reconciliation.engine import reconcile  # noqa: E402
from reconciliation.models import ReconciliationResult  # noqa: E402
from reconciliation.repository import (  # noqa: E402
    load_bank_records,
    load_ledger_records,
    write_run,
)
from runtime.db import connection  # noqa: E402
from verification.rules import verify_run  # noqa: E402

#: The golden analysis window (docs/08-seed-data.md).
DEFAULT_MERCHANT = "M123"
DEFAULT_FROM = date(2026, 8, 1)
DEFAULT_TO = date(2026, 8, 24)


async def run_reconciliation(
    conn: AsyncConnection,
    merchant_id: str = DEFAULT_MERCHANT,
    period_from: date = DEFAULT_FROM,
    period_to: date = DEFAULT_TO,
) -> tuple[str, ReconciliationResult]:
    """Load, reconcile, verify, write -- in that order, and never out of it.

    Verification happens *before* the write. A run that fails its invariants
    must not exist in a form anything downstream can read: a half-reconciled
    period is worse than no reconciled period, because it looks like an answer.
    """
    ledger = await load_ledger_records(conn, merchant_id, period_from, period_to)
    bank = await load_bank_records(conn, merchant_id, period_from, period_to)

    result = reconcile(merchant_id, period_from, period_to, ledger, bank)
    verify_run(result, sum(record.amount_paise for record in ledger))

    run_id = await write_run(conn, result)
    return run_id, result


async def main() -> int:
    async with connection() as conn:
        run_id, result = await run_reconciliation(conn)

    print(f"run                {run_id}")
    print(f"period             {result.period_from} -> {result.period_to}")
    print(f"ledger / bank      {result.ledger_count} / {result.bank_count}")
    print(f"matched pairs      {result.matched_pairs}")
    print(f"  clean            {result.matched_clean}")
    print(f"  with exception   {result.matched_with_exception}")
    print(f"unmatched ledger   {result.unmatched_ledger}")
    print(f"unmatched bank     {result.unmatched_bank}")
    print(f"clean match rate   {result.clean_match_rate_ratio}")
    print(f"exceptions         {result.exception_count}")
    for category, count in result.breakdown().items():
        print(f"  {category:<20} {count}")
    print(f"unresolved         {result.unresolved_value_paise()} paise")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
