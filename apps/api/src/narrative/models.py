"""What an answer is: prose, plus a claim for every number inside it.

docs/06-trust-layer.md#grounding. One shape serves both producers, and that is
the point of putting it here rather than in ``llm``:

* the model returns an :class:`Explanation` through a forced tool call;
* the template builds an :class:`Explanation` from evidence rows with no model
  involved at all.

Both then go through the same five grounding checks. A fallback judged by a
weaker gate than the thing it replaces is not a fallback -- it is a way around
the gate -- and giving the two paths one type is what makes running the checks
over both of them the obvious thing to do rather than a discipline.

A :class:`Claim` is a *pointer*, not a computation. It says: this span of prose
states this metric, at this value, in this unit, and here is the evidence row
that already proved it. Nothing in it is believed; every field is checked
against something that was verified before any prose existed.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_serializer

from evidence.vocabulary import Unit

__all__ = ["Claim", "Explanation"]


class Claim(BaseModel):
    """One number in the prose, and the verified row it stands for.

    ``text`` is the span of the narrative that makes the claim -- a sentence or
    a line, not the bare number. It has to be a span rather than an offset pair
    because the model writes it, and an offset a model computed is one more
    thing to distrust; a substring can simply be looked for.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    metric_id: str
    #: Money and counts are integers; ratios and percentage points are Decimals
    #: and travel as strings, so a scale is never lost to a binary float (D-02).
    value: int | Decimal
    unit: Unit
    evidence_id: str

    @field_serializer("value")
    def _serialize_value(self, value: int | Decimal) -> int | str:
        return value if isinstance(value, int) else str(value)


class Explanation(BaseModel):
    """The answer. Prose, its claims, and what it could not cover.

    ``limitations`` is not decoration and not an apology: a tool that did not
    run means the metrics it publishes are *unavailable*, which is a different
    fact from zero and has to be said out loud (Invariant 6). It carries no
    numbers, so it is not subject to grounding -- and, deliberately, the
    template writes the same field the same way.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    narrative: str
    claims: list[Claim] = []
    limitations: list[str] = []
