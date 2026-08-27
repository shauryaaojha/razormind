"""The revenue bridge, without a database.

The bridge has to close to the paise. That property is arithmetic, so it is
tested as arithmetic: hand-built records, no Postgres, and a failure here points
at a formula rather than at a query.

The golden figures come from the generated fixture
(``data/seed/golden/ground_truth.json``); ``test_revenue_db.py`` is what proves
the tool actually reads them back out of the database.
"""

import random
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from runtime.money import ZeroDenominatorError
from tools.finance.bridge import (
    DRIVERS,
    MovementRecord,
    PaymentRecord,
    RevenueWindow,
    attribute,
    build_window,
)

FROM = datetime(2026, 8, 1, tzinfo=UTC).date()
TO = datetime(2026, 8, 24, tzinfo=UTC).date()


def payment(
    identifier: str,
    day: int,
    amount_paise: int,
    *,
    status: str = "CAPTURED",
    fee_paise: int = 0,
    hour: int = 6,
) -> PaymentRecord:
    """A payment attempted at ``hour`` UTC on ``day`` August 2026."""
    attempted = datetime(2026, 8, day, hour, tzinfo=UTC)
    return PaymentRecord(
        id=identifier,
        method="UPI",
        instrument="UPI_BANK_ACCOUNT",
        status=status,
        decline_type=None if status == "CAPTURED" else "TECHNICAL_DECLINE",
        amount_paise=amount_paise,
        fee_paise=fee_paise if status == "CAPTURED" else 0,
        attempted_at=attempted,
        captured_at=attempted if status == "CAPTURED" else None,
    )


def window(
    *,
    attempted_value_paise: int,
    gross_payments_paise: int,
    refunds_paise: int = 0,
    fees_paise: int = 0,
    chargebacks_paise: int = 0,
    attempt_count: int = 10,
    capture_count: int = 9,
) -> RevenueWindow:
    """A window built straight from aggregates, for attribution tests."""
    return RevenueWindow(
        period_from=FROM,
        period_to=TO,
        attempt_count=attempt_count,
        capture_count=capture_count,
        attempted_value_paise=attempted_value_paise,
        gross_payments_paise=gross_payments_paise,
        refunds_paise=refunds_paise,
        fees_paise=fees_paise,
        chargebacks_paise=chargebacks_paise,
        attempt_ids=(),
        capture_ids=(),
        refund_ids=(),
        chargeback_ids=(),
    )


# --------------------------------------------------------------------------
# what belongs to a window
# --------------------------------------------------------------------------


class TestScoping:
    def test_a_failure_is_an_attempt_and_not_a_capture(self) -> None:
        """Scoping on capture date would drop every failure and read 100%."""
        result = build_window(
            FROM,
            TO,
            [payment("A", 5, 10000), payment("B", 6, 30000, status="FAILED")],
            [],
            [],
        )
        assert result.attempt_count == 2
        assert result.capture_count == 1
        assert result.attempted_value_paise == 40000
        assert result.gross_payments_paise == 10000
        assert result.success_rate_ratio == Decimal("0.500000")

    def test_the_window_is_half_open_in_ist(self) -> None:
        """[from, to). 23:59 UTC on 31 July is 05:29 IST on 1 August, and counts."""
        late_july = PaymentRecord(
            id="EARLY",
            method="UPI",
            instrument="UPI_BANK_ACCOUNT",
            status="CAPTURED",
            decline_type=None,
            amount_paise=100,
            fee_paise=0,
            attempted_at=datetime(2026, 7, 31, 23, 59, tzinfo=UTC),
            captured_at=datetime(2026, 7, 31, 23, 59, tzinfo=UTC),
        )
        last_moment = payment("LAST", 23, 200, hour=18)
        first_moment_after = payment("AFTER", 23, 400, hour=19)
        result = build_window(FROM, TO, [late_july, last_moment, first_moment_after], [], [])
        assert list(result.capture_ids) == ["EARLY", "LAST"]

    def test_a_refund_belongs_to_the_period_of_the_payment_it_reverses(self) -> None:
        """Not the period it was raised in. Cohort accounting, or the bridge lies."""
        inside = payment("IN", 5, 10000)
        outside = payment("OUT", 30, 90000)
        result = build_window(
            FROM,
            TO,
            [inside, outside],
            [
                MovementRecord("R1", "IN", 1500, "CUSTOMER_REQUEST"),
                MovementRecord("R2", "OUT", 9000, "CUSTOMER_REQUEST"),
            ],
            [],
        )
        assert result.refunds_paise == 1500
        assert list(result.refund_ids) == ["R1"]

    def test_a_refund_against_a_failed_payment_is_ignored(self) -> None:
        """There is nothing to reverse, so it cannot reduce this period's gross."""
        result = build_window(
            FROM,
            TO,
            [payment("F", 5, 10000, status="FAILED")],
            [MovementRecord("R1", "F", 500, "CUSTOMER_REQUEST")],
            [],
        )
        assert result.refunds_paise == 0

    def test_a_flagged_duplicate_is_excluded_from_everything(self) -> None:
        """A duplicated ledger row lifts the ledger count; it is not revenue."""
        result = build_window(
            FROM,
            TO,
            [payment("A", 5, 10000), payment("DUP", 5, 10000)],
            [MovementRecord("R1", "DUP", 400, "DUPLICATE_CHARGE")],
            [],
            excluded_transaction_ids=frozenset({"DUP"}),
        )
        assert result.capture_count == 1
        assert result.gross_payments_paise == 10000
        assert result.refunds_paise == 0

    def test_the_result_does_not_depend_on_input_order(self) -> None:
        """The same property the matcher has, for the same reason."""
        payments = [payment(f"T{index:03d}", 1 + index % 20, 1000 + index) for index in range(40)]
        movements = [MovementRecord(f"R{index}", f"T{index:03d}", 100, "X") for index in range(5)]
        reference = build_window(FROM, TO, payments, movements, [])

        rng = random.Random(7)
        for _ in range(10):
            shuffled = list(payments)
            rng.shuffle(shuffled)
            shuffled_movements = list(movements)
            rng.shuffle(shuffled_movements)
            assert build_window(FROM, TO, shuffled, shuffled_movements, []) == reference

    def test_the_bridge_identity_holds_by_construction(self) -> None:
        result = build_window(
            FROM,
            TO,
            [payment("A", 5, 100000, fee_paise=642)],
            [MovementRecord("R1", "A", 2000, "CUSTOMER_REQUEST")],
            [MovementRecord("C1", "A", 1000, "FRAUD")],
        )
        assert result.net_revenue_paise == 100000 - 2000 - 642 - 1000


