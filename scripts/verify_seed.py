"""The fixture assertions, run before any application code.

These run first because if the fixture is wrong then nothing downstream can be
trusted -- and, worse, every downstream test would be wrong *and green*.

**What changed when the dataset became market-calibrated.** The old checks
compared against hard-coded revenue figures. They cannot any more, and should
not: the money now *emerges* from the calibration layer rather than being
targeted, so asserting `net_revenue == 40_97_868` would only assert that
somebody wrote the same number twice. What these checks assert instead is the
set of properties that must hold however the numbers land:

* identities that must close (the bridge, the attribution, I1-I4)
* counts the scenario deliberately designed (the reconciliation figures)
* calibration reproducing itself (realised decline rates inside the published
  band; realised method shares matching the declared mix)
* the ground truth agreeing with its own dataset

A fixture whose ground truth disagrees with the data it ships is worse than no
ground truth at all, so that last one is a check and not a comment.

Run: ``python scripts/task.py verify-seed``
"""

import json
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from data.calibration.parameters import MERCHANT_MIX  # noqa: E402
from data.seed.generate_seed_data import (  # noqa: E402
    ARTIFACTS,
    GOLDEN,
    HERE,
    NO_COUNTERPART,
    _sha256,
    build,
)

from runtime.fees import FEE_SCHEDULE, Instrument  # noqa: E402
from runtime.money import ratio  # noqa: E402

#: docs/03-reconciliation.md, "Golden expectation". These are counts the
#: scenario designs, so they are legitimately fixed.
GOLDEN_RECONCILIATION = {
    "ledger_count": 342,
    "bank_count": 341,
    "matched_pairs": 338,
    "matched_clean": 327,
    "matched_with_exception": 11,
    "unmatched_ledger": 4,
    "unmatched_bank": 3,
    "exception_count": 15,
}

GOLDEN_EXCEPTIONS = {
    "TIMING_LAG": 7,
    "NO_COUNTERPART": 3,
    "AMOUNT_MISMATCH": 2,
    "FEE_DISCREPANCY": 2,
    "POSSIBLE_DUPLICATE": 1,
}

UNRESOLVED_PAISE = 184_000

#: NPCI publishes ecosystem technical declines at 0.7-0.8% with a target under
#: 1%, and a business-decline target under 5% (OC-149). A baseline outside
#: these is a calibration failure, not a rounding difference.
TD_BAND = (Decimal("0.004"), Decimal("0.012"))
BD_BAND = (Decimal("0.020"), Decimal("0.050"))

#: How far a realised share may drift from its declared one. Apportionment is
#: exact but the population is finite, so a point or so of slack is honest.
SHARE_TOLERANCE = Decimal("0.02")

#: Instruments whose MDR is zero by mandate, not by negotiation.
ZERO_MDR = (Instrument.UPI_BANK_ACCOUNT, Instrument.RUPAY_DEBIT)


class FixtureError(AssertionError):
    """The fixture is not the one the documentation describes."""


def _truth() -> dict[str, object]:
    path = GOLDEN / "ground_truth.json"
    if not path.exists():
        raise FixtureError("golden/ground_truth.json is missing -- run `task.py seed` first")
    loaded: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _section(name: str) -> dict[str, object]:
    section = _truth()[name]
    assert isinstance(section, dict)
    return section


def _int(section: dict[str, object], key: str) -> int:
    return int(str(section[key]))


def _dec(section: dict[str, object], key: str) -> Decimal:
    return Decimal(str(section[key]))


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------


def check_checksums() -> str:
    """1. Every artifact matches checksums.json, and regenerates identically."""
    manifest_path = GOLDEN / "checksums.json"
    if not manifest_path.exists():
        raise FixtureError("golden/checksums.json is missing -- run `task.py seed` first")
    manifest: dict[str, str] = json.loads(manifest_path.read_text(encoding="utf-8"))

    for name in ARTIFACTS:
        path = HERE / name
        if not path.exists():
            raise FixtureError(f"{name} is missing")
        actual = _sha256(path)
        if actual != manifest.get(name):
            raise FixtureError(
                f"{name} checksum drifted\n  expected {manifest.get(name)}\n  actual   {actual}"
            )

    # Determinism is the claim, so rebuild in-process rather than trusting that
    # the file on disk came from this code. A generator that is only
    # deterministic when nothing else has consumed the RNG is not deterministic.
    if build().ground_truth != _truth():
        raise FixtureError("regenerating the dataset produced a different ground truth")
    return f"{len(ARTIFACTS)} artifacts match, and regeneration is identical"


