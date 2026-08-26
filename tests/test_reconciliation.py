"""The reconciliation engine, against the golden fixture.

Phase 2's exit criteria in one file: the golden run reproduced exactly, the
exception breakdown, the unresolved value, SETTLEMENT_91 recorded as a
rejected candidate rather than a match, and the shuffle test.
"""

import random
from dataclasses import asdict
from datetime import date
from decimal import Decimal

import pytest
from data.seed import generate_seed_data as seed

from reconciliation.engine import (
    EmptyPeriodError,
    expected_fee_paise,
    fee_tolerance_paise,
    reconcile,
)
from reconciliation.models import (
    AUTO_MATCH_THRESHOLD,
    BankRecord,
    LedgerRecord,
    ReconciliationResult,
)
from reconciliation.rules import RULES
from runtime.calendar import bank_period
from verification.rules import RunVerificationError, verify_run, violations

# --------------------------------------------------------------------------
# the fixture, in the engine's own vocabulary
# --------------------------------------------------------------------------


def _ledger_records(dataset: seed.Dataset) -> list[LedgerRecord]:
    return [
        LedgerRecord(
            id=txn.id,
            merchant_id=txn.merchant_id,
            external_ref=txn.external_ref,
            utr=txn.utr,
            amount_paise=txn.amount_paise,
            fee_paise=txn.fee_paise,
            captured_at=txn.captured_at,
            settlement_due_date=txn.settlement_due_date,
        )
        for txn in dataset.transactions
        if txn.status == "CAPTURED"
        and txn.captured_at is not None
        and txn.settlement_due_date is not None
        and seed._captured_in(txn, seed.CURRENT)
    ]


def _bank_records(dataset: seed.Dataset) -> list[BankRecord]:
    opens, closes = bank_period(seed.CURRENT_FROM, seed.CURRENT_TO)
    return [
        BankRecord(
            id=stl.id,
            merchant_id=stl.merchant_id,
            bank_ref=stl.bank_ref,
            utr=stl.utr,
            amount_paise=stl.amount_paise,
            fee_paise=stl.fee_paise,
            value_date=stl.value_date,
        )
        for stl in dataset.settlements
        if opens <= stl.value_date < closes
    ]


@pytest.fixture(scope="module")
def dataset() -> seed.Dataset:
    return seed.build()


@pytest.fixture(scope="module")
def ledger(dataset: seed.Dataset) -> list[LedgerRecord]:
    return _ledger_records(dataset)


@pytest.fixture(scope="module")
def bank(dataset: seed.Dataset) -> list[BankRecord]:
    return _bank_records(dataset)


@pytest.fixture(scope="module")
def result(ledger: list[LedgerRecord], bank: list[BankRecord]) -> ReconciliationResult:
    return reconcile(seed.MERCHANT_ID, seed.CURRENT_FROM, seed.CURRENT_TO, ledger, bank)


# --------------------------------------------------------------------------
# exit criteria
# --------------------------------------------------------------------------


def test_the_golden_reconciliation_is_reproduced_exactly(
    result: ReconciliationResult,
) -> None:
    """342 / 341 / 338 / 327 / 15 / 95.61%, from the engine and not from a constant."""
    assert result.ledger_count == 342
    assert result.bank_count == 341
    assert result.matched_pairs == 338
    assert result.matched_clean == 327
    assert result.matched_with_exception == 11
    assert result.unmatched_ledger == 4
    assert result.unmatched_bank == 3
    assert result.exception_count == 15
    assert result.clean_match_rate_ratio == Decimal("0.956140")


def test_the_exception_breakdown_is_exact(result: ReconciliationResult) -> None:
    assert result.breakdown() == {
        "AMOUNT_MISMATCH": 2,
        "FEE_DISCREPANCY": 2,
        "NO_COUNTERPART": 3,
        "POSSIBLE_DUPLICATE": 1,
        "TIMING_LAG": 7,
    }


def test_the_unresolved_value_is_exact(result: ReconciliationResult) -> None:
    assert result.unresolved_value_paise() == 1_840_000
    unresolved = sorted(
        exc.transaction_id
        for exc in result.ledger_exceptions
        if exc.category == "NO_COUNTERPART" and exc.transaction_id is not None
    )
    assert unresolved == ["TXN_183", "TXN_247", "TXN_402"]


