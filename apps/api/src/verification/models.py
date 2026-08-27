"""What a verification pass reports.

Every check is *named*, and a pass collects them all rather than stopping at
the first failure. "Three invariants broke" and "one invariant broke" call for
different responses, and a verifier that raises on the first one cannot tell
the difference.

A tool's ``verify()`` returns one of these. It never returns silently on
failure because the result is not a boolean anyone can ignore -- the caller in
``tools/base.py`` calls :meth:`VerificationResult.raise_if_failed` before any
output leaves the tool.
"""

from dataclasses import dataclass, field

__all__ = ["Checks", "VerificationError", "VerificationResult"]


class VerificationError(AssertionError):
    """A computation failed its own stated invariants and must not be published."""

    def __init__(self, subject: str, failures: tuple[str, ...]) -> None:
        self.subject = subject
        self.failures = failures
        super().__init__(f"{subject} failed verification:\n  " + "\n  ".join(failures))


@dataclass(frozen=True)
class VerificationResult:
    """Which checks ran, and which of them broke."""

    checks: tuple[str, ...]
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures

    def raise_if_failed(self, subject: str) -> None:
        if self.failures:
            raise VerificationError(subject, self.failures)


@dataclass
class Checks:
    """Accumulates named checks. Every ``require`` is recorded, pass or fail."""

    _checks: list[str] = field(default_factory=list)
    _failures: list[str] = field(default_factory=list)

    def require(self, name: str, holds: bool, detail: str) -> None:
        self._checks.append(name)
        if not holds:
            self._failures.append(f"{name}: {detail}")

    def equal(self, name: str, actual: object, expected: object) -> None:
        self.require(name, actual == expected, f"got {actual!r}, expected {expected!r}")

    def result(self) -> VerificationResult:
        return VerificationResult(tuple(self._checks), tuple(self._failures))
