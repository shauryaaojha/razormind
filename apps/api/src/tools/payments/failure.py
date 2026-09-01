"""``payments.failure_analysis`` v1.0 -- where the payments went, and why.

Publishes the blended success rate and each rail's rate as **different metric
ids**. That is the fix for [C-03](../../../../docs/00-corrections.md): the
original vision put a UPI rate of 96.8% falling to 82.9% next to a
portfolio-level "14.3% increase in failures", with no derivation between them
and no unit on the second. Two numbers that mean different things cannot share
a name, and once they do not, an explainer cannot quietly substitute one for
the other.

The blended rate is not an average of the rail rates -- it is the ratio of the
summed counts, and ``verify()`` asserts that the rails' counts sum to the
blended ones exactly.

It takes a ``run_id`` for the same reason the revenue analysis does, and this
is not optional: the fixture's duplicated ledger row is a captured payment, so
without the run's duplicate set ``succeeded_value_paise`` would exceed
``gross_payments_paise`` by exactly one payment and the cross-tool consistency
check the spec asks for could never pass.
"""

from decimal import Decimal
from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, model_validator

from evidence.models import Evidence
from runtime.money import ZeroDenominatorError, pp_change, ratio
from verification.models import Checks, VerificationResult

from ..analysis import AnalysisInput, load_run_facts_or_refuse, unreconciled_comparison
from ..base import DeterministicTool, Period, ToolContext, ToolError
from ..publishing import EvidencePublisher
from ..records import PaymentRecord
from ..repository import load_payments
from .rates import FailureWindow, MethodSlice, build_failure_window, method_changes

__all__ = ["FailureAnalysisInput", "FailureAnalysisOutput", "FailureAnalysisTool"]


class FailureAnalysisInput(AnalysisInput):
    """The window, what to compare it against, the run, and optionally one rail."""

    method: str | None = None

    @model_validator(mode="after")
    def _method_is_a_rail(self) -> Self:
        if self.method is not None and self.method not in {"UPI", "CARD", "NETBANKING", "WALLET"}:
            raise ValueError(f"{self.method!r} is not a payment method")
        return self


class MethodBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: str
    attempt_count: int
    succeeded_count: int
    attempted_value_paise: int
    succeeded_value_paise: int
    failed_value_paise: int
    success_rate_ratio: str
    #: ``None`` when the rail had no attempts in the comparison period. A rail
    #: that did not exist has no rate to have moved from, and a zero would
    #: render as a -100 pp swing (Invariant 6).
    success_rate_pp_change: str | None


class FailureSide(BaseModel):
    """One period, blended."""

    model_config = ConfigDict(frozen=True)

    period: Period
    attempt_count: int
    succeeded_count: int
    failed_count: int
    attempted_value_paise: int
    succeeded_value_paise: int
    failed_value_paise: int
    success_rate_ratio: str
    technical_decline_ratio: str
    business_decline_ratio: str


class FailureSources(BaseModel):
    model_config = ConfigDict(frozen=True)

    attempt_transaction_ids: list[str]
    succeeded_transaction_ids: list[str]
    by_method_attempt_ids: dict[str, list[str]]
    by_method_succeeded_ids: dict[str, list[str]]


class FailureAnalysisOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    scope_method: str | None

    current: FailureSide
    prior: FailureSide

    success_rate_pp_change: str
    technical_decline_pp_change: str
    business_decline_pp_change: str

    by_method: list[MethodBreakdown]
    #: The same rails for the comparison period. Carried because a pp change
    #: must cite the two rates it was computed from -- recovering the prior rate
    #: by inverting the published change would make layer 4 re-derive the answer
    #: from the answer, which is a check that cannot fail.
    prior_by_method: list[MethodBreakdown]

    limitations: list[str]
    current_sources: FailureSources
    prior_sources: FailureSources


