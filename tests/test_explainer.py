"""Regenerate once, then fall back, and never ship a number nobody checked.

The provider here is scripted. That is not a shortcut around testing the real
one: what needs asserting is that *an ungrounded answer cannot get out*, and a
live model that happened to be right on the day would demonstrate nothing about
that. The eval suite measures how often a real model is grounded on the first
attempt; this file measures what happens when it is not.

Every path out of the explainer is exercised: grounded first time, grounded
after a correction, ungrounded twice, malformed twice, and no model at all.
"""

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

import pytest

from evidence.builder import EvidenceSet
from evidence_fixtures import MERCHANT, bridge
from llm.explainer import MAX_ATTEMPTS, Draft, TemplateGroundingError, brief, explain
from llm.provider import Completion, DisabledProvider, ProviderTimeoutError, json_schema_for
from narrative import template as template_module
from narrative.render import canonical

QUESTION = "Why did net revenue fall in August?"


class ScriptedProvider:
    """Returns prepared responses in order, then repeats the last one."""

    name = "scripted"

    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: Mapping[str, Any],
        max_tokens: int,
        timeout_seconds: int,
    ) -> Completion:
        del system, schema, max_tokens, timeout_seconds
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self.responses) - 1)
        return Completion(
            text=self.responses[index], model="scripted", input_tokens=0, output_tokens=0
        )


class BrokenProvider:
    """A provider that is configured and does not answer."""

    name = "broken"

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: Mapping[str, Any],
        max_tokens: int,
        timeout_seconds: int,
    ) -> Completion:
        del system, prompt, schema, max_tokens, timeout_seconds
        raise ProviderTimeoutError("no response in 60s")


@pytest.fixture
def published() -> EvidenceSet:
    return EvidenceSet(bridge())


def answer(published: EvidenceSet, sentences: Sequence[tuple[str, str]]) -> str:
    """A well-formed response stating the named metrics, correctly."""
    rows = {row.metric_id: row for row in published}
    narrative = " ".join(sentence for _, sentence in sentences)
    return json.dumps(
        {
            "narrative": narrative,
            "claims": [
                {
                    "text": sentence,
                    "metric_id": metric_id,
                    "value": _wire(rows[metric_id].value),
                    "unit": rows[metric_id].unit,
                    "evidence_id": rows[metric_id].id,
                }
                for metric_id, sentence in sentences
            ],
        }
    )


def _wire(value: int | Decimal) -> int | str:
    return value if isinstance(value, int) else str(value)


def grounded(published: EvidenceSet) -> str:
    return answer(
        published,
        [
            ("net_revenue_paise", f"Net revenue was {canonical(39_447_800, 'paise')}."),
            (
                "net_revenue_change_ratio",
                f"That is {canonical(Decimal('-0.175956'), 'ratio')} against the prior window.",
            ),
        ],
    )


def rounded(published: EvidenceSet) -> str:
    """The same answer with the ratio restated to one decimal place."""
    row = next(row for row in published if row.metric_id == "net_revenue_change_ratio")
    sentence = "Net revenue fell 17.6% against the prior window."
    return json.dumps(
        {
            "narrative": sentence,
            "claims": [
                {
                    "text": sentence,
                    "metric_id": row.metric_id,
                    "value": str(row.value),
                    "unit": row.unit,
                    "evidence_id": row.id,
                }
            ],
        }
    )


def invented() -> str:
    sentence = "Net revenue was ₹5,00,000.00."
    return json.dumps({"narrative": sentence, "claims": []})


# --------------------------------------------------------------------------


async def test_a_grounded_answer_is_used_as_written(published: EvidenceSet) -> None:
    provider = ScriptedProvider(grounded(published))
    result = await explain(published, provider=provider, question=QUESTION, merchant_id=MERCHANT)
    assert result.source == "LLM"
    assert result.grounding_attempts == 1
    assert result.grounding.passed
    assert "Net revenue was ₹3,94,478.00." in result.explanation.narrative
    assert len(provider.prompts) == 1


async def test_an_invented_figure_is_regenerated_and_then_falls_back(
    published: EvidenceSet,
) -> None:
    """The exit criterion, in one test: caught, retried, and never shown."""
    provider = ScriptedProvider(invented(), invented())
    result = await explain(published, provider=provider, question=QUESTION, merchant_id=MERCHANT)
    assert len(provider.prompts) == MAX_ATTEMPTS
    assert result.source == "TEMPLATE_FALLBACK"
    assert result.reason == "GROUNDING_FAILED"
    assert result.grounding_attempts == MAX_ATTEMPTS
    assert "₹5,00,000.00" not in result.explanation.narrative


