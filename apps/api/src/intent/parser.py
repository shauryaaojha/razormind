"""Turning a question into an intent, or asking one back.

The parser is the first place a model touches an execution and one of only two
places it ever does. It gets a schema and a question; it returns which analysis
to run and over which windows. It does not get the data, cannot see a number,
and its output is checked by the validator before a single tool runs.

**The gate is hard, not a heuristic.** Below ``intent_confidence_threshold``, or
with a required window missing, the run ends in ``NEEDS_CLARIFICATION`` and asks
one question. Guessing a comparison period is the single easiest way to produce
a confidently wrong finance answer -- "revenue is down 17.6%" against a window
nobody chose is indistinguishable, in the output, from the same sentence against
the right one.

**A parse failure is a retry, then a failure.** Never a free-text fallback: a
model that could not produce a valid intent has not earned a second, looser
channel to influence the run through.
"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from llm.provider import (
    Completion,
    LLMProvider,
    ProviderError,
    ProviderUnavailableError,
)

from .models import INTENT_TYPES, Clarification, Intent

__all__ = [
    "MAX_ATTEMPTS",
    "IntentParseError",
    "ParseOutcome",
    "intent_schema",
    "parse_intent",
    "system_prompt",
]

#: One retry. A second malformed response is a broken provider, not bad luck,
#: and looping on it turns a failure into a bill.
MAX_ATTEMPTS = 2

MAX_TOKENS = 1024


class IntentParseError(Exception):
    """The model produced nothing usable, twice, or no model was available."""

    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self.detail = detail or {}
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ParseOutcome:
    """Exactly one of these is set.

    A dataclass rather than a union return so the caller has to look at which
    one it got. ``intent`` means proceed; ``clarification`` means stop and ask.
    """

    intent: Intent | None = None
    clarification: Clarification | None = None
    #: What the provider charged, for the eval suite. ``None`` when no model ran.
    usage: Completion | None = None

    @property
    def needs_clarification(self) -> bool:
        return self.clarification is not None


def intent_schema() -> dict[str, Any]:
    """The JSON schema the provider constrains its output to.

    Generated from the model rather than written out, so the prompt and the
    thing it is validated against cannot drift apart.
    """
    return _inline_defs(Intent.model_json_schema(by_alias=True))


def _inline_defs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve ``$ref``s into the schema body.

    Providers accept ``$defs``, but a self-contained schema is what a reader of
    the prompt log can actually check the response against.
    """
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                return resolve(dict(defs[ref.removeprefix("#/$defs/")]))
            return {key: resolve(value) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    resolved: dict[str, Any] = resolve(schema)
    return resolved


def system_prompt(merchant_id: str, today: date) -> str:
    """What the model is told. Short, and every line load-bearing.

    ``today`` is passed in rather than read from a clock: "last month" has to
    resolve against the execution's own date, and a parser that read the wall
    clock could not be replayed.
    """
    return "\n".join(
        [
            "You route finance questions for a payments platform. You classify the question "
            "and identify the date windows. You never compute or state a number.",
            "",
            f"Available analyses: {', '.join(INTENT_TYPES)}.",
            "",
            f"The merchant is {merchant_id}. Echo it exactly; never substitute another.",
            f"Today is {today.isoformat()}. Periods are half-open: `to` is EXCLUSIVE, so "
            "the window through 23 August is to=2026-08-24.",
            "",
            "Set clarification_needed and give one clarification question when:",
            "  - the question does not name a period, or",
            "  - the analysis compares two windows and only one is identifiable, or",
            "  - you are not confident which analysis is being asked for.",
            "Do not guess a comparison period. Asking is always better than assuming: a "
            "comparison against a window nobody chose reads exactly like a correct answer.",
            "",
            "confidence_ratio is your own confidence in this routing, from 0 to 1.",
        ]
    )


async def parse_intent(
    question: str,
    *,
    provider: LLMProvider,
    merchant_id: str,
    today: date,
    threshold: Decimal,
    timeout_seconds: int = 30,
) -> ParseOutcome:
    """Parse, or ask. Raises only when no usable answer could be obtained at all."""
    completion = await _ask(question, provider, merchant_id, today, timeout_seconds)
    intent = _validate(completion, merchant_id)
    return _gate(intent, threshold, completion)


async def _ask(
    question: str,
    provider: LLMProvider,
    merchant_id: str,
    today: date,
    timeout_seconds: int,
) -> Completion:
    system = system_prompt(merchant_id, today)
    schema = intent_schema()
    last: ProviderError | None = None
    for _ in range(MAX_ATTEMPTS):
        try:
            return await provider.structured(
                system=system,
                prompt=question,
                schema=schema,
                max_tokens=MAX_TOKENS,
                timeout_seconds=timeout_seconds,
            )
        except ProviderUnavailableError as error:
            # Not retried. "No model is configured" does not become true on a
            # second attempt, and retrying it turns a clear message into a slow
            # one.
            raise IntentParseError(
                "PROVIDER_UNAVAILABLE", error.message, {"provider": provider.name}
            ) from error
        except ProviderError as error:
            last = error
    raise IntentParseError(
        "INTENT_PARSE_FAILED",
        f"the model failed {MAX_ATTEMPTS} times: {last.message if last else 'unknown'}",
        {"provider": provider.name},
    )


def _validate(completion: Completion, merchant_id: str) -> Intent:
    """The response must be an ``Intent``. There is no looser second channel.

    Parsed from the raw JSON text rather than from a dict, so ``0.92`` becomes
    ``Decimal("0.92")`` exactly instead of arriving via a binary float.
    """
    try:
        intent = Intent.model_validate_json(completion.text)
    except ValidationError as error:
        raise IntentParseError(
            "INTENT_PARSE_FAILED",
            f"the model's response is not a valid intent: {error.error_count()} error(s)",
            {"response": _trimmed(completion.text)},
        ) from error

    if intent.merchant_id != merchant_id:
        # Caught here as well as in the validator. The parser knows the session
        # merchant, so it can say what happened; by the time a plan reaches the
        # validator, the wrong id has already been copied into every node.
        raise IntentParseError(
            "MERCHANT_SCOPE_VIOLATION",
            f"the model named merchant {intent.merchant_id!r}, "
            f"but this session is scoped to {merchant_id!r}",
            {"requested": intent.merchant_id, "authorised": merchant_id},
        )
    return intent


def _gate(intent: Intent, threshold: Decimal, completion: Completion) -> ParseOutcome:
    """Ask rather than assume. Three reasons, each with its own code."""
    if intent.clarification_needed or intent.confidence_ratio < threshold:
        return ParseOutcome(
            clarification=Clarification(
                question=intent.clarification or _default_question(intent),
                reason="LOW_CONFIDENCE",
                confidence_ratio=intent.confidence_ratio,
                partial=intent,
            ),
            usage=completion,
        )
    if intent.period is None:
        return ParseOutcome(
            clarification=Clarification(
                question="Which period should I analyse?",
                reason="MISSING_PERIOD",
                confidence_ratio=intent.confidence_ratio,
                partial=intent,
            ),
            usage=completion,
        )
    if intent.requires_comparison() and intent.comparison_period is None:
        return ParseOutcome(
            clarification=Clarification(
                question=(
                    f"Which period should I compare {intent.period} against? "
                    "The preceding window of the same length, or the same dates last month?"
                ),
                reason="MISSING_COMPARISON_PERIOD",
                confidence_ratio=intent.confidence_ratio,
                partial=intent,
            ),
            usage=completion,
        )
    return ParseOutcome(intent=intent, usage=completion)


def _default_question(intent: Intent) -> str:
    return (
        f"I am not confident enough to run this ({intent.confidence_ratio}). "
        "Which analysis do you want, and over which dates?"
    )


def _trimmed(text: str, limit: int = 400) -> str:
    """Enough of the response to debug with, never the whole thing in a log."""
    compact = json.dumps(text)[1:-1]
    return compact if len(compact) <= limit else compact[:limit] + "..."
