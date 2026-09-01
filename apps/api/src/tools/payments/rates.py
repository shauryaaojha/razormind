"""Success rates, blended and per rail. Pure, no database.

The blended rate is not an average of the per-rail rates. It is the ratio of
the summed counts, and the per-rail rates are the same counts split up -- so
the two reconcile *exactly*, by construction, and ``verify()`` asserts the
identity rather than a tolerance.

That distinction is the whole of [C-03](../../../../docs/00-corrections.md).
The original vision quoted a UPI rate of 96.8% falling to 82.9% next to a
portfolio-level claim of "14.3% more failures", with no derivation from one to
the other and no unit on the second. Here a rail's rate and the portfolio's
rate are different metric ids measured over different record sets, and the
explainer cannot substitute one for the other because they do not share a name.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from runtime.money import Paise, pp_change, ratio

from ..records import PaymentRecord, scope_attempts

__all__ = ["FailureWindow", "MethodSlice", "build_failure_window", "method_changes"]


@dataclass(frozen=True)
class MethodSlice:
    """One rail's attempts and captures inside a window."""

    method: str
    attempt_count: int
    succeeded_count: int
    attempted_value_paise: Paise
    succeeded_value_paise: Paise
    attempt_ids: tuple[str, ...]
    succeeded_ids: tuple[str, ...]

    @property
    def success_rate_ratio(self) -> Decimal:
        return ratio(self.succeeded_count, self.attempt_count)

    @property
    def failed_value_paise(self) -> Paise:
        return self.attempted_value_paise - self.succeeded_value_paise


@dataclass(frozen=True)
class FailureWindow:
    """One period's attempts, blended and split by rail."""

    period_from: date
    period_to: date
    scope_method: str | None

    attempt_count: int
    succeeded_count: int
    attempted_value_paise: Paise
    succeeded_value_paise: Paise
    technical_decline_count: int
    business_decline_count: int

    by_method: tuple[MethodSlice, ...]

    attempt_ids: tuple[str, ...]
    succeeded_ids: tuple[str, ...]

    @property
    def failed_count(self) -> int:
        return self.attempt_count - self.succeeded_count

    @property
    def failed_value_paise(self) -> Paise:
        return self.attempted_value_paise - self.succeeded_value_paise

    @property
    def success_rate_ratio(self) -> Decimal:
        return ratio(self.succeeded_count, self.attempt_count)

    @property
    def technical_decline_ratio(self) -> Decimal:
        return ratio(self.technical_decline_count, self.attempt_count)

    @property
    def business_decline_ratio(self) -> Decimal:
        """Declines that are the customer's, not the platform's.

        Published beside the technical rate because the *asymmetry* between them
        is the evidence. Technical declines tripling while business declines
        stay flat is what attributes a movement to the rails rather than to
        customers running out of money; either number alone says nothing.
        """
        return ratio(self.business_decline_count, self.attempt_count)


def build_failure_window(
    period_from: date,
    period_to: date,
    payments: Iterable[PaymentRecord],
    excluded_transaction_ids: frozenset[str] = frozenset(),
    scope_method: str | None = None,
) -> FailureWindow:
    """Scope, then split by rail.

    ``scope_method`` narrows the whole window to one rail -- the shape of "why
    is UPI failing". The narrowed window is *not* comparable with the revenue
    bridge, and the tool says so in its limitations rather than publishing a
    partial figure under a portfolio name.
    """
    attempts = scope_attempts(period_from, period_to, payments, excluded_transaction_ids)
    if scope_method is not None:
        attempts = [record for record in attempts if record.method == scope_method]
    succeeded = [record for record in attempts if record.captured]

    slices = tuple(
        _slice(method, [record for record in attempts if record.method == method])
        for method in sorted({record.method for record in attempts})
    )

    return FailureWindow(
        period_from=period_from,
        period_to=period_to,
        scope_method=scope_method,
        attempt_count=len(attempts),
        succeeded_count=len(succeeded),
        attempted_value_paise=sum(record.amount_paise for record in attempts),
        succeeded_value_paise=sum(record.amount_paise for record in succeeded),
        technical_decline_count=sum(
            1 for record in attempts if record.decline_type == "TECHNICAL_DECLINE"
        ),
        business_decline_count=sum(
            1 for record in attempts if record.decline_type == "BUSINESS_DECLINE"
        ),
        by_method=slices,
        attempt_ids=tuple(record.id for record in attempts),
        succeeded_ids=tuple(record.id for record in succeeded),
    )


def _slice(method: str, records: list[PaymentRecord]) -> MethodSlice:
    succeeded = [record for record in records if record.captured]
    return MethodSlice(
        method=method,
        attempt_count=len(records),
        succeeded_count=len(succeeded),
        attempted_value_paise=sum(record.amount_paise for record in records),
        succeeded_value_paise=sum(record.amount_paise for record in succeeded),
        attempt_ids=tuple(record.id for record in records),
        succeeded_ids=tuple(record.id for record in succeeded),
    )


def method_changes(prior: FailureWindow, current: FailureWindow) -> dict[str, Decimal]:
    """Each rail's success-rate move, in percentage points.

    A rail present in one window and not the other is **absent** from the
    result rather than carrying a change against an assumed zero: a rail with
    no attempts has no success rate, and inventing one would put a -100 pp
    swing in front of a reader (Invariant 6).
    """
    before = {entry.method: entry for entry in prior.by_method}
    return {
        entry.method: pp_change(entry.success_rate_ratio, before[entry.method].success_rate_ratio)
        for entry in current.by_method
        if entry.method in before and before[entry.method].attempt_count > 0
    }
