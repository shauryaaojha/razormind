"""Ten seeded questions, and the gate that refuses to guess.

The provider here is **scripted**: it returns the JSON a model would return, so
the parser's own behaviour -- validation, the confidence gate, the three
clarification reasons, the merchant check, the retry -- is tested
deterministically and completely. A test that called a real model would measure
the model, cost money to run, and fail for reasons unrelated to this code.

Whether a real model produces the right intent for these questions is a
different question with a different answer, and Phase 11's eval suite is where
it belongs: it is a *score*, not a pass/fail, because a model that is right 29
times out of 30 has not broken the build.
"""

import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from intent.models import Intent
from intent.parser import (
    IntentParseError,
    intent_schema,
    parse_intent,
    system_prompt,
)
from llm.provider import (
    Completion,
    DisabledProvider,
    ProviderError,
    ProviderTimeoutError,
)

MERCHANT = "M123"
TODAY = date(2026, 8, 24)
THRESHOLD = Decimal("0.75")

AUGUST = {"from": "2026-08-01", "to": "2026-08-24"}
JULY = {"from": "2026-07-01", "to": "2026-07-24"}


class ScriptedProvider:
    """Returns a fixed response. Counts calls, so a retry is visible."""

    name = "scripted"

    def __init__(self, *responses: str | ProviderError) -> None:
        self._responses = list(responses)
        self.calls = 0

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
        self.calls += 1
        response = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(response, ProviderError):
            raise response
        return Completion(text=response, model="scripted", input_tokens=0, output_tokens=0)


def says(**fields: Any) -> ScriptedProvider:
    body: dict[str, Any] = {
        "merchant_id": MERCHANT,
        "confidence_ratio": "0.92",
        "clarification_needed": False,
        **fields,
    }
    return ScriptedProvider(json.dumps(body))


async def parse(provider: Any, question: str = "why?") -> Any:
    return await parse_intent(
        question,
        provider=provider,
        merchant_id=MERCHANT,
        today=TODAY,
        threshold=THRESHOLD,
    )


# --------------------------------------------------------------------------
# the ten seeded questions
# --------------------------------------------------------------------------

#: Question, the response a model should give, and what the parser must do with
#: it. Seven route and three ask -- and the three that ask are the ones that
#: matter: every one of them is a question a system that guesses would answer
#: confidently and wrongly.
SEEDED: tuple[tuple[str, dict[str, Any], str], ...] = (
    (
        "Why did net revenue fall in August compared with July?",
        {"intent": "revenue_diagnosis", "period": AUGUST, "comparison_period": JULY},
        "revenue_diagnosis",
    ),
    (
        "Break down the revenue decline for 1-23 August against the same window in July.",
        {"intent": "revenue_diagnosis", "period": AUGUST, "comparison_period": JULY},
        "revenue_diagnosis",
    ),
    (
        "Did our payment success rate drop in August?",
        {"intent": "failure_analysis", "period": AUGUST, "comparison_period": JULY},
        "failure_analysis",
    ),
    (
        "Are UPI failures up month over month?",
        {"intent": "failure_analysis", "period": AUGUST, "comparison_period": JULY},
        "failure_analysis",
    ),
    (
        "How did reconciliation go for August?",
        {"intent": "reconciliation_status", "period": AUGUST},
        "reconciliation_status",
    ),
    (
        "Are refunds higher this month than last?",
        {"intent": "refund_analysis", "period": AUGUST, "comparison_period": JULY},
        "refund_analysis",
    ),
    (
        "What is our chargeback exposure in August versus July?",
        {"intent": "chargeback_analysis", "period": AUGUST, "comparison_period": JULY},
        "chargeback_analysis",
    ),
    (
        "How did revenue change?",
        {
            "intent": "revenue_diagnosis",
            "period": AUGUST,
            "clarification_needed": True,
            "clarification": "Which period should I compare against?",
        },
        "CLARIFY",
    ),
    (
        "Show me the numbers.",
        {"intent": "revenue_diagnosis", "confidence_ratio": "0.31"},
        "CLARIFY",
    ),
    (
        "Is anything wrong?",
        {"intent": "revenue_diagnosis", "period": AUGUST, "confidence_ratio": "0.55"},
        "CLARIFY",
    ),
)


@pytest.mark.parametrize(("question", "response", "expected"), SEEDED)
async def test_the_seeded_questions_route_or_ask(
    question: str, response: dict[str, Any], expected: str
) -> None:
    outcome = await parse(says(**response), question)
    if expected == "CLARIFY":
        assert outcome.needs_clarification, f"{question!r} should have asked"
        assert outcome.clarification is not None
        assert outcome.clarification.question
    else:
        assert outcome.intent is not None, f"{question!r} should have routed"
        assert outcome.intent.intent == expected


async def test_three_of_the_ten_ask_rather_than_guess() -> None:
    """Asserted as a count so a change to the gate cannot pass silently.

    A gate that quietly stopped firing would leave every one of these ten
    questions answered -- three of them against a window nobody chose.
    """
    assert len(SEEDED) == 10
    assert len([row for row in SEEDED if row[2] == "CLARIFY"]) == 3


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------


