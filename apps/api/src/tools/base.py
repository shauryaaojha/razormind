"""The deterministic tool contract (docs/04-tool-contract.md#the-contract).

Every financial number in RazorMind is produced by a tool implementing this
contract. Nothing else is allowed to compute one.

Fixes C-11: the original ``DeterministicTool`` declared no ``@abstractmethod``,
so a subclass that forgot ``verify`` inherited a no-op body and published
unverified numbers. Here it fails to instantiate.

``ClassVar`` on ``name``/``version`` matters just as much: the original wrote
``name: str``, an instance-field annotation binding nothing, so
``registry[tool.name]`` would have raised ``AttributeError`` at import time.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from evidence.models import Evidence
from verification.models import VerificationResult

__all__ = [
    "DeterministicTool",
    "Period",
    "ToolContext",
    "ToolError",
    "ToolInput",
    "ToolRun",
    "ToolSpec",
]


class ToolError(Exception):
    """An unrecoverable failure inside a tool.

    Carries a stable ``code`` because callers -- the executor, the API, the
    eval suite -- must switch on something that survives a reworded message.
    """

    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self.detail = detail or {}
        super().__init__(f"{code}: {message}")


class Period(BaseModel):
    """A half-open interval ``[from, to)`` of IST calendar dates (D-03)."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    from_: date = Field(alias="from")
    to: date

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.from_ >= self.to:
            raise ValueError(f"period start {self.from_} must precede period end {self.to}")
        return self

    def __str__(self) -> str:
        return f"[{self.from_}, {self.to})"


class ToolInput(BaseModel):
    """What every tool is asked for: a merchant and a window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    merchant_id: str = Field(min_length=1, max_length=32)
    period: Period


@dataclass(frozen=True)
class ToolContext:
    """What a tool is *allowed* to touch.

    The input says what to compute; the context says what the caller may
    compute. They overlap on ``merchant_id`` and ``period`` deliberately, and
    :meth:`DeterministicTool.run` refuses when they disagree -- a plan that
    names a merchant the caller is not scoped to must fail before it reaches
    a query, not depend on row-level security to save it.

    It carries **no LLM client**, and cannot: ``tools`` importing ``llm`` is a
    build failure (contract 1 in ``.importlinter``).
    """

    merchant_id: str
    period: Period
    execution_id: str
    conn: AsyncConnection
    reconciliation_run_id: str | None = None


class ToolSpec(BaseModel):
    """A tool, described well enough to validate a plan against it.

    The plan validator rejects a plan naming an unregistered tool *before*
    execution, which it can only do from a machine-readable description
    (docs/05-agent-runtime.md#validation).
    """

    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    required_role: str
    metrics: list[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolRun[TIn: BaseModel, TOut: BaseModel]:
    """One completed call: input, output, verification, evidence."""

    input: TIn
    output: TOut
    verification: VerificationResult
    evidence: tuple[Evidence, ...]


class DeterministicTool[TIn: BaseModel, TOut: BaseModel](ABC):
    """A pure, reproducible financial computation.

    Same inputs + same database snapshot => byte-identical outputs. No clock
    reads, no randomness, no network, no LLM. The period comes from the
    validated input; a tool that reads a clock is a bug, not a design choice
    (docs/04-tool-contract.md#determinism-requirements).
    """

    name: ClassVar[str]
    version: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]
    required_role: ClassVar[str] = "ANALYST"

    #: The metric ids this tool publishes. Phase 4 checks these against the
    #: registered vocabulary; the plan validator reads them from ``describe()``.
    metrics: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    async def execute(self, inp: TIn, ctx: ToolContext) -> TOut:
        """Compute the result. Raises ToolError on unrecoverable failure."""

    @abstractmethod
    def verify(self, inp: TIn, out: TOut) -> VerificationResult:
        """Assert the tool's own invariants. Never returns silently on failure."""

    @abstractmethod
    def evidence(self, inp: TIn, out: TOut, ctx: ToolContext) -> list[Evidence]:
        """One Evidence per metric the tool publishes, each with its support.

        Takes ``ctx`` where docs/04-tool-contract.md originally took only
        ``(inp, out)``. Evidence carries ``execution_id`` by C-15b, and a tool
        that is handed no execution cannot fill it -- the original signature
        made its own required field unfillable (D-28).
        """

    def validate(self, raw: Mapping[str, Any]) -> TIn:
        """Parse and validate raw input. Override only for cross-field rules."""
        return cast(TIn, self.input_model.model_validate(dict(raw)))

    async def run(self, raw: Mapping[str, Any], ctx: ToolContext) -> ToolRun[TIn, TOut]:
        """validate -> scope -> execute -> verify -> evidence, in that order.

        The order is the contract. Verification happens before evidence is
        built and before any output leaves the tool, so an output that fails
        its own invariants never exists in a form anything downstream can read.
        """
        inp = self.validate(raw)
        self._enforce_scope(inp, ctx)
        out = await self.execute(inp, ctx)
        verification = self.verify(inp, out)
        verification.raise_if_failed(f"{self.name} v{self.version}")
        return ToolRun(
            input=inp,
            output=out,
            verification=verification,
            evidence=tuple(self.evidence(inp, out, ctx)),
        )

    def _enforce_scope(self, inp: TIn, ctx: ToolContext) -> None:
        """The input may not reach outside what the context authorises."""
        merchant_id = getattr(inp, "merchant_id", ctx.merchant_id)
        if merchant_id != ctx.merchant_id:
            raise ToolError(
                "MERCHANT_SCOPE_VIOLATION",
                f"input names merchant {merchant_id!r}, "
                f"but this execution is scoped to {ctx.merchant_id!r}",
                {"requested": merchant_id, "authorised": ctx.merchant_id},
            )
        period = getattr(inp, "period", ctx.period)
        if period != ctx.period:
            raise ToolError(
                "PERIOD_SCOPE_VIOLATION",
                f"input names period {period}, but this execution analyses {ctx.period}",
                {"requested": str(period), "authorised": str(ctx.period)},
            )

    @classmethod
    def spec(cls) -> ToolSpec:
        return ToolSpec(
            name=cls.name,
            version=cls.version,
            required_role=cls.required_role,
            metrics=list(cls.metrics),
            input_schema=cls.input_model.model_json_schema(),
            output_schema=cls.output_model.model_json_schema(),
        )
