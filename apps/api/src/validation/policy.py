"""What the caller is allowed to ask for, and what the data can answer.

Separated from the checks themselves so the validator stays a pure function of
(plan, policy). A validator that reached for a database or a session would be
untestable in exactly the cases that matter -- eleven distinct rejections, each
of which has to be reachable on demand.

The dataset range is a *fact about the fixture*, read from it rather than
written down. A hard-coded range is a second copy of the seed's calendar, and
the day the two disagree the validator rejects a period that exists or admits
one that does not.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from plan.models import ROLE_RANK, Role
from runtime.calendar import ist_date
from runtime.schema import transactions

__all__ = ["Policy", "dataset_range", "load_policy"]

SUPPORTED_CURRENCY = "INR"


@dataclass(frozen=True)
class Policy:
    """The session, as far as the validator is concerned."""

    merchant_id: str
    role: Role
    dataset_from: date
    #: Exclusive, like every other period in this system.
    dataset_to: date
    currency: str = SUPPORTED_CURRENCY

    def permits(self, required_role: Role) -> bool:
        return ROLE_RANK[self.role] >= ROLE_RANK[required_role]

    def covers(self, period_from: date, period_to: date) -> bool:
        return self.dataset_from <= period_from and period_to <= self.dataset_to


async def dataset_range(conn: AsyncConnection, merchant_id: str) -> tuple[date, date]:
    """The window the merchant actually has records in, as IST dates.

    The upper bound is exclusive, so it is the day *after* the last attempt --
    a half-open period ending on the last attempt's own date would exclude it,
    and the validator would reject the one window the fixture is built around.
    """
    row = (
        await conn.execute(
            select(
                func.min(transactions.c.attempted_at),
                func.max(transactions.c.attempted_at),
            ).where(transactions.c.merchant_id == merchant_id)
        )
    ).one()
    earliest, latest = row[0], row[1]
    if earliest is None or latest is None:
        raise LookupError(f"merchant {merchant_id!r} has no transactions to bound a period with")
    last = ist_date(latest)
    return ist_date(earliest), date.fromordinal(last.toordinal() + 1)


async def load_policy(conn: AsyncConnection, merchant_id: str, role: Role) -> Policy:
    """The policy for this session, with the range read from the data."""
    earliest, latest = await dataset_range(conn, merchant_id)
    return Policy(merchant_id=merchant_id, role=role, dataset_from=earliest, dataset_to=latest)
