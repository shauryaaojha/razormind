"""Paise arithmetic. The only module in the codebase permitted to round.

Rules (docs/02-data-model.md#money, correction C-01):

* Money is an integer number of **paise**. Never a float, never a Decimal at
  rest, never a string.
* Every money-bearing field name ends in ``_paise``.
* Rounding is ``ROUND_HALF_UP`` and happens exactly **once** per calculation,
  here. Callers never write ``round()``, ``/`` or ``float()`` on money.

``scripts/check_no_float.py`` enforces the last rule mechanically.
"""

from decimal import ROUND_HALF_UP, Decimal, localcontext

__all__ = [
    "RATIO_SCALE",
    "Paise",
    "ZeroDenominatorError",
    "apply_rate",
    "apply_ratio",
    "quantize_paise",
    "quantize_ratio",
    "ratio",
]

type Paise = int
"""An integer number of paise. 100 paise = 1 rupee."""

RATIO_SCALE = Decimal("0.000001")
"""Ratios are Decimals at scale 6. Field suffix ``_ratio``."""

_WHOLE = Decimal(1)


class ZeroDenominatorError(ZeroDivisionError):
    """A ratio was requested against a zero denominator.

    This is a caller error, never a zero result. Invariant 6: incomplete data
    yields an explicit limitation, never an invented, estimated or zero value.
    """


def _require_decimal(value: object, name: str) -> Decimal:
    """Reject anything that is not a Decimal -- a float most of all."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    return value


def _require_int(value: object, name: str) -> int:
    """Reject anything that is not a true int -- bool included."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be int, got {type(value).__name__}")
    return value


def apply_rate(amount_paise: Paise, rate: Decimal) -> Paise:
    """Multiply a paise amount by a rate, rounding half-up to whole paise.

    ``rate`` must be a :class:`~decimal.Decimal`. A float is rejected rather
    than coerced: a float rate is the exact defect C-01 exists to stop, and
    accepting one silently would make the rounding point unreproducible.

    >>> apply_rate(428320000, Decimal("0.0100"))
    4283200
    """
    _require_int(amount_paise, "amount_paise")
    if not isinstance(rate, Decimal):
        raise TypeError(f"rate must be Decimal, got {type(rate).__name__}")
    return int((Decimal(amount_paise) * rate).quantize(_WHOLE, rounding=ROUND_HALF_UP))


def apply_ratio(amount_paise: Paise, numerator: Paise, denominator: Paise) -> Paise:
    """``amount * numerator / denominator``, rounded half-up **once**.

    The rate/volume attribution needs a proportion applied to a money amount
    without ever materialising the proportion as a rounded rate first -- doing
    that twice is how a bridge stops closing. Precision is raised locally so
    the single rounding is the only one that happens.

    >>> apply_ratio(-58_800_000, 516_000_000, 533_000_000)   # the volume effect
    -56924579
    """
    _require_int(amount_paise, "amount_paise")
    _require_int(numerator, "numerator")
    _require_int(denominator, "denominator")
    if denominator == 0:
        raise ZeroDenominatorError("apply_ratio denominator is zero")
    with localcontext() as context:
        context.prec = 60
        scaled = Decimal(amount_paise) * Decimal(numerator) / Decimal(denominator)
    return int(scaled.quantize(_WHOLE, rounding=ROUND_HALF_UP))


def ratio(numerator: Paise, denominator: Paise) -> Decimal:
    """Exact ratio at scale 6.

    A zero denominator raises :class:`ZeroDenominatorError`; it never returns zero.

    >>> ratio(409786800, 499740000)   # net revenue, current / prior
    Decimal('0.820000')
    """
    _require_int(numerator, "numerator")
    _require_int(denominator, "denominator")
    if denominator == 0:
        raise ZeroDenominatorError("ratio denominator is zero")
    return (Decimal(numerator) / Decimal(denominator)).quantize(RATIO_SCALE, rounding=ROUND_HALF_UP)


def quantize_paise(exact: Decimal) -> Paise:
    """Round an exact Decimal to whole paise, half-up.

    The verifier re-evaluates a published formula in exact arithmetic and then
    has to land on the same integer the tool published. That final step is a
    rounding, so it belongs here rather than in ``evidence/formula.py`` -- if
    the two modules each rounded, "the tool and its formula disagree" and "the
    two roundings disagree" would be indistinguishable failures.

    >>> quantize_paise(Decimal("4283199.5"))
    4283200
    """
    return int(_require_decimal(exact, "exact").quantize(_WHOLE, rounding=ROUND_HALF_UP))


def quantize_ratio(exact: Decimal) -> Decimal:
    """Round an exact Decimal to a scale-6 ratio, half-up.

    >>> quantize_ratio(Decimal("-0.1759555"))
    Decimal('-0.175956')
    """
    return _require_decimal(exact, "exact").quantize(RATIO_SCALE, rounding=ROUND_HALF_UP)
