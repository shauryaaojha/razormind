"""What an execution plan is, and how it is layered for running.

A plan is a DAG of tool calls. Nothing in it is a computation -- it is a
statement of *which* computations to run, in what order, with which inputs. That
separation is what lets v2 hand plan construction to a model without
re-auditing the trust boundary: an LLM-proposed plan goes through the same
validator, and the validator does not soften.

**Inputs may reference an upstream node's output**, because they have to. Every
analysis tool needs the reconciliation `run_id`, and that value does not exist
until reconciliation has run. A :class:`NodeRef` says so explicitly -- naming the
node and the field -- rather than through string interpolation, so the validator
can check that the reference resolves and that the referenced node is actually a
dependency (D-45).
"""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from intent.models import IntentPeriod, IntentType

__all__ = ["ExecutionPlan", "NodeRef", "PlanNode", "Role"]

type Role = Literal["OWNER", "ANALYST", "VIEWER"]

#: Ascending privilege. A caller satisfies a node when their rank is at least
#: the node's.
ROLE_RANK: dict[str, int] = {"VIEWER": 0, "ANALYST": 1, "OWNER": 2}


class NodeRef(BaseModel):
    """An input taken from a node that ran earlier."""

    model_config = ConfigDict(frozen=True)

    from_node: str
    field: str

    def __str__(self) -> str:
        return f"{self.from_node}.{self.field}"


class PlanNode(BaseModel):
    """One tool call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    tool: str
    version: str
    inputs: dict[str, Any] = {}
    references: dict[str, NodeRef] = {}
    depends_on: list[str] = []
    required_role: Role = "ANALYST"
    #: A required node's failure fails the whole run. Only
    #: ``finance.reconciliation`` is one: every other tool reads the reconciled
    #: set, so proceeding without it produces numbers of unknown provenance.
    required: bool = False


class ExecutionPlan(BaseModel):
    """The whole DAG, plus the scope it runs under."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: IntentType
    merchant_id: str = Field(min_length=1, max_length=32)
    period: IntentPeriod
    comparison_period: IntentPeriod | None = None
    currency: str = "INR"
    nodes: list[PlanNode] = Field(min_length=1)

    @model_validator(mode="after")
    def _node_ids_are_unique(self) -> Self:
        """A repeated id makes every ``depends_on`` naming it ambiguous.

        Refused in the model rather than left to the validator because a plan
        with two nodes called ``reconcile`` has no single meaning to reject --
        the graph the validator would walk is already not the graph the author
        wrote.
        """
        seen = [node.id for node in self.nodes]
        duplicated = sorted({node for node in seen if seen.count(node) > 1})
        if duplicated:
            raise ValueError(f"node id(s) used more than once: {', '.join(duplicated)}")
        return self

    def node(self, node_id: str) -> PlanNode | None:
        return next((node for node in self.nodes if node.id == node_id), None)

    def topological_layers(self) -> list[list[PlanNode]]:
        """Nodes grouped so everything in a layer can run at once.

        Layers rather than a flat topological order, because the point is
        concurrency: the four analysis tools depend only on reconciliation and
        have no reason to wait for each other.

        Raises ``ValueError`` on a cycle. The validator calls this first and
        turns it into ``INVALID_DAG``; callers past validation can assume it
        holds.
        """
        remaining = {node.id: set(node.depends_on) for node in self.nodes}
        by_id = {node.id: node for node in self.nodes}
        layers: list[list[PlanNode]] = []

        while remaining:
            ready = sorted(node_id for node_id, waiting in remaining.items() if not waiting)
            if not ready:
                raise ValueError(
                    "plan has a dependency cycle among: " + ", ".join(sorted(remaining))
                )
            layers.append([by_id[node_id] for node_id in ready])
            for node_id in ready:
                del remaining[node_id]
            for waiting in remaining.values():
                waiting.difference_update(ready)
        return layers
