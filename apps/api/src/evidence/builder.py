"""The evidence produced by one execution, as a set that can be walked.

A tool hands back a list of rows. Four tools hand back four lists, and the
useful object is the union: layer 4 of verification resolves an operand
reference to another row, the provenance drawer walks from a row to its
operands, and the cross-tool consistency layer looks for the same quantity
published twice. All three need lookup, not iteration.

Two kinds of reference resolve here, and they look different on purpose:

* an **evidence id** -- ``finance.revenue_analysis/1.0/net_revenue_paise/
  2026-08-01_2026-08-24`` -- names exactly one row, period and dimension
  included;
* a **cross-tool reference** -- ``finance.reconciliation.
  unresolved_exception_value_paise`` -- names a metric another tool owns,
  without pinning its version or window, because the citing tool has no
  business knowing either.

The second is resolved against the rows this execution actually produced. A
reference that resolves to nothing is not tolerated: an operand nobody can look
up is where a provenance chain silently ends, and the whole point of the chain
is that it does not.
"""

from collections.abc import Iterable, Iterator, Sequence
from decimal import Decimal

from .models import Evidence

__all__ = ["LITERAL", "DuplicateEvidenceError", "EvidenceSet", "collect"]

#: The operand reference for a number that is part of the formula rather than a
#: metric -- the ``100`` in a percentage-point conversion. It resolves to no row
#: by design, and layer 4 checks the value against the expression instead.
LITERAL = "literal"


class DuplicateEvidenceError(ValueError):
    """Two rows claim the same evidence id.

    An id encodes tool, version, metric, period and dimension, so a collision
    means two different numbers are published under one name -- and every
    citation of that name then resolves to whichever row happened to be indexed
    last.
    """


class EvidenceSet:
    """Every row one execution published, indexed for lookup."""

    def __init__(self, rows: Iterable[Evidence]) -> None:
        indexed: dict[str, Evidence] = {}
        for row in rows:
            existing = indexed.get(row.id)
            if existing is not None and existing != row:
                raise DuplicateEvidenceError(
                    f"evidence id {row.id!r} is published twice with different content: "
                    f"{existing.value} by {existing.tool_name} and {row.value} by {row.tool_name}"
                )
            indexed[row.id] = row
        self._rows = tuple(indexed.values())
        self._by_id = indexed

    @property
    def rows(self) -> tuple[Evidence, ...]:
        return self._rows

    def __len__(self) -> int:
        return len(self._rows)

    def __iter__(self) -> Iterator[Evidence]:
        return iter(self._rows)

    def __contains__(self, evidence_id: object) -> bool:
        return evidence_id in self._by_id

    def get(self, evidence_id: str) -> Evidence | None:
        return self._by_id.get(evidence_id)

    def resolve(self, reference: str, period_from: str | None = None) -> Evidence | None:
        """The row a formula operand names, or ``None``.

        An evidence id resolves directly. A cross-tool reference resolves to the
        row for the citing metric's own period when there is one, because a tool
        publishing a metric for two windows would otherwise have its prior-period
        figure cited as a current-period one -- which is the failure
        ``period_from`` is part of the identity to prevent.
        """
        direct = self._by_id.get(reference)
        if direct is not None:
            return direct

        candidates = [row for row in self._rows if f"{row.tool_name}.{row.metric_id}" == reference]
        if not candidates:
            return None
        if period_from is not None:
            for row in candidates:
                if row.period_from == period_from:
                    return row
        return candidates[0] if len(candidates) == 1 else None

    def by_metric(self, metric_id: str) -> tuple[Evidence, ...]:
        return tuple(row for row in self._rows if row.metric_id == metric_id)

    def published(self, metric_id: str) -> frozenset[int | Decimal]:
        """Every distinct value published for a metric, across tools and windows."""
        return frozenset(row.value for row in self.by_metric(metric_id))

    def for_tool(self, tool_name: str) -> tuple[Evidence, ...]:
        return tuple(row for row in self._rows if row.tool_name == tool_name)


def collect(*groups: Sequence[Evidence]) -> EvidenceSet:
    """One set from several tools' rows."""
    return EvidenceSet(row for group in groups for row in group)
