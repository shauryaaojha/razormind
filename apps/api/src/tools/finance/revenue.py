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
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from evidence.models import Evidence
from runtime.money import Paise, ZeroDenominatorError, ratio
from verification.models import Checks, VerificationResult

from ..analysis import AnalysisInput, load_run_facts_or_refuse
from ..base import DeterministicTool, Period, ToolContext, ToolError
from ..publishing import EvidencePublisher
from ..repository import RunFacts, load_chargebacks, load_payments, load_refunds
from .bridge import DRIVERS, Attribution, RevenueWindow, attribute, build_window

__all__ = ["RevenueAnalysisInput", "RevenueAnalysisOutput", "RevenueAnalysisTool"]


class RevenueAnalysisInput(AnalysisInput):
    """The analysis window, what to compare it against, and the run behind it."""


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
        facts = await load_run_facts_or_refuse(inp, ctx)

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


class _EvidenceBuilder(EvidencePublisher):
    """The revenue bridge, expressed as rows someone can disbelieve.

    Only the two shapes specific to this tool live here -- one window's lines,
    and the metrics about the movement between two windows. Ids, units and the
    leaf/derived split come from ``EvidencePublisher``, so four tools cannot
    drift into four conventions.
    """

    def window(self, bridge: RevenueBridge, sources: WindowSources) -> list[Evidence]:
        period = bridge.period
        attempted = (
            f"IST attempt date in [{period.from_}, {period.to}) -- attempts, not captures, "
            "because a failure has no capture instant"
        )
        captured = f"{attempted}, and status = CAPTURED"
        reversal = (
            "tied to a capture in the window; a refund belongs to the period of the payment "
            "it reverses, not the period it was raised in (D-31)"
        )
        return [
            self.total(
                "attempted_value_paise",
                period,
                bridge.attempted_value_paise,
                "amount_paise",
                "transactions",
                attempted,
                sources.attempt_transaction_ids,
            ),
            self.total(
                "gross_payments_paise",
                period,
                bridge.gross_payments_paise,
                "amount_paise",
                "transactions",
                captured,
                sources.capture_transaction_ids,
            ),
            self.total(
                "fees_paise",
                period,
                bridge.fees_paise,
                "fee_paise",
                "transactions",
                captured + "; the fee follows the instrument, not a flat rate (D-24)",
                sources.capture_transaction_ids,
            ),
            self.total(
                "refunds_paise",
                period,
                bridge.refunds_paise,
                "amount_paise",
                "refunds",
                reversal,
                sources.refund_ids,
            ),
            self.total(
                "chargebacks_paise",
                period,
                bridge.chargebacks_paise,
                "amount_paise",
                "chargebacks",
                reversal,
                sources.chargeback_ids,
            ),
            self.derived(
                "net_revenue_paise",
                period,
                bridge.net_revenue_paise,
                "gross - refunds - fees - chargebacks",
                {
                    "gross": self.identifier("gross_payments_paise", period),
                    "refunds": self.identifier("refunds_paise", period),
                    "fees": self.identifier("fees_paise", period),
                    "chargebacks": self.identifier("chargebacks_paise", period),
                },
                {
                    "gross": bridge.gross_payments_paise,
                    "refunds": bridge.refunds_paise,
                    "fees": bridge.fees_paise,
                    "chargebacks": bridge.chargebacks_paise,
                },
                ["bridge identity (docs/06-trust-layer.md#bridge-identity)"],
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
            self.derived(
                "net_revenue_change_paise",
                here,
                out.net_revenue_change_paise,
                "current - prior",
                {"current": net_current, "prior": net_prior},
                {"current": current.net_revenue_paise, "prior": prior.net_revenue_paise},
                ["delta identity"],
            ),
            self.derived(
                "net_revenue_change_ratio",
                here,
                Decimal(out.net_revenue_change_ratio),
                "(current - prior) / prior",
                {"current": net_current, "prior": net_prior},
                {"current": current.net_revenue_paise, "prior": prior.net_revenue_paise},
                ["ratio at scale 6, rounded half-up once (D-01)"],
            ),
            self.derived(
                "attribution.attempt_volume_effect_paise",
                here,
                effects["ATTEMPT_VOLUME"],
                # rate_prior * (attempted_current - attempted_prior), applied as
                # a single rounding rather than materialising the rate first.
                "(attempted_current - attempted_prior) * gross_prior / attempted_prior",
                {
                    "attempted_current": self.identifier("attempted_value_paise", here),
                    "attempted_prior": self.identifier("attempted_value_paise", there),
                    "gross_prior": self.identifier("gross_payments_paise", there),
                },
                {
                    "attempted_current": current.attempted_value_paise,
                    "attempted_prior": prior.attempted_value_paise,
                    "gross_prior": prior.gross_payments_paise,
                },
                ["rate/volume split (docs/06-trust-layer.md#bridge-identity)"],
            ),
            self.derived(
                "attribution.success_rate_effect_paise",
                here,
                effects["SUCCESS_RATE"],
                # The exact remainder of the volume effect, not a second
                # independent rounding: rounding both is how a bridge stops
                # closing.
                "(gross_current - gross_prior) - volume",
                {
                    "gross_current": self.identifier("gross_payments_paise", here),
                    "gross_prior": self.identifier("gross_payments_paise", there),
                    "volume": self.identifier("attribution.attempt_volume_effect_paise", here),
                },
                {
                    "gross_current": current.gross_payments_paise,
                    "gross_prior": prior.gross_payments_paise,
                    "volume": effects["ATTEMPT_VOLUME"],
                },
                ["rate/volume split, computed as the remainder"],
            ),
        ]

        for driver, metric_id, field_name in (
            ("REFUNDS", "attribution.refunds_effect_paise", "refunds_paise"),
            ("FEES", "attribution.fees_effect_paise", "fees_paise"),
            ("CHARGEBACKS", "attribution.chargebacks_effect_paise", "chargebacks_paise"),
        ):
            rows.append(
                self.derived(
                    metric_id,
                    here,
                    effects[driver],
                    # A delta, negated: more refunds is less revenue. Entering
                    # these as gross values was C-02 error #2.
                    "prior - current",
                    {
                        "current": self.identifier(field_name, here),
                        "prior": self.identifier(field_name, there),
                    },
                    {
                        "current": getattr(current, field_name),
                        "prior": getattr(prior, field_name),
                    },
                    ["deductions enter the bridge as deltas, never as gross values"],
                )
            )

        rows.append(
            self.derived(
                "rounding_residual_paise",
                here,
                out.rounding_residual_paise,
                "change - volume - rate - refunds - fees - chargebacks",
                {
                    "change": self.identifier("net_revenue_change_paise", here),
                    "volume": self.identifier("attribution.attempt_volume_effect_paise", here),
                    "rate": self.identifier("attribution.success_rate_effect_paise", here),
                    "refunds": self.identifier("attribution.refunds_effect_paise", here),
                    "fees": self.identifier("attribution.fees_effect_paise", here),
                    "chargebacks": self.identifier("attribution.chargebacks_effect_paise", here),
                },
                {
                    "change": out.net_revenue_change_paise,
                    "volume": effects["ATTEMPT_VOLUME"],
                    "rate": effects["SUCCESS_RATE"],
                    "refunds": effects["REFUNDS"],
                    "fees": effects["FEES"],
                    "chargebacks": effects["CHARGEBACKS"],
                },
                ["the plug; abs(residual) <= term count, or it is a formula error"],
            )
        )
        rows.append(
            self.derived(
                "confidence_band_ratio",
                here,
                Decimal(out.confidence_band_ratio),
                "unresolved / net",
                {
                    "unresolved": self.cross_tool(
                        "finance.reconciliation", "unresolved_exception_value_paise"
                    ),
                    "net": net_current,
                },
                {
                    "unresolved": out.unresolved_exception_value_paise,
                    "net": current.net_revenue_paise,
                },
                ["a band on the bridge, never a term in it (Invariant 7)"],
            )
        )
        return rows
