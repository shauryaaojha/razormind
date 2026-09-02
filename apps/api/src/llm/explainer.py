"""Phrasing verified numbers, and the two ways that is allowed to fail.

The model gets the metrics, their units, their windows, the exact string each
one is written as, and the formula that produced the derived ones. It does not
get the database, the tools, the question's merchant's other data, or any
number that has not already passed all five verification layers. Its entire
privilege is word order.

```text
attempt 1 -> grounded?  -> answer, response_source = LLM
          -> not grounded, name every failure
attempt 2 -> grounded?  -> answer, response_source = LLM
          -> not grounded
                        -> template, response_source = TEMPLATE_FALLBACK
```

Handing the failed claims back on the second attempt is what makes one retry
worth having. A bare "try again" re-rolls the same dice; "you wrote 95.80%, the
verified figure is 95.8012%" is a correction, and most grounding failures are
that kind of near miss (C-15h).

**A provider failure skips straight to the template.** No retry, because a
missing model does not become present on a second call, and no error, because
the numbers are already verified and the user is entitled to them. This is the
one degradation in the system that costs nothing but prose.

The template is subject to the same five checks, and if it somehow failed them
this module raises rather than returning. That is not defensive coding: prose
whose numbers were not matched against the evidence is the exact output the
trust layer exists to make impossible, and there is no version of "the fallback
is ungrounded" that should reach a reader.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from evidence.builder import EvidenceSet
from evidence.models import Evidence
from narrative.models import Claim, Explanation
from narrative.render import canonical
from narrative.template import compose
from verification.models import VerificationResult

from .grounding import check_grounding, literals_for
from .provider import Completion, LLMProvider, ProviderError, json_schema_for

__all__ = [
    "MAX_ATTEMPTS",
    "Explained",
    "TemplateGroundingError",
    "brief",
    "explain",
    "system_prompt",
]

#: One generation, one correction. A third attempt would be a third bill for a
#: model that has now been told exactly what was wrong and still missed.
MAX_ATTEMPTS = 2

MAX_TOKENS = 4096

#: Longer than the intent parser's budget: this call carries the whole evidence
#: brief and writes several paragraphs, where the parser emits one small object.
TIMEOUT_SECONDS = 60

type ResponseSource = Literal["LLM", "TEMPLATE_FALLBACK"]


class TemplateGroundingError(RuntimeError):
    """The deterministic fallback failed the grounding gate. Nothing may be shown."""


class Draft(BaseModel):
    """What the model returns. Narrower than :class:`Explanation`, on purpose.

    ``limitations`` is not in here and never will be. What a run could not
    cover is a fact the executor holds -- which nodes failed, and with which
    code -- and asking the model to restate it would put a sentence about
    missing data next to no way of checking it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    narrative: str
    claims: list[Claim] = []


@dataclass(frozen=True)
class Explained:
    """The answer, where it came from, and what it cost to get there."""

    explanation: Explanation
    source: ResponseSource
    grounding_attempts: int
    grounding: VerificationResult
    #: Why the template was used, when it was. ``None`` on the model path.
    reason: str | None = None
    usage: tuple[Completion, ...] = ()

    @property
    def from_model(self) -> bool:
        return self.source == "LLM"


async def explain(
    published: EvidenceSet,
    *,
    provider: LLMProvider,
    question: str,
    merchant_id: str,
    limitations: Sequence[str] = (),
    timeout_seconds: int = TIMEOUT_SECONDS,
) -> Explained:
    """Ask the model to phrase the verified metrics; fall back to the template."""
    fallback = compose(published, limitations=limitations)
    literals = literals_for(published, merchant_id)

    system = system_prompt()
    evidence_brief = brief(published)
    corrections: tuple[str, ...] = ()
    spent: list[Completion] = []
    last: VerificationResult | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            completion = await provider.structured(
                system=system,
                prompt=_prompt(question, evidence_brief, limitations, corrections),
                schema=json_schema_for(Draft),
                max_tokens=MAX_TOKENS,
                timeout_seconds=timeout_seconds,
            )
        except ProviderError as error:
            # The whole message, not just the code. "PROVIDER_UNAVAILABLE" on
            # its own cannot tell a missing key from a retired model from a
            # rate limit, and those want three different responses from whoever
            # reads the event log. The code stays the prefix.
            return _fallback(fallback, published, literals, attempt - 1, str(error), tuple(spent))

        spent.append(completion)
        try:
            draft = Draft.model_validate_json(completion.text)
        except ValidationError as error:
            corrections = (f"your response was not a valid answer: {error.error_count()} error(s)",)
            last = None
            continue

        candidate = Explanation(
            narrative=draft.narrative,
            claims=draft.claims,
            limitations=list(limitations),
        )
        grounded = check_grounding(candidate, published, literals=literals)
        if grounded.passed:
            return Explained(
                explanation=candidate,
                source="LLM",
                grounding_attempts=attempt,
                grounding=grounded,
                usage=tuple(spent),
            )
        last = grounded
        corrections = grounded.failures

    reason = "GROUNDING_FAILED" if last is not None else "MALFORMED_EXPLANATION"
    return _fallback(fallback, published, literals, MAX_ATTEMPTS, reason, tuple(spent))


