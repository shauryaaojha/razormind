"""``finance.revenue_analysis`` v1.0 -- the bridge, and why it moved.

The hardest tool in the set, and the one that proves the contract is usable.
It publishes eleven metrics across two windows, and every one of them has to
survive layer 4 of verification: the verifier re-evaluates the declared formula
against the declared operands and demands the same number back.

It takes a ``run_id`` because reconciliation is an *input* to revenue, not a
report published beside it. The run supplies two things of different kinds:

* the ledger rows flagged ``POSSIBLE_DUPLICATE``, which change the numbers -- a
  duplicated capture is not revenue and must come out of gross;
* the unresolved exception value, which changes **no** number. It is reported
  as a confidence band on the whole bridge. Netting it in was the third of
  C-02's three errors, and it stays out (Invariant 7).
"""

from decimal import Decimal
from typing import ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from evidence.models import Aggregation, Evidence, Formula
from runtime.money import Paise, ZeroDenominatorError, ratio
from verification.models import Checks, VerificationResult

from ..base import DeterministicTool, Period, ToolContext, ToolError, ToolInput
from .bridge import DRIVERS, Attribution, RevenueWindow, attribute, build_window
from .repository import (
    RunFacts,
    load_chargebacks,
    load_payments,
    load_refunds,
    load_run_facts,
)

__all__ = ["RevenueAnalysisInput", "RevenueAnalysisOutput", "RevenueAnalysisTool"]


class RevenueAnalysisInput(ToolInput):
    """The analysis window, what to compare it against, and the run behind it."""

    comparison_period: Period
    run_id: str

    @model_validator(mode="after")
    def _periods_are_disjoint(self) -> Self:
        overlaps = self.comparison_period.from_ < self.period.to and (
            self.period.from_ < self.comparison_period.to
        )
        if overlaps:
            raise ValueError(
                f"comparison period {self.comparison_period} overlaps the analysis period "
                f"{self.period}; the shared payments would be counted on both sides of the bridge"
            )
        return self


class RevenueBridge(BaseModel):
    """One window, decomposed. ``net`` is derived, never stored independently."""

    model_config = ConfigDict(frozen=True)

    period: Period
    attempt_count: int
    capture_count: int
    attempted_value_paise: int
    gross_payments_paise: int
    refunds_paise: int
    fees_paise: int
    chargebacks_paise: int
    net_revenue_paise: int
    success_rate_ratio: str


class WindowSources(BaseModel):
    """The records behind one window, so ``evidence(inp, out)`` needs no re-query."""

    model_config = ConfigDict(frozen=True)

    attempt_transaction_ids: list[str]
    capture_transaction_ids: list[str]
    refund_ids: list[str]
    chargeback_ids: list[str]


class AttributionTerm(BaseModel):
    model_config = ConfigDict(frozen=True)

    driver: str
    effect_paise: int
    #: ``None`` when net revenue did not move: a share of nothing is not zero,
    #: it is undefined, and Invariant 6 forbids inventing the zero.
    share_of_change_ratio: str | None


class RevenueAnalysisOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    current: RevenueBridge
    prior: RevenueBridge

    net_revenue_change_paise: int
    net_revenue_change_ratio: str

    attribution: list[AttributionTerm]
    #: Mandatory, computed as the plug, and asserted small. A residual larger
    #: than the number of terms means a formula error, not rounding.
    rounding_residual_paise: int

    unresolved_exception_value_paise: int
    confidence_band_ratio: str

    limitations: list[str]
    current_sources: WindowSources
    prior_sources: WindowSources