def test_settlement_91_is_a_rejected_candidate_not_a_match(
    result: ReconciliationResult,
) -> None:
    """The single most important row in the demo.

    It is found, scored, and deliberately not taken. A system that cannot show
    the near miss it rejected is asking to be trusted rather than earning it.
    """
    assert seed.NEAR_MISS_ID not in {match.settlement_id for match in result.matches}

    exception = next(
        exc
        for exc in result.ledger_exceptions
        if exc.transaction_id == "TXN_183" and exc.category == "NO_COUNTERPART"
    )
    candidates = exception.detail["candidates"]
    assert isinstance(candidates, list)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["settlement_id"] == seed.NEAR_MISS_ID
    assert candidate["rule"] == "AMOUNT_DATE_CANDIDATE"
    assert candidate["confidence_ratio"] == "0.72"
    assert "0.85" in str(candidate["rejected_because"])


def test_shuffling_the_inputs_changes_nothing(
    ledger: list[LedgerRecord], bank: list[BankRecord]
) -> None:
    """Twenty random input orders, byte-identical output.

    This is the test C-07 exists for. Before the assignment rule was pinned,
    two correct implementations could disagree on the match rate -- and so
    could one implementation on two different days, depending on what order
    the database happened to return rows in.
    """
    rng = random.Random(1234)
    baseline = reconcile(seed.MERCHANT_ID, seed.CURRENT_FROM, seed.CURRENT_TO, ledger, bank)
    reference = asdict(baseline)

    for attempt in range(20):
        shuffled_ledger = list(ledger)
        shuffled_bank = list(bank)
        rng.shuffle(shuffled_ledger)
        rng.shuffle(shuffled_bank)
        run = reconcile(
            seed.MERCHANT_ID,
            seed.CURRENT_FROM,
            seed.CURRENT_TO,
            shuffled_ledger,
            shuffled_bank,
        )
        assert asdict(run) == reference, f"shuffle {attempt} produced a different run"


def test_the_run_passes_verification(
    result: ReconciliationResult, ledger: list[LedgerRecord]
) -> None:
    total = sum(record.amount_paise for record in ledger)
    assert violations(result, total) == []
    assert verify_run(result, total) is result


# --------------------------------------------------------------------------
# the assignment rule itself
# --------------------------------------------------------------------------


def test_every_match_is_one_to_one(result: ReconciliationResult) -> None:
    transactions = [match.transaction_id for match in result.matches]
    settlements = [match.settlement_id for match in result.matches]
    assert len(set(transactions)) == len(transactions)
    assert len(set(settlements)) == len(settlements)


def test_no_match_sits_below_the_auto_match_threshold(
    result: ReconciliationResult,
) -> None:
    assert all(match.confidence_ratio >= AUTO_MATCH_THRESHOLD for match in result.matches)


def test_rules_are_in_descending_confidence_order() -> None:
    """Strict priority order is what makes the greedy pass deterministic."""
    confidences = [rule.confidence_ratio for rule in RULES]
    assert confidences == sorted(confidences, reverse=True)
    assert len(set(confidences)) == len(confidences)


def test_the_rules_that_fire_on_the_fixture(result: ReconciliationResult) -> None:
    """Most pairs are exact; the weaker rules exist and are exercised.

    A fixture where every pair matched on rule 1 would leave rules 2 and 3
    untested by the golden run, which is how a matcher acquires a rule nobody
    has ever seen run.
    """
    used = {match.rule for match in result.matches}
    assert "EXACT_UTR" in used
    assert "REF_AMOUNT" in used, "the null-UTR path never fired"
    assert "REF_DATE_WINDOW" in used, "the amount-mismatch path never fired"
    assert "AMOUNT_DATE_CANDIDATE" not in used, "rule 5 must never produce a match"


def test_the_duplicate_loses_to_the_one_to_one_rule(
    result: ReconciliationResult, dataset: seed.Dataset
) -> None:
    """Both rows want the same settlement. Exactly one may have it."""
    duplicate = next(
        exc for exc in result.ledger_exceptions if exc.category == "POSSIBLE_DUPLICATE"
    )
    twin = next(
        txn
        for txn in dataset.transactions
        if txn.id != duplicate.transaction_id
        and txn.utr is not None
        and txn.utr == next(t.utr for t in dataset.transactions if t.id == duplicate.transaction_id)
    )
    blocked_by = duplicate.detail["blocked_by_settlement_id"]
    assert any(
        match.transaction_id == twin.id and match.settlement_id == blocked_by
        for match in result.matches
    )


