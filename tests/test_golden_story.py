"""The fixture is the specification. These tests are the gate on it.

`scripts/verify_seed.py` holds the seven assertions from docs/08-seed-data.md;
this module runs each one as a named test so a failure points at the specific
identity that broke, and adds the properties the fixture must have for the
Phase 2 matcher to be able to reproduce the golden reconciliation at all.
"""

from collections import Counter
from decimal import Decimal

import pytest
from data.seed import generate_seed_data as seed
from scripts import verify_seed


@pytest.fixture(scope="module")
def dataset() -> seed.Dataset:
    return seed.build()


# --------------------------------------------------------------------------
# the seven assertions
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "check"), verify_seed.CHECKS, ids=[n for n, _ in verify_seed.CHECKS]
)
def test_fixture_assertion(name: str, check: object) -> None:
    assert callable(check)
    check()


# --------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------


def test_two_builds_are_identical() -> None:
    """The claim is reproducibility, so build it twice and compare everything.

    A generator that only agrees with itself when nothing else has consumed
    the RNG is not deterministic -- which is why the seed is a local
    `random.Random(42)` and never `random.seed()`.
    """
    first, second = seed.build(), seed.build()
    assert first.transactions == second.transactions
    assert first.settlements == second.settlements
    assert first.refunds == second.refunds
    assert first.chargebacks == second.chargebacks
    assert first.ground_truth == second.ground_truth


def test_allocation_is_exact_regardless_of_weights() -> None:
    """Largest-remainder apportionment must never lose or invent a unit."""
    import random

    rng = random.Random(7)
    for _ in range(200):
        total = rng.randint(0, 10_000_000)
        weights = [rng.randint(1, 999) for _ in range(rng.randint(1, 40))]
        parts = seed.allocate(total, weights)
        assert sum(parts) == total
        assert len(parts) == len(weights)


def test_allocation_respects_a_floor() -> None:
    parts = seed.allocate(1000, [1, 1, 98], floor=10)
    assert sum(parts) == 1000
    assert min(parts) >= 10


def test_allocation_rejects_impossible_inputs() -> None:
    with pytest.raises(ValueError, match="zero parts"):
        seed.allocate(10, [])
    with pytest.raises(ValueError, match="weights must be non-negative"):
        seed.allocate(10, [1, -1])
    with pytest.raises(ValueError, match="must not all be zero"):
        seed.allocate(10, [0, 0])
    with pytest.raises(ValueError, match="cannot cover a floor"):
        seed.allocate(10, [1, 1], floor=100)


# --------------------------------------------------------------------------
# properties the matcher will depend on (Phase 2)
# --------------------------------------------------------------------------


def test_every_amount_is_a_whole_number_of_rupees(dataset: seed.Dataset) -> None:
    """This is what makes the 1.00% fee exact rather than nearly exact."""
    for txn in dataset.transactions:
        assert txn.amount_paise % 100 == 0, txn.id
    for movement in [*dataset.refunds, *dataset.chargebacks]:
        assert movement.amount_paise % 100 == 0, movement.id


def test_every_fee_follows_its_instrument_rule(dataset: seed.Dataset) -> None:
    """Not a flat percentage. The funding source decides the fee.

    Under a flat rate a fee discrepancy is arithmetic noise; under a schedule
    it means a named commercial rule was applied wrongly.
    """
    from runtime.fees import FEE_SCHEDULE, Instrument

    for txn in dataset.transactions:
        if txn.status != "CAPTURED":
            assert txn.fee_paise == 0, f"{txn.id} was declined but carries a fee"
            continue
        rule = FEE_SCHEDULE[Instrument(txn.instrument)]
        assert txn.fee_paise == rule.fee_paise(txn.amount_paise), txn.id


def test_zero_mdr_rails_really_cost_nothing(dataset: seed.Dataset) -> None:
    """Bank-account UPI and RuPay debit carry no MDR, by mandate since 2020.

    A flat 1% model could not express this at all -- which is why it had to go.
    """
    zero_rated = [
        txn
        for txn in dataset.transactions
        if txn.status == "CAPTURED" and txn.instrument in {"UPI_BANK_ACCOUNT", "RUPAY_DEBIT"}
    ]
    assert zero_rated, "the fixture contains no zero-MDR captures at all"
    assert all(txn.fee_paise == 0 for txn in zero_rated)


def test_the_blended_fee_rate_is_nothing_like_one_percent(
    dataset: seed.Dataset,
) -> None:
    """A mix dominated by zero-MDR UPI cannot cost 1% blended."""
    current = dataset.ground_truth["current"]
    assert isinstance(current, dict)
    assert Decimal(str(current["effective_fee_rate_ratio"])) < Decimal("0.0100")


