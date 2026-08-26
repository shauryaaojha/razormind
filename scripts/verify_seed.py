"""The seven fixture assertions, run before any application code.

docs/08-seed-data.md lists these and Phase 1 makes them a gate. They run first
because if the fixture is wrong then nothing downstream can be trusted -- and,
worse, every downstream test would be wrong *and green*.

Each check returns a line of evidence, not just a boolean, so a failure says
what the number actually was.

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

from data.seed.generate_seed_data import (  # noqa: E402
    ARTIFACTS,
    GOLDEN,
    HERE,
    NO_COUNTERPART,
    _sha256,
    build,
)

from runtime.money import ratio  # noqa: E402

#: docs/03-reconciliation.md, "Golden expectation".
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

#: docs/08-seed-data.md, "Golden figures". Paise.
GOLDEN_WINDOWS = {
    "prior": {
        "attempted_value_paise": 533_000_000,
        "gross_payments_paise": 516_000_000,
        "refunds_paise": 10_000_000,
        "fees_paise": 5_160_000,
        "chargebacks_paise": 1_100_000,
        "net_revenue_paise": 499_740_000,
    },
    "current": {
        "attempted_value_paise": 474_200_000,
        "gross_payments_paise": 428_320_000,
        "refunds_paise": 12_400_000,
        "fees_paise": 4_283_200,
        "chargebacks_paise": 1_850_000,
        "net_revenue_paise": 409_786_800,
    },
}

GOLDEN_RATES = {
    "prior": {"blended": "0.968105", "UPI": "0.968000", "share_UPI": "0.466600"},
    "current": {"blended": "0.903248", "UPI": "0.829001", "share_UPI": "0.466600"},
}

UNRESOLVED_PAISE = 1_840_000
NET_CHANGE_PAISE = -89_953_200
NET_CHANGE_RATIO = "-0.180000"


class FixtureError(AssertionError):
    """The fixture is not the one the documentation describes."""


def _expectations() -> dict[str, object]:
    path = GOLDEN / "expectations.json"
    if not path.exists():
        raise FixtureError("golden/expectations.json is missing -- run `task.py seed` first")
    loaded: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


# --------------------------------------------------------------------------
# the seven checks
# --------------------------------------------------------------------------


def check_checksums() -> str:
    """1. Every artifact matches golden/checksums.json, and regenerates identically."""
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

    # Determinism is the claim, so rebuild in-process and compare the
    # expectations rather than trusting that the file on disk came from this
    # code. A generator that is only deterministic when nothing else has run
    # is not deterministic.
    rebuilt = build().expectations
    if rebuilt != _expectations():
        raise FixtureError("regenerating the dataset produced different expectations")
    return f"{len(ARTIFACTS)} artifacts match, and regeneration is identical"


def check_bridge_closes() -> str:
    """2. gross - refunds - fees - chargebacks == net, in both windows."""
    expectations = _expectations()
    lines = []
    for window, golden in GOLDEN_WINDOWS.items():
        actual = expectations[window]
        assert isinstance(actual, dict)
        for field, expected in golden.items():
            if actual[field] != expected:
                raise FixtureError(f"{window}.{field} is {actual[field]}, expected {expected}")
        derived = (
            int(actual["gross_payments_paise"])
            - int(actual["refunds_paise"])
            - int(actual["fees_paise"])
            - int(actual["chargebacks_paise"])
        )
        if derived != int(actual["net_revenue_paise"]):
            raise FixtureError(
                f"{window} bridge does not close: {derived} != {actual['net_revenue_paise']}"
            )
        lines.append(f"{window} net {actual['net_revenue_paise']}")
    return "; ".join(lines)


def check_attribution() -> str:
    """3. The causes sum to the change, with a zero rounding residual."""
    attribution = _expectations()["attribution"]
    assert isinstance(attribution, dict)
    terms = attribution["terms"]
    assert isinstance(terms, dict)

    total = sum(int(value) for value in terms.values()) + int(
        attribution["rounding_residual_paise"]
    )
    if total != NET_CHANGE_PAISE:
        raise FixtureError(f"attribution sums to {total}, but the net change is {NET_CHANGE_PAISE}")
    # The residual field is mandatory but must be zero for this fixture: the
    # rate/volume split is defined so the two terms are exact complements.
    residual = int(attribution["rounding_residual_paise"])
    if residual != 0:
        raise FixtureError(f"rounding residual is {residual}, expected 0")
    if attribution["net_change_ratio"] != NET_CHANGE_RATIO:
        raise FixtureError(
            f"net change ratio is {attribution['net_change_ratio']}, expected {NET_CHANGE_RATIO}"
        )
    return f"{len(terms)} terms sum to {NET_CHANGE_PAISE} paise, residual 0, {NET_CHANGE_RATIO}"


def check_method_mix() -> str:
    """4. The blended success rate falls out of the method mix.

    Not asserted independently -- recomputed from each method's share and rate,
    which is the whole point of C-03. In the original spec the UPI figure and
    the headline figure were unrelated numbers that happened to share a page.
    """
    expectations = _expectations()
    lines = []
    for window, golden in GOLDEN_RATES.items():
        actual = expectations[window]
        assert isinstance(actual, dict)
        by_method = actual["by_method"]
        assert isinstance(by_method, dict)

        if actual["success_rate_ratio"] != golden["blended"]:
            raise FixtureError(
                f"{window} blended rate is {actual['success_rate_ratio']}, "
                f"expected {golden['blended']}"
            )
        if by_method["UPI"]["success_rate_ratio"] != golden["UPI"]:
            raise FixtureError(
                f"{window} UPI rate is {by_method['UPI']['success_rate_ratio']}, "
                f"expected {golden['UPI']}"
            )
        if by_method["UPI"]["attempted_share_ratio"] != golden["share_UPI"]:
            raise FixtureError(
                f"{window} UPI share is {by_method['UPI']['attempted_share_ratio']}, "
                f"expected {golden['share_UPI']}"
            )

        # Rebuild the blend from the parts.
        blended = sum(
            Decimal(method["attempted_share_ratio"]) * Decimal(method["success_rate_ratio"])
            for method in by_method.values()
        )
        headline = Decimal(str(actual["success_rate_ratio"]))
        if abs(blended - headline) > Decimal("0.000002"):
            raise FixtureError(f"{window} mix recomputes to {blended}, headline says {headline}")
        lines.append(f"{window} {headline}")
    return "; ".join(lines)


def check_reconciliation_invariants() -> str:
    """5. I1-I4 hold on the designed counts, and the identifiers are unique.

    I5 and I6 are database unique constraints and belong to Phase 2, when
    match rows exist. What Phase 1 can prove is that the fixture it hands to
    the matcher is arithmetically capable of satisfying them.
    """
    recon = _expectations()["reconciliation"]
    assert isinstance(recon, dict)

    for field, expected in GOLDEN_RECONCILIATION.items():
        if recon[field] != expected:
            raise FixtureError(f"reconciliation.{field} is {recon[field]}, expected {expected}")

    ledger = int(recon["ledger_count"])
    bank = int(recon["bank_count"])
    pairs = int(recon["matched_pairs"])
    clean = int(recon["matched_clean"])
    flagged = int(recon["matched_with_exception"])
    unmatched_ledger = int(recon["unmatched_ledger"])
    unmatched_bank = int(recon["unmatched_bank"])

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
    if not Decimal("0") <= Decimal(str(recon["clean_match_rate_ratio"])) <= Decimal("1"):
        raise FixtureError("I4 violated: clean match rate is outside [0, 1]")

    dataset = build()
    txn_ids = [txn.id for txn in dataset.transactions]
    stl_ids = [stl.id for stl in dataset.settlements]
    if len(set(txn_ids)) != len(txn_ids):
        raise FixtureError("duplicate transaction ids -- I5 could never hold")
    if len(set(stl_ids)) != len(stl_ids):
        raise FixtureError("duplicate settlement ids -- I6 could never hold")

    return f"I1-I4 hold on {ledger} ledger / {bank} bank records, rate {expected_rate}"


def check_exception_breakdown() -> str:
    """6. The exception counts equal the golden breakdown, and sum to the total."""
    recon = _expectations()["reconciliation"]
    assert isinstance(recon, dict)
    breakdown = recon["exceptions_by_category"]
    assert isinstance(breakdown, dict)

    if breakdown != GOLDEN_EXCEPTIONS:
        raise FixtureError(f"exception breakdown is {breakdown}, expected {GOLDEN_EXCEPTIONS}")
    total = sum(breakdown.values())
    if total != int(recon["exception_count"]):
        raise FixtureError(
            f"breakdown sums to {total}, exception_count is {recon['exception_count']}"
        )
    # The identity that makes the count meaningful: an exception is exactly a
    # ledger record that is not MATCHED_CLEAN.
    if total != int(recon["ledger_count"]) - int(recon["matched_clean"]):
        raise FixtureError("exception count is not ledger_count - matched_clean")
    return " / ".join(f"{name} {count}" for name, count in sorted(breakdown.items()))


def check_unresolved_value() -> str:
    """7. The unresolved NO_COUNTERPART value is exactly 1,840,000 paise."""
    recon = _expectations()["reconciliation"]
    assert isinstance(recon, dict)
    if int(recon["unresolved_paise"]) != UNRESOLVED_PAISE:
        raise FixtureError(
            f"unresolved value is {recon['unresolved_paise']}, expected {UNRESOLVED_PAISE}"
        )
    expected_ids = [txn_id for txn_id, _, _ in NO_COUNTERPART]
    if recon["unresolved_transaction_ids"] != expected_ids:
        raise FixtureError(
            f"unresolved ids are {recon['unresolved_transaction_ids']}, expected {expected_ids}"
        )

    dataset = build()
    by_id = {txn.id: txn for txn in dataset.transactions}
    total = sum(by_id[txn_id].amount_paise for txn_id in expected_ids)
    if total != UNRESOLVED_PAISE:
        raise FixtureError(f"the named records sum to {total}, expected {UNRESOLVED_PAISE}")

    settled = {stl.id for stl in dataset.settlements}
    for txn_id in expected_ids:
        if any(stl_id for stl_id in settled if stl_id == txn_id):  # pragma: no cover
            raise FixtureError(f"{txn_id} should have no counterpart")
    return f"{UNRESOLVED_PAISE} paise across {', '.join(expected_ids)}"


CHECKS: tuple[tuple[str, Callable[[], str]], ...] = (
    ("checksums and determinism", check_checksums),
    ("bridge closes", check_bridge_closes),
    ("attribution residual", check_attribution),
    ("method mix", check_method_mix),
    ("reconciliation invariants", check_reconciliation_invariants),
    ("exception breakdown", check_exception_breakdown),
    ("unresolved value", check_unresolved_value),
)


def main() -> int:
    failures = 0
    for index, (name, check) in enumerate(CHECKS, start=1):
        try:
            detail = check()
        except FixtureError as error:
            failures += 1
            print(f"{index}. {name}: FAIL", file=sys.stderr)
            print(f"     {error}", file=sys.stderr)
        else:
            print(f"{index}. {name}: ok -- {detail}")
    if failures:
        print(f"\nverify-seed FAILED ({failures} of {len(CHECKS)})", file=sys.stderr)
        return 1
    print(f"\nverify-seed OK ({len(CHECKS)}/{len(CHECKS)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