class TestTheConfidenceGate:
    async def test_below_the_threshold_asks(self) -> None:
        outcome = await parse(
            says(
                intent="revenue_diagnosis",
                period=AUGUST,
                comparison_period=JULY,
                confidence_ratio="0.74",
            )
        )
        assert outcome.clarification is not None
        assert outcome.clarification.reason == "LOW_CONFIDENCE"

    async def test_exactly_at_the_threshold_proceeds(self) -> None:
        """The threshold is a floor, not a fence. 0.75 is confident enough."""
        outcome = await parse(
            says(
                intent="revenue_diagnosis",
                period=AUGUST,
                comparison_period=JULY,
                confidence_ratio="0.75",
            )
        )
        assert outcome.intent is not None

    async def test_a_missing_period_asks(self) -> None:
        outcome = await parse(says(intent="revenue_diagnosis"))
        assert outcome.clarification is not None
        assert outcome.clarification.reason == "MISSING_PERIOD"

    async def test_a_missing_comparison_asks_and_offers_two_options(self) -> None:
        """Guessing this is the single easiest way to be confidently wrong."""
        outcome = await parse(says(intent="revenue_diagnosis", period=AUGUST))
        assert outcome.clarification is not None
        assert outcome.clarification.reason == "MISSING_COMPARISON_PERIOD"
        assert "preceding window" in outcome.clarification.question

    async def test_reconciliation_status_needs_no_comparison(self) -> None:
        outcome = await parse(says(intent="reconciliation_status", period=AUGUST))
        assert outcome.intent is not None

    async def test_a_clarification_keeps_what_was_understood(self) -> None:
        """A resumed execution should not start from nothing."""
        outcome = await parse(says(intent="refund_analysis", period=AUGUST))
        assert outcome.clarification is not None
        assert outcome.clarification.partial is not None
        assert outcome.clarification.partial.intent == "refund_analysis"


# --------------------------------------------------------------------------
# refusals
# --------------------------------------------------------------------------


class TestRefusals:
    async def test_a_foreign_merchant_is_refused(self) -> None:
        """C-13. The merchant comes from the session; the model only echoes it."""
        provider = ScriptedProvider(
            json.dumps(
                {
                    "intent": "revenue_diagnosis",
                    "merchant_id": "M999",
                    "period": AUGUST,
                    "comparison_period": JULY,
                    "confidence_ratio": "0.95",
                    "clarification_needed": False,
                }
            )
        )
        with pytest.raises(IntentParseError, match="MERCHANT_SCOPE_VIOLATION") as caught:
            await parse(provider)
        assert caught.value.detail == {"requested": "M999", "authorised": MERCHANT}

    async def test_an_unparseable_response_is_retried_once_then_fails(self) -> None:
        provider = ScriptedProvider("not json at all")
        with pytest.raises(IntentParseError, match="INTENT_PARSE_FAILED"):
            await parse(provider)
        # One call: the response arrived and was invalid. A retry is for a
        # provider that failed, not for a model that answered badly -- asking
        # the same question again is how a parse failure becomes a bill.
        assert provider.calls == 1

    async def test_a_provider_failure_is_retried(self) -> None:
        provider = ScriptedProvider(
            ProviderTimeoutError("slow"),
            json.dumps(
                {
                    "intent": "revenue_diagnosis",
                    "merchant_id": MERCHANT,
                    "period": AUGUST,
                    "comparison_period": JULY,
                    "confidence_ratio": "0.9",
                    "clarification_needed": False,
                }
            ),
        )
        outcome = await parse(provider)
        assert provider.calls == 2
        assert outcome.intent is not None

    async def test_two_provider_failures_fail(self) -> None:
        provider = ScriptedProvider(ProviderTimeoutError("slow"))
        with pytest.raises(IntentParseError, match="INTENT_PARSE_FAILED"):
            await parse(provider)
        assert provider.calls == 2

    async def test_no_provider_is_not_retried(self) -> None:
        """ "No model is configured" does not become false on a second attempt."""
        with pytest.raises(IntentParseError, match="PROVIDER_UNAVAILABLE"):
            await parse(DisabledProvider("llm_enabled is false"))

    async def test_an_unknown_intent_type_is_refused(self) -> None:
        with pytest.raises(IntentParseError, match="INTENT_PARSE_FAILED"):
            await parse(says(intent="delete_everything", period=AUGUST))

    async def test_a_confidence_outside_zero_to_one_is_refused(self) -> None:
        with pytest.raises(IntentParseError):
            await parse(
                says(
                    intent="revenue_diagnosis",
                    period=AUGUST,
                    comparison_period=JULY,
                    confidence_ratio="1.4",
                )
            )


class TestTheContract:
    def test_the_schema_carries_no_unresolved_refs(self) -> None:
        """A provider is sent one self-contained schema, not a graph of them."""
        rendered = json.dumps(intent_schema())
        assert "$ref" not in rendered
        assert "$defs" not in rendered

    def test_the_schema_uses_the_wire_name_for_the_period_start(self) -> None:
        schema = intent_schema()
        assert "from" in schema["properties"]["period"]["anyOf"][0]["properties"]

    def test_the_prompt_states_the_half_open_convention(self) -> None:
        """`to` is exclusive, and a model that assumes otherwise is off by a day."""
        prompt = system_prompt(MERCHANT, TODAY)
        assert "EXCLUSIVE" in prompt
        assert MERCHANT in prompt
        assert TODAY.isoformat() in prompt

    def test_confidence_survives_as_an_exact_decimal(self) -> None:
        """Parsed from JSON text, so 0.1 is 0.1 and not the nearest double."""
        intent = Intent.model_validate_json(
            json.dumps(
                {
                    "intent": "revenue_diagnosis",
                    "merchant_id": MERCHANT,
                    "confidence_ratio": 0.1,
                    "clarification_needed": False,
                }
            )
        )
        assert intent.confidence_ratio == Decimal("0.1")