def test_declines_carry_a_type_and_successes_do_not(dataset: seed.Dataset) -> None:
    """NPCI separates technical from business declines and so does this fixture.

    Without the split an investigation can only report that a success rate
    moved, which is a symptom rather than a finding.
    """
    for txn in dataset.transactions:
        if txn.status == "FAILED":
            assert txn.decline_type in {"TECHNICAL_DECLINE", "BUSINESS_DECLINE"}, txn.id
            assert txn.decline_reason, txn.id
        else:
            assert txn.decline_type is None, txn.id
            assert txn.decline_reason is None, txn.id


def test_the_incident_is_localised_to_named_issuers(dataset: seed.Dataset) -> None:
    """A spike everywhere is weather. A spike at three issuers is a finding."""
    incident = dataset.ground_truth["incident"]
    assert isinstance(incident, dict)
    affected = Decimal(str(incident["technical_decline_ratio_affected"]))
    unaffected = Decimal(str(incident["technical_decline_ratio_unaffected"]))
    assert affected > unaffected
    assert affected > Decimal("0.03")


def test_no_money_value_is_a_float(dataset: seed.Dataset) -> None:
    """C-01, checked on the data and not only on the source."""
    for txn in dataset.transactions:
        assert type(txn.amount_paise) is int
        assert type(txn.fee_paise) is int
    for stl in dataset.settlements:
        assert type(stl.amount_paise) is int
        assert type(stl.fee_paise) is int


def test_ids_are_unique(dataset: seed.Dataset) -> None:
    """I5 and I6 are unenforceable if the fixture itself repeats an id."""
    for records in (
        dataset.transactions,
        dataset.settlements,
        dataset.refunds,
        dataset.chargebacks,
    ):
        ids = [record.id for record in records]
        assert len(set(ids)) == len(ids)


def test_utrs_are_unique_except_for_the_planted_duplicate(dataset: seed.Dataset) -> None:
    """The one repeated UTR is the whole POSSIBLE_DUPLICATE story.

    If any other UTR repeated, rule 1 would consume the wrong settlement and
    the golden match count would move -- silently.
    """
    counts = Counter(txn.utr for txn in dataset.transactions if txn.utr is not None)
    repeated = {utr for utr, count in counts.items() if count > 1}
    duplicate = next(t for t in dataset.transactions if t.id == seed.DUPLICATE_ID)
    assert repeated == {duplicate.utr}


def test_the_duplicate_shadows_a_real_capture(dataset: seed.Dataset) -> None:
    by_id = {txn.id: txn for txn in dataset.transactions}
    duplicate = by_id[seed.DUPLICATE_ID]
    twin = next(
        txn for txn in dataset.transactions if txn.utr == duplicate.utr and txn.id != duplicate.id
    )
    assert duplicate.amount_paise == twin.amount_paise
    assert duplicate.external_ref == twin.external_ref
    # Exactly one settlement exists for the pair, which is what forces one of
    # them into the UNMATCHED bucket under the one-to-one rule.
    settlements = [stl for stl in dataset.settlements if stl.utr == duplicate.utr]
    assert len(settlements) == 1


def test_the_unresolved_records_have_no_settlement(dataset: seed.Dataset) -> None:
    by_id = {txn.id: txn for txn in dataset.transactions}
    refs = {stl.bank_ref for stl in dataset.settlements}
    for txn_id, amount in seed.NO_COUNTERPART:
        assert by_id[txn_id].amount_paise == amount
        assert by_id[txn_id].external_ref not in refs


def test_the_near_miss_can_only_reach_rule_five(dataset: seed.Dataset) -> None:
    """SETTLEMENT_91 is the demo's most important row.

    Same amount as TXN_183, no reference, and four business days past the SLA.
    Rules 1 and 2 need a reference; rule 3 needs a reference; rule 4 needs a
    lag within two days. Only rule 5 remains, at 0.72 -- below the 0.85
    auto-match threshold, so it is a rejected candidate rather than a match.
    """
    from runtime.calendar import business_days_between

    near_miss = next(s for s in dataset.settlements if s.id == seed.NEAR_MISS_ID)
    source = next(t for t in dataset.transactions if t.id == "TXN_183")

    assert near_miss.amount_paise == source.amount_paise
    assert near_miss.bank_ref is None
    assert near_miss.utr is None
    assert source.settlement_due_date is not None
    lag = business_days_between(source.settlement_due_date, near_miss.value_date)
    assert lag == seed.NEAR_MISS_LAG_BUSINESS_DAYS
    assert lag > 3, "a lag inside the window would make this a match, not a candidate"
    assert lag <= 5, "a lag beyond five days would not even be a candidate"


