"""Building evidence rows, once, for every tool.

Four tools publish forty-odd metrics between them. Each row needs a stable id,
the execution, the tool and version, the declared unit, the period, and either
a formula or an aggregation -- and getting the *unit* wrong is the failure C-04
is about. So the unit is never passed in: it is read from the metric id through
the vocabulary, which means a tool cannot publish a ratio as a percentage point
even by typo.

Ids are deterministic and self-describing:

``finance.revenue_analysis/1.0/net_revenue_paise/2026-08-01_2026-08-24``

so an operand reference in a formula resolves to exactly one row, and a
prior-period figure can never be mistaken for a current-period one. A metric
measured over a dimension appends the slice after a tilde:
``.../by_method.success_rate_ratio/2026-08-01_2026-08-24~UPI``.

The tilde is not decoration. An evidence id is the last segment of
``GET /executions/{id}/evidence/{evidence_id}``, and ``#`` is the fragment
delimiter -- a browser would never send the slice to the server at all, so the
request would silently resolve to the blended row instead of the UPI one and
return a plausible wrong answer. ``~`` is unreserved in RFC 3986 and needs no
encoding (D-42).
"""

from decimal import Decimal
from typing import Literal

from evidence.models import Aggregation, Anchor, Evidence, Formula
from evidence.vocabulary import unit_for

from .base import Period

__all__ = ["SLICE", "EvidencePublisher"]

#: Where an operand is a metric another tool owns rather than a row this tool
#: published. Written as ``<tool>.<metric_id>`` so the reference is readable and
#: the provenance walker can tell it apart from an evidence id.
CROSS_TOOL = "{tool}.{metric_id}"

#: Separates a dimensioned row's slice from the rest of its id. Unreserved in
#: RFC 3986, because the id travels in a URL path (D-42).
SLICE = "~"


class EvidencePublisher:
    """Makes the evidence rows for one tool run."""

    def __init__(self, tool: str, version: str, execution_id: str, checks: list[str]) -> None:
        self.tool = tool
        self.version = version
        self.execution_id = execution_id
        self.checks = checks

    def identifier(self, metric_id: str, period: Period, dimension_value: str | None = None) -> str:
        base = f"{self.tool}/{self.version}/{metric_id}/{period.from_}_{period.to}"
        return f"{base}{SLICE}{dimension_value}" if dimension_value is not None else base

    def _row(
        self,
        metric_id: str,
        period: Period,
        value: int | Decimal,
        *,
        formula: Formula | None = None,
        aggregation: Aggregation | None = None,
        inputs: dict[str, int | Decimal],
        source_record_ids: list[str],
        rules: list[str],
        dimension_value: str | None = None,
    ) -> Evidence:
        return Evidence(
            id=self.identifier(metric_id, period, dimension_value),
            execution_id=self.execution_id,
            tool_name=self.tool,
            tool_version=self.version,
            metric_id=metric_id,
            unit=unit_for(metric_id),
            value=value,
            period_from=period.from_.isoformat(),
            period_to=period.to.isoformat(),
            dimension_value=dimension_value,
            formula=formula,
            aggregation=aggregation,
            inputs=inputs,
            source_record_ids=source_record_ids,
            rules_applied=rules,
            verification_checks=self.checks,
        )

    def fold(
        self,
        metric_id: str,
        period: Period,
        value: int,
        *,
        operation: Literal["SUM", "COUNT"],
        field_name: str,
        over: str,
        predicate: str,
        scoped_by: Anchor,
        record_ids: list[str],
        dimension_value: str | None = None,
    ) -> Evidence:
        """A leaf metric: a fold over the records it cites, with no arithmetic.

        It carries an ``Aggregation`` rather than a ``Formula`` because there is
        no expression to re-evaluate -- the verifier re-sums the cited ids
        instead. Handing it a synthetic formula would make layer 4 a check that
        passes by construction (D-29).
        """
        return self._row(
            metric_id,
            period,
            value,
            aggregation=Aggregation(
                operation=operation,
                field_name=field_name,
                over=over,
                predicate=predicate,
                unit=unit_for(metric_id),
                scoped_by=scoped_by,
            ),
            inputs={"record_count": len(record_ids)},
            source_record_ids=record_ids,
            rules=[predicate],
            dimension_value=dimension_value,
        )

    def total(
        self,
        metric_id: str,
        period: Period,
        value: int,
        field_name: str,
        over: str,
        predicate: str,
        scoped_by: Anchor,
        record_ids: list[str],
        dimension_value: str | None = None,
    ) -> Evidence:
        """A summed money leaf."""
        return self.fold(
            metric_id,
            period,
            value,
            operation="SUM",
            field_name=field_name,
            over=over,
            predicate=predicate,
            scoped_by=scoped_by,
            record_ids=record_ids,
            dimension_value=dimension_value,
        )

    def tally(
        self,
        metric_id: str,
        period: Period,
        value: int,
        over: str,
        predicate: str,
        scoped_by: Anchor,
        record_ids: list[str],
        dimension_value: str | None = None,
    ) -> Evidence:
        """A counted leaf."""
        return self.fold(
            metric_id,
            period,
            value,
            operation="COUNT",
            field_name="id",
            over=over,
            predicate=predicate,
            scoped_by=scoped_by,
            record_ids=record_ids,
            dimension_value=dimension_value,
        )

    def derived(
        self,
        metric_id: str,
        period: Period,
        value: int | Decimal,
        expression: str,
        operands: dict[str, str],
        inputs: dict[str, int | Decimal],
        rules: list[str],
        dimension_value: str | None = None,
    ) -> Evidence:
        """A metric computed from other metrics, stated in the formula grammar.

        It cites no source records, and cannot: its provenance runs through its
        operands, each of which resolves to another row that either cites
        records or has operands of its own (D-40).
        """
        return self._row(
            metric_id,
            period,
            value,
            formula=Formula(expression=expression, operands=operands, unit=unit_for(metric_id)),
            inputs=inputs,
            source_record_ids=[],
            rules=rules,
            dimension_value=dimension_value,
        )

    def cross_tool(self, tool: str, metric_id: str) -> str:
        """An operand another tool owns."""
        return CROSS_TOOL.format(tool=tool, metric_id=metric_id)
