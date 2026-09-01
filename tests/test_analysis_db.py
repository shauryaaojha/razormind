"""The four analysis tools against a real Postgres, and the agreements between them.

Phase 4's exit criteria are mostly *cross-tool* claims -- that the blended rate
falls out of the method mix, that a rail's rate is a different metric from the
portfolio's, and that two tools computing the same quantity land on the same
number. Those cannot be tested inside one tool, so they are tested here.

The declared numbers come from ``data/seed/golden/ground_truth.json``. Where
the Phase 4 spec quotes figures (96.81% -> 90.32% blended, UPI 96.8% -> 82.9%),
those describe the pre-calibration fixture and were superseded by the
market-calibrated dataset (D-25, D-26). The *structural* criteria they were
expressing are what is asserted here.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from evidence.formula import evaluate
from evidence.models import Evidence
from evidence.vocabulary import EQUIVALENCES, METRICS, unit_for
from runtime.db import connection
from runtime.money import quantize_paise, quantize_pp, quantize_ratio, ratio
from tools.base import Period, ToolContext, ToolError
from tools.catalog import REGISTRY
from tools.finance.reconciliation import ReconciliationOutput
from tools.finance.refunds import RefundAnalysisOutput
from tools.finance.revenue import RevenueAnalysisOutput
from tools.payments.failure import FailureAnalysisOutput
from tools.risk.chargebacks import ChargebackAnalysisOutput

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parents[1]
TRUTH = json.loads((ROOT / "data" / "seed" / "golden" / "ground_truth.json").read_text("utf-8"))

MERCHANT = str(TRUTH["merchant_id"])
CURRENT = Period(
    **{
        "from": date.fromisoformat(TRUTH["current"]["period_from"]),
        "to": date.fromisoformat(TRUTH["current"]["period_to"]),
    }
)
PRIOR = Period(
    **{
        "from": date.fromisoformat(TRUTH["prior"]["period_from"]),
        "to": date.fromisoformat(TRUTH["prior"]["period_to"]),
    }
)


class Diagnosis:
    """Every v1 tool, run over the golden window under one execution id."""

    def __init__(
        self,
        run: ReconciliationOutput,
        revenue: RevenueAnalysisOutput,
        failure: FailureAnalysisOutput,
        refunds: RefundAnalysisOutput,
        chargebacks: ChargebackAnalysisOutput,
        evidence: tuple[Evidence, ...],
    ) -> None:
        self.run = run
        self.revenue = revenue
        self.failure = failure
        self.refunds = refunds
        self.chargebacks = chargebacks
        self.evidence = evidence


async def _diagnose(execution_id: str = "test-analysis", method: str | None = None) -> Diagnosis:
    """Reconcile, then run the four analyses against that run."""
    window = {"from": CURRENT.from_, "to": CURRENT.to}
    comparison = {"from": PRIOR.from_, "to": PRIOR.to}

    async with connection() as conn:
        ctx = ToolContext(
            merchant_id=MERCHANT, period=CURRENT, execution_id=execution_id, conn=conn
        )
        reconciled = await REGISTRY.resolve("finance.reconciliation").run(
            {"merchant_id": MERCHANT, "period": window}, ctx
        )
        run_out = reconciled.output
        assert isinstance(run_out, ReconciliationOutput)

        request = {
            "merchant_id": MERCHANT,
            "period": window,
            "comparison_period": comparison,
            "run_id": run_out.run_id,
        }
        revenue = await REGISTRY.resolve("finance.revenue_analysis").run(request, ctx)
        failure = await REGISTRY.resolve("payments.failure_analysis").run(
            {**request, "method": method} if method else request, ctx
        )
        refunds = await REGISTRY.resolve("finance.refund_analysis").run(request, ctx)
        chargebacks = await REGISTRY.resolve("risk.chargeback_analysis").run(request, ctx)

    for produced, expected in (
        (revenue.output, RevenueAnalysisOutput),
        (failure.output, FailureAnalysisOutput),
        (refunds.output, RefundAnalysisOutput),
        (chargebacks.output, ChargebackAnalysisOutput),
    ):
        assert isinstance(produced, expected)

    return Diagnosis(
        run=run_out,
        revenue=revenue.output,
        failure=failure.output,
        refunds=refunds.output,
        chargebacks=chargebacks.output,
        evidence=(
            *reconciled.evidence,
            *revenue.evidence,
            *failure.evidence,
            *refunds.evidence,
            *chargebacks.evidence,
        ),
    )


@pytest.fixture(scope="module")
async def diagnosis() -> Diagnosis:
    return await _diagnose(execution_id="test-analysis-module")


# --------------------------------------------------------------------------
# payments.failure_analysis
# --------------------------------------------------------------------------


class TestFailureAnalysis:
    @pytest.mark.parametrize("window", ["current", "prior"])
    def test_the_blended_figures_match_the_ground_truth(
        self, diagnosis: Diagnosis, window: str
    ) -> None:
        expected = TRUTH[window]
        side = diagnosis.failure.current if window == "current" else diagnosis.failure.prior

        assert side.attempt_count == expected["attempt_count"]
        assert side.succeeded_count == expected["capture_count"]
        assert side.attempted_value_paise == expected["attempted_value_paise"]
        assert side.succeeded_value_paise == expected["gross_payments_paise"]
        assert side.success_rate_ratio == expected["success_rate_ratio"]
        assert side.technical_decline_ratio == expected["technical_decline_ratio"]
        assert side.business_decline_ratio == expected["business_decline_ratio"]

    @pytest.mark.parametrize("window", ["current", "prior"])
    def test_every_rail_matches_the_ground_truth(self, diagnosis: Diagnosis, window: str) -> None:
        expected = TRUTH[window]["by_method"]
        breakdown = (
            diagnosis.failure.by_method
            if window == "current"
            else diagnosis.failure.prior_by_method
        )
        assert {entry.method for entry in breakdown} == set(expected)
        for entry in breakdown:
            rail = expected[entry.method]
            assert entry.attempt_count == rail["attempt_count"]
            assert entry.succeeded_count == rail["capture_count"]
            assert entry.succeeded_value_paise == rail["gross_paise"]
            assert entry.success_rate_ratio == rail["success_rate_ratio"]

    def test_the_blended_rate_falls_out_of_the_method_mix(self, diagnosis: Diagnosis) -> None:
        """The Phase 4 exit criterion, as an exact identity rather than a figure.

        The blended rate is the ratio of the summed counts. It is *not* an
        average of the rail rates, and the two differ whenever the rails carry
        different volumes -- which is the whole reason the vision's UPI figure
        could not be reconciled with its portfolio claim (C-03).
        """
        side = diagnosis.failure.current
        rails = diagnosis.failure.by_method

        assert sum(entry.attempt_count for entry in rails) == side.attempt_count
        assert sum(entry.succeeded_count for entry in rails) == side.succeeded_count
        assert side.success_rate_ratio == f"{ratio(side.succeeded_count, side.attempt_count):.6f}"

        total = sum((Decimal(entry.success_rate_ratio) for entry in rails), Decimal(0))
        mean_of_rates = total / len(rails)
        assert quantize_ratio(mean_of_rates) != Decimal(side.success_rate_ratio)

    def test_the_upi_rate_is_a_different_metric_from_the_blended_rate(
        self, diagnosis: Diagnosis
    ) -> None:
        """C-03. Not a different *value* -- a different id, so they cannot be swapped."""
        published = {row.metric_id for row in diagnosis.evidence}
        assert "success_rate_ratio" in published
        assert "by_method.success_rate_ratio" in published

        upi = [
            row
            for row in diagnosis.evidence
            if row.metric_id == "by_method.success_rate_ratio"
            and row.dimension_value == "UPI"
            and row.period_from == CURRENT.from_.isoformat()
        ]
        assert len(upi) == 1
        assert upi[0].value == Decimal(TRUTH["current"]["by_method"]["UPI"]["success_rate_ratio"])

    def test_the_percentage_point_moves(self, diagnosis: Diagnosis) -> None:
        """A point, not a percent (C-04)."""
        assert diagnosis.failure.success_rate_pp_change == "-1.34"
        upi = next(entry for entry in diagnosis.failure.by_method if entry.method == "UPI")
        assert upi.success_rate_pp_change == "-1.82"

    def test_technical_declines_move_and_business_declines_do_not(
        self, diagnosis: Diagnosis
    ) -> None:
        """The asymmetry is the evidence, not either rate on its own.

        Technical declines roughly tripling while business declines stay flat is
        what attributes the movement to the rails rather than to customers.
        """
        technical = Decimal(diagnosis.failure.technical_decline_pp_change)
        business = Decimal(diagnosis.failure.business_decline_pp_change)
        assert technical > Decimal("1.0")
        assert abs(business) < Decimal("1.0")

    async def test_scoping_to_one_rail_says_so(self) -> None:
        """A narrowed figure must not be readable as a portfolio figure."""
        scoped = await _diagnose(execution_id="test-analysis-upi", method="UPI")
        assert scoped.failure.scope_method == "UPI"
        assert (
            scoped.failure.current.attempt_count
            == (TRUTH["current"]["by_method"]["UPI"]["attempt_count"])
        )
        assert any("scoped to UPI" in limitation for limitation in scoped.failure.limitations)


# --------------------------------------------------------------------------
# finance.refund_analysis and risk.chargeback_analysis
# --------------------------------------------------------------------------


class TestReversals:
    def test_refund_totals_and_rate(self, diagnosis: Diagnosis) -> None:
        current = diagnosis.refunds.current
        assert current.value_paise == TRUTH["current"]["refunds_paise"]
        assert current.gross_payments_paise == TRUTH["current"]["gross_payments_paise"]
        assert current.rate_ratio == (
            f"{ratio(current.value_paise, current.gross_payments_paise):.6f}"
        )
        assert diagnosis.refunds.prior.value_paise == TRUTH["prior"]["refunds_paise"]

    def test_chargeback_totals_and_rate(self, diagnosis: Diagnosis) -> None:
        current = diagnosis.chargebacks.current
        assert current.value_paise == TRUTH["current"]["chargebacks_paise"]
        assert current.rate_ratio == (
            f"{ratio(current.value_paise, current.gross_payments_paise):.6f}"
        )
        assert diagnosis.chargebacks.prior.value_paise == TRUTH["prior"]["chargebacks_paise"]

    def test_the_changes_agree_with_the_bridge_terms(self, diagnosis: Diagnosis) -> None:
        """The bridge enters these negated; the tools report them as they moved."""
        effects = {term.driver: term.effect_paise for term in diagnosis.revenue.attribution}
        assert diagnosis.refunds.refund_value_change_paise == -effects["REFUNDS"]
        assert diagnosis.chargebacks.chargeback_value_change_paise == -effects["CHARGEBACKS"]

    def test_reason_breakdowns_sum_to_the_totals(self, diagnosis: Diagnosis) -> None:
        for output in (diagnosis.refunds, diagnosis.chargebacks):
            for entry in (output.current, output.prior):
                assert sum(item.count for item in entry.by_reason) == entry.count
                assert sum(item.value_paise for item in entry.by_reason) == entry.value_paise

    def test_reasons_are_named_not_bucketed(self, diagnosis: Diagnosis) -> None:
        assert {item.reason for item in diagnosis.refunds.current.by_reason} <= {
            "CUSTOMER_REQUEST",
            "ITEM_UNAVAILABLE",
            "DUPLICATE_CHARGE",
        }
        assert {item.reason for item in diagnosis.chargebacks.current.by_reason} <= {
            "FRAUD",
            "SERVICE_NOT_RENDERED",
        }


# --------------------------------------------------------------------------
# cross-tool consistency
# --------------------------------------------------------------------------


class TestConsistency:
    def test_gross_payments_equals_succeeded_value(self, diagnosis: Diagnosis) -> None:
        """The Phase 4 exit criterion, exactly -- not to the nearest rupee."""
        assert (
            diagnosis.revenue.current.gross_payments_paise
            == diagnosis.failure.current.succeeded_value_paise
        )
        assert (
            diagnosis.revenue.prior.gross_payments_paise
            == diagnosis.failure.prior.succeeded_value_paise
        )

    def test_attempted_value_agrees_under_the_same_metric_id(self, diagnosis: Diagnosis) -> None:
        """Two tools, one id. The consistency layer finds these without help."""
        assert (
            diagnosis.revenue.current.attempted_value_paise
            == diagnosis.failure.current.attempted_value_paise
        )

    def test_every_declared_equivalence_holds(self, diagnosis: Diagnosis) -> None:
        """The table in the vocabulary, checked against the data it describes."""
        values: dict[tuple[str, str], set[int | Decimal]] = {}
        for row in diagnosis.evidence:
            values.setdefault((row.metric_id, row.period_from), set()).add(row.value)

        for left, right in EQUIVALENCES:
            for period in (CURRENT.from_.isoformat(), PRIOR.from_.isoformat()):
                left_values = values.get((left, period))
                right_values = values.get((right, period))
                assert left_values and right_values, f"{left}/{right} missing for {period}"
                assert left_values == right_values, (
                    f"{left} and {right} disagree for {period}: {left_values} vs {right_values}"
                )

    def test_a_metric_published_by_two_tools_has_one_value(self, diagnosis: Diagnosis) -> None:
        """gross_payments_paise comes from three tools. All three must agree."""
        by_key: dict[tuple[str, str], set[int | Decimal]] = {}
        publishers: dict[tuple[str, str], set[str]] = {}
        for row in diagnosis.evidence:
            if row.dimension_value is not None:
                continue
            key = (row.metric_id, row.period_from)
            by_key.setdefault(key, set()).add(row.value)
            publishers.setdefault(key, set()).add(row.tool_name)

        shared = {key for key, tools in publishers.items() if len(tools) > 1}
        assert shared, "no metric is published by more than one tool"
        for key in shared:
            assert len(by_key[key]) == 1, f"{key} disagrees across {publishers[key]}"


# --------------------------------------------------------------------------
# evidence, across all four tools
# --------------------------------------------------------------------------


class TestEvidence:
    def test_every_row_names_a_registered_metric_with_its_declared_unit(
        self, diagnosis: Diagnosis
    ) -> None:
        for row in diagnosis.evidence:
            assert row.metric_id in METRICS
            assert row.unit == unit_for(row.metric_id)

    def test_every_formula_re_evaluates_to_its_published_value(self, diagnosis: Diagnosis) -> None:
        """Layer 4 in miniature, now across four tools and forty-odd metrics."""
        derived = [row for row in diagnosis.evidence if row.formula is not None]
        assert len(derived) > 30

        quantize = {"paise": quantize_paise, "ratio": quantize_ratio, "pp": quantize_pp}
        for row in derived:
            assert row.formula is not None
            exact = evaluate(row.formula.expression, row.inputs)
            assert quantize[row.unit](exact) == row.value, (
                f"{row.id} does not match its own formula"
            )

    def test_every_leaf_cites_the_records_it_counts(self, diagnosis: Diagnosis) -> None:
        for row in diagnosis.evidence:
            if row.aggregation is None:
                continue
            assert len(row.source_record_ids) == row.inputs["record_count"]
            if row.value != 0 and row.aggregation.operation == "COUNT":
                assert len(row.source_record_ids) == row.value

    def test_every_dimensioned_row_names_its_slice(self, diagnosis: Diagnosis) -> None:
        for row in diagnosis.evidence:
            declared = METRICS[row.metric_id]
            assert (row.dimension_value is not None) == (declared.dimension is not None)

    def test_evidence_ids_are_unique(self, diagnosis: Diagnosis) -> None:
        """Two rows with one id is how a rail figure gets cited as a portfolio one."""
        ids = [row.id for row in diagnosis.evidence]
        assert len(set(ids)) == len(ids)

    def test_operands_resolve(self, diagnosis: Diagnosis) -> None:
        known = {row.id for row in diagnosis.evidence}
        for row in diagnosis.evidence:
            if row.formula is None:
                continue
            for operand, reference in row.formula.operands.items():
                assert reference in known or "." in reference, (
                    f"{row.id} operand {operand} points at {reference}"
                )


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------


class TestRefusals:
    @pytest.mark.parametrize(
        "tool_name",
        ["payments.failure_analysis", "finance.refund_analysis", "risk.chargeback_analysis"],
    )
    async def test_an_unknown_run_is_refused_by_every_tool(self, tool_name: str) -> None:
        async with connection() as conn:
            with pytest.raises(ToolError) as raised:
                await REGISTRY.resolve(tool_name).run(
                    {
                        "merchant_id": MERCHANT,
                        "period": {"from": CURRENT.from_, "to": CURRENT.to},
                        "comparison_period": {"from": PRIOR.from_, "to": PRIOR.to},
                        "run_id": "rec_nothing",
                    },
                    ToolContext(
                        merchant_id=MERCHANT,
                        period=CURRENT,
                        execution_id="test-missing-run",
                        conn=conn,
                    ),
                )
        assert raised.value.code == "RUN_NOT_FOUND"
