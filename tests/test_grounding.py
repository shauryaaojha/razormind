"""Rendering, the template, and the five checks between a number and a sentence.

The test that matters most here is not any single check -- it is
``test_the_template_passes_the_gate_it_exists_to_be_the_fallback_for``. A
fallback judged more leniently than the thing it replaces is not a fallback,
and the only way to know the two paths are held to one standard is to run the
standard over both.

Everything else is a defect somebody would otherwise ship: a rate restated to
one decimal place, a percentage point written with a percent sign, a figure in
the prose that no claim accounts for.
"""

from decimal import Decimal

import pytest

from evidence.builder import EvidenceSet
from evidence.models import Aggregation, Evidence
from evidence.vocabulary import METRICS
from evidence_fixtures import MERCHANT, PRIOR, WINDOW, bridge
from llm.grounding import CHECKS, check_grounding, literals_for
from narrative.models import Claim, Explanation
from narrative.render import canonical, renderings
from narrative.template import compose, label


@pytest.fixture
def published() -> EvidenceSet:
    return EvidenceSet(bridge())


def one_claim(published: EvidenceSet, metric_id: str, sentence: str) -> Explanation:
    """An answer stating exactly one metric, in the sentence given."""
    row = next(row for row in published if row.metric_id == metric_id)
    return Explanation(
        narrative=sentence,
        claims=[
            Claim(
                text=sentence,
                metric_id=row.metric_id,
                value=row.value,
                unit=row.unit,
                evidence_id=row.id,
            )
        ],
    )


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def test_money_is_grouped_the_indian_way() -> None:
    assert canonical(40_626_000, "paise") == "₹4,06,260.00"
    assert canonical(123_456_789_00, "paise") == "₹12,34,56,789.00"
    assert canonical(-1_178_200, "paise") == "-₹11,782.00"


def test_dropping_a_trailing_zero_is_allowed_and_dropping_a_digit_is_not() -> None:
    forms = renderings(40_626_000, "paise")
    assert "₹4,06,260" in forms  # the paise are zero; nothing was lost
    assert "₹4,06,26" not in forms
    assert "₹406260.00" not in forms  # a different grouping is a different string


def test_a_ratio_is_written_as_a_percentage_with_every_digit_kept() -> None:
    assert canonical(Decimal("0.958012"), "ratio") == "95.8012%"
    assert canonical(Decimal("0.958000"), "ratio") == "95.80%"
    assert canonical(Decimal("-0.175956"), "ratio") == "-17.5956%"


def test_a_percentage_point_is_never_written_with_a_percent_sign() -> None:
    forms = renderings(Decimal("-1.34"), "pp")
    assert forms[0] == "-1.34"
    assert not any("%" in form for form in forms)


def test_the_unsigned_magnitude_is_accepted_because_the_sign_lives_in_the_verb() -> None:
    forms = renderings(Decimal("-1.34"), "pp")
    assert "1.34" in forms and "-1.34" in forms


def test_counts_are_grouped_but_never_decimalised() -> None:
    assert canonical(342, "count") == "342"
    assert canonical(13_420, "count") == "13,420"
    assert "13420" in renderings(13_420, "count")


def test_a_value_of_the_wrong_python_type_for_its_unit_is_refused() -> None:
    with pytest.raises(TypeError):
        renderings(Decimal("1.5"), "paise")
    with pytest.raises(TypeError):
        renderings(1, "ratio")


# --------------------------------------------------------------------------
# labels and the template
# --------------------------------------------------------------------------


def test_a_label_is_derived_from_the_metric_id_and_carries_no_digits() -> None:
    rows = {row.metric_id: row for row in _every_row()}
    assert label(rows["net_revenue_paise"]) == "Net revenue"
    assert label(rows["success_rate_pp_change"]) == "Success rate change"
    assert not any(character.isdigit() for row in _every_row() for character in label(row))