def test_timing_lags_are_all_inside_the_exception_window(
    result: ReconciliationResult,
) -> None:
    lags = [
        exc.detail["lag_days"] for exc in result.ledger_exceptions if exc.category == "TIMING_LAG"
    ]
    assert len(lags) == 7
    assert all(isinstance(lag, int) and 0 < lag <= 3 for lag in lags)


def test_amount_mismatches_report_the_discrepancy_not_the_payment(
    result: ReconciliationResult,
) -> None:
    """An exception's amount is the exposure, not the transaction value."""
    deltas = sorted(
        exc.amount_paise for exc in result.ledger_exceptions if exc.category == "AMOUNT_MISMATCH"
    )
    assert deltas == [100, 25_000]  # Rs 1 and Rs 250


# --------------------------------------------------------------------------
# fee tolerance
# --------------------------------------------------------------------------


def test_fee_tolerance_has_a_one_rupee_floor() -> None:
    """Without the floor, half-up rounding on small payments trips false alarms."""
    assert fee_tolerance_paise(expected_fee_paise(100_00)) == 100
    assert fee_tolerance_paise(expected_fee_paise(10_000_00)) == 100
    assert fee_tolerance_paise(expected_fee_paise(100_000_00)) == 500


def test_fee_discrepancies_are_the_planted_ones(result: ReconciliationResult) -> None:
    flagged = [exc for exc in result.ledger_exceptions if exc.category == "FEE_DISCREPANCY"]
    assert len(flagged) == 2
    for exc in flagged:
        assert abs(int(str(exc.detail["fee_delta_paise"]))) > int(
            str(exc.detail["tolerance_paise"])
        )


# --------------------------------------------------------------------------
# verification refuses a bad run
# --------------------------------------------------------------------------


def test_verification_catches_a_broken_match_rate(result: ReconciliationResult) -> None:
    from dataclasses import replace

    tampered = replace(result, clean_match_rate_ratio=Decimal("0.990000"))
    found = violations(tampered)
    assert any(item.startswith("I4") for item in found)
    with pytest.raises(RunVerificationError, match="I4"):
        verify_run(tampered)


def test_verification_catches_a_double_matched_settlement(
    result: ReconciliationResult,
) -> None:
    """I6, before the database has to say it with a constraint name."""
    from dataclasses import replace

    first = result.matches[0]
    tampered = replace(result, matches=(*result.matches, replace(first, transaction_id="TXN_X")))
    found = violations(tampered)
    assert any(item.startswith("I6") for item in found)


def test_verification_catches_counts_that_do_not_add_up(
    result: ReconciliationResult,
) -> None:
    from dataclasses import replace

    tampered = replace(result, unmatched_ledger=result.unmatched_ledger + 1)
    found = violations(tampered)
    assert any(item.startswith("I1") for item in found)
    assert any(item.startswith("I2") for item in found)


def test_an_empty_period_is_refused_rather_than_answered_with_zero() -> None:
    """ "We matched none of them" and "there were none" are different facts.

    A zero match rate would render them identically. Invariant 6: incomplete
    data yields an explicit limitation, never an invented zero -- so the engine
    refuses, and the caller says why.
    """
    with pytest.raises(EmptyPeriodError, match="no ledger records"):
        reconcile("M123", date(2026, 1, 1), date(2026, 1, 2), [], [])


def test_a_period_with_no_bank_records_still_reconciles(
    ledger: list[LedgerRecord],
) -> None:
    """A bank file that never arrived is a real answer: everything unmatched."""
    run = reconcile(seed.MERCHANT_ID, seed.CURRENT_FROM, seed.CURRENT_TO, ledger[:5], [])
    assert run.matched_pairs == 0
    assert run.unmatched_ledger == 5
    assert run.clean_match_rate_ratio == Decimal(0)
    assert run.exception_count == 5
    assert violations(run) == []
