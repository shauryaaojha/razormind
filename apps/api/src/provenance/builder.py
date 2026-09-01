"""Walking a number down to the records it came from.

docs/06-trust-layer.md#provenance. Every authoritative number resolves to source
records, and this is what does the resolving:

```text
net_revenue_change_ratio  -0.175956
  (current - prior) / prior
  +-- current  net_revenue_paise  39012295
  |     gross - refunds - fees - chargebacks
  |     +-- gross  gross_payments_paise  40626000   -> 337 transaction ids
  |     +-- refunds  refunds_paise  1178200         -> 18 refund ids
  |     +-- fees  fees_paise  260805                -> 337 transaction ids
  |     +-- chargebacks  chargebacks_paise  174700  -> 4 chargeback ids
  +-- prior  net_revenue_paise  47342482
        ...
```

The walk has no knowledge of revenue, refunds or reconciliation. Every level is
an ``Evidence`` row that either declares a formula -- in which case its operands
are references to more rows -- or declares a fold, in which case it cites
records and the walk stops. That is what lets the provenance drawer be a
generic recursive renderer rather than a component per metric, and it is why a
derived row is not allowed to cite records directly: a node with both would
have two accounts of where its number came from and no way to keep them in step
(D-40).

A cycle is refused rather than truncated. Evidence describes a computation, and
a computation whose operands depend on their own result did not happen -- a
depth limit would quietly render half of it as though it had.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from evidence.builder import LITERAL, EvidenceSet
from evidence.models import Evidence

__all__ = [
    "MAX_DEPTH",
    "Operand",
    "ProvenanceCycleError",
    "ProvenanceNode",
    "UnknownEvidenceError",
    "leaves",
    "source_records",
    "walk",
]

#: A guard, not a policy. The revenue bridge's deepest chain is four levels; a
#: walk that reaches twelve has found a shape nobody designed.
MAX_DEPTH = 12


class UnknownEvidenceError(LookupError):
    """The requested evidence id is not part of this execution."""


class ProvenanceCycleError(ValueError):
    """A metric is, transitively, an operand of itself."""


@dataclass(frozen=True)
class Operand:
    """One named input to a formula, and where it resolves.

    ``node`` is ``None`` for a literal -- the ``100`` in a percentage-point
    conversion is part of the arithmetic, not a metric, and giving it a fake
    evidence row would put a number in the provenance tree that no record
    supports.
    """

    name: str
    reference: str
    value: int | Decimal
    node: "ProvenanceNode | None"

    @property
    def is_literal(self) -> bool:
        return self.reference == LITERAL


@dataclass(frozen=True)
class ProvenanceNode:
    """One level of the chain."""

    evidence_id: str
    tool_name: str
    tool_version: str
    metric_id: str
    unit: str
    value: int | Decimal
    period_from: str
    period_to: str
    dimension_value: str | None
    support: Literal["FORMULA", "AGGREGATION"]
    #: The expression for a derived node, the predicate for a leaf. What a
    #: reader looks at to decide whether the right thing was computed.
    detail: str
    rules_applied: tuple[str, ...]
    operands: tuple[Operand, ...]
    source_record_ids: tuple[str, ...]

    @property
    def is_leaf(self) -> bool:
        return self.support == "AGGREGATION"


def walk(published: EvidenceSet, evidence_id: str, depth: int = MAX_DEPTH) -> ProvenanceNode:
    """The whole chain below one metric.

    Raises rather than returning a partial tree: a provenance drawer that
    renders "and then something" is worse than one that says the chain is
    broken, because the first looks complete.
    """
    row = published.get(evidence_id)
    if row is None:
        raise UnknownEvidenceError(
            f"no evidence {evidence_id!r} in this execution; provenance can only be walked "
            "over the rows the execution actually published"
        )
    return _node(published, row, (), depth)


def _node(
    published: EvidenceSet, row: Evidence, path: tuple[str, ...], depth: int
) -> ProvenanceNode:
    if row.id in path:
        raise ProvenanceCycleError("evidence forms a cycle: " + " -> ".join([*path, row.id]))
    if depth <= 0:
        raise ProvenanceCycleError(f"provenance below {row.id!r} is deeper than {MAX_DEPTH} levels")

    operands: list[Operand] = []
    if row.formula is not None:
        for name, reference in sorted(row.formula.operands.items()):
            cited = None if reference == LITERAL else published.resolve(reference, row.period_from)
            operands.append(
                Operand(
                    name=name,
                    reference=reference,
                    value=row.inputs[name],
                    node=(
                        None
                        if cited is None
                        else _node(published, cited, (*path, row.id), depth - 1)
                    ),
                )
            )

    return ProvenanceNode(
        evidence_id=row.id,
        tool_name=row.tool_name,
        tool_version=row.tool_version,
        metric_id=row.metric_id,
        unit=row.unit,
        value=row.value,
        period_from=row.period_from,
        period_to=row.period_to,
        dimension_value=row.dimension_value,
        support="FORMULA" if row.formula is not None else "AGGREGATION",
        detail=(row.formula.expression if row.formula is not None else _predicate(row)),
        rules_applied=tuple(row.rules_applied),
        operands=tuple(operands),
        source_record_ids=tuple(row.source_record_ids),
    )


def _predicate(row: Evidence) -> str:
    fold = row.aggregation
    assert fold is not None  # one of the two is always present
    return f"{fold.operation}({fold.field_name}) over {fold.over} where {fold.predicate}"


def leaves(node: ProvenanceNode) -> Iterator[ProvenanceNode]:
    """Every node at the bottom of the chain, in walk order."""
    if node.is_leaf:
        yield node
        return
    for operand in node.operands:
        if operand.node is not None:
            yield from leaves(operand.node)


def source_records(node: ProvenanceNode) -> tuple[str, ...]:
    """Every source record the chain reaches, deduplicated and sorted.

    This is the answer to "show me the transactions behind this percentage".
    """
    found: set[str] = set()
    for leaf in leaves(node):
        found.update(leaf.source_record_ids)
    return tuple(sorted(found))