def _every_row() -> list[Evidence]:
    """One row per registered metric, so every label is exercised."""
    rows: list[Evidence] = []
    for metric_id, entry in METRICS.items():
        value: int | Decimal = 1 if entry.unit in {"paise", "count"} else Decimal("0.50")
        dimension = None
        if entry.dimension is not None:
            dimension = sorted(entry.values)[0] if entry.values else "DUPLICATE"
        rows.append(
            Evidence(
                id=f"t/1.0/{metric_id}/{WINDOW[0]}_{WINDOW[1]}",
                execution_id="exec",
                tool_name="t",
                tool_version="1.0",
                metric_id=metric_id,
                unit=entry.unit,
                value=value,
                period_from=WINDOW[0],
                period_to=WINDOW[1],
                dimension_value=dimension,
                aggregation=Aggregation(
                    operation="SUM",
                    field_name="amount_paise",
                    over="transactions",
                    predicate="everything",
                    unit=entry.unit,
                    scoped_by="ATTEMPT_DATE",
                ),
                source_record_ids=["TXN_1"],
            )
        )
    return rows


def test_the_template_states_every_verified_row_once(published: EvidenceSet) -> None:
    explanation = compose(published)
    assert len(explanation.claims) == len(published)
    for row in published:
        assert canonical(row.value, row.unit) in explanation.narrative


def test_the_template_passes_the_gate_it_exists_to_be_the_fallback_for(
    published: EvidenceSet,
) -> None:
    explanation = compose(published)
    report = check_grounding(explanation, published, literals=literals_for(published, MERCHANT))
    assert report.passed, report.failures


def test_the_template_reads_the_current_window_before_the_comparison(
    published: EvidenceSet,
) -> None:
    narrative = compose(published).narrative
    assert narrative.index(f"[{WINDOW[0]}") < narrative.index(f"[{PRIOR[0]}")


def test_the_template_says_what_did_not_run_without_inventing_it(
    published: EvidenceSet,
) -> None:
    limitation = "payments.failure_analysis did not run (failed); its metrics are unavailable."
    explanation = compose(published, limitations=[limitation])
    assert explanation.limitations == [limitation]
    # Not restated in the prose: a limitation is the executor's fact, and the
    # narrative is subject to grounding.
    assert limitation not in explanation.narrative


# --------------------------------------------------------------------------
# the five checks
# --------------------------------------------------------------------------


def test_all_five_checks_run_over_a_real_answer(published: EvidenceSet) -> None:
    report = check_grounding(
        compose(published), published, literals=literals_for(published, MERCHANT)
    )
    for name in CHECKS:
        assert any(check.startswith(name) for check in report.checks), name


def test_an_invented_figure_is_caught(published: EvidenceSet) -> None:
    explanation = one_claim(
        published, "net_revenue_paise", "Net revenue was ₹3,94,478.00, down from ₹5,00,000.00."
    )
    report = check_grounding(explanation, published, literals=literals_for(published, MERCHANT))
    assert not report.passed
    assert any("₹5,00,000.00" in failure for failure in report.failures)


def test_a_number_with_no_claim_at_all_is_caught(published: EvidenceSet) -> None:
    explanation = Explanation(narrative="Revenue fell by ₹4,06,260.00.", claims=[])
    report = check_grounding(explanation, published, literals=literals_for(published, MERCHANT))
    assert not report.passed
    assert any(
        CHECKS[0] in failure or "no claim covers it" in failure for failure in report.failures
    )


def test_the_analysis_dates_and_the_merchant_may_appear_unclaimed(
    published: EvidenceSet,
) -> None:
    explanation = one_claim(
        published,
        "net_revenue_paise",
        f"For {MERCHANT} over 2026-08-01 to 2026-08-24, net revenue was ₹3,94,478.00.",
    )
    report = check_grounding(explanation, published, literals=literals_for(published, MERCHANT))
    assert report.passed, report.failures


def test_a_date_outside_the_analysis_is_not_exempt(published: EvidenceSet) -> None:
    explanation = one_claim(
        published, "net_revenue_paise", "Since 2025-01-01 net revenue was ₹3,94,478.00."
    )
    report = check_grounding(explanation, published, literals=literals_for(published, MERCHANT))
    assert not report.passed


def test_an_unregistered_metric_id_is_caught(published: EvidenceSet) -> None:
    row = next(row for row in published if row.metric_id == "net_revenue_paise")
    sentence = "Profit was ₹3,94,478.00."
    explanation = Explanation(
        narrative=sentence,
        claims=[
            Claim(
                text=sentence,
                metric_id="profit_paise",
                value=row.value,
                unit="paise",
                evidence_id=row.id,
            )
        ],
    )
    report = check_grounding(explanation, published, literals=literals_for(published, MERCHANT))
    assert not report.passed
    assert any(CHECKS[1] in failure for failure in report.failures)


