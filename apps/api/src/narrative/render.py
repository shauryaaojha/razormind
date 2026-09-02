"""How a verified number is written down, and what spellings of it are accepted.

Grounding byte-matches (D-11), and a byte-match needs bytes to match against.
This module is where they are decided, for both directions at once: the template
renderer writes the canonical form, and the grounding gate accepts a claim only
if every number inside it is one of the forms listed here.

Two rules shape the list.

**Stripping a trailing zero is not rounding.** ``0.958000`` and ``0.958`` are
the same number written two ways; ``0.958012`` and ``0.958`` are not. So the
percent form of a ratio drops trailing zeros down to two decimal places and
keeps every digit that carries information -- which is what makes ``95.80%``
acceptable for ``0.958000`` and rejected for ``0.958012``.

**Sign lives in the verb, magnitude lives in the number.** English writes "net
revenue fell by 83,30,187" far more often than "net revenue changed by
-83,30,187", so the unsigned magnitude is accepted for a signed value. This is
a deliberate, bounded relaxation: it is the *direction word* that goes
unchecked, never a digit (D-48). No amount of byte-matching can catch "revenue
rose by -17.6%" anyway, because that sentence byte-matches perfectly.

A percentage point is never written with a ``%``. That is C-04's entire
subject: 1.34 percentage points and 1.34 percent are different quantities, and
accepting the second spelling for the first would put the confusion back
underneath the check that exists to stop it.
"""

from decimal import Decimal
from typing import Final, assert_never

from evidence.vocabulary import Unit

__all__ = ["RUPEE", "canonical", "renderings"]

#: The rupee sign, spelled out so a mis-encoded source file is a visible defect
#: rather than a symbol that renders as a box in one terminal.
RUPEE: Final = "₹"

_HUNDRED: Final = Decimal(100)

#: Minimum decimal places kept when trailing zeros are stripped. Two, because
#: "95.8%" reads as an approximation and "95.80%" reads as a measurement, and
#: the number is a measurement.
_MIN_DECIMALS: Final = 2


def canonical(value: int | Decimal, unit: Unit) -> str:
    """The one form the template writes. Always the first accepted rendering."""
    return renderings(value, unit)[0]


def renderings(value: int | Decimal, unit: Unit) -> tuple[str, ...]:
    """Every numeric token that may stand for this value, canonical first.

    The list is short on purpose. It admits spellings that lose no digit -- the
    currency symbol, the trailing ``.00`` on a whole number of rupees, the sign
    on a signed value -- and nothing that restates, rescales or rounds.
    """
    match unit:
        case "paise":
            return _paise_forms(_as_int(value, unit))
        case "count":
            return _count_forms(_as_int(value, unit))
        case "ratio":
            return _ratio_forms(_as_decimal(value, unit))
        case "pp":
            return _pp_forms(_as_decimal(value, unit))
        case _:
            # Exhaustive over Unit. Written out rather than left implicit so
            # that adding a fifth unit fails type-checking here, at the place
            # that would otherwise render it as something plausible.
            assert_never(unit)


# --------------------------------------------------------------------------
# per unit
# --------------------------------------------------------------------------


def _paise_forms(value: int) -> tuple[str, ...]:
    """``40626000`` -> ``₹4,06,260.00``, plus the spellings that lose no digit."""
    rupees, fraction = divmod(abs(value), 100)
    whole = _grouped(rupees)
    exact = f"{whole}.{fraction:02d}"
    forms = [f"{RUPEE}{exact}", exact]
    if fraction == 0:
        # Dropping ".00" drops no information. Dropping ".01" would.
        forms += [f"{RUPEE}{whole}", whole]
    return _signed(forms, negative=value < 0)


def _count_forms(value: int) -> tuple[str, ...]:
    """``342`` -> ``342``; ``1234`` -> ``1,234``, ungrouped also accepted."""
    grouped = _grouped(abs(value))
    plain = str(abs(value))
    forms = [grouped] if grouped == plain else [grouped, plain]
    return _signed(forms, negative=value < 0)


def _ratio_forms(value: Decimal) -> tuple[str, ...]:
    """``0.958012`` -> ``95.8012%``, or the bare ratio for prose that wants it.

    Multiplying by an exact ``Decimal(100)`` shifts the point; it does not
    round, and there is no scale at which it could. That matters here more than
    anywhere: a ratio rendered through a rounding step would make the byte-match
    a check on the renderer rather than on the model.
    """
    return _signed(
        [f"{_trimmed(abs(value) * _HUNDRED)}%", _trimmed(abs(value))],
        negative=value < 0,
    )


def _pp_forms(value: Decimal) -> tuple[str, ...]:
    """``-1.34`` -> ``-1.34``. Never with a ``%``: a point is not a percent (C-04)."""
    return _signed([_trimmed(abs(value))], negative=value < 0)


# --------------------------------------------------------------------------
# shared
# --------------------------------------------------------------------------


def _signed(forms: list[str], *, negative: bool) -> tuple[str, ...]:
    """Prefix the negative forms, and keep the unsigned ones alongside (D-48)."""
    if not negative:
        return tuple(dict.fromkeys(forms))
    return tuple(dict.fromkeys([f"-{form}" for form in forms] + forms))


def _grouped(magnitude: int) -> str:
    """Indian digit grouping: last three, then twos. ``12345678`` -> ``1,23,45,678``."""
    digits = str(magnitude)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups: list[str] = []
    while len(head) > 2:
        head, pair = head[:-2], head[-2:]
        groups.append(pair)
    groups.append(head)
    return ",".join(reversed(groups)) + "," + tail


def _trimmed(value: Decimal) -> str:
    """Fixed-point text with trailing zeros stripped, never below two places."""
    text = f"{value:f}"
    whole, _, fraction = text.partition(".")
    fraction = fraction.rstrip("0")
    fraction = fraction.ljust(_MIN_DECIMALS, "0")
    return f"{whole}.{fraction}"


def _as_int(value: int | Decimal, unit: Unit) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"a {unit} value must be an int, got {type(value).__name__}")
    return value


def _as_decimal(value: int | Decimal, unit: Unit) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"a {unit} value must be a Decimal, got {type(value).__name__}")
    return value
