"""The planner, the DAG, and every one of the eleven ways a plan is refused.

The exit criterion is that each rejection is *reachable* and returns *its own*
code. That is a stronger requirement than it looks: a validator where two checks
share a code, or where one check is unreachable because an earlier one always
fires first, passes a "the validator rejects bad plans" test and fails this one.

Nothing here touches a database. The policy is a value, which is the whole
reason it is one -- a validator that had to reach for a connection could not be
driven into eleven distinct states on demand.
"""

from datetime import date
from typing import Any

import pytest

from intent.models import Intent, IntentPeriod, IntentType
from orchestrator.planner import RECONCILE, PlanningError, build_plan, tools_for
from plan.models import ExecutionPlan, NodeRef, PlanNode
from tools.catalog import REGISTRY
from validation.plan_validator import REJECTION_CODES, parse_plan, validate_plan
from validation.policy import Policy

MERCHANT = "M123"
AUGUST = IntentPeriod(**{"from": date(2026, 8, 1), "to": date(2026, 8, 24)})
JULY = IntentPeriod(**{"from": date(2026, 7, 1), "to": date(2026, 7, 24)})

POLICY = Policy(
    merchant_id=MERCHANT,
    role="ANALYST",
    dataset_from=date(2026, 6, 1),
    dataset_to=date(2026, 9, 1),
)


def intent(kind: str = "revenue_diagnosis", **overrides: Any) -> Intent:
    fields: dict[str, Any] = {
        "intent": kind,
        "merchant_id": MERCHANT,
        "period": AUGUST,
        "comparison_period": JULY,
        "confidence_ratio": "0.95",
        **overrides,
    }
    return Intent.model_validate(fields)


def codes(plan: ExecutionPlan, policy: Policy = POLICY) -> tuple[str, ...]:
    return validate_plan(plan, policy, REGISTRY).codes


# --------------------------------------------------------------------------
# the planner
# --------------------------------------------------------------------------


class TestThePlanner:
    def test_revenue_diagnosis_is_reconciliation_then_four_analyses(self) -> None:
        plan = build_plan(intent())
        assert [node.id for node in plan.nodes] == [
            RECONCILE,
            "revenue",
            "failures",
            "refunds",
            "chargebacks",
        ]

    def test_the_four_analyses_are_one_layer(self) -> None:
        """They depend on reconciliation and on nothing else, so they run at once."""
        layers = build_plan(intent()).topological_layers()
        assert [len(layer) for layer in layers] == [1, 4]
        assert layers[0][0].id == RECONCILE

    def test_only_reconciliation_is_required(self) -> None:
        """Its failure fails the run; any other tool's costs one metric group."""
        plan = build_plan(intent())
        assert [node.id for node in plan.nodes if node.required] == [RECONCILE]

    def test_the_run_id_is_a_reference_not_a_value(self) -> None:
        """It does not exist until reconciliation has run."""
        plan = build_plan(intent())
        revenue = plan.node("revenue")
        assert revenue is not None
        assert revenue.references["run_id"] == NodeRef(from_node=RECONCILE, field="run_id")
        assert "run_id" not in revenue.inputs

    def test_reconciliation_status_plans_one_node(self) -> None:
        plan = build_plan(intent("reconciliation_status", comparison_period=None))
        assert len(plan.nodes) == 1
        assert plan.topological_layers() == [[plan.nodes[0]]]

    def test_a_narrow_intent_plans_only_its_own_tool(self) -> None:
        plan = build_plan(intent("refund_analysis"))
        assert [node.tool for node in plan.nodes] == [
            "finance.reconciliation",
            "finance.refund_analysis",
        ]

    def test_every_planned_tool_is_registered(self) -> None:
        kinds: tuple[IntentType, ...] = (
            "revenue_diagnosis",
            "failure_analysis",
            "reconciliation_status",
        )
        for kind in kinds:
            for tool in tools_for(kind):
                assert tool in REGISTRY

    def test_planning_without_a_period_raises_rather_than_defaulting(self) -> None:
        with pytest.raises(PlanningError, match="MISSING_PERIOD"):
            build_plan(intent(period=None))

    def test_planning_a_comparison_intent_without_one_raises(self) -> None:
        with pytest.raises(PlanningError, match="MISSING_COMPARISON_PERIOD"):
            build_plan(intent(comparison_period=None))


class TestTheGraph:
    def test_a_cycle_is_refused(self) -> None:
        plan = ExecutionPlan(
            intent="revenue_diagnosis",
            merchant_id=MERCHANT,
            period=AUGUST,
            nodes=[
                PlanNode(id="a", tool="finance.reconciliation", version="1.0", depends_on=["b"]),
                PlanNode(id="b", tool="finance.reconciliation", version="1.0", depends_on=["a"]),
            ],
        )
        with pytest.raises(ValueError, match="cycle"):
            plan.topological_layers()

    def test_a_repeated_node_id_is_refused_by_the_model(self) -> None:
        """Every `depends_on` naming it would be ambiguous."""
        with pytest.raises(ValueError, match="used more than once"):
            ExecutionPlan(
                intent="revenue_diagnosis",
                merchant_id=MERCHANT,
                period=AUGUST,
                nodes=[
                    PlanNode(id="a", tool="finance.reconciliation", version="1.0"),
                    PlanNode(id="a", tool="finance.reconciliation", version="1.0"),
                ],
            )


# --------------------------------------------------------------------------
# the eleven gates
# --------------------------------------------------------------------------


