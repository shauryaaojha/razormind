"""Refunds and chargebacks: the same shape, twice. Pure, no database.

``finance.refund_analysis`` and ``risk.chargeback_analysis`` answer the same
three questions about different tables -- how much, at what rate against gross,
and how did that move. Writing the arithmetic twice would guarantee that
``refund_value_paise`` and the bridge's ``refunds_paise`` eventually disagree
in some edge the two copies handle differently, which is exactly the class of
defect the cross-tool consistency check exists to catch and a poor reason to
give it something to find.

The rate is a **value** rate: movement value over gross payments. The card
networks' chargeback threshold is a *count* ratio, which is a different
quantity; it is deliberately not published under the same name, because a
"chargeback rate" that is sometimes a count ratio and sometimes a value ratio
is precisely the ambiguity C-04 exists to remove.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from runtime.money import Paise, ratio

from .records import MovementRecord, PaymentRecord, movements_for, scope_attempts

__all__ = ["MovementWindow", "ReasonSlice", "build_movement_window"]


@dataclass(frozen=True)
class ReasonSlice:
    """One reason, and what it accounts for."""

    reason: str
    count: int
    value_paise: Paise
    movement_ids: tuple[str, ...]


@dataclass(frozen=True)
class MovementWindow:
    """One period of refunds or chargebacks, against the gross they reverse."""

    period_from: date
    period_to: date

    count: int
    value_paise: Paise
    #: The denominator, computed here rather than taken on trust, so the rate
    #: and the value it is a rate *of* come from one scoping of one record set.
    gross_payments_paise: Paise

    by_reason: tuple[ReasonSlice, ...]
    movement_ids: tuple[str, ...]
    capture_ids: tuple[str, ...]

    @property
    def rate_ratio(self) -> Decimal:
        """Movement value over gross payments.

        A window with no captured payments raises rather than reporting zero:
        "nothing was refunded" and "there was nothing to refund" are different
        facts, and a zero would render them identically (Invariant 6).
        """
        return ratio(self.value_paise, self.gross_payments_paise)


def build_movement_window(
    period_from: date,
    period_to: date,
    payments: Iterable[PaymentRecord],
    movements: Iterable[MovementRecord],
    excluded_transaction_ids: frozenset[str] = frozenset(),
) -> MovementWindow:
    """Scope the payments, then the movements that reverse them."""
    captures = [
        record
        for record in scope_attempts(period_from, period_to, payments, excluded_transaction_ids)
        if record.captured
    ]
    capture_ids = [record.id for record in captures]
    scoped = movements_for(movements, capture_ids)

    reasons = tuple(
        ReasonSlice(
            reason=reason,
            count=len(group),
            value_paise=sum(movement.amount_paise for movement in group),
            movement_ids=tuple(movement.id for movement in group),
        )
        for reason, group in (
            (reason, [movement for movement in scoped if movement.reason == reason])
            for reason in sorted({movement.reason for movement in scoped})
        )
    )

    return MovementWindow(
        period_from=period_from,
        period_to=period_to,
        count=len(scoped),
        value_paise=sum(movement.amount_paise for movement in scoped),
        gross_payments_paise=sum(record.amount_paise for record in captures),
        by_reason=reasons,
        movement_ids=tuple(movement.id for movement in scoped),
        capture_ids=tuple(capture_ids),
    )
