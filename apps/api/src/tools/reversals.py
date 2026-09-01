"""The half of ``finance.refund_analysis`` and ``risk.chargeback_analysis`` that is identical.

Both answer the same three questions about different tables: how much, at what
rate against the gross it reverses, and how did that move. The only differences
are the table, the metric ids, and what the numbers mean -- so the arithmetic,
the verification identities and the evidence shape live here once, and each
tool supplies its own vocabulary.

Sharing this is not tidiness. ``refund_value_paise`` must equal the revenue
bridge's ``refunds_paise`` exactly, and two independent implementations of "sum
the refunds against captures in this window" would eventually disagree in some
edge each handled differently. That is precisely the defect the cross-tool
consistency check exists to catch, and a poor reason to hand it something.
"""

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from evidence.models import Evidence
from runtime.money import ratio
from verification.models import Checks, VerificationResult

from .base import Period
from .movements import MovementWindow
from .publishing import EvidencePublisher

__all__ = [
    "ReasonBreakdown",
    "ReversalNaming",
    "ReversalSide",
    "ReversalSources",
    "change_row",
    "reversal_rows",
    "side",
    "sources",
    "verify_reversal",
]


@dataclass(frozen=True)
class ReversalNaming:
    """The metric ids one of the two tools publishes, and the words it uses."""

    value_metric: str
    count_metric: str
    rate_metric: str
    change_metric: str
    by_reason_value_metric: str
    by_reason_count_metric: str
    table: str
    noun: str
    #: What this reversal is called in the revenue bridge, so the equivalence
    #: is visible in the evidence rather than only in the vocabulary table.
    bridge_metric: str


# --------------------------------------------------------------------------
# output pieces, shared by both tools
# --------------------------------------------------------------------------


class ReasonBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)

    reason: str
    count: int
    value_paise: int
    share_of_value_ratio: str


class ReversalSide(BaseModel):
    """One period of reversals, against the gross they reverse."""

    model_config = ConfigDict(frozen=True)

    period: Period
    count: int
    value_paise: int
    gross_payments_paise: int
    rate_ratio: str
    by_reason: list[ReasonBreakdown]


class ReversalSources(BaseModel):
    model_config = ConfigDict(frozen=True)

    movement_ids: list[str]
    capture_transaction_ids: list[str]
    by_reason_movement_ids: dict[str, list[str]]


def side(period: Period, window: MovementWindow) -> ReversalSide:
    return ReversalSide(
        period=period,
        count=window.count,
        value_paise=window.value_paise,
        gross_payments_paise=window.gross_payments_paise,
        rate_ratio=f"{window.rate_ratio:.6f}",
        by_reason=[
            ReasonBreakdown(
                reason=entry.reason,
                count=entry.count,
                value_paise=entry.value_paise,
                share_of_value_ratio=f"{ratio(entry.value_paise, window.value_paise):.6f}",
            )
            for entry in window.by_reason
        ],
    )


def sources(window: MovementWindow) -> ReversalSources:
    return ReversalSources(
        movement_ids=list(window.movement_ids),
        capture_transaction_ids=list(window.capture_ids),
        by_reason_movement_ids={
            entry.reason: list(entry.movement_ids) for entry in window.by_reason
        },
    )


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------


def verify_reversal(
    current: ReversalSide,
    prior: ReversalSide,
    current_sources: ReversalSources,
    prior_sources: ReversalSources,
    change_paise: int,
    naming: ReversalNaming,
) -> VerificationResult:
    """The identities both tools must satisfy."""
    checks = Checks()

    for label, entry, entry_sources in (
        ("current", current, current_sources),
        ("prior", prior, prior_sources),
    ):
        checks.equal(
            f"{label}_reason_counts_sum_to_the_total",
            sum(reason.count for reason in entry.by_reason),
            entry.count,
        )
        checks.equal(
            f"{label}_reason_values_sum_to_the_total",
            sum(reason.value_paise for reason in entry.by_reason),
            entry.value_paise,
        )
        checks.equal(
            f"{label}_movement_ids_support_the_count",
            len(entry_sources.movement_ids),
            entry.count,
        )
        checks.equal(
            f"{label}_rate_is_what_it_claims",
            entry.rate_ratio,
            f"{ratio(entry.value_paise, entry.gross_payments_paise):.6f}",
        )
        checks.require(
            f"{label}_value_is_not_negative",
            entry.value_paise >= 0,
            f"{naming.noun} value is {entry.value_paise}",
        )
        checks.require(
            f"{label}_value_does_not_exceed_the_gross_it_reverses",
            entry.value_paise <= entry.gross_payments_paise,
            f"{entry.value_paise} reversed against {entry.gross_payments_paise} captured",
        )

    checks.equal(
        "change_is_current_minus_prior",
        change_paise,
        current.value_paise - prior.value_paise,
    )
    return checks.result()


