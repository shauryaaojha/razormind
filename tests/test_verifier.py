"""The five layers, each caught doing its job on a deliberately broken tool.

Every test here mutates something a real tool could plausibly get wrong and
asserts the *named* layer refuses it. Asserting only that verification failed
would pass just as happily if one layer were catching everything and the other
four were dead code, which is the failure mode a layered verifier is most
exposed to.

The fixtures are built by hand rather than by running a tool. A test that
needed the revenue analysis to produce a wrong number could only get one by
breaking the revenue analysis, and then it would be testing the mutation rather
than the verifier.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from evidence.models import Aggregation, Anchor, Evidence, Formula
from evidence.vocabulary import METRICS
from verification.models import VerificationError
from verification.sources import (
    DatabaseSources,
    SourceRecord,
    StaticSources,
    UnknownRecordSetError,
)
from verification.verifier import LAYERS, ToolOutcome, verify_execution

MERCHANT_WINDOW = ("2026-08-01", "2026-08-24")
PRIOR_WINDOW = ("2026-07-01", "2026-07-24")

TOOL = "finance.revenue_analysis"


class Bridge(BaseModel):
    gross_payments_paise: int
    net_revenue_paise: int


def leaf(
    metric_id: str,
    value: int,
    record_ids: list[str],
    *,
    tool: str = TOOL,
    window: tuple[str, str] = MERCHANT_WINDOW,
    operation: str = "SUM",
    field_name: str = "amount_paise",
    over: str = "transactions",
    dimension_value: str | None = None,
) -> Evidence:
    unit = METRICS[metric_id].unit
    slice_of = f"~{dimension_value}" if dimension_value else ""
    return Evidence(
        id=f"{tool}/1.0/{metric_id}/{window[0]}_{window[1]}{slice_of}",
        execution_id="exec",
        tool_name=tool,
        tool_version="1.0",
        metric_id=metric_id,
        unit=unit,
        value=value,
        period_from=window[0],
        period_to=window[1],
        dimension_value=dimension_value,
        aggregation=Aggregation(
            operation=operation,  # type: ignore[arg-type]
            field_name=field_name,
            over=over,
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
    *,
    tool: str = TOOL,
    window: tuple[str, str] = MERCHANT_WINDOW,
) -> Evidence:
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
        inputs=inputs,
    )


def identifier(metric_id: str, window: tuple[str, str] = MERCHANT_WINDOW, tool: str = TOOL) -> str:
    return f"{tool}/1.0/{metric_id}/{window[0]}_{window[1]}"


def found(*ids: str, anchor: str = "2026-08-05", amount: int = 1000) -> dict[str, SourceRecord]:
    return {
        record_id: SourceRecord(
            id=record_id,
            anchor=date.fromisoformat(anchor),
            amount_paise=amount,
            fee_paise=0,
        )
        for record_id in ids
    }


def records(*ids: str, anchor: str = "2026-08-05", amount: int = 1000) -> StaticSources:
    return StaticSources(found(*ids, anchor=anchor, amount=amount))


def bridge_rows() -> list[Evidence]:
    """A tiny but complete revenue bridge: two leaves and the metric above them."""
    return [
        leaf("gross_payments_paise", 3000, ["TXN_1", "TXN_2", "TXN_3"]),
        leaf("refunds_paise", 1000, ["RFND_1"], over="refunds"),
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
    ]


def bridge_sources() -> StaticSources:
    return records("TXN_1", "TXN_2", "TXN_3", "RFND_1")


def outcome(rows: list[Evidence], output: BaseModel | None = None) -> ToolOutcome:
    return ToolOutcome(
        tool_name=TOOL,
        tool_version="1.0",
        output=output or Bridge(gross_payments_paise=3000, net_revenue_paise=2000),
        evidence=tuple(rows),
    )


# --------------------------------------------------------------------------


class TestTheHappyPath:
    async def test_a_sound_bundle_passes_every_layer(self) -> None:
        report = await verify_execution([outcome(bridge_rows())], bridge_sources())
        assert report.passed
        assert [layer.layer for layer in report.layers] == list(LAYERS)
        assert report.blocked_at is None
        assert report.status == "EXPLAINING"

    async def test_every_layer_actually_ran_some_checks(self) -> None:
        """A layer that checks nothing passes trivially and proves nothing.

        Two tools, because that is what gives the consistency layer anything to
        do: with one tool there is no second opinion to compare against, and it
        correctly runs zero comparisons.
        """
        agreeing = ToolOutcome(
            tool_name="payments.failure_analysis",
            tool_version="1.0",
            output=Bridge(gross_payments_paise=3000, net_revenue_paise=0),
            evidence=(
                leaf(
                    "succeeded_value_paise",
                    3000,
                    ["TXN_1", "TXN_2", "TXN_3"],
                    tool="payments.failure_analysis",
                ),
            ),
        )
        report = await verify_execution([outcome(bridge_rows()), agreeing], bridge_sources())
        assert report.passed
        assert all(layer.checks for layer in report.layers)


class TestLayerOneType:
    async def test_a_float_in_an_output_is_caught(self) -> None:
        class Loose(BaseModel):
            gross_payments_paise: float

        report = await verify_execution(
            [outcome(bridge_rows(), Loose(gross_payments_paise=3000.0))], bridge_sources()
        )
        assert report.blocked_at == "TYPE"
        assert any("carries_no_float" in failure for failure in report.failures)

    async def test_later_layers_do_not_run(self) -> None:
        class Loose(BaseModel):
            gross_payments_paise: float

        report = await verify_execution(
            [outcome(bridge_rows(), Loose(gross_payments_paise=3000.0))], bridge_sources()
        )
        assert [layer.layer for layer in report.layers] == ["TYPE"]

    async def test_a_ratio_carried_as_an_int_is_caught(self) -> None:
        rows = bridge_rows()
        rows.append(
            Evidence.model_construct(
                id=identifier("clean_match_rate_ratio"),
                execution_id="exec",
                tool_name=TOOL,
                tool_version="1.0",
                metric_id="clean_match_rate_ratio",
                unit="ratio",
                value=1,
                period_from=MERCHANT_WINDOW[0],
                period_to=MERCHANT_WINDOW[1],
                dimension_value=None,
                formula=Formula(expression="a", operands={"a": "literal"}, unit="ratio"),
                aggregation=None,
                inputs={"a": 1},
                source_record_ids=[],
                rules_applied=[],
                verification_checks=[],
            )
        )
        report = await verify_execution([outcome(rows)], bridge_sources())
        assert report.blocked_at == "TYPE"
        assert any("value_is_a_Decimal" in failure for failure in report.failures)


class TestLayerTwoRange:
    async def test_an_unsigned_metric_published_negative_is_caught(self) -> None:
        """``Evidence`` refuses this at construction, so the layer sees a built row."""
        rows = bridge_rows()
        rows[0] = Evidence.model_construct(**{**rows[0].__dict__, "value": -1})
        report = await verify_execution([outcome(rows)], bridge_sources())
        assert report.blocked_at == "RANGE"
        assert any("sign_is_declared" in failure for failure in report.failures)

    async def test_a_signed_metric_published_negative_is_fine(self) -> None:
        rows = bridge_rows()
        rows.append(
            derived(
                "net_revenue_change_paise",
                -500,
                "current - prior",
                {"current": identifier("net_revenue_paise"), "prior": "literal"},
                {"current": 2000, "prior": 2500},
            )
        )
        report = await verify_execution([outcome(rows)], bridge_sources())
        assert report.passed

    async def test_a_ratio_above_one_is_caught(self) -> None:
        rows = bridge_rows()
        rows.append(
            derived(
                "clean_match_rate_ratio",
                Decimal("1.500000"),
                "a / b",
                {"a": "literal", "b": "literal"},
                {"a": 3, "b": 2},
            )
        )
        report = await verify_execution([outcome(rows)], bridge_sources())
        assert report.blocked_at == "RANGE"
        assert any("ratio_is_a_proportion" in failure for failure in report.failures)

    async def test_an_unquantized_ratio_is_caught(self) -> None:
        """Scale 6 is the contract. A seventh decimal place means two roundings."""
        rows = bridge_rows()
        rows.append(
            derived(
                "clean_match_rate_ratio",
                Decimal("0.9561404"),
                "a / b",
                {"a": "literal", "b": "literal"},
                {"a": 327, "b": 342},
            )
        )
        report = await verify_execution([outcome(rows)], bridge_sources())
        assert report.blocked_at == "RANGE"
        assert any("quantized_to_scale_6" in failure for failure in report.failures)


class TestLayerThreeConsistency:
    async def test_two_tools_disagreeing_on_one_metric_is_caught(self) -> None:
        mine = bridge_rows()
        theirs = [
            leaf(
                "gross_payments_paise",
                2999,
                ["TXN_1", "TXN_2", "TXN_3"],
                tool="finance.refund_analysis",
            )
        ]
        report = await verify_execution(
            [
                outcome(mine),
                ToolOutcome(
                    tool_name="finance.refund_analysis",
                    tool_version="1.0",
                    output=Bridge(gross_payments_paise=2999, net_revenue_paise=0),
                    evidence=tuple(theirs),
                ),
            ],
            bridge_sources(),
        )
        assert report.blocked_at == "CONSISTENCY"
        assert any("agrees_across_tools" in failure for failure in report.failures)

    async def test_a_declared_equivalence_that_does_not_hold_is_caught(self) -> None:
        """``gross_payments_paise`` and ``succeeded_value_paise`` are one quantity."""
        mine = bridge_rows()
        theirs = [
            leaf(
                "succeeded_value_paise",
                2500,
                ["TXN_1", "TXN_2"],
                tool="payments.failure_analysis",
            )
        ]
        report = await verify_execution(
            [
                outcome(mine),
                ToolOutcome(
                    tool_name="payments.failure_analysis",
                    tool_version="1.0",
                    output=Bridge(gross_payments_paise=2500, net_revenue_paise=0),
                    evidence=tuple(theirs),
                ),
            ],
            bridge_sources(),
        )
        assert report.blocked_at == "CONSISTENCY"
        assert any(
            "gross_payments_paise==succeeded_value_paise" in failure for failure in report.failures
        )

    async def test_two_rows_claiming_one_id_is_caught(self) -> None:
        rows = bridge_rows()
        rows.append(leaf("gross_payments_paise", 9999, ["TXN_9"]))
        report = await verify_execution([outcome(rows)], bridge_sources())
        assert report.blocked_at == "CONSISTENCY"
        assert any("evidence_ids_are_unique" in failure for failure in report.failures)


class TestLayerFourFormula:
    """The Phase 5 exit criterion: a number its own formula does not produce."""

    async def test_a_metric_that_contradicts_its_formula_is_caught(self) -> None:
        rows = bridge_rows()
        rows[2] = derived(
            "net_revenue_paise",
            2500,  # gross - refunds is 2000
            "gross - refunds",
            {
                "gross": identifier("gross_payments_paise"),
                "refunds": identifier("refunds_paise"),
            },
            {"gross": 3000, "refunds": 1000},
        )
        report = await verify_execution([outcome(rows)], bridge_sources())
        assert report.blocked_at == "FORMULA"
        assert any("reproduces_its_own_formula" in failure for failure in report.failures)

    async def test_an_operand_that_disagrees_with_its_evidence_is_caught(self) -> None:
        """Citing a row and then evaluating against a different number."""
        rows = bridge_rows()
        rows[2] = derived(
            "net_revenue_paise",
            1500,
            "gross - refunds",
            {
                "gross": identifier("gross_payments_paise"),
                "refunds": identifier("refunds_paise"),
            },
            {"gross": 3000, "refunds": 1500},
        )
        report = await verify_execution([outcome(rows)], bridge_sources())
        assert report.blocked_at == "FORMULA"
        assert any("matches_its_evidence" in failure for failure in report.failures)

    async def test_an_operand_naming_nothing_is_caught(self) -> None:
        rows = bridge_rows()
        rows[2] = derived(
            "net_revenue_paise",
            2000,
            "gross - refunds",
            {"gross": identifier("gross_payments_paise"), "refunds": "finance.nowhere.refunds"},
            {"gross": 3000, "refunds": 1000},
        )
        report = await verify_execution([outcome(rows)], bridge_sources())
        assert report.blocked_at == "FORMULA"
        assert any("operand_refunds_resolves" in failure for failure in report.failures)

    async def test_an_undeclared_operand_is_caught(self) -> None:
        rows = bridge_rows()
        rows[2] = Evidence(
            id=identifier("net_revenue_paise"),
            execution_id="exec",
            tool_name=TOOL,
            tool_version="1.0",
            metric_id="net_revenue_paise",
            unit="paise",
            value=2000,
            period_from=MERCHANT_WINDOW[0],
            period_to=MERCHANT_WINDOW[1],
            formula=Formula(
                expression="gross - refunds - fees",
                operands={"gross": identifier("gross_payments_paise")},
                unit="paise",
            ),
            inputs={"gross": 3000},
        )
        report = await verify_execution([outcome(rows)], bridge_sources())
        assert report.blocked_at == "FORMULA"
        assert any("operands_are_declared" in failure for failure in report.failures)

    async def test_a_count_that_does_not_match_its_records_is_caught(self) -> None:
        rows = bridge_rows()
        rows.append(
            leaf(
                "matched_clean_count",
                7,
                ["TXN_1", "TXN_2"],
                operation="COUNT",
                field_name="id",
            )
        )
        report = await verify_execution([outcome(rows)], bridge_sources())
        assert report.blocked_at == "FORMULA"
        assert any("count_is_the_size_of_the_set" in failure for failure in report.failures)

    async def test_a_formula_outside_the_grammar_is_caught(self) -> None:
        rows = bridge_rows()
        rows[2] = derived(
            "net_revenue_paise",
            2000,
            "__import__('os').system('true')",
            {"gross": identifier("gross_payments_paise")},
            {"gross": 3000},
        )
        report = await verify_execution([outcome(rows)], bridge_sources())
        assert report.blocked_at == "FORMULA"


class TestLayerFiveSource:
    """The other Phase 5 exit criterion: a record outside the period."""

    async def test_a_record_outside_the_period_is_caught(self) -> None:
        report = await verify_execution(
            [outcome(bridge_rows())],
            StaticSources(found("TXN_1", "TXN_2", "RFND_1") | found("TXN_3", anchor="2026-09-14")),
        )
        assert report.blocked_at == "SOURCE"
        assert any("inside_the_period" in failure for failure in report.failures)
        assert any("TXN_3@2026-09-14" in failure for failure in report.failures)

    async def test_a_record_that_does_not_exist_is_caught(self) -> None:
        report = await verify_execution(
            [outcome(bridge_rows())], records("TXN_1", "TXN_2", "RFND_1")
        )
        assert report.blocked_at == "SOURCE"
        assert any("cited_records_exist" in failure for failure in report.failures)

    async def test_a_sum_that_does_not_refold_is_caught(self) -> None:
        """The leaf's answer to layer 4: re-sum the column, land on the figure."""
        rows = [
            leaf("gross_payments_paise", 3000, ["TXN_1", "TXN_2", "TXN_3"]),
            leaf("refunds_paise", 1000, ["RFND_1"], over="refunds"),
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
        ]
        # Each record is worth 900, not 1000, so gross re-folds to 2700.
        report = await verify_execution(
            [outcome(rows)], records("TXN_1", "TXN_2", "TXN_3", "RFND_1", amount=900)
        )
        assert report.blocked_at == "SOURCE"
        assert any("re_folds_from_its_records" in failure for failure in report.failures)

    async def test_a_record_set_nothing_can_resolve_is_caught(self) -> None:
        """Reported as unresolvable, not as "every record is missing"."""
        rows = [leaf("refunds_paise", 1000, ["RFND_1"], over="invoices")]
        with pytest.raises(UnknownRecordSetError):
            await DatabaseSources(None).resolve("invoices", "VALUE_DATE", ["RFND_1"])  # type: ignore[arg-type]
        report = await verify_execution(
            [
                ToolOutcome(
                    tool_name=TOOL,
                    tool_version="1.0",
                    output=Bridge(gross_payments_paise=0, net_revenue_paise=0),
                    evidence=tuple(rows),
                )
            ],
            _Unresolvable(),
        )
        assert report.blocked_at == "SOURCE"
        assert any("record_set_is_resolvable" in failure for failure in report.failures)