def test_a_value_restated_at_a_lower_precision_fails_the_byte_match(
    published: EvidenceSet,
) -> None:
    """The exit criterion: a rate restated to one decimal place is not the rate."""
    row = next(row for row in published if row.metric_id == "success_rate_ratio")
    sentence = "The success rate was 95.8%."
    explanation = Explanation(
        narrative=sentence,
        claims=[
            Claim(
                text=sentence,
                metric_id=row.metric_id,
                value=Decimal("0.958"),
                unit=row.unit,
                evidence_id=row.id,
            )
        ],
    )
    report = check_grounding(explanation, published, literals=literals_for(published, MERCHANT))
    assert not report.passed
    assert any("0.958012" in failure for failure in report.failures)


def test_the_right_value_written_wrongly_still_fails(published: EvidenceSet) -> None:
    """A model may declare the exact figure and round it in the sentence."""
    explanation = one_claim(published, "success_rate_ratio", "The success rate was 95.8%.")
    report = check_grounding(explanation, published, literals=literals_for(published, MERCHANT))
    assert not report.passed
    assert any("95.8%" in failure for failure in report.failures)


def test_a_percentage_point_written_as_a_percent_is_caught(published: EvidenceSet) -> None:
    explanation = one_claim(
        published, "success_rate_pp_change", "The success rate moved by -1.34%."
    )
    report = check_grounding(explanation, published, literals=literals_for(published, MERCHANT))
    assert not report.passed


def test_a_claim_in_the_wrong_unit_is_caught(published: EvidenceSet) -> None:
    row = next(row for row in published if row.metric_id == "success_rate_pp_change")
    sentence = "The success rate moved by -1.34."
    explanation = Explanation(
        narrative=sentence,
        claims=[
            Claim(
                text=sentence,
                metric_id=row.metric_id,
                value=row.value,
                unit="ratio",
                evidence_id=row.id,
            )
        ],
    )
    report = check_grounding(explanation, published, literals=literals_for(published, MERCHANT))
    assert not report.passed
    assert any(CHECKS[3] in failure for failure in report.failures)


def test_an_evidence_id_from_no_execution_is_caught(published: EvidenceSet) -> None:
    sentence = "Net revenue was ₹3,94,478.00."
    explanation = Explanation(
        narrative=sentence,
        claims=[
            Claim(
                text=sentence,
                metric_id="net_revenue_paise",
                value=39_447_800,
                unit="paise",
                evidence_id="somebody/1.0/net_revenue_paise/2026-08-01_2026-08-24",
            )
        ],
    )
    report = check_grounding(explanation, published, literals=literals_for(published, MERCHANT))
    assert not report.passed
    assert any(CHECKS[4] in failure for failure in report.failures)


def test_a_claim_whose_text_is_not_in_the_answer_is_caught(published: EvidenceSet) -> None:
    row = next(row for row in published if row.metric_id == "net_revenue_paise")
    explanation = Explanation(
        narrative="Net revenue held steady.",
        claims=[
            Claim(
                text="Net revenue was ₹3,94,478.00.",
                metric_id=row.metric_id,
                value=row.value,
                unit=row.unit,
                evidence_id=row.id,
            )
        ],
    )
    report = check_grounding(explanation, published, literals=literals_for(published, MERCHANT))
    assert not report.passed
    assert any("is not a span of the answer" in failure for failure in report.failures)


def test_a_claim_covering_the_whole_answer_does_not_launder_the_other_numbers(
    published: EvidenceSet,
) -> None:
    """The obvious way to satisfy check 1 cheaply, and it fails check 3."""
    row = next(row for row in published if row.metric_id == "net_revenue_paise")
    narrative = "Net revenue was ₹3,94,478.00 and something else was ₹9,99,999.00."
    explanation = Explanation(
        narrative=narrative,
        claims=[
            Claim(
                text=narrative,
                metric_id=row.metric_id,
                value=row.value,
                unit=row.unit,
                evidence_id=row.id,
            )
        ],
    )
    report = check_grounding(explanation, published, literals=literals_for(published, MERCHANT))
    assert not report.passed
    assert any("₹9,99,999.00" in failure for failure in report.failures)


def test_literals_are_taken_from_the_evidence_not_from_the_answer(
    published: EvidenceSet,
) -> None:
    allowed = literals_for(published)
    assert allowed == {WINDOW[0], WINDOW[1], PRIOR[0], PRIOR[1]}