class FailureAnalysisTool(DeterministicTool[FailureAnalysisInput, FailureAnalysisOutput]):
    """Blended and per-rail success rates, with the decline taxonomy behind them."""

    name: ClassVar[str] = "payments.failure_analysis"
    version: ClassVar[str] = "1.0"
    input_model: ClassVar[type[BaseModel]] = FailureAnalysisInput
    output_model: ClassVar[type[BaseModel]] = FailureAnalysisOutput
    metrics: ClassVar[tuple[str, ...]] = (
        "attempt_count",
        "succeeded_count",
        "attempted_value_paise",
        "succeeded_value_paise",
        "failed_value_paise",
        "success_rate_ratio",
        "success_rate_pp_change",
        "technical_decline_ratio",
        "business_decline_ratio",
        "by_method.attempt_count",
        "by_method.succeeded_count",
        "by_method.attempted_value_paise",
        "by_method.succeeded_value_paise",
        "by_method.success_rate_ratio",
        "by_method.success_rate_pp_change",
    )

    async def execute(self, inp: FailureAnalysisInput, ctx: ToolContext) -> FailureAnalysisOutput:
        facts = await load_run_facts_or_refuse(inp, ctx)

        current = await self._window(ctx, inp, inp.period, facts.duplicate_transaction_ids)
        prior = await self._window(ctx, inp, inp.comparison_period, frozenset())

        try:
            changes = method_changes(prior, current)
            blended = pp_change(current.success_rate_ratio, prior.success_rate_ratio)
            technical = pp_change(current.technical_decline_ratio, prior.technical_decline_ratio)
            business = pp_change(current.business_decline_ratio, prior.business_decline_ratio)
        except ZeroDenominatorError as error:
            raise ToolError(
                "COMPARISON_PERIOD_EMPTY",
                f"no attempts in {inp.comparison_period}: {error}",
                {"comparison_period": str(inp.comparison_period)},
            ) from error

        return FailureAnalysisOutput(
            run_id=facts.run_id,
            scope_method=inp.method,
            current=_side(inp.period, current),
            prior=_side(inp.comparison_period, prior),
            success_rate_pp_change=f"{blended:.2f}",
            technical_decline_pp_change=f"{technical:.2f}",
            business_decline_pp_change=f"{business:.2f}",
            by_method=[_breakdown(entry, changes) for entry in current.by_method],
            prior_by_method=[_breakdown(entry, {}) for entry in prior.by_method],
            limitations=_limitations(inp, current, prior),
            current_sources=_sources(current),
            prior_sources=_sources(prior),
        )

    @staticmethod
    async def _window(
        ctx: ToolContext, inp: FailureAnalysisInput, period: Period, excluded: frozenset[str]
    ) -> FailureWindow:
        payments: list[PaymentRecord] = await load_payments(
            ctx.conn, inp.merchant_id, period.from_, period.to
        )
        return build_failure_window(period.from_, period.to, payments, excluded, inp.method)

    def verify(self, inp: FailureAnalysisInput, out: FailureAnalysisOutput) -> VerificationResult:
        """The blended figures must be the rails, summed. Not approximately."""
        checks = Checks()

        for label, side, sources in (
            ("current", out.current, out.current_sources),
            ("prior", out.prior, out.prior_sources),
        ):
            checks.equal(
                f"{label}_attempts_split_into_success_and_failure",
                side.succeeded_count + side.failed_count,
                side.attempt_count,
            )
            checks.equal(
                f"{label}_value_splits_the_same_way",
                side.succeeded_value_paise + side.failed_value_paise,
                side.attempted_value_paise,
            )
            checks.equal(
                f"{label}_success_rate_is_what_it_claims",
                side.success_rate_ratio,
                f"{ratio(side.succeeded_count, side.attempt_count):.6f}",
            )
            checks.equal(
                f"{label}_attempt_ids_support_the_count",
                len(sources.attempt_transaction_ids),
                side.attempt_count,
            )
            checks.equal(
                f"{label}_succeeded_ids_support_the_count",
                len(sources.succeeded_transaction_ids),
                side.succeeded_count,
            )
            checks.require(
                f"{label}_declines_do_not_exceed_failures",
                _rate(side.technical_decline_ratio) + _rate(side.business_decline_ratio)
                <= Decimal(1),
                "technical and business declines together exceed every attempt",
            )

        # ---- the blended rate falls out of the method mix, exactly ----
        checks.equal(
            "rails_attempts_sum_to_the_blended_count",
            sum(entry.attempt_count for entry in out.by_method),
            out.current.attempt_count,
        )
        checks.equal(
            "rails_successes_sum_to_the_blended_count",
            sum(entry.succeeded_count for entry in out.by_method),
            out.current.succeeded_count,
        )
        checks.equal(
            "rails_value_sums_to_the_blended_value",
            sum(entry.succeeded_value_paise for entry in out.by_method),
            out.current.succeeded_value_paise,
        )
        checks.require(
            "no_rail_rate_is_published_as_the_blended_rate",
            all(
                entry.success_rate_ratio != out.current.success_rate_ratio
                or entry.attempt_count == out.current.attempt_count
                for entry in out.by_method
            ),
            "a rail rate coincides with the blended rate without covering every attempt",
        )
        checks.equal(
            "blended_pp_change_is_what_it_claims",
            out.success_rate_pp_change,
            f"{pp_change(_rate(out.current.success_rate_ratio), _rate(out.prior.success_rate_ratio)):.2f}",
        )
        checks.require(
            "every_rail_rate_is_a_ratio",
            all(
                Decimal(0) <= _rate(entry.success_rate_ratio) <= Decimal(1)
                for entry in out.by_method
            ),
            "a rail success rate is outside [0, 1]",
        )
        checks.equal("run_is_the_requested_one", out.run_id, inp.run_id)
        checks.equal("scope_is_the_requested_one", out.scope_method, inp.method)
        return checks.result()

    def evidence(
        self, inp: FailureAnalysisInput, out: FailureAnalysisOutput, ctx: ToolContext
    ) -> list[Evidence]:
        publisher = EvidencePublisher(
            self.name, self.version, ctx.execution_id, list(self.verify(inp, out).checks)
        )
        rows: list[Evidence] = []
        for side, sources in (
            (out.current, out.current_sources),
            (out.prior, out.prior_sources),
        ):
            rows.extend(_blended_rows(publisher, side, sources))

        rows.extend(_method_rows(publisher, out))
        rows.append(
            publisher.derived(
                "success_rate_pp_change",
                out.current.period,
                Decimal(out.success_rate_pp_change),
                "(current - prior) * 100",
                {
                    "current": publisher.identifier("success_rate_ratio", out.current.period),
                    "prior": publisher.identifier("success_rate_ratio", out.prior.period),
                },
                {
                    "current": _rate(out.current.success_rate_ratio),
                    "prior": _rate(out.prior.success_rate_ratio),
                },
                [
                    "a percentage point is not a percent; the conversion happens once, in "
                    "runtime.money.pp_change (C-04)"
                ],
            )
        )
        return rows


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------


