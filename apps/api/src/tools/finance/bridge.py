"""The revenue bridge and its rate/volume attribution. Pure, no database.

Kept separate from the tool for the same reason ``reconciliation/engine.py`` is
separate from its repository: the arithmetic that has to close to the paise is
testable on hand-built records, and a bug in it should not need a live Postgres
to reproduce.

Scoping lives in ``tools/records.py``, shared with the other three analysis
tools, so ``gross_payments_paise`` here and ``succeeded_value_paise`` there are
the same number by construction rather than by coincidence.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from runtime.money import Paise, apply_ratio, ratio

from ..records import MovementRecord, PaymentRecord, movements_for, scope_attempts

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
#:
#: These stay five distinct metric ids rather than one metric sliced by a
#: ``driver`` dimension, unlike ``by_method.*``. A dimension slices the *same*
#: computation across values; these are five different computations -- the
#: volume effect applies a proportion, the refund effect is a negated delta --
#: and calling them one metric would make a shared formula impossible to state.
DRIVERS = ("ATTEMPT_VOLUME", "SUCCESS_RATE", "REFUNDS", "FEES", "CHARGEBACKS")


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
    """Scope, then total. A function of the records, not of the caller's order."""
    attempts = scope_attempts(period_from, period_to, payments, excluded_transaction_ids)
    captures = [record for record in attempts if record.captured]
    captured_ids = [record.id for record in captures]

    window_refunds = movements_for(refunds, captured_ids)
    window_chargebacks = movements_for(chargebacks, captured_ids)

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
        capture_ids=tuple(captured_ids),
        refund_ids=tuple(movement.id for movement in window_refunds),
        chargeback_ids=tuple(movement.id for movement in window_chargebacks),
    )


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
