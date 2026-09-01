"""``risk.chargeback_analysis`` v1.0 -- what was disputed, and at what rate.

Structurally identical to the refund analysis and deliberately built from the
same module: ``chargeback_value_paise`` must equal the revenue bridge's
``chargebacks_paise`` to the paise, and a second implementation of "sum the
chargebacks against captures in this window" is the most likely way for that to
stop being true.

``chargeback_rate_ratio`` is a **value** rate -- disputed value over gross. The
card networks' monitoring thresholds are a *count* ratio over transactions,
which is a different quantity with a different denominator. It is not published
under this name, because a rate that is sometimes one and sometimes the other
is exactly the ambiguity C-04 exists to remove; ``chargeback_count`` is
published beside it so a count-based ratio can be built without guessing which
one a reader is looking at.
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
from ..repository import load_chargebacks, load_payments
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

__all__ = ["ChargebackAnalysisInput", "ChargebackAnalysisOutput", "ChargebackAnalysisTool"]

NAMING = ReversalNaming(
    value_metric="chargeback_value_paise",
    count_metric="chargeback_count",
    rate_metric="chargeback_rate_ratio",
    change_metric="chargeback_value_change_paise",
    by_reason_value_metric="by_reason.chargeback_value_paise",
    by_reason_count_metric="by_reason.chargeback_count",
    table="chargebacks",
    noun="chargeback",
    bridge_metric="chargebacks_paise",
)


class ChargebackAnalysisInput(AnalysisInput):
    """Window, comparison, and the run that says which captures are real."""


class ChargebackAnalysisOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    current: ReversalSide
    prior: ReversalSide
    chargeback_value_change_paise: int

    limitations: list[str]
    current_sources: ReversalSources
    prior_sources: ReversalSources


class ChargebackAnalysisTool(DeterministicTool[ChargebackAnalysisInput, ChargebackAnalysisOutput]):
    """Chargeback value, rate against gross, movement, and the reasons behind it."""

    name: ClassVar[str] = "risk.chargeback_analysis"
    version: ClassVar[str] = "1.0"
    input_model: ClassVar[type[BaseModel]] = ChargebackAnalysisInput
    output_model: ClassVar[type[BaseModel]] = ChargebackAnalysisOutput
    metrics: ClassVar[tuple[str, ...]] = (
        "chargeback_value_paise",
        "chargeback_count",
        "chargeback_rate_ratio",
        "chargeback_value_change_paise",
        "gross_payments_paise",
        "by_reason.chargeback_value_paise",
        "by_reason.chargeback_count",
    )

    async def execute(
        self, inp: ChargebackAnalysisInput, ctx: ToolContext
    ) -> ChargebackAnalysisOutput:
        facts = await load_run_facts_or_refuse(inp, ctx)
        current = await self._window(ctx, inp, inp.period, facts.duplicate_transaction_ids)
        prior = await self._window(ctx, inp, inp.comparison_period, frozenset())

        try:
            current_side = side(inp.period, current)
            prior_side = side(inp.comparison_period, prior)
        except ZeroDenominatorError as error:
            raise ToolError(
                "NO_GROSS_TO_RATE_AGAINST",
                f"no captured payments to compute a chargeback rate against: {error}",
                {"period": str(inp.period)},
            ) from error

        return ChargebackAnalysisOutput(
            run_id=facts.run_id,
            current=current_side,
            prior=prior_side,
            chargeback_value_change_paise=current.value_paise - prior.value_paise,
            limitations=[unreconciled_comparison(inp.comparison_period)],
            current_sources=sources(current),
            prior_sources=sources(prior),
        )

    @staticmethod
    async def _window(
        ctx: ToolContext,
        inp: ChargebackAnalysisInput,
        period: Period,
        excluded: frozenset[str],
    ) -> MovementWindow:
        payments = await load_payments(ctx.conn, inp.merchant_id, period.from_, period.to)
        captured = [record.id for record in payments if record.captured]
        return build_movement_window(
            period.from_,
            period.to,
            payments,
            await load_chargebacks(ctx.conn, inp.merchant_id, captured),
            excluded,
        )

    def verify(
        self, inp: ChargebackAnalysisInput, out: ChargebackAnalysisOutput
    ) -> VerificationResult:
        return verify_reversal(
            out.current,
            out.prior,
            out.current_sources,
            out.prior_sources,
            out.chargeback_value_change_paise,
            NAMING,
        )

    def evidence(
        self, inp: ChargebackAnalysisInput, out: ChargebackAnalysisOutput, ctx: ToolContext
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
            change_row(publisher, out.current, out.prior, out.chargeback_value_change_paise, NAMING)
        )
        return rows
