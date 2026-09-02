"""Guard: no float, and no rounding, anywhere near a money path.

Correction C-01 says money is an integer number of paise and that
``runtime/money.py`` is the only module allowed to round. That is a convention
until something fails the build. This is that something.

Three checks, all textual, all deliberately dumb -- a source scan cannot be
tricked by an import alias the way a runtime check can. It reads **code**,
though, not prose: string literals and comments are blanked out first, because
an evidence id like ``.../net_revenue_paise/2026-08-01_2026-08-24`` in a
docstring is not a division, and a guard that cries wolf on documentation gets
worked around rather than fixed. Blanking is done by ``tokenize``, so it
cannot be fooled by a quote inside a string.

1. A field or annotation named ``*_paise`` typed as ``float``.
2. ``float(`` or a ``float`` annotation in a **money-bearing** package.
3. ``round()`` or ``/`` on a ``_paise`` name outside ``runtime/money.py``.

Check 2 is the blanket one, and it is scoped rather than universal. The agent
plane -- the planner, the validator, the intent parser, the model boundary --
computes no money and deals in seconds and monotonic clocks, which the standard
library types as floats. Banning them there would mean either writing awkward
code to dodge a guard or, far more likely, someone adding a broad exemption that
also covers the packages the guard exists for. The scope matches what the
message has always claimed.

Checks 1, 3 and 4 stay universal, because they are about money specifically:
a ``_paise`` field, a division on one, or a ``round()`` is a violation wherever
it appears.

Run: ``python scripts/check_no_float.py``
"""

import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = [ROOT / "apps" / "api" / "src", ROOT / "data" / "seed"]

# The single module permitted to round.
ROUNDING_EXEMPT = {ROOT / "apps" / "api" / "src" / "runtime" / "money.py"}

#: Packages where a money value is computed, rendered or stored. Check 2 -- the
#: blanket float ban -- applies here and nowhere else.
MONEY_BEARING = (
    "runtime",
    "reconciliation",
    "tools",
    "evidence",
    "verification",
    "provenance",
    "narrative",
    "routes",
)

PAISE_FLOAT = re.compile(r"\w*_paise\w*\s*:\s*float\b")
FLOAT_ANNOTATION = re.compile(r":\s*float\b|->\s*float\b|\bfloat\(")
PAISE_DIVISION = re.compile(r"\w*_paise\w*\s*/(?!/)")
ROUND_CALL = re.compile(r"(?<![.\w])round\s*\(")

CHECKS = (
    (PAISE_FLOAT, "a _paise field typed as float"),
    (FLOAT_ANNOTATION, "float used in a money-bearing package"),
    (PAISE_DIVISION, "division applied to a _paise value"),
    (ROUND_CALL, "round() outside runtime/money.py"),
)


def _carries_money(path: Path) -> bool:
    """Whether the blanket float ban applies to this file."""
    parts = path.parts
    if "seed" in parts:
        return True
    return any(package in parts for package in MONEY_BEARING)


def _iter_sources() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        if root.exists():
            files.extend(sorted(root.rglob("*.py")))
    return files


def _code_lines(source: str) -> list[str]:
    """The source with every string literal and comment blanked out.

    Line numbers and column positions are preserved so a violation still points
    at the right place; only the *content* of strings and comments is replaced,
    with spaces.
    """
    lines = source.splitlines()
    blanked = list(lines)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # An unparseable file is not something to silently pass: fall back to
        # scanning it raw rather than skipping it.
        return lines
    for token in tokens:
        if token.type not in (tokenize.STRING, tokenize.COMMENT, tokenize.FSTRING_MIDDLE):
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row, end_row + 1):
            index = row - 1
            if index >= len(blanked):
                continue
            text = blanked[index]
            begins = start_col if row == start_row else 0
            ends = end_col if row == end_row else len(text)
            blanked[index] = text[:begins] + " " * (ends - begins) + text[ends:]
    return blanked


def scan() -> list[str]:
    """Return one human-readable violation per offending line."""
    violations: list[str] = []
    for path in _iter_sources():
        exempt = path in ROUNDING_EXEMPT
        money = _carries_money(path)
        source = path.read_text(encoding="utf-8")
        raw = source.splitlines()
        for lineno, code in enumerate(_code_lines(source), start=1):
            line = raw[lineno - 1]
            if not code.strip():
                continue
            for pattern, message in CHECKS:
                if exempt and pattern in (ROUND_CALL, FLOAT_ANNOTATION):
                    continue
                if pattern is FLOAT_ANNOTATION and not money:
                    continue
                if pattern.search(code):
                    rel = path.relative_to(ROOT).as_posix()
                    violations.append(f"{rel}:{lineno}: {message}\n    {line.strip()}")
    return violations


def main() -> int:
    violations = scan()
    if violations:
        print("no-float check FAILED -- money is integer paise (C-01):\n", file=sys.stderr)
        for violation in violations:
            print(violation, file=sys.stderr)
        return 1
    print(f"no-float check OK ({len(_iter_sources())} files scanned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
