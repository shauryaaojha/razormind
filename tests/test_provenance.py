"""Walking the evidence graph, and refusing to walk a broken one.

The walker has no knowledge of any metric. These tests are built from a small
hand-made graph rather than from the revenue analysis for that reason: if the
walk needed to know what a revenue bridge looks like, the provenance drawer
would need a component per metric, and the generic recursive renderer the whole
design rests on would not be possible.
"""

from decimal import Decimal

import pytest

from evidence.builder import EvidenceSet, collect
from evidence.models import Aggregation, Evidence, Formula
from evidence.vocabulary import METRICS
from provenance.builder import (
    ProvenanceCycleError,
    UnknownEvidenceError,
    leaves,
    source_records,
    walk,
)

WINDOW = ("2026-08-01", "2026-08-24")
TOOL = "finance.revenue_analysis"


def identifier(metric_id: str, window: tuple[str, str] = WINDOW) -> str:
    return f"{TOOL}/1.0/{metric_id}/{window[0]}_{window[1]}"


def leaf(
    metric_id: str, value: int, record_ids: list[str], window: tuple[str, str] = WINDOW
) -> Evidence:
    unit = METRICS[metric_id].unit
    return Evidence(
        id=identifier(metric_id, window),
        execution_id="exec",
        tool_name=TOOL,
        tool_version="1.0",
        metric_id=metric_id,
        unit=unit,
        value=value,
        period_from=window[0],
        period_to=window[1],
        aggregation=Aggregation(
            operation="SUM",
            field_name="amount_paise",
            over="transactions",
            predicate="the records in the window",
            unit=unit,
            scoped_by="ATTEMPT_DATE",
        ),
        inputs={"record_count": len(record_ids)},
        source_record_ids=record_ids,
    )


def derived(
    metric_id: str,
    value: int | Decimal,
    expression: str,
    operands: dict[str, str],
    inputs: dict[str, int | Decimal],
    window: tuple[str, str] = WINDOW,
) -> Evidence:
    unit = METRICS[metric_id].unit
    return Evidence(
        id=identifier(metric_id, window),
        execution_id="exec",
        tool_name=TOOL,
        tool_version="1.0",
        metric_id=metric_id,
        unit=unit,
        value=value,
        period_from=window[0],
        period_to=window[1],
        formula=Formula(expression=expression, operands=operands, unit=unit),
        inputs=inputs,
    )


def graph() -> EvidenceSet:
    """gross - refunds = net, and net over a literal."""
    return collect(
        [
            leaf("gross_payments_paise", 3000, ["TXN_1", "TXN_2", "TXN_3"]),
            leaf("refunds_paise", 1000, ["RFND_1"]),
            derived(
                "net_revenue_paise",
                2000,
                "gross - refunds",
                {
                    "gross": identifier("gross_payments_paise"),
                    "refunds": identifier("refunds_paise"),
                },
                {"gross": 3000, "refunds": 1000},
            ),
            derived(
                "confidence_band_ratio",
                Decimal("0.005000"),
                "unresolved / net",
                {"unresolved": "literal", "net": identifier("net_revenue_paise")},
                {"unresolved": 10, "net": 2000},
            ),
        ]
    )


