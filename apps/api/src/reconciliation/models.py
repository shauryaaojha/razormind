"""The reconciliation domain, as immutable values.

Everything here is a frozen dataclass with a total ordering available, because
the engine's whole claim is that its output is a pure function of its input --
independent of database row order, dict iteration order, or concurrency
(docs/03-reconciliation.md#assignment). Mutable records would make that claim
unverifiable, and the shuffle test is what checks it.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from runtime.money import Paise

__all__ = [
    "AUTO_MATCH_THRESHOLD",
    "BankRecord",
    "Candidate",
    "LedgerRecord",
    "Match",
    "MatchOutcome",
    "ReconciliationException",
    "ReconciliationResult",
    "RejectedCandidate",
]

#: Rules 1-4 auto-match. Rule 5 produces a candidate recorded on the exception,
#: never a match (docs/03-reconciliation.md#rules). The database enforces this
#: too -- reconciliation_matches has a CHECK on confidence_ratio.
AUTO_MATCH_THRESHOLD = Decimal("0.85")


@dataclass(frozen=True, order=True)
class LedgerRecord:
    """One settlement-eligible capture. The ledger side of the reconciliation."""

    id: str
    merchant_id: str
    external_ref: str
    utr: str | None
    amount_paise: Paise
    fee_paise: Paise
    captured_at: datetime
    settlement_due_date: date


@dataclass(frozen=True, order=True)
class BankRecord:
    """One settlement line. The bank side."""

    id: str
    merchant_id: str
    bank_ref: str | None
    utr: str | None
    amount_paise: Paise
    fee_paise: Paise
    value_date: date


@dataclass(frozen=True)
class Candidate:
    """A pairing a rule proposes, before assignment decides whether to take it."""

    ledger: LedgerRecord
    bank: BankRecord
    rule: str
    confidence_ratio: Decimal
    reason: str
    amount_delta_paise: Paise
    lag_days: int

    def tie_break_key(self) -> tuple[int, int, date, str, str]:
        """A **total** order over candidate pairs.

        The first three keys are the ones a human would use. The last two exist
        purely for totality: no two distinct pairs can compare equal, so the
        sort result does not depend on the sorting algorithm's stability or on
        the order candidates were generated in. That is what makes the match
        set reproducible (C-07).
        """
        return (
            abs(self.amount_delta_paise),
            abs(self.lag_days),
            self.bank.value_date,
            self.bank.id,
            self.ledger.id,
        )


@dataclass(frozen=True)
class RejectedCandidate:
    """A pairing that was found and deliberately not taken.

    This is the row the provenance drawer opens onto when a user asks why
    something is unmatched. A 99% match rate that cannot show these is worth
    less than a 95.61% one that can.
    """

    settlement_id: str
    rule: str
    confidence_ratio: Decimal
    rejected_because: str


@dataclass(frozen=True)
class Match:
    """A confirmed one-to-one pairing."""

    transaction_id: str
    settlement_id: str
    rule: str
    confidence_ratio: Decimal
    reason: str
    amount_delta_paise: Paise
    lag_days: int


@dataclass(frozen=True)
class ReconciliationException:
    """A discrepancy. Surfaced, never silently discarded (Invariant 5)."""

    category: str
    side: str
    transaction_id: str | None
    settlement_id: str | None
    amount_paise: Paise
    detail: dict[str, object] = field(default_factory=dict)

    def sort_key(self) -> tuple[str, str, str]:
        return (self.category, self.transaction_id or "", self.settlement_id or "")


@dataclass(frozen=True)
class MatchOutcome:
    """Which bucket a ledger record landed in (docs/03-reconciliation.md)."""

    MATCHED_CLEAN = "MATCHED_CLEAN"
    MATCHED_WITH_EXCEPTION = "MATCHED_WITH_EXCEPTION"
    UNMATCHED = "UNMATCHED"


@dataclass(frozen=True)
class ReconciliationResult:
    """One run. Immutable once written; re-running a period creates a new run.

    That immutability is what makes "which numbers did we see on the 24th?" an
    answerable question.
    """

    merchant_id: str
    period_from: date
    period_to: date
    ledger_count: int
    bank_count: int
    matched_pairs: int
    matched_clean: int
    matched_with_exception: int
    unmatched_ledger: int
    unmatched_bank: int
    clean_match_rate_ratio: Decimal
    matches: tuple[Match, ...]
    exceptions: tuple[ReconciliationException, ...]

    @property
    def ledger_exceptions(self) -> tuple[ReconciliationException, ...]:
        """The headline exception set.

        The published count is **ledger-side**: exactly the ledger records that
        are not MATCHED_CLEAN. Bank-side rows are reported separately as
        ``unmatched_bank`` -- counting them in the same total would double-count
        one discrepancy seen from two sides. See D-20.
        """
        return tuple(exc for exc in self.exceptions if exc.side == "LEDGER")

    @property
    def bank_exceptions(self) -> tuple[ReconciliationException, ...]:
        return tuple(exc for exc in self.exceptions if exc.side == "BANK")

    @property
    def exception_count(self) -> int:
        return len(self.ledger_exceptions)

    def breakdown(self) -> dict[str, int]:
        """Ledger-side exception counts by category, in canonical order."""
        counts: dict[str, int] = {}
        for exc in self.ledger_exceptions:
            counts[exc.category] = counts.get(exc.category, 0) + 1
        return dict(sorted(counts.items()))

    def unresolved_value_paise(self) -> Paise:
        """Value the bank has not confirmed.

        Reported as a confidence band on the revenue figures, and **never**
        netted into any of them (I7, and the third of C-02's three errors).
        """
        return sum(
            exc.amount_paise for exc in self.ledger_exceptions if exc.category == "NO_COUNTERPART"
        )