class RevenueAnalysisTool(DeterministicTool[RevenueAnalysisInput, RevenueAnalysisOutput]):
    """The revenue bridge for two periods, plus the attribution between them."""

    name: ClassVar[str] = "finance.revenue_analysis"
    version: ClassVar[str] = "1.0"
    input_model: ClassVar[type[BaseModel]] = RevenueAnalysisInput
    output_model: ClassVar[type[BaseModel]] = RevenueAnalysisOutput
    metrics: ClassVar[tuple[str, ...]] = (
        "attempted_value_paise",
        "gross_payments_paise",
        "refunds_paise",
        "fees_paise",
        "chargebacks_paise",
        "net_revenue_paise",
        "net_revenue_change_paise",
        "net_revenue_change_ratio",
        "attribution.attempt_volume_effect_paise",
        "attribution.success_rate_effect_paise",
        "attribution.refunds_effect_paise",
        "attribution.fees_effect_paise",
        "attribution.chargebacks_effect_paise",
        "rounding_residual_paise",
        "confidence_band_ratio",
    )

    async def execute(self, inp: RevenueAnalysisInput, ctx: ToolContext) -> RevenueAnalysisOutput:
        facts = await self._run_facts(inp, ctx)

        current = await self._window(
            ctx, inp.merchant_id, inp.period, facts.duplicate_transaction_ids
        )
        prior = await self._window(ctx, inp.merchant_id, inp.comparison_period, frozenset())

        try:
            attribution = attribute(prior, current)
        except ZeroDenominatorError as error:
            # A prior window with no attempts, or no net revenue, has no
            # proportion to apply. That is an explicit limitation, never a zero.
            raise ToolError(
                "COMPARISON_PERIOD_EMPTY",
                f"cannot attribute against {inp.comparison_period}: {error}",
                {"comparison_period": str(inp.comparison_period)},
            ) from error

        return RevenueAnalysisOutput(
            run_id=facts.run_id,
            current=_bridge(inp.period, current),
            prior=_bridge(inp.comparison_period, prior),
            net_revenue_change_paise=attribution.net_change_paise,
            net_revenue_change_ratio=f"{attribution.net_change_ratio:.6f}",
            attribution=[
                AttributionTerm(
                    driver=effect.driver,
                    effect_paise=effect.effect_paise,
                    share_of_change_ratio=_share(effect.effect_paise, attribution),
                )
                for effect in attribution.effects
            ],
            rounding_residual_paise=attribution.rounding_residual_paise,
            unresolved_exception_value_paise=facts.unresolved_paise,
            confidence_band_ratio=f"{ratio(facts.unresolved_paise, current.net_revenue_paise):.6f}",
            limitations=_limitations(facts, prior),
            current_sources=_sources(current),
            prior_sources=_sources(prior),
        )

    async def _run_facts(self, inp: RevenueAnalysisInput, ctx: ToolContext) -> RunFacts:
        """The run must exist, belong to this merchant, and cover this period.

        Checked rather than assumed. A run over a different window would import
        another period's duplicates and another period's confidence band, and
        the bridge would still close -- around the wrong number.
        """
        facts = await load_run_facts(ctx.conn, inp.run_id)
        if facts is None:
            raise ToolError(
                "RUN_NOT_FOUND",
                f"no reconciliation run {inp.run_id}",
                {"run_id": inp.run_id},
            )
        if facts.merchant_id != inp.merchant_id:
            raise ToolError(
                "MERCHANT_SCOPE_VIOLATION",
                f"run {inp.run_id} belongs to another merchant",
                {"run_id": inp.run_id},
            )
        if (facts.period_from, facts.period_to) != (inp.period.from_, inp.period.to):
            raise ToolError(
                "RUN_PERIOD_MISMATCH",
                f"run {inp.run_id} covers [{facts.period_from}, {facts.period_to}), "
                f"but the analysis period is {inp.period}",
                {"run_id": inp.run_id, "analysis_period": str(inp.period)},
            )
        return facts

    @staticmethod
    async def _window(
        ctx: ToolContext, merchant_id: str, period: Period, excluded: frozenset[str]
    ) -> RevenueWindow:
        payments = await load_payments(ctx.conn, merchant_id, period.from_, period.to)
        captured = [record.id for record in payments if record.captured]
        return build_window(
            period.from_,
            period.to,
            payments,
            await load_refunds(ctx.conn, merchant_id, captured),
            await load_chargebacks(ctx.conn, merchant_id, captured),
            excluded,
        )

    def verify(self, inp: RevenueAnalysisInput, out: RevenueAnalysisOutput) -> VerificationResult:
        """The bridge identity, the delta identity, and the residual bound.

        docs/06-trust-layer.md#bridge-identity. These are the checks C-02 would
        have failed: its bridge did not close, its refund and fee terms entered
        as gross values rather than deltas, and its unresolved exceptions were
        netted into the result.
        """
        checks = Checks()

        for label, window, sources in (
            ("current", out.current, out.current_sources),
            ("prior", out.prior, out.prior_sources),
        ):
            checks.equal(
                f"{label}_bridge_closes",
                window.net_revenue_paise,
                window.gross_payments_paise
                - window.refunds_paise
                - window.fees_paise
                - window.chargebacks_paise,
            )
            checks.require(
                f"{label}_deductions_are_not_negative",
                min(window.refunds_paise, window.fees_paise, window.chargebacks_paise) >= 0,
                "a deduction is negative",
            )
            checks.require(
                f"{label}_captures_do_not_exceed_attempts",
                window.capture_count <= window.attempt_count,
                f"{window.capture_count} captures out of {window.attempt_count} attempts",
            )
            checks.require(
                f"{label}_gross_does_not_exceed_attempted",
                window.gross_payments_paise <= window.attempted_value_paise,
                f"gross {window.gross_payments_paise} over attempted "
                f"{window.attempted_value_paise}",
            )
            checks.equal(
                f"{label}_attempt_ids_support_the_count",
                len(sources.attempt_transaction_ids),
                window.attempt_count,
            )
            checks.equal(
                f"{label}_capture_ids_support_the_count",
                len(sources.capture_transaction_ids),
                window.capture_count,
            )
            checks.equal(
                f"{label}_success_rate_is_what_it_claims",
                window.success_rate_ratio,
                f"{ratio(window.capture_count, window.attempt_count):.6f}",
            )

        checks.equal(
            "delta_is_current_minus_prior",
            out.net_revenue_change_paise,
            out.current.net_revenue_paise - out.prior.net_revenue_paise,
        )
        checks.equal(
            "change_ratio_is_what_it_claims",
            out.net_revenue_change_ratio,
            f"{ratio(out.net_revenue_change_paise, out.prior.net_revenue_paise):.6f}",
        )

        effects = sum(term.effect_paise for term in out.attribution)
        checks.equal(
            "attribution_closes",
            effects + out.rounding_residual_paise,
            out.net_revenue_change_paise,
        )
        checks.require(
            "residual_is_rounding_not_a_formula_error",
            abs(out.rounding_residual_paise) <= len(out.attribution),
            f"residual {out.rounding_residual_paise} exceeds the "
            f"{len(out.attribution)} attribution terms",
        )
        checks.equal(
            "every_driver_is_attributed",
            [term.driver for term in out.attribution],
            list(DRIVERS),
        )

        checks.require(
            "unresolved_value_is_a_band_not_a_term",
            out.unresolved_exception_value_paise >= 0
            and all(term.driver != "UNRESOLVED" for term in out.attribution),
            "unresolved exception value has leaked into the bridge",
        )
        checks.equal(
            "confidence_band_is_what_it_claims",
            out.confidence_band_ratio,
            f"{ratio(out.unresolved_exception_value_paise, out.current.net_revenue_paise):.6f}",
        )
        checks.equal("run_is_the_requested_one", out.run_id, inp.run_id)
        checks.equal(
            "periods_are_the_requested_ones",
            (out.current.period, out.prior.period),
            (inp.period, inp.comparison_period),
        )
        return checks.result()

    def evidence(
        self, inp: RevenueAnalysisInput, out: RevenueAnalysisOutput, ctx: ToolContext
    ) -> list[Evidence]:
        checked = list(self.verify(inp, out).checks)
        builder = _EvidenceBuilder(self.name, self.version, ctx.execution_id, checked)

        rows: list[Evidence] = []
        for window, sources in (
            (out.current, out.current_sources),
            (out.prior, out.prior_sources),
        ):
            rows.extend(builder.window(window, sources))
        rows.extend(builder.change(out))
        return rows