def _rate(text: str) -> Decimal:
    return Decimal(text)


def _breakdown(entry: MethodSlice, changes: dict[str, Decimal]) -> MethodBreakdown:
    return MethodBreakdown(
        method=entry.method,
        attempt_count=entry.attempt_count,
        succeeded_count=entry.succeeded_count,
        attempted_value_paise=entry.attempted_value_paise,
        succeeded_value_paise=entry.succeeded_value_paise,
        failed_value_paise=entry.failed_value_paise,
        success_rate_ratio=f"{entry.success_rate_ratio:.6f}",
        success_rate_pp_change=(
            f"{changes[entry.method]:.2f}" if entry.method in changes else None
        ),
    )


def _side(period: Period, window: FailureWindow) -> FailureSide:
    return FailureSide(
        period=period,
        attempt_count=window.attempt_count,
        succeeded_count=window.succeeded_count,
        failed_count=window.failed_count,
        attempted_value_paise=window.attempted_value_paise,
        succeeded_value_paise=window.succeeded_value_paise,
        failed_value_paise=window.failed_value_paise,
        success_rate_ratio=f"{window.success_rate_ratio:.6f}",
        technical_decline_ratio=f"{window.technical_decline_ratio:.6f}",
        business_decline_ratio=f"{window.business_decline_ratio:.6f}",
    )


def _sources(window: FailureWindow) -> FailureSources:
    return FailureSources(
        attempt_transaction_ids=list(window.attempt_ids),
        succeeded_transaction_ids=list(window.succeeded_ids),
        by_method_attempt_ids={entry.method: list(entry.attempt_ids) for entry in window.by_method},
        by_method_succeeded_ids={
            entry.method: list(entry.succeeded_ids) for entry in window.by_method
        },
    )


def _limitations(
    inp: FailureAnalysisInput, current: FailureWindow, prior: FailureWindow
) -> list[str]:
    limitations = [unreconciled_comparison(inp.comparison_period)]
    if inp.method is not None:
        limitations.append(
            f"Every figure is scoped to {inp.method}. These are not portfolio figures and do "
            "not correspond to the revenue bridge, which covers every rail."
        )
    missing = {entry.method for entry in prior.by_method} - {
        entry.method for entry in current.by_method
    }
    if missing:
        limitations.append(
            f"{', '.join(sorted(missing))} had attempts in the comparison period and none in "
            "the analysis period, so no change is reported for it."
        )
    return limitations