class _Unresolvable:
    """A resolver that knows no record sets at all."""

    async def resolve(
        self, over: str, scoped_by: Anchor, record_ids: Sequence[str]
    ) -> Mapping[str, SourceRecord]:
        del scoped_by, record_ids
        raise UnknownRecordSetError(f"nothing resolves {over!r}")


class TestTheReport:
    async def test_a_failing_report_raises_with_every_failure_named(self) -> None:
        rows = bridge_rows()
        rows[2] = derived(
            "net_revenue_paise",
            2500,
            "gross - refunds",
            {
                "gross": identifier("gross_payments_paise"),
                "refunds": identifier("refunds_paise"),
            },
            {"gross": 3000, "refunds": 1000},
        )
        report = await verify_execution([outcome(rows)], bridge_sources())
        with pytest.raises(VerificationError, match="FORMULA"):
            report.raise_if_failed("execution")

    async def test_a_blocked_report_says_so(self) -> None:
        rows = bridge_rows()
        rows.append(leaf("gross_payments_paise", 1, ["TXN_1"]))
        report = await verify_execution([outcome(rows)], bridge_sources())
        assert report.status == "BLOCKED"


class TestEvidenceRefusesTheImpossible:
    """Some mutations never reach the verifier, because the model refuses them."""

    def test_a_derived_row_may_not_cite_records(self) -> None:
        with pytest.raises(ValidationError, match="provenance runs through its operands"):
            Evidence(
                id="e",
                execution_id="x",
                tool_name=TOOL,
                tool_version="1.0",
                metric_id="net_revenue_paise",
                unit="paise",
                value=1,
                period_from=MERCHANT_WINDOW[0],
                period_to=MERCHANT_WINDOW[1],
                formula=Formula(expression="a", operands={"a": "literal"}, unit="paise"),
                inputs={"a": 1},
                source_record_ids=["TXN_1"],
            )

    def test_an_unsigned_metric_may_not_be_published_negative(self) -> None:
        with pytest.raises(ValidationError, match="not a signed metric"):
            leaf("gross_payments_paise", -1, ["TXN_1"])

    def test_a_signed_metric_may(self) -> None:
        row = derived(
            "net_revenue_change_paise",
            -8330187,
            "current - prior",
            {"current": "literal", "prior": "literal"},
            {"current": 39012295, "prior": 47342482},
        )
        assert row.value == -8330187
