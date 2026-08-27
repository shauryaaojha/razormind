"""The tool contract and the registry.

The contract's value is entirely in what it refuses. C-11 was a
``DeterministicTool`` with no ``@abstractmethod``: a subclass that forgot
``verify`` inherited a no-op body and published unverified numbers, and nothing
anywhere said so. Most of this file is that class of failure, made loud.
"""

from datetime import date
from typing import ClassVar

import pytest
from pydantic import BaseModel, ValidationError

from evidence.models import Aggregation, Evidence, Formula
from tools.base import DeterministicTool, Period, ToolContext, ToolError, ToolInput
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


class DoubleOutput(BaseModel):
    doubled_count: int


class DoubleTool(DeterministicTool[ToolInput, DoubleOutput]):
    """The smallest thing that satisfies the contract."""

    name: ClassVar[str] = "test.double"
    version: ClassVar[str] = "1.0"
    input_model: ClassVar[type[BaseModel]] = ToolInput
    output_model: ClassVar[type[BaseModel]] = DoubleOutput
    metrics: ClassVar[tuple[str, ...]] = ("doubled_count",)

    should_lie: bool = False

    async def execute(self, inp: ToolInput, ctx: ToolContext) -> DoubleOutput:
        return DoubleOutput(doubled_count=7 if self.should_lie else 2)

    def verify(self, inp: ToolInput, out: DoubleOutput) -> VerificationResult:
        checks = Checks()
        checks.equal("doubled_is_two", out.doubled_count, 2)
        return checks.result()

    def evidence(self, inp: ToolInput, out: DoubleOutput, ctx: ToolContext) -> list[Evidence]:
        return [
            Evidence(
                id="test.double/1.0/doubled_count",
                execution_id=ctx.execution_id,
                tool_name=self.name,
                tool_version=self.version,
                metric_id="doubled_count",
                unit="count",
                value=out.doubled_count,
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
        run = await DoubleTool().run(
            {"merchant_id": "M123", "period": {"from": AUGUST.from_, "to": AUGUST.to}},
            context(),
        )
        assert run.output.doubled_count == 2
        assert run.verification.passed
        assert [item.metric_id for item in run.evidence] == ["doubled_count"]

    async def test_a_tool_whose_output_fails_its_own_invariants_never_returns_it(
        self,
    ) -> None:
        """C-11 in one test: verification is not advisory."""
        tool = DoubleTool()
        tool.should_lie = True
        with pytest.raises(VerificationError, match="doubled_is_two"):
            await tool.run(
                {"merchant_id": "M123", "period": {"from": AUGUST.from_, "to": AUGUST.to}},
                context(),
            )

    def test_a_tool_missing_an_abstract_method_cannot_be_instantiated(self) -> None:
        """The Phase 3 exit criterion, and the whole reason for the ABC."""

        class Forgetful(DeterministicTool[ToolInput, DoubleOutput]):
            name: ClassVar[str] = "test.forgetful"
            version: ClassVar[str] = "1.0"
            input_model: ClassVar[type[BaseModel]] = ToolInput
            output_model: ClassVar[type[BaseModel]] = DoubleOutput

            async def execute(self, inp: ToolInput, ctx: ToolContext) -> DoubleOutput:
                return DoubleOutput(doubled_count=2)

        with pytest.raises(TypeError, match="abstract"):
            Forgetful()  # type: ignore[abstract]

    async def test_an_input_naming_another_merchant_is_refused(self) -> None:
        """Prefigures MERCHANT_SCOPE_VIOLATION. Not left to row-level security."""
        with pytest.raises(ToolError) as raised:
            await DoubleTool().run(
                {"merchant_id": "M999", "period": {"from": AUGUST.from_, "to": AUGUST.to}},
                context(merchant_id="M123"),
            )
        assert raised.value.code == "MERCHANT_SCOPE_VIOLATION"

    async def test_an_input_naming_another_period_is_refused(self) -> None:
        with pytest.raises(ToolError) as raised:
            await DoubleTool().run(
                {"merchant_id": "M123", "period": {"from": JULY.from_, "to": JULY.to}},
                context(period=AUGUST),
            )
        assert raised.value.code == "PERIOD_SCOPE_VIOLATION"

    def test_a_reversed_period_is_refused_at_validation(self) -> None:
        with pytest.raises(ValidationError, match="must precede"):
            Period(**{"from": date(2026, 8, 24), "to": date(2026, 8, 1)})

    def test_the_spec_is_machine_readable(self) -> None:
        spec = DoubleTool.spec()
        assert spec.name == "test.double"
        assert spec.metrics == ["doubled_count"]
        assert "merchant_id" in spec.input_schema["properties"]
        assert "doubled_count" in spec.output_schema["properties"]


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
                metric_id="m",
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
                metric_id="m",
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
    def test_both_v1_tools_are_registered(self) -> None:
        assert "finance.reconciliation" in REGISTRY
        assert "finance.revenue_analysis" in REGISTRY
        assert len(REGISTRY) == 2

    def test_resolve_without_a_version_takes_the_highest(self) -> None:
        registry = ToolRegistry()

        class V2(DoubleTool):
            version: ClassVar[str] = "2.3"

        class V10(DoubleTool):
            version: ClassVar[str] = "10.0"

        registry.register(DoubleTool())
        registry.register(V2())
        registry.register(V10())
        assert registry.resolve("test.double").version == "10.0"
        assert registry.resolve("test.double", "2.3").version == "2.3"

    def test_versions_are_compared_as_numbers_not_strings(self) -> None:
        """``"10.0" < "9.0"`` lexicographically, which would silently resolve backwards."""
        assert parse_version("10.0") > parse_version("9.0")

    def test_a_malformed_version_is_refused(self) -> None:
        with pytest.raises(ToolError) as raised:
            parse_version("1.0.0")
        assert raised.value.code == "INVALID_TOOL_VERSION"

    def test_registering_the_same_name_and_version_twice_is_refused(self) -> None:
        registry = ToolRegistry()
        registry.register(DoubleTool())
        with pytest.raises(ToolError) as raised:
            registry.register(DoubleTool())
        assert raised.value.code == "DUPLICATE_TOOL"

    def test_a_tool_declaring_no_name_is_refused_at_registration(self) -> None:
        """The failure names the class, instead of surfacing as an AttributeError."""

        class Nameless(DoubleTool):
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
            "finance.revenue_analysis",
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