def _blended_rows(
    publisher: EvidencePublisher, side: FailureSide, sources: FailureSources
) -> list[Evidence]:
    period = side.period
    attempted = (
        f"IST attempt date in [{period.from_}, {period.to}) -- attempts, not captures, "
        "because a failure has no capture instant"
    )
    succeeded = f"{attempted}, and status = CAPTURED"
    return [
        publisher.tally(
            "attempt_count",
            period,
            side.attempt_count,
            "transactions",
            attempted,
            "ATTEMPT_DATE",
            sources.attempt_transaction_ids,
        ),
        publisher.tally(
            "succeeded_count",
            period,
            side.succeeded_count,
            "transactions",
            succeeded,
            "ATTEMPT_DATE",
            sources.succeeded_transaction_ids,
        ),
        publisher.total(
            "attempted_value_paise",
            period,
            side.attempted_value_paise,
            "amount_paise",
            "transactions",
            attempted,
            "ATTEMPT_DATE",
            sources.attempt_transaction_ids,
        ),
        publisher.total(
            "succeeded_value_paise",
            period,
            side.succeeded_value_paise,
            "amount_paise",
            "transactions",
            succeeded,
            "ATTEMPT_DATE",
            sources.succeeded_transaction_ids,
        ),
        publisher.derived(
            "failed_value_paise",
            period,
            side.failed_value_paise,
            "attempted - succeeded",
            {
                "attempted": publisher.identifier("attempted_value_paise", period),
                "succeeded": publisher.identifier("succeeded_value_paise", period),
            },
            {
                "attempted": side.attempted_value_paise,
                "succeeded": side.succeeded_value_paise,
            },
            ["value that was attempted and not captured"],
        ),
        publisher.derived(
            "success_rate_ratio",
            period,
            Decimal(side.success_rate_ratio),
            "succeeded / attempts",
            {
                "succeeded": publisher.identifier("succeeded_count", period),
                "attempts": publisher.identifier("attempt_count", period),
            },
            {"succeeded": side.succeeded_count, "attempts": side.attempt_count},
            ["the blended rate is the ratio of summed counts, not an average of the rail rates"],
        ),
    ]


def _method_rows(publisher: EvidencePublisher, out: FailureAnalysisOutput) -> list[Evidence]:
    rows: list[Evidence] = []
    for side, breakdown, sources in (
        (out.current, out.by_method, out.current_sources),
        (out.prior, out.prior_by_method, out.prior_sources),
    ):
        for entry in breakdown:
            rows.extend(_rail_rows(publisher, side.period, entry, sources))

    prior_rates = {entry.method: entry for entry in out.prior_by_method}
    for entry in out.by_method:
        if entry.success_rate_pp_change is None:
            continue
        rail = entry.method
        rows.append(
            publisher.derived(
                "by_method.success_rate_pp_change",
                out.current.period,
                Decimal(entry.success_rate_pp_change),
                "(current - prior) * 100",
                {
                    "current": publisher.identifier(
                        "by_method.success_rate_ratio", out.current.period, rail
                    ),
                    "prior": publisher.identifier(
                        "by_method.success_rate_ratio", out.prior.period, rail
                    ),
                },
                {
                    "current": Decimal(entry.success_rate_ratio),
                    "prior": Decimal(prior_rates[rail].success_rate_ratio),
                },
                [f"{rail} rate movement, in percentage points"],
                dimension_value=rail,
            )
        )
    return rows


def _rail_rows(
    publisher: EvidencePublisher,
    period: Period,
    entry: MethodBreakdown,
    sources: FailureSources,
) -> list[Evidence]:
    rail = entry.method
    attempts = sources.by_method_attempt_ids.get(rail, [])
    succeeded = sources.by_method_succeeded_ids.get(rail, [])
    predicate = f"attempts in the window on the {rail} rail"
    return [
        publisher.tally(
            "by_method.attempt_count",
            period,
            entry.attempt_count,
            "transactions",
            predicate,
            "ATTEMPT_DATE",
            attempts,
            rail,
        ),
        publisher.tally(
            "by_method.succeeded_count",
            period,
            entry.succeeded_count,
            "transactions",
            f"{predicate}, and status = CAPTURED",
            "ATTEMPT_DATE",
            succeeded,
            rail,
        ),
        publisher.total(
            "by_method.attempted_value_paise",
            period,
            entry.attempted_value_paise,
            "amount_paise",
            "transactions",
            predicate,
            "ATTEMPT_DATE",
            attempts,
            rail,
        ),
        publisher.total(
            "by_method.succeeded_value_paise",
            period,
            entry.succeeded_value_paise,
            "amount_paise",
            "transactions",
            f"{predicate}, and status = CAPTURED",
            "ATTEMPT_DATE",
            succeeded,
            rail,
        ),
        publisher.derived(
            "by_method.success_rate_ratio",
            period,
            Decimal(entry.success_rate_ratio),
            "succeeded / attempts",
            {
                "succeeded": publisher.identifier("by_method.succeeded_count", period, rail),
                "attempts": publisher.identifier("by_method.attempt_count", period, rail),
            },
            {"succeeded": entry.succeeded_count, "attempts": entry.attempt_count},
            [f"{rail} only; a different metric from the blended rate (C-03)"],
            dimension_value=rail,
        ),
    ]
