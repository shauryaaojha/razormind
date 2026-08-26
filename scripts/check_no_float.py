"""Guard: no float, and no rounding, anywhere near a money path.

Correction C-01 says money is an integer number of paise and that
``runtime/money.py`` is the only module allowed to round. That is a convention
until something fails the build. This is that something.

Three checks, all textual, all deliberately dumb -- a source scan cannot be
tricked by an import alias the way a runtime check can:

1. A field or annotation named ``*_paise`` typed as ``float``.
2. ``float(`` or a ``float`` annotation anywhere in the API source.
3. ``round()`` or ``/`` on a ``_paise`` name outside ``runtime/money.py``.

Run: ``python scripts/check_no_float.py``
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = [ROOT / "apps" / "api" / "src", ROOT / "data" / "seed"]

# The single module permitted to round.
ROUNDING_EXEMPT = {ROOT / "apps" / "api" / "src" / "runtime" / "money.py"}

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


def _iter_sources() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        if root.exists():
            files.extend(sorted(root.rglob("*.py")))
    return files


def scan() -> list[str]:
    """Return one human-readable violation per offending line."""
    violations: list[str] = []
    for path in _iter_sources():
        exempt = path in ROUNDING_EXEMPT
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            code = line.split("#", 1)[0]
            if not code.strip():
                continue
            for pattern, message in CHECKS:
                if exempt and pattern in (ROUND_CALL, FLOAT_ANNOTATION):
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