def _fallback(
    explanation: Explanation,
    published: EvidenceSet,
    literals: frozenset[str],
    attempts: int,
    reason: str,
    usage: tuple[Completion, ...],
) -> Explained:
    """The template, checked by the same gate the model had to pass."""
    grounded = check_grounding(explanation, published, literals=literals)
    if not grounded.passed:
        raise TemplateGroundingError(
            "the deterministic template is not grounded against its own evidence:\n  "
            + "\n  ".join(grounded.failures)
        )
    return Explained(
        explanation=explanation,
        source="TEMPLATE_FALLBACK",
        grounding_attempts=attempts,
        grounding=grounded,
        reason=reason,
        usage=usage,
    )


# --------------------------------------------------------------------------
# what the model is given
# --------------------------------------------------------------------------


def system_prompt() -> str:
    """The rules, stated as rules rather than as preferences.

    Every one of them is also a check in ``grounding.py``. A prompt that asked
    for something nothing verified would be a request; a prompt that asks for
    exactly what is checked is a specification, and the failure of the model to
    meet it is caught rather than published.
    """
    return "\n".join(
        [
            "You write the explanation for a payments finance investigation. Every number has "
            "already been computed and verified. You are phrasing them and nothing else.",
            "",
            "Rules, each of which is mechanically checked before your answer is shown:",
            "  - Use only the figures in the evidence brief. Never compute, convert, "
            "round, restate at a different precision, or infer a number.",
            "  - Write each figure exactly as the brief writes it, character for character.",
            "  - Every number in your narrative needs a claim naming the metric, the value, "
            "the unit and the evidence id it came from.",
            "  - claims[].text must be an exact substring of your narrative, long enough to "
            "contain the figure it is about and nothing else numeric.",
            "  - claims[].value must be exactly the value column of the brief: an integer for "
            "paise and count metrics, a quoted string for ratio and pp metrics.",
            "  - The analysis dates and the merchant id may appear without a claim. No other "
            "digit may.",
            "",
            "A percentage point is not a percent. Never write a pp figure with a % sign.",
            "",
            "Lead with what changed and why, then the supporting detail. Several short "
            "paragraphs, no headings, no bullet lists, no markdown.",
        ]
    )


def brief(published: EvidenceSet) -> str:
    """The evidence, as the model sees it: id, metric, value, and what made it.

    The rendered string is in the brief rather than left to the model to
    format, which is what turns "write the number exactly" from a hope into an
    instruction that can be followed. A model asked to render 40626000 paise
    itself would have to choose a grouping convention, and the byte-match would
    then be a test of that choice.
    """
    lines = [
        "evidence_id | metric | unit | value as written | window | support",
    ]
    lines.extend(_row(row) for row in sorted(published, key=lambda row: row.id))
    return "\n".join(lines)


def _row(row: Evidence) -> str:
    metric_id = (
        row.metric_id if row.dimension_value is None else f"{row.metric_id}[{row.dimension_value}]"
    )
    support = (
        f"= {row.formula.expression}"
        if row.formula is not None
        else f"{row.aggregation.operation} over {row.aggregation.over}"
        if row.aggregation is not None
        else ""
    )
    return " | ".join(
        [
            row.id,
            metric_id,
            row.unit,
            canonical(row.value, row.unit),
            f"[{row.period_from}, {row.period_to})",
            support,
        ]
    )


def _prompt(
    question: str,
    evidence_brief: str,
    limitations: Sequence[str],
    corrections: Iterable[str],
) -> str:
    parts = [f"The question asked was: {question}", "", "Evidence brief:", evidence_brief]
    if limitations:
        parts += [
            "",
            "These analyses did not run. Say so plainly; do not estimate what they "
            "would have shown, and do not treat their metrics as zero:",
            *(f"  - {limitation}" for limitation in limitations),
        ]
    failures = list(corrections)
    if failures:
        parts += [
            "",
            "Your previous answer was rejected by the grounding check. Fix exactly these "
            "and change nothing else:",
            *(f"  - {failure}" for failure in failures),
        ]
    return "\n".join(parts)
