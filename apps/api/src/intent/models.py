"""What the model is allowed to decide.

An intent is a routing decision and two date ranges. It is the entire surface
through which a language model influences an execution, and it contains no
number that anybody reads: every figure is computed underneath it by a
deterministic tool and verified before it reaches prose.

Fixes [C-13](../../../../docs/00-corrections.md): the original execution record
had no ``merchant_id``, so every query was either cross-tenant or depended on
the model inventing a tenant id. Here the merchant is *echoed* from the session,
and the validator refuses a plan whose intent names a different one -- the model
can say the wrong thing, and it will be caught, which is a different property
from trusting it not to.
"""

from datetime import date
from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "INTENT_TYPES",
    "Clarification",
    "Intent",
    "IntentPeriod",
    "IntentType",
]

type IntentType = Literal[
    "revenue_diagnosis",
    "reconciliation_status",
    "failure_analysis",
    "refund_analysis",
    "chargeback_analysis",
]

#: In the order the planner considers them. Listed explicitly as well as in the
#: type because the parser puts them in the prompt, and a prompt built from a
#: hand-written list is a prompt that drifts from the type.
INTENT_TYPES: tuple[IntentType, ...] = (
    "revenue_diagnosis",
    "reconciliation_status",
    "failure_analysis",
    "refund_analysis",
    "chargeback_analysis",
)


class IntentPeriod(BaseModel):
    """A half-open window, as the model states it.

    Separate from ``tools.base.Period`` on purpose. This one is *untrusted*: it
    carries whatever the model said, including a start after its end, and it is
    the validator's job to reject that with a code rather than the parser's job
    to raise deep inside a JSON decode.
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    from_: date = Field(alias="from")
    to: date

    def __str__(self) -> str:
        return f"[{self.from_}, {self.to})"


class Intent(BaseModel):
    """The parsed question.

    ``confidence_ratio`` is not a metric in the vocabulary and never will be: it
    is a property of the parse, not of the merchant's money, and nothing may
    ever claim it in prose. It carries the unit suffix anyway, because a number
    in `[0, 1]` that is not called a ratio is the habit C-04 is about.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    intent: IntentType
    merchant_id: str = Field(min_length=1, max_length=32)
    period: IntentPeriod | None = None
    comparison_period: IntentPeriod | None = None

    confidence_ratio: Decimal = Field(ge=0, le=1)
    clarification_needed: bool = False
    #: The one question to ask, when the parser cannot proceed. Exactly one:
    #: a list of questions is a form, and a user who is asked three things at
    #: once answers the easy one.
    clarification: str | None = None

    @model_validator(mode="after")
    def _a_clarification_has_a_question(self) -> Self:
        if self.clarification_needed and not self.clarification:
            raise ValueError("clarification_needed is set but no question was given")
        return self

    def requires_comparison(self) -> bool:
        """Whether this intent is meaningless without something to compare against."""
        return self.intent != "reconciliation_status"


class Clarification(BaseModel):
    """A terminal, resumable answer: the system asked instead of guessing."""

    model_config = ConfigDict(frozen=True)

    question: str
    reason: Literal["LOW_CONFIDENCE", "MISSING_PERIOD", "MISSING_COMPARISON_PERIOD"]
    confidence_ratio: Decimal
    #: What the parser did understand, so a resumed execution does not start over.
    partial: Intent | None = None
