"""Eleven gates, and nothing runs until every one of them passes.

docs/05-agent-runtime.md#validation. A rejection is a **structured object**, not
an exception message: the UI renders it, the failure tests assert on its `code`,
and the eval suite counts them. A rejection that could only be read by a human
is a rejection nothing can be built on.

Two properties are the whole point:

* **It fires before any tool runs.** A rejected plan leaves no reconciliation
  run, no evidence, no partial answer -- `REJECTED` is terminal and nothing
  executed.
* **It does not know or care who wrote the plan.** Today the planner is
  deterministic. In v2 a model proposes plans from `registry.describe()`, and
  this file does not change. That is what makes handing planning to a model a
  swap rather than a re-audit.

Every check is evaluated, not short-circuited. "Your period is backwards" and
"your period is backwards *and* names another merchant" call for different
responses, and a validator that stopped at the first would make the second
invisible until the user fixed the first and resubmitted.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from plan.models import ExecutionPlan, PlanNode
from tools.base import ToolError
from tools.registry import ToolRegistry

from .policy import Policy

__all__ = [
    "REJECTION_CODES",
    "Rejection",
    "ValidationOutcome",
    "validate_plan",
]

#: Every way a plan can be refused. Exhaustive on purpose: a rejection with a
#: code nobody listed is a rejection no client can handle.
REJECTION_CODES: tuple[str, ...] = (
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
)


@dataclass(frozen=True)
class Rejection:
    """One reason a plan may not run."""

    code: str
    message: str
    detail: dict[str, Any]

    def as_error(self) -> dict[str, Any]:
        return {
            "status": "rejected",
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ValidationOutcome:
    """Every reason the plan was refused, or none."""

    rejections: tuple[Rejection, ...]

    @property
    def approved(self) -> bool:
        return not self.rejections

    @property
    def first(self) -> Rejection | None:
        """The rejection to report when only one can be shown.

        In ``REJECTION_CODES`` order rather than discovery order, so the same
        broken plan always reports the same reason -- a message that changes
        with dict iteration is a message nobody can write a test against.
        """
        if not self.rejections:
            return None
        return min(self.rejections, key=lambda item: REJECTION_CODES.index(item.code))

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(rejection.code for rejection in self.rejections)


def parse_plan(raw: Mapping[str, Any]) -> ExecutionPlan | Rejection:
    """The schema gate. A plan that is not an ``ExecutionPlan`` is not a plan.

    Kept apart from :func:`validate_plan` because the other ten checks need a
    parsed plan to read: there is no meaningful "does the period start before it
    ends" question to ask of a dict that has no period.
    """
    try:
        return ExecutionPlan.model_validate(dict(raw))
    except ValidationError as error:
        return Rejection(
            "INVALID_PLAN_SCHEMA",
            "The plan does not match the execution-plan schema.",
            {"errors": [_readable(item) for item in error.errors()]},
        )


def validate_plan(plan: ExecutionPlan, policy: Policy, registry: ToolRegistry) -> ValidationOutcome:
    """Every gate, all of them evaluated."""
    found: list[Rejection] = []
    found.extend(_scope(plan, policy))
    found.extend(_periods(plan, policy))
    found.extend(_graph(plan))
    found.extend(_nodes(plan, policy, registry))
    return ValidationOutcome(tuple(found))


# --------------------------------------------------------------------------


def _scope(plan: ExecutionPlan, policy: Policy) -> list[Rejection]:
    found: list[Rejection] = []
    if plan.merchant_id != policy.merchant_id:
        found.append(
            Rejection(
                "MERCHANT_SCOPE_VIOLATION",
                "The plan names a merchant this session is not scoped to.",
                {"requested": plan.merchant_id, "authorised": policy.merchant_id},
            )
        )
    if plan.currency != policy.currency:
        found.append(
            Rejection(
                "UNSUPPORTED_CURRENCY",
                f"Only {policy.currency} is supported.",
                {"requested": plan.currency},
            )
        )
    return found


def _periods(plan: ExecutionPlan, policy: Policy) -> list[Rejection]:
    found: list[Rejection] = []
    windows = [("period", plan.period)]
    if plan.comparison_period is not None:
        windows.append(("comparison_period", plan.comparison_period))

    for name, window in windows:
        if window.from_ >= window.to:
            found.append(
                Rejection(
                    "INVALID_PERIOD",
                    f"{name} starts on or after it ends.",
                    {name: {"from": window.from_.isoformat(), "to": window.to.isoformat()}},
                )
            )
        elif not policy.covers(window.from_, window.to):
            found.append(
                Rejection(
                    "PERIOD_OUT_OF_RANGE",
                    f"{name} reaches outside the available data.",
                    {
                        name: {"from": window.from_.isoformat(), "to": window.to.isoformat()},
                        "available": {
                            "from": policy.dataset_from.isoformat(),
                            "to": policy.dataset_to.isoformat(),
                        },
                    },
                )
            )

    comparison = plan.comparison_period
    if comparison is not None and (
        comparison.from_ < plan.period.to and plan.period.from_ < comparison.to
    ):
        # Not a stylistic objection. Payments in the overlap are counted on both
        # sides of the comparison, so the change between the two windows is
        # partly a comparison of a set with itself.
        found.append(
            Rejection(
                "OVERLAPPING_PERIODS",
                "Comparison period overlaps the analysis period.",
                {
                    "period": {
                        "from": plan.period.from_.isoformat(),
                        "to": plan.period.to.isoformat(),
                    },
                    "comparison_period": {
                        "from": comparison.from_.isoformat(),
                        "to": comparison.to.isoformat(),
                    },
                },
            )
        )
    return found


def _graph(plan: ExecutionPlan) -> list[Rejection]:
    known = {node.id for node in plan.nodes}
    dangling = sorted(
        f"{node.id} -> {required}"
        for node in plan.nodes
        for required in node.depends_on
        if required not in known
    )
    if dangling:
        return [
            Rejection(
                "INVALID_DAG",
                "A node depends on something that is not in the plan.",
                {"unresolved": dangling},
            )
        ]
    try:
        plan.topological_layers()
    except ValueError as error:
        return [Rejection("INVALID_DAG", str(error), {"nodes": sorted(known)})]
    return []


def _nodes(plan: ExecutionPlan, policy: Policy, registry: ToolRegistry) -> list[Rejection]:
    found: list[Rejection] = []
    by_id = {node.id: node for node in plan.nodes}

    for node in plan.nodes:
        try:
            tool = registry.resolve(node.tool, node.version)
        except ToolError:
            # A plan naming a tool nobody registered is a rejection, not an
            # exception: the caller gets a code, and nothing has run.
            found.append(
                Rejection(
                    "UNKNOWN_TOOL",
                    f"No tool {node.tool} at version {node.version}.",
                    {"node": node.id, "tool": node.tool, "version": node.version},
                )
            )
            continue

        if not policy.permits(node.required_role):
            found.append(
                Rejection(
                    "INSUFFICIENT_PERMISSION",
                    f"{node.tool} requires {node.required_role}; the caller is {policy.role}.",
                    {"node": node.id, "required": node.required_role, "caller": policy.role},
                )
            )

        found.extend(_references(node, by_id))
        found.extend(_inputs(node, tool.input_model, plan))
    return found


def _references(node: PlanNode, by_id: Mapping[str, PlanNode]) -> list[Rejection]:
    """A referenced value must come from a node this one waits for.

    The eleventh gate, which docs/05-agent-runtime.md did not list. It has to
    exist because every analysis tool takes the reconciliation ``run_id``, and
    that value does not exist until reconciliation has run: a reference to a
    node that is not a dependency resolves to nothing, and "nothing" would
    arrive at the tool as a missing input at execution time rather than as a
    rejection before anything ran (D-45).
    """
    found: list[Rejection] = []
    for name, reference in sorted(node.references.items()):
        if reference.from_node not in by_id:
            found.append(
                Rejection(
                    "UNRESOLVED_INPUT_REFERENCE",
                    f"{node.id}.{name} reads from {reference.from_node}, which is not in the plan.",
                    {"node": node.id, "input": name, "reference": str(reference)},
                )
            )
        elif reference.from_node not in node.depends_on:
            found.append(
                Rejection(
                    "UNRESOLVED_INPUT_REFERENCE",
                    f"{node.id}.{name} reads from {reference.from_node}, "
                    "which it does not depend on and may not have run yet.",
                    {"node": node.id, "input": name, "reference": str(reference)},
                )
            )
    return found


def _inputs(node: PlanNode, input_model: Any, plan: ExecutionPlan) -> list[Rejection]:
    """Every required input is present and typed, references counted as supplied.

    Validated against the tool's own input model rather than a second list of
    field names, so a tool that gains a required field gains this check for free.
    """
    del plan
    candidate = dict(node.inputs)
    for name in node.references:
        # Filled at execution time from the upstream node. A placeholder that
        # satisfies the type is enough here: the reference check above is what
        # proves the real value will exist.
        candidate.setdefault(name, "pending")

    try:
        input_model.model_validate(candidate)
    except ValidationError as error:
        return [
            Rejection(
                "MISSING_TOOL_INPUT",
                f"{node.tool} was not given the inputs it declares.",
                {"node": node.id, "errors": [_readable(item) for item in error.errors()]},
            )
        ]
    return []


def _readable(error: Mapping[str, Any]) -> str:
    location = ".".join(str(part) for part in error.get("loc", ()))
    return f"{location or '<root>'}: {error.get('msg', 'invalid')}"