# --------------------------------------------------------------------------
# output assembly
# --------------------------------------------------------------------------


def _bridge(period: Period, window: RevenueWindow) -> RevenueBridge:
    return RevenueBridge(
        period=period,
        attempt_count=window.attempt_count,
        capture_count=window.capture_count,
        attempted_value_paise=window.attempted_value_paise,
        gross_payments_paise=window.gross_payments_paise,
        refunds_paise=window.refunds_paise,
        fees_paise=window.fees_paise,
        chargebacks_paise=window.chargebacks_paise,
        net_revenue_paise=window.net_revenue_paise,
        success_rate_ratio=f"{window.success_rate_ratio:.6f}",
    )


def _sources(window: RevenueWindow) -> WindowSources:
    return WindowSources(
        attempt_transaction_ids=list(window.attempt_ids),
        capture_transaction_ids=list(window.capture_ids),
        refund_ids=list(window.refund_ids),
        chargeback_ids=list(window.chargeback_ids),
    )


def _share(effect_paise: Paise, attribution: Attribution) -> str | None:
    if attribution.net_change_paise == 0:
        return None
    return f"{ratio(effect_paise, attribution.net_change_paise):.6f}"


def _limitations(facts: RunFacts, prior: RevenueWindow) -> list[str]:
    """What this answer does not cover, said out loud (Invariant 6)."""
    limitations = [
        f"The comparison period [{prior.period_from}, {prior.period_to}) is not reconciled "
        "against bank settlements; its gross carries no duplicate exclusion and no "
        "confidence band.",
        f"{facts.unresolved_paise} paise of the analysis period is unconfirmed by the bank "
        "and is reported as a band, not netted into any figure.",
    ]
    if facts.duplicate_transaction_ids:
        limitations.append(
            f"{len(facts.duplicate_transaction_ids)} ledger record(s) flagged as possible "
            "duplicates by run "
            f"{facts.run_id} are excluded from gross: "
            f"{', '.join(sorted(facts.duplicate_transaction_ids))}."
        )
    return limitations


