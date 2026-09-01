"""Success rates, blended and per rail. No database.

The one property that matters here is that the blended rate is the *summed
counts*, not an average of the rail rates. Those two are different numbers
whenever the rails have different volumes, and the original vision quoted them
interchangeably ([C-03](../docs/00-corrections.md)).
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from runtime.money import ZeroDenominatorError, pp_change
from tools.payments.rates import build_failure_window, method_changes
from tools.records import PaymentRecord

FROM = date(2026, 8, 1)
TO = date(2026, 8, 24)


def payment(
    identifier: str,
    method: str,
    amount_paise: int,
    *,
    status: str = "CAPTURED",
    decline_type: str | None = None,
    day: int = 5,
) -> PaymentRecord:
    attempted = datetime(2026, 8, day, 6, tzinfo=UTC)
    return PaymentRecord(
        id=identifier,
        method=method,
        instrument="UPI_BANK_ACCOUNT" if method == "UPI" else "CREDIT_CARD",
        status=status,
        decline_type=decline_type,
        amount_paise=amount_paise,
        fee_paise=0,
        attempted_at=attempted,
        captured_at=attempted if status == "CAPTURED" else None,
    )


#: Two rails with very different volumes and very different rates. The blended
#: rate is 6/8 = 0.75; the mean of the rail rates is (5/6 + 1/2)/2 = 0.6667.
MIXED = [
    payment("U1", "UPI", 100),
    payment("U2", "UPI", 100),
    payment("U3", "UPI", 100),
    payment("U4", "UPI", 100),
    payment("U5", "UPI", 100),
    payment("U6", "UPI", 100, status="FAILED", decline_type="TECHNICAL_DECLINE"),
    payment("C1", "CARD", 900),
    payment("C2", "CARD", 900, status="FAILED", decline_type="BUSINESS_DECLINE"),
]


class TestBlending:
    def test_the_blended_rate_is_the_summed_counts_not_an_average_of_rates(self) -> None:
        window = build_failure_window(FROM, TO, MIXED)
        assert window.success_rate_ratio == Decimal("0.750000")

        rates = {entry.method: entry.success_rate_ratio for entry in window.by_method}
        assert rates == {"UPI": Decimal("0.833333"), "CARD": Decimal("0.500000")}
        mean_of_rates = (rates["UPI"] + rates["CARD"]) / 2
        assert window.success_rate_ratio != mean_of_rates

    def test_the_rails_counts_sum_to_the_blended_counts(self) -> None:
        window = build_failure_window(FROM, TO, MIXED)
        assert sum(entry.attempt_count for entry in window.by_method) == window.attempt_count
        assert sum(entry.succeeded_count for entry in window.by_method) == window.succeeded_count
        assert (
            sum(entry.succeeded_value_paise for entry in window.by_method)
            == window.succeeded_value_paise
        )

    def test_volume_share_is_not_value_share(self) -> None:
        """UPI is most of the payments and a minority of the money."""
        window = build_failure_window(FROM, TO, MIXED)
        upi = next(entry for entry in window.by_method if entry.method == "UPI")
        assert upi.attempt_count > window.attempt_count - upi.attempt_count
        assert upi.attempted_value_paise < window.attempted_value_paise - upi.attempted_value_paise

    def test_a_failure_is_an_attempt(self) -> None:
        window = build_failure_window(FROM, TO, MIXED)
        assert window.attempt_count == 8
        assert window.succeeded_count == 6
        assert window.failed_count == 2
        assert window.failed_value_paise == 100 + 900

    def test_the_decline_taxonomy_splits(self) -> None:
        """Technical and business declines are counted separately, never together."""
        window = build_failure_window(FROM, TO, MIXED)
        assert window.technical_decline_count == 1
        assert window.business_decline_count == 1
        assert window.technical_decline_ratio == Decimal("0.125000")
        assert window.business_decline_ratio == Decimal("0.125000")

    def test_rails_are_reported_in_a_stable_order(self) -> None:
        window = build_failure_window(FROM, TO, list(reversed(MIXED)))
        assert [entry.method for entry in window.by_method] == ["CARD", "UPI"]

    def test_an_empty_window_has_no_rate(self) -> None:
        """Invariant 6: no attempts is not a zero success rate."""
        window = build_failure_window(FROM, TO, [])
        with pytest.raises(ZeroDenominatorError):
            _ = window.success_rate_ratio


class TestScoping:
    def test_scoping_to_one_rail_narrows_everything(self) -> None:
        window = build_failure_window(FROM, TO, MIXED, scope_method="UPI")
        assert window.scope_method == "UPI"
        assert window.attempt_count == 6
        assert [entry.method for entry in window.by_method] == ["UPI"]
        assert window.success_rate_ratio == Decimal("0.833333")

    def test_a_flagged_duplicate_is_excluded(self) -> None:
        window = build_failure_window(FROM, TO, MIXED, excluded_transaction_ids=frozenset({"U1"}))
        assert window.attempt_count == 7
        assert "U1" not in window.attempt_ids


class TestPercentagePoints:
    def test_a_rail_change_is_in_points_not_percent(self) -> None:
        prior = build_failure_window(FROM, TO, MIXED)
        current = build_failure_window(
            FROM,
            TO,
            [
                *MIXED[:5],
                payment("U6", "UPI", 100, status="FAILED", decline_type="TECHNICAL_DECLINE"),
                MIXED[6],
                MIXED[7],
            ],
        )
        assert method_changes(prior, current) == {
            "UPI": Decimal("0.00"),
            "CARD": Decimal("0.00"),
        }

    def test_the_golden_blended_move(self) -> None:
        """0.958042 -> 0.944598 is a fall of 1.34 points, not of 1.34 percent."""
        assert pp_change(Decimal("0.944598"), Decimal("0.958042")) == Decimal("-1.34")

    def test_a_rail_absent_from_the_comparison_period_reports_no_change(self) -> None:
        """A rail that did not exist has no rate to have moved from."""
        prior = build_failure_window(
            FROM, TO, [record for record in MIXED if record.method == "UPI"]
        )
        current = build_failure_window(FROM, TO, MIXED)
        assert set(method_changes(prior, current)) == {"UPI"}