class TestValidation:
    def test_the_planner_s_own_plan_is_approved(self) -> None:
        assert validate_plan(build_plan(intent()), POLICY, REGISTRY).approved

    def test_invalid_plan_schema(self) -> None:
        rejection = parse_plan({"intent": "revenue_diagnosis", "nodes": []})
        assert not isinstance(rejection, ExecutionPlan)
        assert rejection.code == "INVALID_PLAN_SCHEMA"

    def test_unknown_tool(self) -> None:
        plan = build_plan(intent())
        broken = plan.model_copy(
            update={"nodes": [plan.nodes[0].model_copy(update={"version": "9.9"})]}
        )
        assert "UNKNOWN_TOOL" in codes(broken)

    def test_invalid_dag(self) -> None:
        plan = build_plan(intent())
        broken = plan.model_copy(
            update={
                "nodes": [
                    plan.nodes[0],
                    plan.nodes[1].model_copy(update={"depends_on": ["nowhere"]}),
                ]
            }
        )
        assert "INVALID_DAG" in codes(broken)

    def test_invalid_period(self) -> None:
        plan = build_plan(intent())
        backwards = IntentPeriod.model_construct(from_=date(2026, 8, 24), to=date(2026, 8, 1))
        assert "INVALID_PERIOD" in codes(plan.model_copy(update={"period": backwards}))

    def test_overlapping_periods(self) -> None:
        plan = build_plan(intent())
        overlapping = IntentPeriod(**{"from": date(2026, 8, 10), "to": date(2026, 8, 20)})
        assert "OVERLAPPING_PERIODS" in codes(
            plan.model_copy(update={"comparison_period": overlapping})
        )

    def test_period_out_of_range(self) -> None:
        plan = build_plan(intent())
        future = IntentPeriod(**{"from": date(2027, 1, 1), "to": date(2027, 2, 1)})
        assert "PERIOD_OUT_OF_RANGE" in codes(plan.model_copy(update={"period": future}))

    def test_unsupported_currency(self) -> None:
        plan = build_plan(intent())
        assert "UNSUPPORTED_CURRENCY" in codes(plan.model_copy(update={"currency": "USD"}))

    def test_merchant_scope_violation(self) -> None:
        """The second gate on C-13, after the parser's."""
        plan = build_plan(intent())
        assert "MERCHANT_SCOPE_VIOLATION" in codes(plan.model_copy(update={"merchant_id": "M999"}))

    def test_insufficient_permission(self) -> None:
        viewer = Policy(
            merchant_id=MERCHANT,
            role="VIEWER",
            dataset_from=POLICY.dataset_from,
            dataset_to=POLICY.dataset_to,
        )
        assert "INSUFFICIENT_PERMISSION" in codes(build_plan(intent()), viewer)

    def test_missing_tool_input(self) -> None:
        plan = build_plan(intent())
        stripped = plan.nodes[1].model_copy(update={"inputs": {"merchant_id": MERCHANT}})
        assert "MISSING_TOOL_INPUT" in codes(
            plan.model_copy(update={"nodes": [plan.nodes[0], stripped]})
        )

    def test_unresolved_input_reference(self) -> None:
        """The eleventh gate: a reference to a node this one does not wait for."""
        plan = build_plan(intent())
        detached = plan.nodes[1].model_copy(update={"depends_on": []})
        assert "UNRESOLVED_INPUT_REFERENCE" in codes(
            plan.model_copy(update={"nodes": [plan.nodes[0], detached]})
        )

    def test_every_declared_code_is_reachable(self) -> None:
        """The list and the checks agree, or a client is handling a code nothing emits."""
        reached = {
            "INVALID_PLAN_SCHEMA",
            "UNKNOWN_TOOL",
            "INVALID_DAG",
            "INVALID_PERIOD",
            "OVERLAPPING_PERIODS",
            "PERIOD_OUT_OF_RANGE",
            "UNSUPPORTED_CURRENCY",
            "MERCHANT_SCOPE_VIOLATION",
            "INSUFFICIENT_PERMISSION",
            "MISSING_TOOL_INPUT",
            "UNRESOLVED_INPUT_REFERENCE",
        }
        assert reached == set(REJECTION_CODES)
        assert len(REJECTION_CODES) == 11

    def test_every_reason_is_reported_not_just_the_first(self) -> None:
        """Fixing one problem should not reveal a second on the next submission."""
        plan = build_plan(intent())
        doubly = plan.model_copy(update={"merchant_id": "M999", "currency": "USD"})
        assert set(codes(doubly)) == {"MERCHANT_SCOPE_VIOLATION", "UNSUPPORTED_CURRENCY"}

    def test_the_reported_rejection_is_stable(self) -> None:
        """Same broken plan, same headline reason, regardless of check order."""
        plan = build_plan(intent())
        doubly = plan.model_copy(update={"merchant_id": "M999", "currency": "USD"})
        outcome = validate_plan(doubly, POLICY, REGISTRY)
        assert outcome.first is not None
        assert outcome.first.code == "UNSUPPORTED_CURRENCY"

    def test_a_rejection_renders_as_the_documented_shape(self) -> None:
        plan = build_plan(intent())
        outcome = validate_plan(plan.model_copy(update={"merchant_id": "M999"}), POLICY, REGISTRY)
        assert outcome.first is not None
        rendered = outcome.first.as_error()
        assert rendered["status"] == "rejected"
        assert rendered["code"] == "MERCHANT_SCOPE_VIOLATION"
        assert rendered["detail"] == {"requested": "M999", "authorised": MERCHANT}
