"""The revenue bridge and its rate/volume attribution. Pure, no database.

Kept separate from the tool for the same reason ``reconciliation/engine.py`` is
separate from its repository: the arithmetic that has to close to the paise is
testable on hand-built records, and a bug in it should not need a live Postgres
to reproduce.

Two rules decide what belongs to a window, and both matter:

* **A payment belongs to the window it was attempted in**, not captured in.
  Scoping by capture date silently drops every failure -- a failure has no
  capture instant -- and every success rate then reads 100%.
* **A refund or chargeback belongs to the window of the payment it reverses**,
  not the window it was raised in. A refund raised on 26 August against an
  August payment is August's; netting it into September would compare one
  cohort's gross against another cohort's returns. Scoping refunds by their own
  ``created_at`` would have moved one of this fixture's eighteen refunds into
  the wrong window.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from runtime.calendar import ist_date
from runtime.money import Paise, apply_ratio, ratio

__all__ = [
    "DRIVERS",
    "Attribution",
    "Effect",
    "MovementRecord",
    "PaymentRecord",
    "RevenueWindow",
    "attribute",
    "build_window",
]

#: Attribution drivers, in the order the bridge reports them. Volume first
#: because it is the largest term in the golden scenario, and the table should
#: read top-down like the explanation.
DRIVERS = ("ATTEMPT_VOLUME", "SUCCESS_RATE", "REFUNDS", "FEES", "CHARGEBACKS")


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


@dataclass(frozen=True)
class RevenueWindow:
    """One period's bridge, plus the records supporting every line of it."""

    period_from: date
    period_to: date

    attempt_count: int
    capture_count: int
    attempted_value_paise: Paise
    gross_payments_paise: Paise
    refunds_paise: Paise
    fees_paise: Paise
    chargebacks_paise: Paise

    attempt_ids: tuple[str, ...]
    capture_ids: tuple[str, ...]
    refund_ids: tuple[str, ...]
    chargeback_ids: tuple[str, ...]

    @property
    def net_revenue_paise(self) -> Paise:
        """The bridge identity, and the only place it is computed."""
        return (
            self.gross_payments_paise
            - self.refunds_paise
            - self.fees_paise
            - self.chargebacks_paise
        )

    @property
    def success_rate_ratio(self) -> Decimal:
        return ratio(self.capture_count, self.attempt_count)


@dataclass(frozen=True)
class Effect:
    """One driver's contribution to the change in net revenue."""

    driver: str
    effect_paise: Paise


@dataclass(frozen=True)
class Attribution:
    """The change in net revenue, decomposed so that it closes."""

    net_change_paise: Paise
    net_change_ratio: Decimal
    effects: tuple[Effect, ...]
    rounding_residual_paise: Paise

    @property
    def term_count(self) -> int:
        return len(self.effects)


def build_window(
    period_from: date,
    period_to: date,
    payments: Iterable[PaymentRecord],
    refunds: Iterable[MovementRecord],
    chargebacks: Iterable[MovementRecord],
    excluded_transaction_ids: frozenset[str] = frozenset(),
) -> RevenueWindow:
    """Scope, then total. A function of the records, not of the caller's order.

    ``excluded_transaction_ids`` is the reconciliation run's set of ledger rows
    flagged ``POSSIBLE_DUPLICATE``. A duplicate lifts the ledger count and is
    not revenue; excluding it here is why a reconciliation run is an *input* to
    this analysis rather than a report published alongside it.
    """
    attempts = sorted(
        record
        for record in payments
        if record.id not in excluded_transaction_ids
        and period_from <= ist_date(record.attempted_at) < period_to
    )
    captures = [record for record in attempts if record.captured]
    captured_ids = {record.id for record in captures}

    window_refunds = _movements_for(refunds, captured_ids)
    window_chargebacks = _movements_for(chargebacks, captured_ids)

    return RevenueWindow(
        period_from=period_from,
        period_to=period_to,
        attempt_count=len(attempts),
        capture_count=len(captures),
        attempted_value_paise=sum(record.amount_paise for record in attempts),
        gross_payments_paise=sum(record.amount_paise for record in captures),
        refunds_paise=sum(movement.amount_paise for movement in window_refunds),
        fees_paise=sum(record.fee_paise for record in captures),
        chargebacks_paise=sum(movement.amount_paise for movement in window_chargebacks),
        attempt_ids=tuple(record.id for record in attempts),
        capture_ids=tuple(record.id for record in captures),
        refund_ids=tuple(movement.id for movement in window_refunds),
        chargeback_ids=tuple(movement.id for movement in window_chargebacks),
    )


def _movements_for(
    movements: Iterable[MovementRecord], transaction_ids: set[str]
) -> Sequence[MovementRecord]:
    return sorted(movement for movement in movements if movement.transaction_id in transaction_ids)


def attribute(prior: RevenueWindow, current: RevenueWindow) -> Attribution:
    """Decompose the change in net revenue into five drivers plus a residual.

    The gross change splits the standard way, with ``rate = gross / attempted``:

    ``volume = rate_prior * (attempted_current - attempted_prior)``
    ``rate   = attempted_current * (rate_current - rate_prior)``

    The two are computed as *one* rounding and its exact remainder rather than
    as two independent roundings. Rounding both is how a bridge stops closing,
    and C-02's stated causes summed to 51% of the decline they claimed.

    Refunds, fees and chargebacks enter as **deltas**, negated -- an increase in
    fees is a decrease in revenue. Entering them as gross values was the second
    of C-02's three errors.

    Unresolved reconciliation exceptions are deliberately **not** a term. They
    are a confidence band on the whole bridge, not a driver of it; folding them
    in was the third error.
    """
    volume_effect = apply_ratio(
        current.attempted_value_paise - prior.attempted_value_paise,
        prior.gross_payments_paise,
        prior.attempted_value_paise,
    )
    rate_effect = (current.gross_payments_paise - prior.gross_payments_paise) - volume_effect

    effects = (
        Effect("ATTEMPT_VOLUME", volume_effect),
        Effect("SUCCESS_RATE", rate_effect),
        Effect("REFUNDS", prior.refunds_paise - current.refunds_paise),
        Effect("FEES", prior.fees_paise - current.fees_paise),
        Effect("CHARGEBACKS", prior.chargebacks_paise - current.chargebacks_paise),
    )
    net_change = current.net_revenue_paise - prior.net_revenue_paise
    return Attribution(
        net_change_paise=net_change,
        net_change_ratio=ratio(net_change, prior.net_revenue_paise),
        effects=effects,
        rounding_residual_paise=net_change - sum(effect.effect_paise for effect in effects),
    )
