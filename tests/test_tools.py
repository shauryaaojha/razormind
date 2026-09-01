"""The tool contract and the registry.

The contract's value is entirely in what it refuses. C-11 was a
``DeterministicTool`` with no ``@abstractmethod``: a subclass that forgot
``verify`` inherited a no-op body and published unverified numbers, and nothing
anywhere said so. Most of this file is that class of failure, made loud.
"""

from datetime import date
from decimal import Decimal
from typing import ClassVar

import pytest
from pydantic import BaseModel, ValidationError

from evidence.models import Aggregation, Evidence, Formula
from evidence.vocabulary import METRICS, unit_for
from tools.base import (
    DeterministicTool,
    Period,
    ToolContext,
    ToolError,
    ToolInput,
    UnregisteredMetricError,
)
from tools.catalog import REGISTRY, build_registry
from tools.finance.reconciliation import ReconciliationTool
from tools.finance.revenue import RevenueAnalysisInput, RevenueAnalysisTool
from tools.registry import ToolRegistry, parse_version
from verification.models import Checks, VerificationError, VerificationResult

AUGUST = Period(**{"from": date(2026, 8, 1), "to": date(2026, 8, 24)})
JULY = Period(**{"from": date(2026, 7, 1), "to": date(2026, 7, 24)})


# --------------------------------------------------------------------------
# a tool built for these tests only
# --------------------------------------------------------------------------


class CountingOutput(BaseModel):
    exception_count: int


class CountingTool(DeterministicTool[ToolInput, CountingOutput]):
    """The smallest thing that satisfies the contract.

    It publishes ``exception_count`` rather than an invented id because the
    vocabulary admits no invented ids -- including from a test double. That
    constraint applying to test code as well as production code is the point.
    """

    name: ClassVar[str] = "test.counting"
    version: ClassVar[str] = "1.0"
    input_model: ClassVar[type[BaseModel]] = ToolInput
    output_model: ClassVar[type[BaseModel]] = CountingOutput
    metrics: ClassVar[tuple[str, ...]] = ("exception_count",)

    should_lie: bool = False

    async def execute(self, inp: ToolInput, ctx: ToolContext) -> CountingOutput:
        return CountingOutput(exception_count=7 if self.should_lie else 2)

    def verify(self, inp: ToolInput, out: CountingOutput) -> VerificationResult:
        checks = Checks()
        checks.equal("count_is_two", out.exception_count, 2)
        return checks.result()

    def evidence(self, inp: ToolInput, out: CountingOutput, ctx: ToolContext) -> list[Evidence]:
        return [
            Evidence(
                id="test.counting/1.0/exception_count",
                execution_id=ctx.execution_id,
                tool_name=self.name,
                tool_version=self.version,
                metric_id="exception_count",
                unit="count",
                value=out.exception_count,
                period_from=inp.period.from_.isoformat(),
                period_to=inp.period.to.isoformat(),
                aggregation=Aggregation(
                    operation="COUNT",
                    field_name="id",
                    over="nothing",
                    predicate="none",
                    unit="count",
                ),
                inputs={"record_count": 0},
            )
        ]