def check_bridge_closes() -> str:
    """2. gross - refunds - fees - chargebacks == net, in both windows."""
    lines = []
    for window in ("prior", "current"):
        actual = _section(window)
        derived = (
            _int(actual, "gross_payments_paise")
            - _int(actual, "refunds_paise")
            - _int(actual, "fees_paise")
            - _int(actual, "chargebacks_paise")
        )
        if derived != _int(actual, "net_revenue_paise"):
            raise FixtureError(
                f"{window} bridge does not close: {derived} != {actual['net_revenue_paise']}"
            )
        if _int(actual, "gross_payments_paise") > _int(actual, "attempted_value_paise"):
            raise FixtureError(f"{window} gross exceeds attempted value")
        lines.append(f"{window} net {actual['net_revenue_paise']}")
    return "; ".join(lines)


def check_attribution() -> str:
    """3. The causes sum to the change, with a zero rounding residual."""
    attribution = _section("attribution")
    terms = attribution["terms"]
    assert isinstance(terms, dict)

    net_change = _int(attribution, "net_change_paise")
    total = sum(int(str(value)) for value in terms.values()) + _int(
        attribution, "rounding_residual_paise"
    )
    if total != net_change:
        raise FixtureError(f"attribution sums to {total}, but the net change is {net_change}")
    residual = _int(attribution, "rounding_residual_paise")
    if residual != 0:
        raise FixtureError(f"rounding residual is {residual}, expected 0")
    if net_change >= 0:
        raise FixtureError(f"the scenario is a revenue decline, but net change is {net_change}")
    return (
        f"{len(terms)} terms sum to {net_change} paise, residual 0, "
        f"{attribution['net_change_ratio']}"
    )


def check_method_mix() -> str:
    """4. Volume share and value share are different numbers, both calibrated.

    The single most important calibration fact: UPI is dominant by count and
    much less dominant by value, because its ticket is small. A generator that
    used one share for both would be modelling a world that cannot exist, and
    this check is what stops that regressing.
    """
    declared = {profile.method: profile for profile in MERCHANT_MIX}
    lines = []
    for window in ("prior", "current"):
        by_method = _section(window)["by_method"]
        assert isinstance(by_method, dict)

        missing = set(declared) - set(by_method)
        if missing:
            raise FixtureError(f"{window} is missing methods entirely: {sorted(missing)}")

        for method, profile in declared.items():
            stats = by_method[method]
            volume = Decimal(str(stats["volume_share_ratio"]))
            value = Decimal(str(stats["value_share_ratio"]))
            if abs(volume - profile.volume_share) > SHARE_TOLERANCE:
                raise FixtureError(
                    f"{window} {method} volume share is {volume}, declared {profile.volume_share}"
                )
            ticket = int(str(stats["mean_ticket_paise"]))
            drift = abs(ticket - profile.mean_ticket_paise)
            if drift * 100 > profile.mean_ticket_paise * 5:
                raise FixtureError(
                    f"{window} {method} mean ticket is {ticket}, "
                    f"declared {profile.mean_ticket_paise}"
                )
            if method == "UPI" and value >= volume:
                raise FixtureError(
                    f"{window} UPI value share {value} is not below its volume share "
                    f"{volume} -- the low-ticket property has been lost"
                )
        upi = by_method["UPI"]
        lines.append(
            f"{window} UPI {upi['volume_share_ratio']} of volume, "
            f"{upi['value_share_ratio']} of value"
        )
    return "; ".join(lines)