# --------------------------------------------------------------------------
# evidence
# --------------------------------------------------------------------------


class _EvidenceBuilder:
    """Turns a published output into the rows that let someone disbelieve it.

    An operand reference is an evidence id of this tool's own rows where one
    exists, ``<tool>.<metric_id>`` for a metric another tool owns, and
    ``"literal"`` otherwise. That is what lets the provenance drawer be a
    generic recursive renderer: every operand either resolves to more evidence
    or terminates.
    """

    def __init__(self, tool: str, version: str, execution_id: str, checks: list[str]) -> None:
        self.tool = tool
        self.version = version
        self.execution_id = execution_id
        self.checks = checks

    def identifier(self, metric_id: str, period: Period) -> str:
        return f"{self.tool}/{self.version}/{metric_id}/{period.from_}_{period.to}"

    def _row(
        self,
        metric_id: str,
        period: Period,
        unit: Literal["paise", "ratio", "count"],
        value: int | Decimal,
        *,
        formula: Formula | None = None,
        aggregation: Aggregation | None = None,
        inputs: dict[str, int | Decimal],
        source_record_ids: list[str],
        rules: list[str],
    ) -> Evidence:
        return Evidence(
            id=self.identifier(metric_id, period),
            execution_id=self.execution_id,
            tool_name=self.tool,
            tool_version=self.version,
            metric_id=metric_id,
            unit=unit,
            value=value,
            period_from=period.from_.isoformat(),
            period_to=period.to.isoformat(),
            formula=formula,
            aggregation=aggregation,
            inputs=inputs,
            source_record_ids=source_record_ids,
            rules_applied=rules,
            verification_checks=self.checks,
        )

    def _sum(
        self,
        metric_id: str,
        period: Period,
        value: int,
        field_name: str,
        over: str,
        predicate: str,
        record_ids: list[str],
    ) -> Evidence:
        """A leaf: no arithmetic to re-evaluate, only records to re-sum."""
        return self._row(
            metric_id,
            period,
            "paise",
            value,
            aggregation=Aggregation(
                operation="SUM",
                field_name=field_name,
                over=over,
                predicate=predicate,
                unit="paise",
            ),
            inputs={"record_count": len(record_ids)},
            source_record_ids=record_ids,
            rules=[predicate],
        )

    def window(self, bridge: RevenueBridge, sources: WindowSources) -> list[Evidence]:
        period = bridge.period
        attempted = (
            f"IST attempt date in [{period.from_}, {period.to}) -- attempts, not captures, "
            "because a failure has no capture instant"
        )
        captured = f"{attempted}, and status = CAPTURED"
        reversal = (
            "tied to a capture in the window; a refund belongs to the period of the payment "
            "it reverses, not the period it was raised in"
        )
        return [
            self._sum(
                "attempted_value_paise",
                period,
                bridge.attempted_value_paise,
                "amount_paise",
                "transactions",
                attempted,
                sources.attempt_transaction_ids,
            ),
            self._sum(
                "gross_payments_paise",
                period,
                bridge.gross_payments_paise,
                "amount_paise",
                "transactions",
                captured,
                sources.capture_transaction_ids,
            ),
            self._sum(
                "fees_paise",
                period,
                bridge.fees_paise,
                "fee_paise",
                "transactions",
                captured + "; the fee follows the instrument, not a flat rate (D-24)",
                sources.capture_transaction_ids,
            ),
            self._sum(
                "refunds_paise",
                period,
                bridge.refunds_paise,
                "amount_paise",
                "refunds",
                reversal,
                sources.refund_ids,
            ),
            self._sum(
                "chargebacks_paise",
                period,
                bridge.chargebacks_paise,
                "amount_paise",
                "chargebacks",
                reversal,
                sources.chargeback_ids,
            ),
            self._row(
                "net_revenue_paise",
                period,
                "paise",
                bridge.net_revenue_paise,
                formula=Formula(
                    expression="gross - refunds - fees - chargebacks",
                    operands={
                        "gross": self.identifier("gross_payments_paise", period),
                        "refunds": self.identifier("refunds_paise", period),
                        "fees": self.identifier("fees_paise", period),
                        "chargebacks": self.identifier("chargebacks_paise", period),
                    },
                    unit="paise",
                ),
                inputs={
                    "gross": bridge.gross_payments_paise,
                    "refunds": bridge.refunds_paise,
                    "fees": bridge.fees_paise,
                    "chargebacks": bridge.chargebacks_paise,
                },
                source_record_ids=[],
                rules=["bridge identity (docs/06-trust-layer.md#bridge-identity)"],
            ),
        ]

    def change(self, out: RevenueAnalysisOutput) -> list[Evidence]:
        """Metrics about the movement between the two windows.

        Filed under the **analysis** period: a change is a property of the
        window being explained, and the comparison window is named in the
        operands rather than in the identity.
        """
        current, prior = out.current, out.prior
        here, there = current.period, prior.period
        net_current = self.identifier("net_revenue_paise", here)
        net_prior = self.identifier("net_revenue_paise", there)
        effects = {term.driver: term.effect_paise for term in out.attribution}

        rows = [
            self._row(
                "net_revenue_change_paise",
                here,
                "paise",
                out.net_revenue_change_paise,
                formula=Formula(
                    expression="current - prior",
                    operands={"current": net_current, "prior": net_prior},
                    unit="paise",
                ),
                inputs={"current": current.net_revenue_paise, "prior": prior.net_revenue_paise},
                source_record_ids=[],
                rules=["delta identity"],
            ),
            self._row(
                "net_revenue_change_ratio",
                here,
                "ratio",
                Decimal(out.net_revenue_change_ratio),
                formula=Formula(
                    expression="(current - prior) / prior",
                    operands={"current": net_current, "prior": net_prior},
                    unit="ratio",
                ),
                inputs={"current": current.net_revenue_paise, "prior": prior.net_revenue_paise},
                source_record_ids=[],
                rules=["ratio at scale 6, rounded half-up once (D-01)"],
            ),
            self._row(
                "attribution.attempt_volume_effect_paise",
                here,
                "paise",
                effects["ATTEMPT_VOLUME"],
                formula=Formula(
                    # rate_prior * (attempted_current - attempted_prior), applied
                    # as a single rounding rather than materialising the rate.
                    expression=(
                        "(attempted_current - attempted_prior) * gross_prior / attempted_prior"
                    ),
                    operands={
                        "attempted_current": self.identifier("attempted_value_paise", here),
                        "attempted_prior": self.identifier("attempted_value_paise", there),
                        "gross_prior": self.identifier("gross_payments_paise", there),
                    },
                    unit="paise",
                ),
                inputs={
                    "attempted_current": current.attempted_value_paise,
                    "attempted_prior": prior.attempted_value_paise,
                    "gross_prior": prior.gross_payments_paise,
                },
                source_record_ids=[],
                rules=["rate/volume split (docs/06-trust-layer.md#bridge-identity)"],
            ),
            self._row(
                "attribution.success_rate_effect_paise",
                here,
                "paise",
                effects["SUCCESS_RATE"],
                formula=Formula(
                    # The exact remainder of the volume effect, not a second
                    # independent rounding: rounding both is how a bridge stops
                    # closing.
                    expression="(gross_current - gross_prior) - volume",
                    operands={
                        "gross_current": self.identifier("gross_payments_paise", here),
                        "gross_prior": self.identifier("gross_payments_paise", there),
                        "volume": self.identifier("attribution.attempt_volume_effect_paise", here),
                    },
                    unit="paise",
                ),
                inputs={
                    "gross_current": current.gross_payments_paise,
                    "gross_prior": prior.gross_payments_paise,
                    "volume": effects["ATTEMPT_VOLUME"],
                },
                source_record_ids=[],
                rules=["rate/volume split, computed as the remainder"],
            ),
        ]

        for driver, metric_id, field_name in (
            ("REFUNDS", "attribution.refunds_effect_paise", "refunds_paise"),
            ("FEES", "attribution.fees_effect_paise", "fees_paise"),
            ("CHARGEBACKS", "attribution.chargebacks_effect_paise", "chargebacks_paise"),
        ):
            rows.append(
                self._row(
                    metric_id,
                    here,
                    "paise",
                    effects[driver],
                    formula=Formula(
                        # A delta, negated: more refunds is less revenue.
                        # Entering these as gross values was C-02 error #2.
                        expression="prior - current",
                        operands={
                            "current": self.identifier(field_name, here),
                            "prior": self.identifier(field_name, there),
                        },
                        unit="paise",
                    ),
                    inputs={
                        "current": getattr(current, field_name),
                        "prior": getattr(prior, field_name),
                    },
                    source_record_ids=[],
                    rules=["deductions enter the bridge as deltas, never as gross values"],
                )
            )

        rows.append(
            self._row(
                "rounding_residual_paise",
                here,
                "paise",
                out.rounding_residual_paise,
                formula=Formula(
                    expression="change - volume - rate - refunds - fees - chargebacks",
                    operands={
                        "change": self.identifier("net_revenue_change_paise", here),
                        "volume": self.identifier("attribution.attempt_volume_effect_paise", here),
                        "rate": self.identifier("attribution.success_rate_effect_paise", here),
                        "refunds": self.identifier("attribution.refunds_effect_paise", here),
                        "fees": self.identifier("attribution.fees_effect_paise", here),
                        "chargebacks": self.identifier(
                            "attribution.chargebacks_effect_paise", here
                        ),
                    },
                    unit="paise",
                ),
                inputs={
                    "change": out.net_revenue_change_paise,
                    "volume": effects["ATTEMPT_VOLUME"],
                    "rate": effects["SUCCESS_RATE"],
                    "refunds": effects["REFUNDS"],
                    "fees": effects["FEES"],
                    "chargebacks": effects["CHARGEBACKS"],
                },
                source_record_ids=[],
                rules=["the plug; abs(residual) <= term count, or it is a formula error"],
            )
        )
        rows.append(
            self._row(
                "confidence_band_ratio",
                here,
                "ratio",
                Decimal(out.confidence_band_ratio),
                formula=Formula(
                    expression="unresolved / net",
                    operands={
                        "unresolved": "finance.reconciliation.unresolved_exception_value_paise",
                        "net": net_current,
                    },
                    unit="ratio",
                ),
                inputs={
                    "unresolved": out.unresolved_exception_value_paise,
                    "net": current.net_revenue_paise,
                },
                source_record_ids=[],
                rules=["a band on the bridge, never a term in it (Invariant 7)"],
            )
        )
        return rows