def test_every_settlement_sits_inside_the_bank_window(dataset: seed.Dataset) -> None:
    """No settlement from outside the analysis window may leak into its cycle.

    A capture two days before the window -- especially after the 18:00 cutoff --
    settles inside the window's cycle and would look like a bank row with no
    ledger counterpart. That is a fabricated exception born of a boundary, and
    the fixture's quiet band exists to make it impossible.
    """
    from runtime.calendar import bank_period

    opens, closes = bank_period(seed.CURRENT_FROM, seed.CURRENT_TO)
    in_window = [s for s in dataset.settlements if opens <= s.value_date < closes]
    ledger_ids = {
        txn.id
        for txn in dataset.transactions
        if txn.status == "CAPTURED" and seed._captured_in(txn, seed.CURRENT_FROM, seed.CURRENT_TO)
    }
    refs = {txn.external_ref for txn in dataset.transactions if txn.id in ledger_ids}
    planted = {seed.NEAR_MISS_ID, *(stl_id for stl_id, _ in seed.UNMATCHED_BANK_EXTRA)}
    for stl in in_window:
        assert stl.id in planted or stl.bank_ref in refs, (
            f"{stl.id} settled inside the window but belongs to no in-window capture"
        )


def test_timing_lags_stay_inside_the_exception_window(dataset: seed.Dataset) -> None:
    """A lag beyond three business days is not a late pair, it is no pair."""
    from runtime.calendar import business_days_between

    by_ref = {txn.external_ref: txn for txn in dataset.transactions}
    lags = []
    for stl in dataset.settlements:
        if stl.bank_ref is None:
            continue
        txn = by_ref.get(stl.bank_ref)
        if txn is None or txn.settlement_due_date is None:
            continue
        lags.append(business_days_between(txn.settlement_due_date, stl.value_date))
    assert max(lags) <= 3
    assert Counter(lags)[0] > 0, "most settlements should be on time"
    assert sum(1 for lag in lags if lag > 0) == seed.TIMING_LAG_COUNT


def test_the_designed_counts_are_exact(dataset: seed.Dataset) -> None:
    """Counts the scenario designs, so they are legitimately fixed.

    The *money* is not asserted here any more, and should not be: it emerges
    from the calibration layer, so a hard-coded revenue figure would only prove
    that somebody wrote the same number twice. What is checked instead is that
    every identity closes -- see `scripts/verify_seed.py`.
    """
    recon = dataset.ground_truth["reconciliation"]
    assert isinstance(recon, dict)
    assert (
        recon["ledger_count"],
        recon["bank_count"],
        recon["matched_pairs"],
        recon["matched_clean"],
        recon["exception_count"],
    ) == (342, 341, 338, 327, 15)
    assert recon["clean_match_rate_ratio"] == "0.956140"  # 95.61%


def test_the_bridge_closes_with_no_residual(dataset: seed.Dataset) -> None:
    """The property that matters, whatever the numbers turn out to be."""
    attribution = dataset.ground_truth["attribution"]
    assert isinstance(attribution, dict)
    terms = attribution["terms"]
    assert isinstance(terms, dict)

    assert attribution["rounding_residual_paise"] == 0
    assert sum(int(str(v)) for v in terms.values()) == attribution["net_change_paise"]
    assert int(str(attribution["net_change_paise"])) < 0, "the scenario is a decline"


def test_the_ground_truth_carries_its_own_provenance(dataset: seed.Dataset) -> None:
    """A judge asking "where did this data come from?" should not need to ask twice."""
    provenance = dataset.ground_truth["provenance"]
    assert isinstance(provenance, dict)
    assert provenance["transaction_records"] == "synthetic, seeded"
    assert "NPCI" in str(provenance["aggregate_calibration"])
    assert "synthetic" in str(provenance["disclaimer"])
    counts = provenance["parameter_counts"]
    assert isinstance(counts, dict)
    # Both kinds must be present. All-CITED would be a lie; all-ASSUMED would
    # mean the calibration layer is decoration.
    assert counts["CITED"] > 0
    assert counts["ASSUMED"] > 0


def test_the_unresolved_value_is_reported_as_a_confidence_band(
    dataset: seed.Dataset,
) -> None:
    """Rs 18,400 bounds the figures; it is never a term in the bridge.

    C-02's third error was treating unresolved exceptions as a cause of the
    revenue decline. It is not a cause -- it is a statement about how well the
    causes are known, and it must stay out of the attribution.
    """
    from runtime.money import ratio

    current = dataset.ground_truth["current"]
    attribution = dataset.ground_truth["attribution"]
    assert isinstance(current, dict)
    assert isinstance(attribution, dict)
    terms = attribution["terms"]
    assert isinstance(terms, dict)

    band = ratio(verify_seed.UNRESOLVED_PAISE, int(str(current["net_revenue_paise"])))
    assert Decimal(0) < band < Decimal("0.01")
    assert verify_seed.UNRESOLVED_PAISE not in {abs(int(str(v))) for v in terms.values()}
