"""Evidence rows built by hand, for the tests that must not run a tool.

Grounding and the explainer are judged against *published evidence*, and the
only way to hand them a wrong number is to write one. Getting one out of a real
tool would mean breaking the tool, and the test would then be measuring the
break rather than the gate.

Not a conftest: these are functions the tests call with arguments, not fixtures
pytest injects, and there are two conftest files on the path already.
"""

from decimal import Decimal

from evidence.models import Aggregation, Evidence, Formula
from evidence.vocabulary import METRICS

WINDOW = ("2026-08-01", "2026-08-24")
PRIOR = ("2026-07-01", "2026-07-24")
TOOL = "finance.revenue_analysis"
MERCHANT = "M123"


def leaf(
    metric_id: str,
    value: int,
    records: list[str],
    *,
    window: tuple[str, str] = WINDOW,
    over: str = "transactions",
    tool: str = TOOL,
) -> Evidence:
    """A metric folded straight out of the records it cites."""
    unit = METRICS[metric_id].unit
    return Evidence(
        id=f"{tool}/1.0/{metric_id}/{window[0]}_{window[1]}",
        execution_id="exec",
        tool_name=tool,
        tool_version="1.0",
        metric_id=metric_id,
        unit=unit,
        value=value,
        period_from=window[0],
        period_to=window[1],
        aggregation=Aggregation(
            operation="SUM",
            field_name="amount_paise",
            over=over,
            predicate="the records in the window",
            unit=unit,
            scoped_by="ATTEMPT_DATE",
        ),
        source_record_ids=records,
    )


def derived(
    metric_id: str,
    value: int | Decimal,
    expression: str,
    operands: dict[str, str],
    *,
    window: tuple[str, str] = WINDOW,
    tool: str = TOOL,
) -> Evidence:
    """A metric computed from other metrics, addressed by their evidence ids."""
    unit = METRICS[metric_id].unit
    return Evidence(
        id=f"{tool}/1.0/{metric_id}/{window[0]}_{window[1]}",
        execution_id="exec",
        tool_name=tool,
        tool_version="1.0",
        metric_id=metric_id,
        unit=unit,
        value=value,
        period_from=window[0],
        period_to=window[1],
        formula=Formula(expression=expression, operands=operands, unit=unit),
    )


def bridge() -> list[Evidence]:
    """A small revenue bridge, its comparison window, and two rates."""
    gross = leaf("gross_payments_paise", 40_626_000, ["TXN_1", "TXN_2"])
    refunds = leaf("refunds_paise", 1_178_200, ["RFND_1"], over="refunds")
    return [
        gross,
        refunds,
        derived(
            "net_revenue_paise",
            39_447_800,
            "gross - refunds",
            {"gross": gross.id, "refunds": refunds.id},
        ),
        leaf("gross_payments_paise", 49_974_000, ["TXN_9"], window=PRIOR),
        derived(
            "net_revenue_change_ratio",
            Decimal("-0.175956"),
            "(current - prior) / prior",
            {"current": "literal", "prior": "literal"},
        ),
        derived(
            "success_rate_ratio",
            Decimal("0.958012"),
            "succeeded / attempted",
            {"succeeded": "literal", "attempted": "literal"},
            tool="payments.failure_analysis",
        ),
        derived(
            "success_rate_pp_change",
            Decimal("-1.34"),
            "(current - prior) * hundred",
            {"current": "literal", "prior": "literal", "hundred": "literal"},
            tool="payments.failure_analysis",
        ),
    ]
