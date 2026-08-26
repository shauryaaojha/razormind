"""Invariants I1-I6 and the run-level checks.

docs/03-reconciliation.md#invariants. A failed assertion sets the run
``status = FAILED`` and blocks every downstream tool. It never writes a partial
run -- a half-reconciled period is worse than no reconciled period, because it
looks like an answer.

Every check returns a *violation string* rather than raising, so one call
reports everything that is wrong instead of the first thing.
"""

from collections import Counter
from decimal import Decimal

from reconciliation.models import AUTO_MATCH_THRESHOLD, ReconciliationResult
from runtime.money import Paise, ratio

__all__ = ["MIN_CONFIDENCE", "RunVerificationError", "verify_run", "violations"]

#: Rule 5's confidence. Nothing may be published below it, and nothing may be
#: *matched* below AUTO_MATCH_THRESHOLD.
MIN_CONFIDENCE = Decimal("0.72")


class RunVerificationError(AssertionError):
    """A reconciliation run failed verification and must not be written."""


def violations(result: ReconciliationResult, ledger_total_paise: Paise | None = None) -> list[str]:
    """Every invariant this run breaks. Empty means the run may be written."""
    found: list[str] = []

    # ---- I1: every ledger record lands in exactly one bucket ----
    accounted = result.matched_clean + result.matched_with_exception + result.unmatched_ledger
    if accounted != result.ledger_count:
        found.append(
            f"I1: {accounted} ledger records accounted for, but there are {result.ledger_count}"
        )

    # ---- I2: the two sides add up ----
    two_sided = 2 * result.matched_pairs + result.unmatched_ledger + result.unmatched_bank
    if two_sided != result.ledger_count + result.bank_count:
        found.append(
            f"I2: {two_sided} record-slots across both sides, "
            f"but there are {result.ledger_count + result.bank_count}"
        )

    # ---- I3: pairs split into clean and flagged ----
    if result.matched_pairs != result.matched_clean + result.matched_with_exception:
        found.append(
            f"I3: {result.matched_pairs} pairs is not "
            f"{result.matched_clean} clean + {result.matched_with_exception} flagged"
        )

    # ---- I4: the rate is what it claims to be, and is a ratio ----
    if result.ledger_count > 0:
        expected = ratio(result.matched_clean, result.ledger_count)
        if result.clean_match_rate_ratio != expected:
            found.append(
                f"I4: clean match rate is {result.clean_match_rate_ratio}, expected {expected}"
            )
    if not Decimal(0) <= result.clean_match_rate_ratio <= Decimal(1):
        found.append(f"I4: clean match rate {result.clean_match_rate_ratio} is outside [0, 1]")

    # ---- I5 / I6: one-to-one ----
    # The database enforces these with unique constraints. Checking them here
    # too is not redundant: it means a bad run is rejected before it reaches
    # the database, with a message that names the record rather than a
    # constraint violation that names an index.
    for label, counts in (
        ("I5", Counter(match.transaction_id for match in result.matches)),
        ("I6", Counter(match.settlement_id for match in result.matches)),
    ):
        repeated = sorted(record for record, count in counts.items() if count > 1)
        if repeated:
            found.append(f"{label}: {len(repeated)} record(s) matched more than once: {repeated}")

    if len(result.matches) != result.matched_pairs:
        found.append(
            f"match rows ({len(result.matches)}) do not equal matched_pairs ({result.matched_pairs})"
        )

    # ---- run-level checks (docs/03-reconciliation.md#verification-of-the-run) ----
    for match in result.matches:
        if not MIN_CONFIDENCE <= match.confidence_ratio <= Decimal(1):
            found.append(
                f"match {match.transaction_id}->{match.settlement_id} has confidence "
                f"{match.confidence_ratio}, outside [{MIN_CONFIDENCE}, 1]"
            )
        if match.confidence_ratio < AUTO_MATCH_THRESHOLD:
            found.append(
                f"match {match.transaction_id}->{match.settlement_id} was auto-matched at "
                f"{match.confidence_ratio}, below the {AUTO_MATCH_THRESHOLD} threshold"
            )

    for exc in result.exceptions:
        if exc.transaction_id is None and exc.settlement_id is None:
            found.append(f"{exc.category} exception references no record")
        if exc.amount_paise < 0:
            found.append(f"{exc.category} exception has a negative amount")

    # ---- the ledger-side identity that makes the headline count meaningful ----
    if result.exception_count != result.ledger_count - result.matched_clean:
        found.append(
            f"exception count {result.exception_count} is not "
            f"ledger_count - matched_clean ({result.ledger_count - result.matched_clean})"
        )
    if len(result.bank_exceptions) != result.unmatched_bank:
        found.append(
            f"{len(result.bank_exceptions)} bank-side exceptions but "
            f"{result.unmatched_bank} unmatched bank records"
        )

    if ledger_total_paise is not None:
        exception_total = sum(exc.amount_paise for exc in result.ledger_exceptions)
        if exception_total > ledger_total_paise:
            found.append(
                f"exception value {exception_total} exceeds the ledger total {ledger_total_paise}"
            )

    return found


def verify_run(
    result: ReconciliationResult, ledger_total_paise: Paise | None = None
) -> ReconciliationResult:
    """Return the run, or refuse it.

    Called before a run is written. Raising here is the point: a run that fails
    verification must not exist in a form anything downstream can read.
    """
    found = violations(result, ledger_total_paise)
    if found:
        raise RunVerificationError(
            "reconciliation run failed verification:\n  " + "\n  ".join(found)
        )
    return result
