"""Assignment and exception classification.

The one property everything else rests on: ``reconcile`` is a pure function of
``(ledger set, bank set)``. Not of their order, not of dict iteration, not of
how many workers ran. ``tests/test_reconciliation.py`` shuffles the inputs
twenty ways and demands byte-identical output, because the alternative is a
match rate that quietly changes between runs.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from runtime.calendar import MAX_TIMING_LAG_BUSINESS_DAYS
from runtime.money import Paise, apply_rate, ratio

from .models import (
    AUTO_MATCH_THRESHOLD,
    BankRecord,
    LedgerRecord,
    Match,
    ReconciliationException,
    ReconciliationResult,
    RejectedCandidate,
)
from .rules import RULES, amount_delta, lag_days, propose

__all__ = [
    "FEE_RATE",
    "FEE_TOLERANCE_FLOOR_PAISE",
    "FEE_TOLERANCE_RATE",
    "EmptyPeriodError",
    "expected_fee_paise",
    "fee_tolerance_paise",
    "reconcile",
]


class EmptyPeriodError(ValueError):
    """There were no ledger records to reconcile.

    Not an error in the data -- a question with no data behind it. It is raised
    rather than answered with a zero match rate because those are different
    facts: "we matched none of them" and "there were none" would otherwise
    render identically, and Invariant 6 forbids inventing the zero. The caller
    surfaces it as an explicit limitation.
    """


FEE_RATE = Decimal("0.0100")
FEE_TOLERANCE_RATE = Decimal("0.005")

#: The Rs 1.00 floor exists so half-up rounding on small transactions never
#: trips a false discrepancy (C-15g).
FEE_TOLERANCE_FLOOR_PAISE = 100


def expected_fee_paise(amount_paise: Paise) -> Paise:
    return apply_rate(amount_paise, FEE_RATE)


def fee_tolerance_paise(expected: Paise) -> Paise:
    return max(FEE_TOLERANCE_FLOOR_PAISE, apply_rate(expected, FEE_TOLERANCE_RATE))


@dataclass
class _Assignment:
    matches: list[Match]
    matched_pairs: list[tuple[LedgerRecord, BankRecord, Match]]
    #: Ledger id -> candidates found but not taken, for the exception detail.
    rejected: dict[str, list[RejectedCandidate]]
    #: Ledger id -> the settlement it would have matched, already taken by a
    #: higher-priority pair. This is what makes a duplicate a duplicate.
    blocked_by: dict[str, str]


def _assign(ledger: Sequence[LedgerRecord], bank: Sequence[BankRecord]) -> _Assignment:
    """Greedy, strict rule order, one-to-one, total tie-break.

    A rule never revisits a record consumed by a higher-priority rule, so the
    result cannot depend on the order the records arrived in.
    """
    consumed_ledger: set[str] = set()
    consumed_bank: set[str] = set()
    assignment = _Assignment(matches=[], matched_pairs=[], rejected={}, blocked_by={})

    for rule in RULES:
        available_ledger = [r for r in ledger if r.id not in consumed_ledger]
        available_bank = [r for r in bank if r.id not in consumed_bank]
        candidates = propose(rule, available_ledger, available_bank)
        candidates.sort(key=lambda candidate: candidate.tie_break_key())

        for candidate in candidates:
            ledger_taken = candidate.ledger.id in consumed_ledger
            bank_taken = candidate.bank.id in consumed_bank

            if not rule.auto_matches:
                # Rule 5 never consumes anything. It exists to explain, not to
                # decide -- the record it points at is still unmatched.
                if not ledger_taken and not bank_taken:
                    assignment.rejected.setdefault(candidate.ledger.id, []).append(
                        RejectedCandidate(
                            settlement_id=candidate.bank.id,
                            rule=candidate.rule,
                            confidence_ratio=candidate.confidence_ratio,
                            rejected_because=(
                                f"confidence {candidate.confidence_ratio} is below the "
                                f"{AUTO_MATCH_THRESHOLD} auto-match threshold"
                            ),
                        )
                    )
                continue

            if ledger_taken:
                continue
            if bank_taken:
                # This ledger record wanted a settlement that a higher-priority
                # pair already took. That is the definition of a duplicate.
                assignment.blocked_by.setdefault(candidate.ledger.id, candidate.bank.id)
                continue

            match = Match(
                transaction_id=candidate.ledger.id,
                settlement_id=candidate.bank.id,
                rule=candidate.rule,
                confidence_ratio=candidate.confidence_ratio,
                reason=candidate.reason,
                amount_delta_paise=candidate.amount_delta_paise,
                lag_days=candidate.lag_days,
            )
            assignment.matches.append(match)
            assignment.matched_pairs.append((candidate.ledger, candidate.bank, match))
            consumed_ledger.add(candidate.ledger.id)
            consumed_bank.add(candidate.bank.id)

    return assignment


def _classify_pair(ledger: LedgerRecord, bank: BankRecord) -> list[ReconciliationException]:
    """Discrepancies on a pair that was formed.

    A pair can carry more than one; each is its own row, because "this
    settlement was both late and short" is two facts an analyst acts on
    separately.
    """
    found: list[ReconciliationException] = []
    lag = lag_days(ledger, bank)
    delta = amount_delta(ledger, bank)

    if 0 < lag <= MAX_TIMING_LAG_BUSINESS_DAYS:
        found.append(
            ReconciliationException(
                category="TIMING_LAG",
                side="LEDGER",
                transaction_id=ledger.id,
                settlement_id=bank.id,
                amount_paise=ledger.amount_paise,
                detail={
                    "lag_days": lag,
                    "settlement_due_date": ledger.settlement_due_date.isoformat(),
                    "value_date": bank.value_date.isoformat(),
                },
            )
        )

    if delta != 0:
        found.append(
            ReconciliationException(
                category="AMOUNT_MISMATCH",
                side="LEDGER",
                transaction_id=ledger.id,
                settlement_id=bank.id,
                # The exposure is the discrepancy, not the whole payment.
                amount_paise=abs(delta),
                detail={
                    "ledger_amount_paise": ledger.amount_paise,
                    "bank_amount_paise": bank.amount_paise,
                    "amount_delta_paise": delta,
                },
            )
        )

    expected = expected_fee_paise(ledger.amount_paise)
    tolerance = fee_tolerance_paise(expected)
    fee_delta = bank.fee_paise - expected
    if abs(fee_delta) > tolerance:
        found.append(
            ReconciliationException(
                category="FEE_DISCREPANCY",
                side="LEDGER",
                transaction_id=ledger.id,
                settlement_id=bank.id,
                amount_paise=abs(fee_delta),
                detail={
                    "expected_fee_paise": expected,
                    "actual_fee_paise": bank.fee_paise,
                    "tolerance_paise": tolerance,
                    "fee_delta_paise": fee_delta,
                },
            )
        )
    return found


def reconcile(
    merchant_id: str,
    period_from: date,
    period_to: date,
    ledger: Iterable[LedgerRecord],
    bank: Iterable[BankRecord],
) -> ReconciliationResult:
    """Reconcile one period. Pure, total, and order-independent.

    Inputs are sorted by id on the way in. That is not a convenience: it is
    what removes the caller's row order from the result, so a database query
    without a stable ``ORDER BY`` cannot silently change the match rate.
    """
    ledger_records = sorted(ledger, key=lambda record: record.id)
    bank_records = sorted(bank, key=lambda record: record.id)
    if not ledger_records:
        raise EmptyPeriodError(
            f"no ledger records for {merchant_id} in [{period_from}, {period_to})"
        )

    assignment = _assign(ledger_records, bank_records)

    exceptions: list[ReconciliationException] = []
    flagged_pairs = 0
    for ledger_record, bank_record, _ in assignment.matched_pairs:
        pair_exceptions = _classify_pair(ledger_record, bank_record)
        if pair_exceptions:
            flagged_pairs += 1
        exceptions.extend(pair_exceptions)

    matched_ledger = {match.transaction_id for match in assignment.matches}
    matched_bank = {match.settlement_id for match in assignment.matches}

    for record in ledger_records:
        if record.id in matched_ledger:
            continue
        blocked = assignment.blocked_by.get(record.id)
        rejected = assignment.rejected.get(record.id, [])
        if blocked is not None:
            exceptions.append(
                ReconciliationException(
                    category="POSSIBLE_DUPLICATE",
                    side="LEDGER",
                    transaction_id=record.id,
                    settlement_id=None,
                    amount_paise=record.amount_paise,
                    detail={
                        "blocked_by_settlement_id": blocked,
                        "why": (
                            "would have matched a settlement already paired with another "
                            "ledger record; one-to-one assignment admits only the first"
                        ),
                    },
                )
            )
            continue
        exceptions.append(
            ReconciliationException(
                category="NO_COUNTERPART",
                side="LEDGER",
                transaction_id=record.id,
                settlement_id=None,
                amount_paise=record.amount_paise,
                detail={"candidates": [_candidate_detail(c) for c in rejected]},
            )
        )

    for bank_record in bank_records:
        if bank_record.id in matched_bank:
            continue
        exceptions.append(
            ReconciliationException(
                category="NO_COUNTERPART",
                side="BANK",
                transaction_id=None,
                settlement_id=bank_record.id,
                amount_paise=bank_record.amount_paise,
                detail={"value_date": bank_record.value_date.isoformat()},
            )
        )

    matched_pairs = len(assignment.matches)
    unmatched_ledger = len(ledger_records) - matched_pairs
    unmatched_bank = len(bank_records) - matched_pairs
    matched_clean = matched_pairs - flagged_pairs

    return ReconciliationResult(
        merchant_id=merchant_id,
        period_from=period_from,
        period_to=period_to,
        ledger_count=len(ledger_records),
        bank_count=len(bank_records),
        matched_pairs=matched_pairs,
        matched_clean=matched_clean,
        matched_with_exception=flagged_pairs,
        unmatched_ledger=unmatched_ledger,
        unmatched_bank=unmatched_bank,
        clean_match_rate_ratio=ratio(matched_clean, len(ledger_records)),
        matches=tuple(sorted(assignment.matches, key=lambda m: m.transaction_id)),
        exceptions=tuple(sorted(exceptions, key=lambda exc: exc.sort_key())),
    )


def _candidate_detail(candidate: RejectedCandidate) -> dict[str, object]:
    return {
        "settlement_id": candidate.settlement_id,
        "rule": candidate.rule,
        "confidence_ratio": str(candidate.confidence_ratio),
        "rejected_because": candidate.rejected_because,
    }