async def test_the_second_attempt_is_told_exactly_what_was_wrong(
    published: EvidenceSet,
) -> None:
    provider = ScriptedProvider(rounded(published), grounded(published))
    result = await explain(published, provider=provider, question=QUESTION, merchant_id=MERCHANT)
    assert result.source == "LLM"
    assert result.grounding_attempts == 2
    correction = provider.prompts[1]
    assert "rejected by the grounding check" in correction
    assert "17.6%" in correction
    assert "-17.5956%" in correction


async def test_a_malformed_response_twice_falls_back(published: EvidenceSet) -> None:
    provider = ScriptedProvider("{not json at all", "{still not}")
    result = await explain(published, provider=provider, question=QUESTION, merchant_id=MERCHANT)
    assert result.source == "TEMPLATE_FALLBACK"
    assert result.reason == "MALFORMED_EXPLANATION"


async def test_no_model_at_all_still_answers_with_every_verified_figure(
    published: EvidenceSet,
) -> None:
    """Degrade the prose, never the numbers."""
    result = await explain(
        published,
        provider=DisabledProvider("no ANTHROPIC_API_KEY is configured"),
        question=QUESTION,
        merchant_id=MERCHANT,
    )
    assert result.source == "TEMPLATE_FALLBACK"
    assert result.grounding_attempts == 0
    # The code, and then why -- a reader of the event log has to be able to
    # tell a missing key from a rate limit.
    assert result.reason is not None
    assert result.reason.startswith("PROVIDER_UNAVAILABLE: ")
    assert "ANTHROPIC_API_KEY" in result.reason
    for row in published:
        assert canonical(row.value, row.unit) in result.explanation.narrative


async def test_a_provider_timeout_is_not_retried(published: EvidenceSet) -> None:
    result = await explain(
        published, provider=BrokenProvider(), question=QUESTION, merchant_id=MERCHANT
    )
    assert result.source == "TEMPLATE_FALLBACK"
    assert result.reason is not None
    assert result.reason.startswith("PROVIDER_TIMEOUT: ")


async def test_the_fallback_is_held_to_the_same_gate(published: EvidenceSet) -> None:
    result = await explain(
        published, provider=DisabledProvider("off"), question=QUESTION, merchant_id=MERCHANT
    )
    assert result.grounding.passed
    assert len(result.grounding.checks) >= len(published)


async def test_an_ungroundable_template_raises_rather_than_being_shown(
    published: EvidenceSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    """There is no floor below the template, so there is no answer below it either.

    The template cannot produce an unclaimed number by construction, so one is
    forced in. That is the point: the guard exists for the edit that breaks the
    construction, and an unreachable guard nobody has fired is an assumption.
    """
    monkeypatch.setattr(template_module, "PREAMBLE", "Rendered from 3 verified metrics.")
    with pytest.raises(TemplateGroundingError):
        await explain(
            published,
            provider=DisabledProvider("off"),
            question=QUESTION,
            merchant_id=MERCHANT,
        )


def test_the_model_is_never_asked_for_the_limitations() -> None:
    """A limitation is the executor's fact, so there is no field to smuggle one into."""
    assert "limitations" not in json_schema_for(Draft)["properties"]


def test_the_brief_hands_the_model_the_exact_string_to_copy(published: EvidenceSet) -> None:
    text = brief(published)
    for row in published:
        assert row.id in text
        assert canonical(row.value, row.unit) in text


def test_the_brief_carries_the_raw_value_a_claim_has_to_declare(
    published: EvidenceSet,
) -> None:
    """Grounding checks two spellings, so the brief has to hand over two.

    Without the raw column a model can only reach the claim's value by stripping
    the rupee sign and the grouping back off the rendering -- the conversion the
    first rule forbids -- so the instruction contradicted itself and the claim
    was wrong whichever rule the model followed.
    """
    text = brief(published)
    for row in published:
        assert str(row.value) in text
    assert "| value | value as written |" in text


def test_the_brief_never_leaks_a_source_record(published: EvidenceSet) -> None:
    """The model gets metrics and evidence ids. It has no business with rows."""
    assert "TXN_1" not in brief(published)
