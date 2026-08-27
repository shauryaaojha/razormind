"""The two v1 tools against a real Postgres, checked against the ground truth.

The Phase 3 exit criterion is that ``finance.revenue_analysis`` reproduces the
golden bridge and attribution table *exactly*. Exactly means every figure in
``data/seed/golden/ground_truth.json``, not a rounded summary of them -- the
generator derives those numbers from the calibration layer, and a tool that
agrees with them to five figures has a bug the sixth would have caught.

The last class here is a small standing rehearsal for layer 4 of verification:
every published formula is re-evaluated through the restricted interpreter and
must land on the published value. Phase 5 makes that the verifier; running it
now is what proves the formula grammar is strong enough to express the bridge
and weak enough to be worth running.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from evidence.formula import evaluate
from evidence.models import Evidence
from runtime.db import connection
from runtime.money import quantize_paise, quantize_ratio
from tools.base import Period, ToolContext, ToolError
from tools.catalog import REGISTRY
from tools.finance.reconciliation import ReconciliationOutput
from tools.finance.revenue import RevenueAnalysisOutput

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

#: The generator's attribution keys, in the tool's driver order.
TERM_FOR_DRIVER = {
    "ATTEMPT_VOLUME": "attempt_volume_paise",
    "SUCCESS_RATE": "success_rate_paise",
    "REFUNDS": "refunds_paise",
    "FEES": "fees_paise",
    "CHARGEBACKS": "chargebacks_paise",
}


async def _analyse(
    execution_id: str = "test-revenue",
    period: Period = CURRENT,
    comparison: Period = PRIOR,
) -> tuple[ReconciliationOutput, RevenueAnalysisOutput, tuple[Evidence, ...]]:
    """Reconcile, then analyse against that run -- the real dependency order."""
    reconciliation = REGISTRY.resolve("finance.reconciliation")
    revenue = REGISTRY.resolve("finance.revenue_analysis")

    async with connection() as conn:
        reconciled = await reconciliation.run(
            {"merchant_id": MERCHANT, "period": {"from": period.from_, "to": period.to}},
            ToolContext(merchant_id=MERCHANT, period=period, execution_id=execution_id, conn=conn),
        )
        run_out = reconciled.output
        assert isinstance(run_out, ReconciliationOutput)

        analysed = await revenue.run(
            {
                "merchant_id": MERCHANT,
                "period": {"from": period.from_, "to": period.to},
                "comparison_period": {"from": comparison.from_, "to": comparison.to},
                "run_id": run_out.run_id,
            },
            ToolContext(
                merchant_id=MERCHANT,
                period=period,
                execution_id=execution_id,
                conn=conn,
                reconciliation_run_id=run_out.run_id,
            ),
        )

    out = analysed.output
    assert isinstance(out, RevenueAnalysisOutput)
    return run_out, out, analysed.evidence


@pytest.fixture(scope="module")
async def analysis() -> tuple[ReconciliationOutput, RevenueAnalysisOutput, tuple[Evidence, ...]]:
    return await _analyse(execution_id="test-revenue-module")


Analysis = tuple[ReconciliationOutput, RevenueAnalysisOutput, tuple[Evidence, ...]]


# --------------------------------------------------------------------------
# the golden bridge
# --------------------------------------------------------------------------


class TestGoldenBridge:
    @pytest.mark.parametrize("window", ["current", "prior"])
    def test_every_figure_matches_the_ground_truth(self, analysis: Analysis, window: str) -> None:
        _, out, _ = analysis
        expected = TRUTH[window]
        bridge = out.current if window == "current" else out.prior

        assert bridge.attempt_count == expected["attempt_count"]
        assert bridge.capture_count == expected["capture_count"]
        assert bridge.attempted_value_paise == expected["attempted_value_paise"]
        assert bridge.gross_payments_paise == expected["gross_payments_paise"]
        assert bridge.refunds_paise == expected["refunds_paise"]
        assert bridge.fees_paise == expected["fees_paise"]
        assert bridge.chargebacks_paise == expected["chargebacks_paise"]
        assert bridge.net_revenue_paise == expected["net_revenue_paise"]
        assert bridge.success_rate_ratio == expected["success_rate_ratio"]

    def test_the_attribution_table_matches_the_ground_truth(self, analysis: Analysis) -> None:
        _, out, _ = analysis
        expected = TRUTH["attribution"]

        assert out.net_revenue_change_paise == expected["net_change_paise"]
        assert out.net_revenue_change_ratio == expected["net_change_ratio"]
        assert {term.driver: term.effect_paise for term in out.attribution} == {
            driver: expected["terms"][key] for driver, key in TERM_FOR_DRIVER.items()
        }
        assert out.rounding_residual_paise == expected["rounding_residual_paise"]

    def test_the_residual_is_within_its_bound(self, analysis: Analysis) -> None:
        """The Phase 3 exit criterion: abs(residual) <= term count."""
        _, out, _ = analysis
        assert abs(out.rounding_residual_paise) <= len(out.attribution)

    def test_the_bridge_closes_and_the_terms_close(self, analysis: Analysis) -> None:
        _, out, _ = analysis
        for bridge in (out.current, out.prior):
            assert bridge.net_revenue_paise == (
                bridge.gross_payments_paise
                - bridge.refunds_paise
                - bridge.fees_paise
                - bridge.chargebacks_paise
            )
        assert (
            sum(term.effect_paise for term in out.attribution) + out.rounding_residual_paise
            == out.net_revenue_change_paise
        )

    def test_the_incident_is_not_the_primary_driver(self, analysis: Analysis) -> None:
        """The trap, asserted (D-27).

        The technical-decline incident is the salient event in the window and it
        is *not* what moved revenue. A model reasoning from narrative rather
        than arithmetic names it anyway; the arithmetic says attempt volume, by
        an order of magnitude.
        """
        _, out, _ = analysis
        largest = min(out.attribution, key=lambda term: term.effect_paise)
        assert largest.driver == "ATTEMPT_VOLUME"
        rate = next(term for term in out.attribution if term.driver == "SUCCESS_RATE")
        assert abs(largest.effect_paise) > 10 * abs(rate.effect_paise)


# --------------------------------------------------------------------------
# what the reconciliation run contributes
# --------------------------------------------------------------------------


class TestRunDependency:
    def test_the_reconciliation_tool_reproduces_the_golden_run(self, analysis: Analysis) -> None:
        run_out, _, _ = analysis
        expected = TRUTH["reconciliation"]
        assert run_out.ledger_count == expected["ledger_count"]
        assert run_out.bank_count == expected["bank_count"]
        assert run_out.matched_pairs_count == expected["matched_pairs"]
        assert run_out.matched_clean_count == expected["matched_clean"]
        assert run_out.clean_match_rate_ratio == expected["clean_match_rate_ratio"]
        assert run_out.exception_count == expected["exception_count"]
        assert run_out.exception_breakdown == expected["exceptions_by_category"]
        assert run_out.unresolved_exception_value_paise == expected["unresolved_paise"]

    def test_the_duplicated_ledger_row_is_counted_but_not_earned(self, analysis: Analysis) -> None:
        """342 ledger records, 341 payments. The difference is not revenue."""
        run_out, out, _ = analysis
        duplicate = str(TRUTH["reconciliation"]["duplicate_transaction_id"])

        assert duplicate in run_out.sources.ledger_transaction_ids
        assert duplicate not in out.current_sources.capture_transaction_ids
        assert out.current.capture_count == run_out.ledger_count - 1

    def test_the_unresolved_value_is_a_band_and_never_a_bridge_term(
        self, analysis: Analysis
    ) -> None:
        """C-02's third error. It bounds the answer; it does not change it."""
        _, out, _ = analysis
        assert out.unresolved_exception_value_paise == TRUTH["reconciliation"]["unresolved_paise"]
        assert out.confidence_band_ratio == "0.004716"
        assert {term.driver for term in out.attribution} == set(TERM_FOR_DRIVER)

    def test_the_limitations_name_the_unreconciled_comparison_period(
        self, analysis: Analysis
    ) -> None:
        """Invariant 6: what the answer does not cover is said out loud."""
        _, out, _ = analysis
        assert any("not reconciled" in limitation for limitation in out.limitations)
        assert any(
            str(TRUTH["reconciliation"]["duplicate_transaction_id"]) in limitation
            for limitation in out.limitations
        )

    async def test_a_run_from_another_period_is_refused(self) -> None:
        """A run over a different window would import the wrong duplicates and band."""
        reconciliation = REGISTRY.resolve("finance.reconciliation")
        revenue = REGISTRY.resolve("finance.revenue_analysis")
        async with connection() as conn:
            other = await reconciliation.run(
                {"merchant_id": MERCHANT, "period": {"from": PRIOR.from_, "to": PRIOR.to}},
                ToolContext(
                    merchant_id=MERCHANT, period=PRIOR, execution_id="test-wrong-run", conn=conn
                ),
            )
            other_out = other.output
            assert isinstance(other_out, ReconciliationOutput)

            with pytest.raises(ToolError) as raised:
                await revenue.run(
                    {
                        "merchant_id": MERCHANT,
                        "period": {"from": CURRENT.from_, "to": CURRENT.to},
                        "comparison_period": {"from": PRIOR.from_, "to": PRIOR.to},
                        "run_id": other_out.run_id,
                    },
                    ToolContext(
                        merchant_id=MERCHANT,
                        period=CURRENT,
                        execution_id="test-wrong-run",
                        conn=conn,
                    ),
                )
        assert raised.value.code == "RUN_PERIOD_MISMATCH"

    async def test_an_unknown_run_is_a_stable_error_code(self) -> None:
        revenue = REGISTRY.resolve("finance.revenue_analysis")
        async with connection() as conn:
            with pytest.raises(ToolError) as raised:
                await revenue.run(
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


# --------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------


class TestDeterminism:
    async def test_the_same_execution_produces_the_same_run_id(self) -> None:
        """The run id is a function of the request, not of uuid4."""
        first, _, _ = await _analyse(execution_id="test-determinism-a")
        second, _, _ = await _analyse(execution_id="test-determinism-a")
        assert first.run_id == second.run_id

    async def test_a_different_execution_produces_a_different_run(self) -> None:
        first, _, _ = await _analyse(execution_id="test-determinism-b")
        second, _, _ = await _analyse(execution_id="test-determinism-c")
        assert first.run_id != second.run_id

    async def test_the_analysis_is_byte_identical_across_runs(self) -> None:
        _, first, _ = await _analyse(execution_id="test-determinism-d")
        _, second, _ = await _analyse(execution_id="test-determinism-d")
        assert first.model_dump_json() == second.model_dump_json()


# --------------------------------------------------------------------------
# a rehearsal for layer 4
# --------------------------------------------------------------------------


class TestEvidenceRecomputes:
    def test_every_published_metric_has_evidence(self, analysis: Analysis) -> None:
        _, _, rows = analysis
        published = {row.metric_id for row in rows}
        assert published >= {
            "gross_payments_paise",
            "refunds_paise",
            "fees_paise",
            "chargebacks_paise",
            "net_revenue_paise",
            "net_revenue_change_ratio",
            "rounding_residual_paise",
        }
        assert len(rows) == 21, "six per window, nine describing the change"

    def test_every_evidence_row_carries_exactly_one_kind_of_support(
        self, analysis: Analysis
    ) -> None:
        _, _, rows = analysis
        for row in rows:
            assert (row.formula is None) != (row.aggregation is None)

    def test_every_formula_re_evaluates_to_its_published_value(self, analysis: Analysis) -> None:
        """Layer 4, in miniature. The tool is not trusted; its formula is re-run."""
        _, _, rows = analysis
        derived = [row for row in rows if row.formula is not None]
        assert derived, "no derived metrics to check"

        for row in derived:
            assert row.formula is not None
            exact = evaluate(row.formula.expression, row.inputs)
            recomputed: int | Decimal = (
                quantize_ratio(exact) if row.unit == "ratio" else quantize_paise(exact)
            )
            assert recomputed == row.value, f"{row.metric_id} does not match its own formula"

    def test_every_leaf_metric_cites_records(self, analysis: Analysis) -> None:
        """A sum with nothing under it is a number nobody can check."""
        _, _, rows = analysis
        for row in rows:
            if row.aggregation is None or row.value == 0:
                continue
            assert row.source_record_ids, f"{row.metric_id} cites no records"
            assert len(row.source_record_ids) == row.inputs["record_count"]

    def test_operands_resolve_to_other_evidence(self, analysis: Analysis) -> None:
        """The provenance graph has no dangling edges within this tool."""
        _, _, rows = analysis
        known = {row.id for row in rows}
        for row in rows:
            if row.formula is None:
                continue
            for operand, reference in row.formula.operands.items():
                assert reference in known or reference.startswith("finance."), (
                    f"{row.metric_id} operand {operand} points at {reference}, "
                    "which is neither evidence nor a named cross-tool metric"
                )

    def test_the_evidence_ids_are_unique(self, analysis: Analysis) -> None:
        """Two rows with the same id is how a prior figure gets cited as current."""
        _, _, rows = analysis
        assert len({row.id for row in rows}) == len(rows)
