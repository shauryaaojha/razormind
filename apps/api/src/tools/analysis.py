"""What the four period-comparison tools have in common.

Revenue, failure, refund and chargeback analysis all take the same shape: a
window, something to compare it against, and the reconciliation run that says
which ledger rows are real. Writing that three more times would mean three more
chances for one of them to skip the overlap check or the run guard, and the
tool that skipped it would still return plausible numbers.
"""

from typing import Self

from pydantic import model_validator

from .base import Period, ToolContext, ToolError, ToolInput
from .repository import RunFacts, load_run_facts

__all__ = ["AnalysisInput", "load_run_facts_or_refuse", "unreconciled_comparison"]


class AnalysisInput(ToolInput):
    """A window, a comparison, and the run behind the window."""

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
                f"{self.period}; the shared payments would be counted on both sides"
            )
        return self


async def load_run_facts_or_refuse(inp: AnalysisInput, ctx: ToolContext) -> RunFacts:
    """The run must exist, belong to this merchant, and cover this period.

    Checked rather than assumed. A run over a different window would import
    another period's duplicates and another period's confidence band, and every
    figure would still be internally consistent -- around the wrong number.
    """
    facts = await load_run_facts(ctx.conn, inp.run_id)
    if facts is None:
        raise ToolError(
            "RUN_NOT_FOUND", f"no reconciliation run {inp.run_id}", {"run_id": inp.run_id}
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


def unreconciled_comparison(period: Period) -> str:
    """The limitation every one of these tools carries, worded once."""
    return (
        f"The comparison period {period} is not reconciled against bank settlements; its "
        "figures carry no duplicate exclusion and no confidence band."
    )