def check_decline_taxonomy() -> str:
    """5. Technical and business declines exist, and behave differently.

    A technical decline is a bank or NPCI back end failing; a business decline
    is the customer's side. The incident must move the first and leave the
    second alone -- that asymmetry is what lets an investigation name a cause
    instead of a symptom.
    """
    prior = _section("prior")
    current = _section("current")

    baseline_td = _dec(prior, "technical_decline_ratio")
    baseline_bd = _dec(prior, "business_decline_ratio")
    if not TD_BAND[0] <= baseline_td <= TD_BAND[1]:
        raise FixtureError(
            f"baseline technical declines {baseline_td} sit outside the published band {TD_BAND}"
        )
    if not BD_BAND[0] <= baseline_bd <= BD_BAND[1]:
        raise FixtureError(
            f"baseline business declines {baseline_bd} sit outside the published band {BD_BAND}"
        )

    if _dec(current, "technical_decline_ratio") <= baseline_td:
        raise FixtureError("technical declines did not rise in the incident window")
    business_drift = abs(_dec(current, "business_decline_ratio") - baseline_bd)
    if business_drift > Decimal("0.010"):
        raise FixtureError(
            f"business declines moved by {business_drift} -- they are supposed to stay flat, "
            "which is the whole basis for separating a platform failure from a customer one"
        )

    incident = _section("incident")
    affected = _dec(incident, "technical_decline_ratio_affected")
    unaffected = _dec(incident, "technical_decline_ratio_unaffected")
    if affected <= unaffected:
        raise FixtureError(
            f"the incident is not localised: affected issuers {affected}, others {unaffected}"
        )
    if affected < Decimal("0.03"):
        raise FixtureError(f"incident technical declines {affected} are too small to detect")
    return (
        f"TD {baseline_td} -> {current['technical_decline_ratio']}, "
        f"BD flat at {baseline_bd}; incident {affected} vs {unaffected}"
    )


def check_fee_schedule() -> str:
    """6. Fees follow the instrument, and zero-MDR really means zero.

    The flat 1% model could not represent a mandated zero rate at all, which is
    why a fee discrepancy under it was arithmetic noise rather than a finding.
    """
    for instrument in ZERO_MDR:
        rule = FEE_SCHEDULE[instrument]
        for amount in (100_00, 10_000_00, 500_000_00):
            if rule.fee_paise(amount) != 0:
                raise FixtureError(f"{instrument} charged a fee on {amount} paise")

    dataset = build()
    for txn in dataset.transactions:
        if txn.status != "CAPTURED":
            if txn.fee_paise != 0:
                raise FixtureError(f"{txn.id} was declined but carries a fee")
            continue
        expected = FEE_SCHEDULE[Instrument(txn.instrument)].fee_paise(txn.amount_paise)
        if txn.fee_paise != expected:
            raise FixtureError(
                f"{txn.id} ({txn.instrument}) fee is {txn.fee_paise}, rule says {expected}"
            )

    effective = _dec(_section("current"), "effective_fee_rate_ratio")
    if effective >= Decimal("0.0100"):
        raise FixtureError(
            f"the blended fee rate is {effective}, at or above the flat 1% this model replaced -- "
            "a mix dominated by zero-MDR UPI cannot cost that much"
        )
    return f"per-instrument fees hold on {len(dataset.transactions)} records; blended {effective}"


def check_reconciliation_invariants() -> str:
    """7. I1-I4 hold on the designed counts, and the identifiers are unique."""
    recon = _section("reconciliation")
    for field, expected in GOLDEN_RECONCILIATION.items():
        if recon[field] != expected:
            raise FixtureError(f"reconciliation.{field} is {recon[field]}, expected {expected}")

    ledger = _int(recon, "ledger_count")
    bank = _int(recon, "bank_count")
    pairs = _int(recon, "matched_pairs")
    clean = _int(recon, "matched_clean")
    flagged = _int(recon, "matched_with_exception")
    unmatched_ledger = _int(recon, "unmatched_ledger")
    unmatched_bank = _int(recon, "unmatched_bank")

    if clean + flagged + unmatched_ledger != ledger:
        raise FixtureError("I1 violated: ledger records are not fully accounted for")
    if 2 * pairs + unmatched_ledger + unmatched_bank != ledger + bank:
        raise FixtureError("I2 violated: the two sides do not add up")
    if pairs != clean + flagged:
        raise FixtureError("I3 violated: pairs are not clean + flagged")
    expected_rate = str(ratio(clean, ledger))
    if recon["clean_match_rate_ratio"] != expected_rate:
        raise FixtureError(
            f"I4 violated: rate is {recon['clean_match_rate_ratio']}, expected {expected_rate}"
        )

    dataset = build()
    for label, ids in (
        ("I5", [t.id for t in dataset.transactions]),
        ("I6", [s.id for s in dataset.settlements]),
    ):
        if len(set(ids)) != len(ids):
            raise FixtureError(f"duplicate ids -- {label} could never hold")

    return f"I1-I4 hold on {ledger} ledger / {bank} bank records, rate {expected_rate}"


