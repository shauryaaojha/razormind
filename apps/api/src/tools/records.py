"""The records every analysis tool reads, and the one rule that scopes them.

Four tools now compute totals over the same window. If each scoped its own
records, "gross payments" and "succeeded value" would agree only by luck, and
the cross-tool consistency check would be testing whether two copies of the
same code had drifted rather than whether the numbers are right. So the scoping
lives here, once, and everything above calls it.

Two rules, and both were checked against the generated fixture before they were
written down:

* **A payment belongs to the window it was attempted in**, not captured in.
  Scoping by capture date silently drops every failure -- a failure has no
  capture instant -- and every success rate then reads 100%.
* **A refund or chargeback belongs to the window of the payment it reverses**,
  not the window it was raised in. Scoping this fixture's refunds by their own
  ``created_at`` moves one of eighteen into the wrong window
  ([D-31](../../../../docs/decisions.md)).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from runtime.calendar import ist_date
from runtime.money import Paise

__all__ = [
    "MovementRecord",
    "PaymentRecord",
    "movements_for",
    "scope_attempts",
]


@dataclass(frozen=True, order=True)
class PaymentRecord:
    """One payment attempt, successful or not."""

    id: str
    method: str
    instrument: str
    status: str
    decline_type: str | None
    amount_paise: Paise
    fee_paise: Paise
    attempted_at: datetime
    captured_at: datetime | None

    @property
    def captured(self) -> bool:
        return self.status == "CAPTURED"


@dataclass(frozen=True, order=True)
class MovementRecord:
    """A refund or a chargeback, tied to the payment it reverses."""

    id: str
    transaction_id: str
    amount_paise: Paise
    reason: str


def scope_attempts(
    period_from: date,
    period_to: date,
    payments: Iterable[PaymentRecord],
    excluded_transaction_ids: frozenset[str] = frozenset(),
) -> list[PaymentRecord]:
    """Every attempt in the half-open IST window, in id order.

    Sorted rather than left in the caller's order: a query without a stable
    ``ORDER BY`` must not be able to change a total, and sorting here means the
    two layers agree rather than one silently compensating for the other.

    ``excluded_transaction_ids`` is the reconciliation run's set of ledger rows
    flagged ``POSSIBLE_DUPLICATE``. A duplicated capture lifts the ledger count
    and is not revenue, which is why a reconciliation run is an *input* to
    these tools rather than a report published alongside them
    ([D-32](../../../../docs/decisions.md)).
    """
    return sorted(
        record
        for record in payments
        if record.id not in excluded_transaction_ids
        and period_from <= ist_date(record.attempted_at) < period_to
    )


def movements_for(
    movements: Iterable[MovementRecord], transaction_ids: Iterable[str]
) -> list[MovementRecord]:
    """Refunds or chargebacks whose parent payment is in the given set."""
    parents = set(transaction_ids)
    return sorted(movement for movement in movements if movement.transaction_id in parents)
