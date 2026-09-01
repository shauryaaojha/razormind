"""runtime.money -- 100% branch coverage is a Phase 0 exit criterion.

These are not smoke tests. Every rounding boundary and every rejected input is
here because correction C-01 says money is integer paise and that this module
is the only place a rounding decision is made.
"""

from decimal import Decimal

import pytest

from runtime.money import (
    PP_SCALE,
    RATIO_SCALE,
    ZeroDenominatorError,
    apply_rate,
    apply_ratio,
    pp_change,
    quantize_paise,
    quantize_pp,
    quantize_ratio,
    ratio,
)


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


class TestApplyRatio:
    """The rate/volume attribution primitive. One rounding, at the end."""

    def test_the_golden_volume_effect(self) -> None:
        """docs/08-seed-data.md: prior rate applied to the change in attempts."""
        assert apply_ratio(-58_800_000, 516_000_000, 533_000_000) == -56_924_578

    def test_the_two_effects_are_exact_complements(self) -> None:
        """This is what makes the bridge close with a zero residual.

        The rate effect is defined as the remainder of the volume effect, so
        the pair sums to the change in gross by construction rather than by a
        second rounding that happens to agree.
        """
        attempted_prior, attempted_current = 533_000_000, 474_200_000
        gross_prior, gross_current = 516_000_000, 428_320_000
        volume = apply_ratio(attempted_current - attempted_prior, gross_prior, attempted_prior)
        rate = (gross_current - gross_prior) - volume
        assert volume + rate == gross_current - gross_prior

    def test_it_never_rounds_twice(self) -> None:
        """A rate materialised at scale 6 first would give a different answer."""
        via_rate = apply_rate(1_000_000_000, ratio(1, 3))
        via_ratio = apply_ratio(1_000_000_000, 1, 3)
        assert via_ratio == 333_333_333
        assert via_rate != via_ratio

    def test_half_up_away_from_zero(self) -> None:
        assert apply_ratio(5, 1, 2) == 3
        assert apply_ratio(-5, 1, 2) == -3

    def test_zero_denominator_raises(self) -> None:
        with pytest.raises(ZeroDenominatorError, match="apply_ratio denominator is zero"):
            apply_ratio(100, 1, 0)

    def test_rejects_non_integers(self) -> None:
        with pytest.raises(TypeError, match="amount_paise must be int"):
            apply_ratio(1.0, 1, 2)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="numerator must be int"):
            apply_ratio(1, 1.0, 2)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="denominator must be int"):
            apply_ratio(1, 1, 2.0)  # type: ignore[arg-type]


class TestQuantize:
    """The rounding step layer 4 of verification lands on.

    ``evidence/formula.py`` evaluates a declared formula exactly and does not
    round. These are what turn that exact Decimal into the integer or the
    scale-6 ratio a tool published -- one rounding, in the one module allowed to
    make one.
    """

    def test_paise_round_half_up_away_from_zero(self) -> None:
        assert quantize_paise(Decimal("0.5")) == 1
        assert quantize_paise(Decimal("-0.5")) == -1
        assert quantize_paise(Decimal("1.4999")) == 1

    def test_an_exact_integer_is_unchanged(self) -> None:
        assert quantize_paise(Decimal(-7745268)) == -7745268

    def test_paise_result_is_an_int(self) -> None:
        assert type(quantize_paise(Decimal("2.5"))) is int

    def test_the_volume_effect_recomputes_from_its_formula(self) -> None:
        """The golden attribution term, re-derived exactly as the verifier will."""
        exact = Decimal(43134000 - 51293000) * Decimal(48692000) / Decimal(51293000)
        assert quantize_paise(exact) == -7745268

    def test_ratios_quantize_to_scale_six(self) -> None:
        assert quantize_ratio(Decimal("-0.1759555")) == Decimal("-0.175956")
        assert quantize_ratio(Decimal("0.9561403508771")) == Decimal("0.956140")
        assert quantize_ratio(Decimal(1)).as_tuple().exponent == RATIO_SCALE.as_tuple().exponent

    def test_a_float_is_refused_not_coerced(self) -> None:
        """C-01 again: accepting one would make the rounding point unreproducible."""
        with pytest.raises(TypeError, match="must be Decimal"):
            quantize_paise(2.5)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="must be Decimal"):
            quantize_ratio(0.5)  # type: ignore[arg-type]

    def test_an_int_is_refused_too(self) -> None:
        """An int is already exact, so passing one means a unit was confused."""
        with pytest.raises(TypeError, match="must be Decimal"):
            quantize_paise(3)  # type: ignore[arg-type]


class TestPercentagePoints:
    """A percentage point is not a percent (C-04).

    A success rate falling from 0.958042 to 0.944598 fell by 1.34 *points*. It
    did not fall by 1.34 percent -- that would be a fall of about 1.40 points,
    a different number that a reader has no way to tell apart once the unit is
    dropped. Keeping the conversion in one function with a ``_pp`` result is
    what stops the two ever being computed the same way by accident.
    """

    def test_the_golden_blended_move(self) -> None:
        assert pp_change(Decimal("0.944598"), Decimal("0.958042")) == Decimal("-1.34")

    def test_the_golden_upi_move(self) -> None:
        assert pp_change(Decimal("0.946154"), Decimal("0.964401")) == Decimal("-1.82")

    def test_a_rise_is_positive(self) -> None:
        assert pp_change(Decimal("0.958042"), Decimal("0.944598")) == Decimal("1.34")

    def test_a_point_is_not_a_percent(self) -> None:
        """The same move expressed the other way is a different number."""
        points = pp_change(Decimal("0.944598"), Decimal("0.958042"))
        percent = (
            (Decimal("0.944598") - Decimal("0.958042")) / Decimal("0.958042") * 100
        ).quantize(PP_SCALE)
        assert points != percent

    def test_no_change_is_zero_points(self) -> None:
        assert pp_change(Decimal("0.5"), Decimal("0.5")) == Decimal("0.00")

    def test_points_round_half_up(self) -> None:
        assert quantize_pp(Decimal("-1.345")) == Decimal("-1.35")
        assert quantize_pp(Decimal("1.345")) == Decimal("1.35")

    def test_a_float_is_refused(self) -> None:
        with pytest.raises(TypeError, match="must be Decimal"):
            quantize_pp(1.5)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="must be Decimal"):
            pp_change(0.9, Decimal("0.8"))  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="must be Decimal"):
            pp_change(Decimal("0.9"), 0.8)  # type: ignore[arg-type]