def context(merchant_id: str = "M123", period: Period = AUGUST) -> ToolContext:
    """A context with no connection. Nothing here reaches the database."""
    return ToolContext(
        merchant_id=merchant_id,
        period=period,
        execution_id="exec-test",
        conn=None,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------
# the contract
# --------------------------------------------------------------------------


class TestContract:
    async def test_the_happy_path_runs_in_order(self) -> None:
        run = await CountingTool().run(
            {"merchant_id": "M123", "period": {"from": AUGUST.from_, "to": AUGUST.to}},
            context(),
        )
        assert run.output.exception_count == 2
        assert run.verification.passed
        assert [item.metric_id for item in run.evidence] == ["exception_count"]

    async def test_a_tool_whose_output_fails_its_own_invariants_never_returns_it(
        self,
    ) -> None:
        """C-11 in one test: verification is not advisory."""
        tool = CountingTool()
        tool.should_lie = True
        with pytest.raises(VerificationError, match="count_is_two"):
            await tool.run(
                {"merchant_id": "M123", "period": {"from": AUGUST.from_, "to": AUGUST.to}},
                context(),
            )

    def test_a_tool_missing_an_abstract_method_cannot_be_instantiated(self) -> None:
        """The Phase 3 exit criterion, and the whole reason for the ABC."""

        class Forgetful(DeterministicTool[ToolInput, CountingOutput]):
            name: ClassVar[str] = "test.forgetful"
            version: ClassVar[str] = "1.0"
            input_model: ClassVar[type[BaseModel]] = ToolInput
            output_model: ClassVar[type[BaseModel]] = CountingOutput

            async def execute(self, inp: ToolInput, ctx: ToolContext) -> CountingOutput:
                return CountingOutput(exception_count=2)

        with pytest.raises(TypeError, match="abstract"):
            Forgetful()  # type: ignore[abstract]

    async def test_an_input_naming_another_merchant_is_refused(self) -> None:
        """Prefigures MERCHANT_SCOPE_VIOLATION. Not left to row-level security."""
        with pytest.raises(ToolError) as raised:
            await CountingTool().run(
                {"merchant_id": "M999", "period": {"from": AUGUST.from_, "to": AUGUST.to}},
                context(merchant_id="M123"),
            )
        assert raised.value.code == "MERCHANT_SCOPE_VIOLATION"

    async def test_an_input_naming_another_period_is_refused(self) -> None:
        with pytest.raises(ToolError) as raised:
            await CountingTool().run(
                {"merchant_id": "M123", "period": {"from": JULY.from_, "to": JULY.to}},
                context(period=AUGUST),
            )
        assert raised.value.code == "PERIOD_SCOPE_VIOLATION"

    def test_a_reversed_period_is_refused_at_validation(self) -> None:
        with pytest.raises(ValidationError, match="must precede"):
            Period(**{"from": date(2026, 8, 24), "to": date(2026, 8, 1)})

    def test_the_spec_is_machine_readable(self) -> None:
        spec = CountingTool.spec()
        assert spec.name == "test.counting"
        assert spec.metrics == ["exception_count"]
        assert "merchant_id" in spec.input_schema["properties"]
        assert "exception_count" in spec.output_schema["properties"]


# --------------------------------------------------------------------------
# evidence shape
# --------------------------------------------------------------------------


class TestEvidence:
    def test_evidence_carries_exactly_one_kind_of_support(self) -> None:
        """A leaf has an aggregation; a derived metric has a formula. Never both."""
        with pytest.raises(ValidationError, match="exactly one"):
            Evidence(
                id="e",
                execution_id="x",
                tool_name="t",
                tool_version="1.0",
                metric_id="gross_payments_paise",
                unit="paise",
                value=1,
                period_from="2026-08-01",
                period_to="2026-08-24",
            )

    def test_evidence_cannot_claim_both(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            Evidence(
                id="e",
                execution_id="x",
                tool_name="t",
                tool_version="1.0",
                metric_id="gross_payments_paise",
                unit="paise",
                value=1,
                period_from="2026-08-01",
                period_to="2026-08-24",
                formula=Formula(expression="a", operands={"a": "literal"}, unit="paise"),
                aggregation=Aggregation(
                    operation="SUM", field_name="a", over="b", predicate="c", unit="paise"
                ),
            )


# --------------------------------------------------------------------------
# the registry
# --------------------------------------------------------------------------


class TestRegistry:
    def test_every_v1_tool_is_registered(self) -> None:
        for name in (
            "finance.reconciliation",
            "finance.revenue_analysis",
            "payments.failure_analysis",
            "finance.refund_analysis",
            "risk.chargeback_analysis",
        ):
            assert name in REGISTRY
        assert len(REGISTRY) == 5

    def test_resolve_without_a_version_takes_the_highest(self) -> None:
        registry = ToolRegistry()

        class V2(CountingTool):
            version: ClassVar[str] = "2.3"

        class V10(CountingTool):
            version: ClassVar[str] = "10.0"

        registry.register(CountingTool())
        registry.register(V2())
        registry.register(V10())
        assert registry.resolve("test.counting").version == "10.0"
        assert registry.resolve("test.counting", "2.3").version == "2.3"

    def test_versions_are_compared_as_numbers_not_strings(self) -> None:
        """``"10.0" < "9.0"`` lexicographically, which would silently resolve backwards."""
        assert parse_version("10.0") > parse_version("9.0")

    def test_a_malformed_version_is_refused(self) -> None:
        with pytest.raises(ToolError) as raised:
            parse_version("1.0.0")
        assert raised.value.code == "INVALID_TOOL_VERSION"

    def test_registering_the_same_name_and_version_twice_is_refused(self) -> None:
        registry = ToolRegistry()
        registry.register(CountingTool())
        with pytest.raises(ToolError) as raised:
            registry.register(CountingTool())
        assert raised.value.code == "DUPLICATE_TOOL"

    def test_a_tool_declaring_no_name_is_refused_at_registration(self) -> None:
        """The failure names the class, instead of surfacing as an AttributeError."""

        class Nameless(CountingTool):
            name = None  # type: ignore[assignment]

        with pytest.raises(ToolError) as raised:
            ToolRegistry().register(Nameless())
        assert raised.value.code == "INVALID_TOOL"

    def test_an_unregistered_tool_is_a_stable_error_code(self) -> None:
        with pytest.raises(ToolError) as raised:
            REGISTRY.resolve("finance.imaginary")
        assert raised.value.code == "TOOL_NOT_FOUND"

    def test_an_unregistered_version_is_a_stable_error_code(self) -> None:
        with pytest.raises(ToolError) as raised:
            REGISTRY.resolve("finance.reconciliation", "9.9")
        assert raised.value.code == "TOOL_NOT_FOUND"

    def test_describe_is_stable_and_covers_every_tool(self) -> None:
        """A dict-iteration order leaking into a planner prompt would be a bug."""
        specs = build_registry().describe()
        assert [spec.name for spec in specs] == [
            "finance.reconciliation",
            "finance.refund_analysis",
            "finance.revenue_analysis",
            "payments.failure_analysis",
            "risk.chargeback_analysis",
        ]
        assert build_registry().describe() == specs

    def test_the_registered_metrics_are_the_documented_ones(self) -> None:
        """docs/06-trust-layer.md#metric-vocabulary. Phase 4 makes this enforceable."""
        assert set(ReconciliationTool.metrics) >= {
            "ledger_count",
            "bank_count",
            "matched_pairs_count",
            "clean_match_rate_ratio",
            "exception_count",
            "unresolved_exception_value_paise",
        }
        assert set(RevenueAnalysisTool.metrics) >= {
            "gross_payments_paise",
            "refunds_paise",
            "fees_paise",
            "chargebacks_paise",
            "net_revenue_paise",
            "net_revenue_change_ratio",
        }


# --------------------------------------------------------------------------
# revenue input validation
# --------------------------------------------------------------------------


class TestRevenueInput:
    def test_overlapping_periods_are_refused(self) -> None:
        """Payments in the overlap would be counted on both sides of the bridge."""
        with pytest.raises(ValidationError, match="overlaps"):
            RevenueAnalysisInput(
                merchant_id="M123",
                period={"from": date(2026, 8, 1), "to": date(2026, 8, 24)},  # type: ignore[arg-type]
                comparison_period={  # type: ignore[arg-type]
                    "from": date(2026, 7, 15),
                    "to": date(2026, 8, 10),
                },
                run_id="rec_x",
            )

    def test_adjacent_periods_are_allowed(self) -> None:
        """Half-open intervals touch without overlapping (D-03)."""
        parsed = RevenueAnalysisInput(
            merchant_id="M123",
            period={"from": date(2026, 8, 1), "to": date(2026, 8, 24)},  # type: ignore[arg-type]
            comparison_period={"from": date(2026, 7, 8), "to": date(2026, 8, 1)},  # type: ignore[arg-type]
            run_id="rec_x",
        )
        assert parsed.comparison_period.to == parsed.period.from_

    def test_an_unknown_field_is_refused(self) -> None:
        """A plan that names a parameter the tool does not have is a plan bug."""
        with pytest.raises(ValidationError):
            RevenueAnalysisInput.model_validate(
                {
                    "merchant_id": "M123",
                    "period": {"from": "2026-08-01", "to": "2026-08-24"},
                    "comparison_period": {"from": "2026-07-01", "to": "2026-07-24"},
                    "run_id": "rec_x",
                    "method": "UPI",
                }
            )


# --------------------------------------------------------------------------
# the metric vocabulary, enforced at import
# --------------------------------------------------------------------------


class TestVocabularyEnforcement:
    """The Phase 4 exit criterion: an unregistered metric id cannot ship."""

    def test_a_tool_publishing_an_unregistered_metric_fails_at_class_creation(self) -> None:
        with pytest.raises(UnregisteredMetricError, match="invented_thing_paise"):

            class Inventive(CountingTool):
                metrics: ClassVar[tuple[str, ...]] = ("invented_thing_paise",)

    def test_a_metric_id_with_no_unit_suffix_is_refused(self) -> None:
        """C-04: the suffix is what stops a ratio being rendered as money."""
        with pytest.raises(UnregisteredMetricError):

            class Unsuffixed(CountingTool):
                metrics: ClassVar[tuple[str, ...]] = ("revenue",)

    def test_a_tool_publishing_only_registered_metrics_is_fine(self) -> None:
        class Fine(CountingTool):
            metrics: ClassVar[tuple[str, ...]] = ("exception_count", "ledger_count")

        assert Fine.metric_units() == {"exception_count": "count", "ledger_count": "count"}

    def test_every_registered_tool_publishes_only_registered_metrics(self) -> None:
        for spec in build_registry().describe():
            assert set(spec.metrics) <= set(METRICS), spec.name

    def test_the_vocabulary_has_no_metric_nobody_publishes(self) -> None:
        """An entry no tool emits is a promise the system does not keep."""
        published = {
            metric_id for spec in build_registry().describe() for metric_id in spec.metrics
        }
        assert set(METRICS) - published == set()

    def test_evidence_cannot_publish_an_unregistered_metric(self) -> None:
        with pytest.raises(ValidationError, match="not in the vocabulary"):
            _evidence(metric_id="invented_thing_paise", unit="paise", value=1)

    def test_evidence_cannot_publish_a_metric_under_the_wrong_unit(self) -> None:
        """A ratio published as a percentage point renders as a plausible lie."""
        with pytest.raises(ValidationError, match="declares 'ratio'"):
            _evidence(metric_id="success_rate_ratio", unit="pp", value=Decimal("0.94"))

    def test_a_dimensioned_metric_must_name_its_slice(self) -> None:
        with pytest.raises(ValidationError, match="names no method"):
            _evidence(metric_id="by_method.attempt_count", unit="count", value=3)

    def test_an_undimensioned_metric_must_not_name_one(self) -> None:
        with pytest.raises(ValidationError, match="not measured over a dimension"):
            _evidence(metric_id="attempt_count", unit="count", value=3, dimension_value="UPI")

    def test_a_slice_outside_the_declared_values_is_refused(self) -> None:
        """There are four rails. "upi" is not one of them, and neither is "CRYPTO"."""
        with pytest.raises(ValidationError, match="is not a method"):
            _evidence(
                metric_id="by_method.attempt_count",
                unit="count",
                value=3,
                dimension_value="CRYPTO",
            )

    def test_the_unit_of_every_registered_metric_is_derivable(self) -> None:
        for metric_id in METRICS:
            assert unit_for(metric_id) in {"paise", "ratio", "pp", "count"}

    def test_pp_beats_change_when_reading_the_suffix(self) -> None:
        """``success_rate_pp_change`` is percentage points, not a bare change."""
        assert unit_for("success_rate_pp_change") == "pp"
        assert unit_for("net_revenue_change_paise") == "paise"


def _evidence(
    metric_id: str, unit: str, value: int | Decimal, dimension_value: str | None = None
) -> Evidence:
    return Evidence(
        id="e",
        execution_id="x",
        tool_name="t",
        tool_version="1.0",
        metric_id=metric_id,
        unit=unit,  # type: ignore[arg-type]
        value=value,
        period_from="2026-08-01",
        period_to="2026-08-24",
        dimension_value=dimension_value,
        aggregation=Aggregation(
            operation="COUNT", field_name="id", over="t", predicate="p", unit="count"
        ),
    )