class TestTheWalk:
    def test_a_derived_metric_reaches_its_operands(self) -> None:
        node = walk(graph(), identifier("net_revenue_paise"))
        assert node.support == "FORMULA"
        assert node.detail == "gross - refunds"
        assert [operand.name for operand in node.operands] == ["gross", "refunds"]
        assert [operand.node.metric_id for operand in node.operands if operand.node] == [
            "gross_payments_paise",
            "refunds_paise",
        ]

    def test_a_leaf_stops_and_says_what_it_folded(self) -> None:
        node = walk(graph(), identifier("gross_payments_paise"))
        assert node.is_leaf
        assert node.operands == ()
        assert node.detail.startswith("SUM(amount_paise) over transactions where")
        assert node.source_record_ids == ("TXN_1", "TXN_2", "TXN_3")

    def test_the_chain_reaches_source_records(self) -> None:
        node = walk(graph(), identifier("net_revenue_paise"))
        assert source_records(node) == ("RFND_1", "TXN_1", "TXN_2", "TXN_3")

    def test_records_are_deduplicated_across_branches(self) -> None:
        """gross and fees cite the same captures; the drawer should say so once."""
        rows = [
            leaf("gross_payments_paise", 3000, ["TXN_1", "TXN_2"]),
            leaf("fees_paise", 30, ["TXN_1", "TXN_2"]),
            derived(
                "net_revenue_paise",
                2970,
                "gross - fees",
                {"gross": identifier("gross_payments_paise"), "fees": identifier("fees_paise")},
                {"gross": 3000, "fees": 30},
            ),
        ]
        node = walk(collect(rows), identifier("net_revenue_paise"))
        assert source_records(node) == ("TXN_1", "TXN_2")

    def test_a_literal_operand_resolves_to_no_node(self) -> None:
        """The 100 in a pp conversion is arithmetic, not a metric."""
        node = walk(graph(), identifier("confidence_band_ratio"))
        literal = next(operand for operand in node.operands if operand.name == "unresolved")
        assert literal.node is None
        assert literal.is_literal
        assert literal.value == 10

    def test_the_leaves_are_the_bottom_of_every_branch(self) -> None:
        node = walk(graph(), identifier("confidence_band_ratio"))
        assert sorted(leaf.metric_id for leaf in leaves(node)) == [
            "gross_payments_paise",
            "refunds_paise",
        ]


class TestRefusals:
    def test_an_unknown_id_is_refused(self) -> None:
        with pytest.raises(UnknownEvidenceError, match="no evidence"):
            walk(graph(), "finance.revenue_analysis/1.0/nothing_paise/2026-08-01_2026-08-24")

    def test_a_cycle_is_refused_rather_than_truncated(self) -> None:
        """A metric that is transitively its own operand did not happen."""
        rows = [
            derived(
                "net_revenue_paise",
                1,
                "a - b",
                {"a": identifier("gross_payments_paise"), "b": "literal"},
                {"a": 1, "b": 0},
            ),
            derived(
                "gross_payments_paise",
                1,
                "a + b",
                {"a": identifier("net_revenue_paise"), "b": "literal"},
                {"a": 1, "b": 0},
            ),
        ]
        with pytest.raises(ProvenanceCycleError, match="cycle"):
            walk(collect(rows), identifier("net_revenue_paise"))

    def test_a_chain_deeper_than_the_guard_is_refused(self) -> None:
        node_ids = [
            identifier("net_revenue_paise", (f"2026-0{n}-01", f"2026-0{n}-15")) for n in range(1, 6)
        ]
        rows = [
            derived(
                "net_revenue_paise",
                1,
                "a + b",
                {"a": node_ids[n + 1], "b": "literal"},
                {"a": 1, "b": 0},
                window=(f"2026-0{n + 1}-01", f"2026-0{n + 1}-15"),
            )
            for n in range(4)
        ]
        rows.append(leaf("net_revenue_paise", 1, ["TXN_1"], window=("2026-05-01", "2026-05-15")))
        with pytest.raises(ProvenanceCycleError, match="deeper than"):
            walk(collect(rows), node_ids[0], depth=2)


class TestTheSet:
    def test_a_cross_tool_reference_resolves_to_the_citing_period(self) -> None:
        published = collect(
            [
                leaf("gross_payments_paise", 3000, ["TXN_1"], window=("2026-08-01", "2026-08-24")),
                leaf("gross_payments_paise", 4000, ["TXN_9"], window=("2026-07-01", "2026-07-24")),
            ]
        )
        resolved = published.resolve("finance.revenue_analysis.gross_payments_paise", "2026-07-01")
        assert resolved is not None
        assert resolved.value == 4000

    def test_an_ambiguous_cross_tool_reference_resolves_to_nothing(self) -> None:
        """Two windows and no period to choose between them is not a match."""
        published = collect(
            [
                leaf("gross_payments_paise", 3000, ["TXN_1"], window=("2026-08-01", "2026-08-24")),
                leaf("gross_payments_paise", 4000, ["TXN_9"], window=("2026-07-01", "2026-07-24")),
            ]
        )
        assert published.resolve("finance.revenue_analysis.gross_payments_paise") is None
