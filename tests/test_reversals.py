"""Refunds and chargebacks over one window. No database.

Both tools are built from ``tools/movements.py``, so these are the tests for
both. The property that matters is the one that makes cross-tool consistency
meaningful: the value totalled here is the same number the revenue bridge
deducts, computed from the same scoping of the same records.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from runtime.money import ZeroDenominatorError
from tools.finance.bridge import build_window
from tools.movements import build_movement_window
from tools.records import MovementRecord, PaymentRecord

FROM = date(2026, 8, 1)
TO = date(2026, 8, 24)


def payment(
    identifier: str, amount_paise: int, *, day: int = 5, captured: bool = True
) -> PaymentRecord:
    attempted = datetime(2026, 8, day, 6, tzinfo=UTC)
    return PaymentRecord(
        id=identifier,
        method="UPI",
        instrument="UPI_BANK_ACCOUNT",
        status="CAPTURED" if captured else "FAILED",
        decline_type=None if captured else "TECHNICAL_DECLINE",
        amount_paise=amount_paise,
        fee_paise=0,
        attempted_at=attempted,
        captured_at=attempted if captured else None,
    )


PAYMENTS = [payment("T1", 100_000), payment("T2", 60_000), payment("T3", 40_000)]
REFUNDS = [
    MovementRecord("R1", "T1", 5_000, "CUSTOMER_REQUEST"),
    MovementRecord("R2", "T2", 3_000, "CUSTOMER_REQUEST"),
    MovementRecord("R3", "T3", 1_000, "DUPLICATE_CHARGE"),
]


class TestTotals:
    def test_value_rate_and_reasons(self) -> None:
        window = build_movement_window(FROM, TO, PAYMENTS, REFUNDS)
        assert window.count == 3
        assert window.value_paise == 9_000
        assert window.gross_payments_paise == 200_000
        assert window.rate_ratio == Decimal("0.045000")
        assert [(entry.reason, entry.count, entry.value_paise) for entry in window.by_reason] == [
            ("CUSTOMER_REQUEST", 2, 8_000),
            ("DUPLICATE_CHARGE", 1, 1_000),
        ]

    def test_reasons_are_reported_in_a_stable_order(self) -> None:
        window = build_movement_window(FROM, TO, PAYMENTS, list(reversed(REFUNDS)))
        assert [entry.reason for entry in window.by_reason] == [
            "CUSTOMER_REQUEST",
            "DUPLICATE_CHARGE",
        ]

    def test_reason_slices_sum_to_the_total(self) -> None:
        window = build_movement_window(FROM, TO, PAYMENTS, REFUNDS)
        assert sum(entry.count for entry in window.by_reason) == window.count
        assert sum(entry.value_paise for entry in window.by_reason) == window.value_paise

    def test_the_denominator_is_gross_not_attempted(self) -> None:
        """A refund reverses a capture. A failed attempt was never money."""
        window = build_movement_window(
            FROM, TO, [*PAYMENTS, payment("T4", 500_000, captured=False)], REFUNDS
        )
        assert window.gross_payments_paise == 200_000

    def test_a_refund_against_a_payment_outside_the_window_is_excluded(self) -> None:
        outside = payment("T9", 90_000, day=30)
        window = build_movement_window(
            FROM,
            TO,
            [*PAYMENTS, outside],
            [*REFUNDS, MovementRecord("R9", "T9", 9_000, "CUSTOMER_REQUEST")],
        )
        assert window.value_paise == 9_000
        assert "R9" not in window.movement_ids

    def test_a_flagged_duplicate_leaves_both_sides(self) -> None:
        """It is not gross, so its refund is not a refund of gross either."""
        window = build_movement_window(
            FROM, TO, PAYMENTS, REFUNDS, excluded_transaction_ids=frozenset({"T3"})
        )
        assert window.gross_payments_paise == 160_000
        assert window.value_paise == 8_000
        assert [entry.reason for entry in window.by_reason] == ["CUSTOMER_REQUEST"]

    def test_a_window_with_no_gross_has_no_rate(self) -> None:
        with pytest.raises(ZeroDenominatorError):
            _ = build_movement_window(FROM, TO, [], []).rate_ratio


class TestAgreementWithTheBridge:
    """The reason the two tools share one implementation."""

    def test_the_refund_total_is_the_bridge_deduction(self) -> None:
        bridge = build_window(FROM, TO, PAYMENTS, REFUNDS, [])
        movements = build_movement_window(FROM, TO, PAYMENTS, REFUNDS)
        assert movements.value_paise == bridge.refunds_paise

    def test_the_gross_denominators_agree(self) -> None:
        bridge = build_window(FROM, TO, PAYMENTS, REFUNDS, [])
        movements = build_movement_window(FROM, TO, PAYMENTS, REFUNDS)
        assert movements.gross_payments_paise == bridge.gross_payments_paise

    def test_they_agree_under_a_duplicate_exclusion_too(self) -> None:
        excluded = frozenset({"T2"})
        bridge = build_window(FROM, TO, PAYMENTS, REFUNDS, [], excluded)
        movements = build_movement_window(FROM, TO, PAYMENTS, REFUNDS, excluded)
        assert movements.value_paise == bridge.refunds_paise
        assert movements.gross_payments_paise == bridge.gross_payments_paise