# --------------------------------------------------------------------------
# attribution
# --------------------------------------------------------------------------


class TestAttribution:
    def test_the_golden_decomposition(self) -> None:
        """The exact figures in data/seed/golden/ground_truth.json."""
        prior = window(
            attempted_value_paise=51293000,
            gross_payments_paise=48692000,
            refunds_paise=944600,
            fees_paise=302618,
            chargebacks_paise=102300,
        )
        current = window(
            attempted_value_paise=43134000,
            gross_payments_paise=40626000,
            refunds_paise=1178200,
            fees_paise=260805,
            chargebacks_paise=174700,
        )
        result = attribute(prior, current)

        assert result.net_change_paise == -8330187
        assert result.net_change_ratio == Decimal("-0.175956")
        assert {effect.driver: effect.effect_paise for effect in result.effects} == {
            "ATTEMPT_VOLUME": -7745268,
            "SUCCESS_RATE": -320732,
            "REFUNDS": -233600,
            "FEES": 41813,
            "CHARGEBACKS": -72400,
        }
        assert result.rounding_residual_paise == 0

    def test_the_drivers_are_reported_in_a_fixed_order(self) -> None:
        result = attribute(
            window(attempted_value_paise=100, gross_payments_paise=90),
            window(attempted_value_paise=80, gross_payments_paise=70),
        )
        assert tuple(effect.driver for effect in result.effects) == DRIVERS

    def test_deductions_enter_as_deltas_not_as_gross_values(self) -> None:
        """C-02's second error. More refunds is less revenue, by the difference."""
        prior = window(attempted_value_paise=1000, gross_payments_paise=1000, refunds_paise=100)
        current = window(attempted_value_paise=1000, gross_payments_paise=1000, refunds_paise=150)
        effects = {
            effect.driver: effect.effect_paise for effect in attribute(prior, current).effects
        }
        assert effects["REFUNDS"] == -50

    @pytest.mark.parametrize("seed_value", range(25))
    def test_the_bridge_always_closes_within_the_residual_bound(self, seed_value: int) -> None:
        """abs(residual) <= term count, or it is a formula error, not rounding."""
        rng = random.Random(seed_value)

        def draw() -> RevenueWindow:
            attempted = rng.randrange(1_000_00, 100_000_00)
            gross = rng.randrange(attempted // 2, attempted)
            # Deductions stay well under gross so net revenue is positive and
            # the ratio is defined; the residual bound is the property under
            # test, not the arithmetic of an insolvent merchant.
            return window(
                attempted_value_paise=attempted,
                gross_payments_paise=gross,
                refunds_paise=rng.randrange(0, gross // 20),
                fees_paise=rng.randrange(0, gross // 20),
                chargebacks_paise=rng.randrange(0, gross // 20),
            )

        result = attribute(draw(), draw())
        total = sum(effect.effect_paise for effect in result.effects)
        assert total + result.rounding_residual_paise == result.net_change_paise
        assert abs(result.rounding_residual_paise) <= result.term_count

    def test_a_comparison_period_with_no_attempts_is_refused(self) -> None:
        """Invariant 6: no proportion to apply is a limitation, never a zero."""
        with pytest.raises(ZeroDenominatorError):
            attribute(
                window(attempted_value_paise=0, gross_payments_paise=0),
                window(attempted_value_paise=100, gross_payments_paise=90),
            )

    def test_a_comparison_period_with_no_net_revenue_is_refused(self) -> None:
        prior = window(attempted_value_paise=1000, gross_payments_paise=1000, refunds_paise=1000)
        with pytest.raises(ZeroDenominatorError):
            attribute(prior, window(attempted_value_paise=1000, gross_payments_paise=900))
