"""The boundary is only real if violating it fails the build.

Phase 0 exit criterion: "Import-linter fails a deliberate `from llm import ...`
added inside `tools/`." Asserting that the contract *passes* proves nothing --
a contract with a typo in its module list also passes. So these tests plant a
violation, run the linter for real, and assert it fails.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "apps" / "api" / "src" / "tools"


def _lint_imports() -> subprocess.CompletedProcess[str]:
    """Invoke import-linter the way CI does.

    Deliberately the ``lint-imports`` console script. ``python -m
    importlinter.cli`` exits 0 having evaluated nothing, which is how the
    contract silently passed before these tests existed.
    """
    executable = shutil.which("lint-imports")
    assert executable is not None, "lint-imports is not installed"
    return subprocess.run(
        [executable],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.slow
def test_contracts_hold_on_a_clean_tree() -> None:
    result = _lint_imports()
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.slow
def test_a_tool_importing_the_llm_package_fails_the_build() -> None:
    """Invariant 1, mechanically. This is the test the contract exists for."""
    planted = TOOLS / "_boundary_violation_probe.py"
    planted.write_text(
        "# Planted by tests/test_boundaries.py. Deleted in the same test.\n"
        "from llm import provider  # noqa: F401\n",
        encoding="utf-8",
    )
    try:
        result = _lint_imports()
    finally:
        planted.unlink(missing_ok=True)

    assert result.returncode != 0, (
        "import-linter passed with a tools -> llm import present. "
        "The trust boundary is not being enforced.\n" + result.stdout
    )
    assert "tools" in result.stdout and "llm" in result.stdout


@pytest.mark.slow
def test_a_tool_importing_the_vendor_sdk_fails_the_build() -> None:
    """`llm/` is the only package allowed to touch a vendor SDK."""
    planted = TOOLS / "_vendor_violation_probe.py"
    planted.write_text(
        "# Planted by tests/test_boundaries.py. Deleted in the same test.\n"
        "import anthropic  # noqa: F401\n",
        encoding="utf-8",
    )
    try:
        result = _lint_imports()
    finally:
        planted.unlink(missing_ok=True)

    assert result.returncode != 0, (
        "import-linter passed with a tools -> anthropic import present.\n" + result.stdout
    )


def test_no_float_guard_holds() -> None:
    from scripts.check_no_float import scan

    assert scan() == []


def test_no_float_guard_catches_a_float_paise_field() -> None:
    """The guard must actually reject the thing it exists to reject."""
    import scripts.check_no_float as guard

    probe = ROOT / "apps" / "api" / "src" / "runtime" / "_float_probe.py"
    probe.write_text("amount_paise: float = 0.0\n", encoding="utf-8")
    try:
        violations = guard.scan()
    finally:
        probe.unlink(missing_ok=True)

    assert any("_float_probe.py" in v for v in violations)
    assert any("float" in v for v in violations)
