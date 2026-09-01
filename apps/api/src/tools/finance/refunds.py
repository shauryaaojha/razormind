"""``finance.refund_analysis`` v1.0 -- how much came back, and why.

Publishes ``refund_value_paise``, which must equal the revenue bridge's
``refunds_paise`` to the paise. The two names are deliberate: the bridge calls
it a deduction, this tool calls it the subject, and the vocabulary's
equivalence table is what makes the consistency layer compare them at all.

The arithmetic lives in ``tools/reversals.py``, shared with the chargeback
tool. Two copies would eventually disagree about some edge, and the cross-tool
check would then be finding a bug this module created rather than one it exists
to catch.
"""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from evidence.models import Evidence
from runtime.money import ZeroDenominatorError
from verification.models import VerificationResult

from ..analysis import AnalysisInput, load_run_facts_or_refuse, unreconciled_comparison
from ..base import DeterministicTool, Period, ToolContext, ToolError
from ..movements import MovementWindow, build_movement_window
from ..publishing import EvidencePublisher
from ..repository import load_payments, load_refunds
from ..reversals import (
    ReversalNaming,
    ReversalSide,
    ReversalSources,
    change_row,
    reversal_rows,
    side,
    sources,
    verify_reversal,
)

__all__ = ["RefundAnalysisInput", "RefundAnalysisOutput", "RefundAnalysisTool"]

NAMING = ReversalNaming(
    value_metric="refund_value_paise",
    count_metric="refund_count",
    rate_metric="refund_rate_ratio",
    change_metric="refund_value_change_paise",
    by_reason_value_metric="by_reason.refund_value_paise",
    by_reason_count_metric="by_reason.refund_count",
    table="refunds",
    noun="refund",
    bridge_metric="refunds_paise",
)


class RefundAnalysisInput(AnalysisInput):
    """Window, comparison, and the run that says which captures are real."""


class RefundAnalysisOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    current: ReversalSide
    prior: ReversalSide
    refund_value_change_paise: int

    limitations: list[str]
    current_sources: ReversalSources
    prior_sources: ReversalSources


class RefundAnalysisTool(DeterministicTool[RefundAnalysisInput, RefundAnalysisOutput]):
    """Refund value, rate against gross, movement, and the reasons behind it."""

    name: ClassVar[str] = "finance.refund_analysis"
    version: ClassVar[str] = "1.0"
    input_model: ClassVar[type[BaseModel]] = RefundAnalysisInput
    output_model: ClassVar[type[BaseModel]] = RefundAnalysisOutput
    metrics: ClassVar[tuple[str, ...]] = (
        "refund_value_paise",
        "refund_count",
        "refund_rate_ratio",
        "refund_value_change_paise",
        "gross_payments_paise",
        "by_reason.refund_value_paise",
        "by_reason.refund_count",
    )

    async def execute(self, inp: RefundAnalysisInput, ctx: ToolContext) -> RefundAnalysisOutput:
        facts = await load_run_facts_or_refuse(inp, ctx)
        current = await self._window(ctx, inp, inp.period, facts.duplicate_transaction_ids)
        prior = await self._window(ctx, inp, inp.comparison_period, frozenset())

        try:
            current_side = side(inp.period, current)
            prior_side = side(inp.comparison_period, prior)
        except ZeroDenominatorError as error:
            # No captured payments means there is nothing for a refund to be a
            # rate *of*. That is a limitation, not a zero (Invariant 6).
            raise ToolError(
                "NO_GROSS_TO_RATE_AGAINST",
                f"no captured payments to compute a refund rate against: {error}",
                {"period": str(inp.period)},
            ) from error

        return RefundAnalysisOutput(
            run_id=facts.run_id,
            current=current_side,
            prior=prior_side,
            refund_value_change_paise=current.value_paise - prior.value_paise,
            limitations=[unreconciled_comparison(inp.comparison_period)],
            current_sources=sources(current),
            prior_sources=sources(prior),
        )

    @staticmethod
    async def _window(
        ctx: ToolContext, inp: RefundAnalysisInput, period: Period, excluded: frozenset[str]
    ) -> MovementWindow:
        payments = await load_payments(ctx.conn, inp.merchant_id, period.from_, period.to)
        captured = [record.id for record in payments if record.captured]
        return build_movement_window(
            period.from_,
            period.to,
            payments,
            await load_refunds(ctx.conn, inp.merchant_id, captured),
            excluded,
        )

    def verify(self, inp: RefundAnalysisInput, out: RefundAnalysisOutput) -> VerificationResult:
        return verify_reversal(
            out.current,
            out.prior,
            out.current_sources,
            out.prior_sources,
            out.refund_value_change_paise,
            NAMING,
        )

    def evidence(
        self, inp: RefundAnalysisInput, out: RefundAnalysisOutput, ctx: ToolContext
    ) -> list[Evidence]:
        publisher = EvidencePublisher(
            self.name, self.version, ctx.execution_id, list(self.verify(inp, out).checks)
        )
        rows: list[Evidence] = []
        for entry, entry_sources in (
            (out.current, out.current_sources),
            (out.prior, out.prior_sources),
        ):
            rows.extend(reversal_rows(publisher, entry, entry_sources, NAMING))
        rows.append(
            change_row(publisher, out.current, out.prior, out.refund_value_change_paise, NAMING)
        )
        return rows
