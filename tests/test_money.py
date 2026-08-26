"""runtime.money -- 100% branch coverage is a Phase 0 exit criterion.

These are not smoke tests. Every rounding boundary and every rejected input is
here because correction C-01 says money is integer paise and that this module
is the only place a rounding decision is made.
"""

from decimal import Decimal

import pytest

from runtime.money import RATIO_SCALE, ZeroDenominatorError, apply_rate, ratio


class TestApplyRate:
    def test_fee_on_golden_gross(self) -> None:
        """Fees are exactly 1.00% of gross in the fixture (docs/08-seed-data.md)."""
        assert apply_rate(4283200_00, Decimal("0.0100")) == 42832_00
        assert apply_rate(5160000_00, Decimal("0.0100")) == 51600_00

    def test_rounds_half_up_not_half_even(self) -> None:
        """Python's round() is half-to-even. Money is not."""
        assert apply_rate(5, Decimal("0.5")) == 3  # 2.5 -> 3, banker's would give 2
        assert apply_rate(15, Decimal("0.5")) == 8  # 7.5 -> 8, banker's would give 8
        assert apply_rate(25, Decimal("0.5")) == 13  # 12.5 -> 13, banker's would give 12

    def test_rounds_half_up_for_negative_amounts(self) -> None:
        """ROUND_HALF_UP is away from zero, so -2.5 goes to -3."""
        assert apply_rate(-5, Decimal("0.5")) == -3

    def test_below_half_rounds_down(self) -> None:
        assert apply_rate(1, Decimal("0.49")) == 0

    def test_zero_amount(self) -> None:
        assert apply_rate(0, Decimal("0.0100")) == 0

    def test_result_is_int_not_decimal(self) -> None:
        assert type(apply_rate(100, Decimal("0.5"))) is int

    def test_rejects_float_rate(self) -> None:
        """A float rate is the exact defect C-01 exists to stop."""
        with pytest.raises(TypeError, match="rate must be Decimal, got float"):
            apply_rate(100_00, 0.01)  # type: ignore[arg-type]

    def test_rejects_string_rate(self) -> None:
        with pytest.raises(TypeError, match="rate must be Decimal, got str"):
            apply_rate(100_00, "0.01")  # type: ignore[arg-type]

    def test_rejects_float_amount(self) -> None:
        with pytest.raises(TypeError, match="amount_paise must be int, got float"):
            apply_rate(100.0, Decimal("0.01"))  # type: ignore[arg-type]

    def test_rejects_bool_amount(self) -> None:
        """bool is a subclass of int, so mypy accepts this. That is the point:
        the type checker cannot catch it, so the runtime check must."""
        with pytest.raises(TypeError, match="amount_paise must be int, got bool"):
            apply_rate(True, Decimal("0.01"))


class TestRatio:
    def test_golden_net_revenue_ratio_is_exact(self) -> None:
        """The fixture's -18.00% is exact at scale 6, not a rounded 18.0%."""
        assert ratio(4097868_00, 4997400_00) == Decimal("0.820000")

    def test_scale_is_always_six(self) -> None:
        assert ratio(1, 3) == Decimal("0.333333")
        assert ratio(2, 3) == Decimal("0.666667")
        assert ratio(1, 1).as_tuple().exponent == RATIO_SCALE.as_tuple().exponent

    def test_zero_numerator(self) -> None:
        assert ratio(0, 100) == Decimal("0.000000")

    def test_zero_denominator_raises_and_never_returns_zero(self) -> None:
        """Invariant 6: missing data is a limitation, never an invented zero."""
        with pytest.raises(ZeroDenominatorError, match="denominator is zero"):
            ratio(100, 0)

    def test_zero_denominator_is_a_zero_division_error(self) -> None:
        """Callers that catch ZeroDivisionError still behave sanely."""
        assert issubclass(ZeroDenominatorError, ZeroDivisionError)

    def test_rejects_float_numerator(self) -> None:
        with pytest.raises(TypeError, match="numerator must be int, got float"):
            ratio(1.0, 2)  # type: ignore[arg-type]

    def test_rejects_float_denominator(self) -> None:
        with pytest.raises(TypeError, match="denominator must be int, got float"):
            ratio(1, 2.0)  # type: ignore[arg-type]

    def test_rejects_bool_numerator(self) -> None:
        with pytest.raises(TypeError, match="numerator must be int, got bool"):
            ratio(True, 2)  # mypy allows this; bool is an int

    def test_rejects_bool_denominator(self) -> None:
        with pytest.raises(TypeError, match="denominator must be int, got bool"):
            ratio(1, True)  # mypy allows this; bool is an int