# --------------------------------------------------------------------------
# evidence
# --------------------------------------------------------------------------


def reversal_rows(
    publisher: EvidencePublisher,
    entry: ReversalSide,
    entry_sources: ReversalSources,
    naming: ReversalNaming,
) -> list[Evidence]:
    """One period's rows: the totals, the rate, and each reason."""
    period = entry.period
    reversed_by = (
        f"{naming.noun}s tied to a capture in the window; a {naming.noun} belongs to the "
        "period of the payment it reverses, not the period it was raised in (D-31)"
    )
    captured = (
        f"IST attempt date in [{period.from_}, {period.to}), status = CAPTURED, "
        "excluding ledger rows the run flagged as possible duplicates"
    )

    rows = [
        publisher.total(
            naming.value_metric,
            period,
            entry.value_paise,
            "amount_paise",
            naming.table,
            reversed_by,
            "PARENT_ATTEMPT_DATE",
            entry_sources.movement_ids,
        ),
        publisher.tally(
            naming.count_metric,
            period,
            entry.count,
            naming.table,
            reversed_by,
            "PARENT_ATTEMPT_DATE",
            entry_sources.movement_ids,
        ),
        publisher.total(
            "gross_payments_paise",
            period,
            entry.gross_payments_paise,
            "amount_paise",
            "transactions",
            captured,
            "ATTEMPT_DATE",
            entry_sources.capture_transaction_ids,
        ),
        publisher.derived(
            naming.rate_metric,
            period,
            Decimal(entry.rate_ratio),
            "reversed / gross",
            {
                "reversed": publisher.identifier(naming.value_metric, period),
                "gross": publisher.identifier("gross_payments_paise", period),
            },
            {"reversed": entry.value_paise, "gross": entry.gross_payments_paise},
            [
                "a value rate, not a count rate; the two are different quantities and do not "
                "share a name (C-04)"
            ],
        ),
    ]

    for reason in entry.by_reason:
        movement_ids = entry_sources.by_reason_movement_ids.get(reason.reason, [])
        rows.extend(
            [
                publisher.total(
                    naming.by_reason_value_metric,
                    period,
                    reason.value_paise,
                    "amount_paise",
                    naming.table,
                    f"{reversed_by}, with reason {reason.reason}",
                    "PARENT_ATTEMPT_DATE",
                    movement_ids,
                    reason.reason,
                ),
                publisher.tally(
                    naming.by_reason_count_metric,
                    period,
                    reason.count,
                    naming.table,
                    f"{reversed_by}, with reason {reason.reason}",
                    "PARENT_ATTEMPT_DATE",
                    movement_ids,
                    reason.reason,
                ),
            ]
        )
    return rows


def change_row(
    publisher: EvidencePublisher,
    current: ReversalSide,
    prior: ReversalSide,
    change_paise: int,
    naming: ReversalNaming,
) -> Evidence:
    return publisher.derived(
        naming.change_metric,
        current.period,
        change_paise,
        "current - prior",
        {
            "current": publisher.identifier(naming.value_metric, current.period),
            "prior": publisher.identifier(naming.value_metric, prior.period),
        },
        {"current": current.value_paise, "prior": prior.value_paise},
        [
            f"a delta; the revenue bridge enters this as {naming.bridge_metric} negated, "
            "because more reversals is less revenue (C-02 error #2)"
        ],
    )
