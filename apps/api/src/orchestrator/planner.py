"""Intent to DAG. Deterministic, and no model anywhere near it.

docs/05-agent-runtime.md#planning. In v0 and v1 an intent type maps to a fixed
graph. The model chose *which question this is*; it does not choose which tools
answer it, in what order, or with what inputs.

That is not a limitation to be lifted later so much as the thing that makes
lifting it safe. v2 lets a model propose a plan from ``registry.describe()``,
and the validator does not soften for it — an LLM-proposed plan passes exactly
the same eleven gates. Because those gates already exist and already run, the
planner can be swapped without re-auditing the trust boundary.

Every graph has the same shape: reconciliation first and alone, then the
analyses, which depend on it and on nothing else. They take the run id as a
:class:`NodeRef`, because the value does not exist until the first layer has
finished, and because a plan that pretended to know it in advance would be
lying about where its numbers came from.
"""

from intent.models import Intent, IntentType
from plan.models import ExecutionPlan, NodeRef, PlanNode

__all__ = ["RECONCILE", "PlanningError", "build_plan", "tools_for"]

#: The one node every plan starts with, and the only one marked ``required``.
RECONCILE = "reconcile"

#: Intent -> the analyses that answer it. Reconciliation is implicit: it is not
#: an answer to anything on its own except ``reconciliation_status``, and it is
#: an input to everything else (D-32).
ANALYSES: dict[IntentType, tuple[tuple[str, str], ...]] = {
    "revenue_diagnosis": (
        ("revenue", "finance.revenue_analysis"),
        ("failures", "payments.failure_analysis"),
        ("refunds", "finance.refund_analysis"),
        ("chargebacks", "risk.chargeback_analysis"),
    ),
    "reconciliation_status": (),
    "failure_analysis": (("failures", "payments.failure_analysis"),),
    "refund_analysis": (("refunds", "finance.refund_analysis"),),
    "chargeback_analysis": (("chargebacks", "risk.chargeback_analysis"),),
}

#: Pinned per plan, not resolved at execution time. An execution that ran
#: against v1.0 must still say v1.0 a year later, when v2.0 is what
#: ``resolve()`` would return -- its evidence names the formula that actually
#: produced the number.
VERSION = "1.0"


class PlanningError(Exception):
    """The intent cannot be turned into a plan."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def tools_for(intent: IntentType) -> tuple[str, ...]:
    """Every tool a plan for this intent will call, reconciliation included."""
    return ("finance.reconciliation", *(tool for _, tool in ANALYSES[intent]))


def build_plan(intent: Intent) -> ExecutionPlan:
    """The fixed graph for this intent.

    Raises rather than defaulting when the intent is missing a window the graph
    needs. The parser's clarification gate should have caught it first; getting
    here means something bypassed the gate, and inventing a period at this depth
    would put an unasked-for window into every node at once.
    """
    if intent.period is None:
        raise PlanningError("MISSING_PERIOD", "an intent with no period cannot be planned")
    analyses = ANALYSES[intent.intent]
    if analyses and intent.comparison_period is None:
        raise PlanningError(
            "MISSING_COMPARISON_PERIOD",
            f"{intent.intent} compares two windows and only one was given",
        )

    window = {"from": intent.period.from_, "to": intent.period.to}
    nodes = [
        PlanNode(
            id=RECONCILE,
            tool="finance.reconciliation",
            version=VERSION,
            inputs={"merchant_id": intent.merchant_id, "period": window},
            required=True,
        )
    ]
    if intent.comparison_period is not None:
        comparison = {
            "from": intent.comparison_period.from_,
            "to": intent.comparison_period.to,
        }
        nodes.extend(
            PlanNode(
                id=node_id,
                tool=tool,
                version=VERSION,
                inputs={
                    "merchant_id": intent.merchant_id,
                    "period": window,
                    "comparison_period": comparison,
                },
                # The run id does not exist yet. Naming where it comes from is
                # what lets the validator check the dependency is real.
                references={"run_id": NodeRef(from_node=RECONCILE, field="run_id")},
                depends_on=[RECONCILE],
            )
            for node_id, tool in analyses
        )

    return ExecutionPlan(
        intent=intent.intent,
        merchant_id=intent.merchant_id,
        period=intent.period,
        comparison_period=intent.comparison_period,
        nodes=nodes,
    )