def check_exception_breakdown() -> str:
    """8. The exception counts equal the golden breakdown, and sum to the total."""
    recon = _section("reconciliation")
    breakdown = recon["exceptions_by_category"]
    assert isinstance(breakdown, dict)

    if breakdown != GOLDEN_EXCEPTIONS:
        raise FixtureError(f"exception breakdown is {breakdown}, expected {GOLDEN_EXCEPTIONS}")
    total = sum(breakdown.values())
    if total != _int(recon, "exception_count"):
        raise FixtureError(f"breakdown sums to {total}, count is {recon['exception_count']}")
    # The identity that makes the count meaningful: an exception is exactly a
    # ledger record that is not MATCHED_CLEAN.
    if total != _int(recon, "ledger_count") - _int(recon, "matched_clean"):
        raise FixtureError("exception count is not ledger_count - matched_clean")
    return " / ".join(f"{name} {count}" for name, count in sorted(breakdown.items()))


def check_unresolved_value() -> str:
    """9. The unresolved NO_COUNTERPART value is exactly 1,840,000 paise."""
    recon = _section("reconciliation")
    if _int(recon, "unresolved_paise") != UNRESOLVED_PAISE:
        raise FixtureError(
            f"unresolved value is {recon['unresolved_paise']}, expected {UNRESOLVED_PAISE}"
        )
    expected_ids = [txn_id for txn_id, _ in NO_COUNTERPART]
    if recon["unresolved_transaction_ids"] != expected_ids:
        raise FixtureError(
            f"unresolved ids are {recon['unresolved_transaction_ids']}, expected {expected_ids}"
        )

    by_id = {t.id: t for t in build().transactions}
    total = sum(by_id[txn_id].amount_paise for txn_id in expected_ids)
    if total != UNRESOLVED_PAISE:
        raise FixtureError(f"the named records sum to {total}, expected {UNRESOLVED_PAISE}")
    return f"{UNRESOLVED_PAISE} paise across {', '.join(expected_ids)}"


def check_diagnosis_matches_the_data() -> str:
    """10. The declared answer is the one the dataset actually supports.

    A ground truth that disagrees with its own dataset is worse than none: every
    evaluation scored against it would be scoring the wrong thing, confidently.
    So the declared primary driver is checked against the largest term in the
    attribution rather than taken on trust.
    """
    incident = _section("incident")
    expected = incident["expected_diagnosis"]
    assert isinstance(expected, dict)

    terms = _section("attribution")["terms"]
    assert isinstance(terms, dict)
    ranked = sorted(terms.items(), key=lambda item: int(str(item[1])))
    largest_driver = ranked[0][0]

    declared = str(expected["primary_driver"])
    driver_terms = {
        "attempt_volume_decline": "attempt_volume_paise",
        "technical_payment_failures": "success_rate_paise",
    }
    if driver_terms.get(declared) != largest_driver:
        raise FixtureError(
            f"the declared primary driver is {declared!r}, but the largest term in the "
            f"attribution is {largest_driver!r} -- the ground truth disagrees with its dataset"
        )

    if str(expected["affected_method"]) != str(incident["affected_method"]):
        raise FixtureError("the declared affected method is not the one the incident used")
    declared_issuers = expected["affected_issuers"]
    actual_issuers = incident["affected_issuers"]
    assert isinstance(declared_issuers, list)
    assert isinstance(actual_issuers, list)
    if sorted(str(i) for i in declared_issuers) != sorted(str(i) for i in actual_issuers):
        raise FixtureError("the declared affected issuers are not the ones the incident used")
    return f"primary driver {declared!r} is the largest attribution term"


CHECKS: tuple[tuple[str, Callable[[], str]], ...] = (
    ("checksums and determinism", check_checksums),
    ("bridge closes", check_bridge_closes),
    ("attribution residual", check_attribution),
    ("method mix, volume vs value", check_method_mix),
    ("decline taxonomy", check_decline_taxonomy),
    ("per-instrument fees", check_fee_schedule),
    ("reconciliation invariants", check_reconciliation_invariants),
    ("exception breakdown", check_exception_breakdown),
    ("unresolved value", check_unresolved_value),
    ("diagnosis matches the data", check_diagnosis_matches_the_data),
)


def main() -> int:
    failures = 0
    for index, (name, check) in enumerate(CHECKS, start=1):
        try:
            detail = check()
        except FixtureError as error:
            failures += 1
            print(f"{index:>2}. {name}: FAIL", file=sys.stderr)
            print(f"      {error}", file=sys.stderr)
        else:
            print(f"{index:>2}. {name}: ok -- {detail}")
    if failures:
        print(f"\nverify-seed FAILED ({failures} of {len(CHECKS)})", file=sys.stderr)
        return 1
    print(f"\nverify-seed OK ({len(CHECKS)}/{len(CHECKS)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
