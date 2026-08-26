# 04 — Deterministic Tool Contract

Every financial number in RazorMind is produced by a tool implementing this contract. Nothing
else is allowed to compute one.

## The contract

Fixes [C-11](00-corrections.md#c-11-m--deterministictool-is-not-actually-abstract) — the original
had no `@abstractmethod`, so subclasses silently inherited no-op bodies.

```python
from abc import ABC, abstractmethod
from typing import ClassVar, Generic, TypeVar
from pydantic import BaseModel

TIn = TypeVar("TIn", bound=BaseModel)
TOut = TypeVar("TOut", bound=BaseModel)


class DeterministicTool(ABC, Generic[TIn, TOut]):
    """A pure, reproducible financial computation.

    Same inputs + same database snapshot => byte-identical outputs. No clock reads,
    no randomness, no network, no LLM.
    """

    name: ClassVar[str]
    version: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]
    required_role: ClassVar[str] = "ANALYST"

    @abstractmethod
    async def execute(self, inp: TIn, ctx: ToolContext) -> TOut:
        """Compute the result. Raises ToolError on unrecoverable failure."""

    @abstractmethod
    def verify(self, inp: TIn, out: TOut) -> VerificationResult:
        """Assert the tool's own invariants. Never returns silently on failure."""

    @abstractmethod
    def evidence(self, inp: TIn, out: TOut) -> list[Evidence]:
        """One Evidence per metric the tool publishes, each with a Formula."""

    def validate(self, raw: dict) -> TIn:
        """Parse and validate raw input. Override only for cross-field rules."""
        return self.input_model.model_validate(raw)
```

`ClassVar` matters: the original `name: str` was an instance-field annotation that bound nothing,
so `registry[tool.name]` would have raised `AttributeError` at import time.

`ToolContext` carries `merchant_id`, `period`, a database session scoped by RLS, and the
`reconciliation_run_id`. It carries **no** LLM client — enforced by the import lint in
[01-architecture.md](01-architecture.md#boundary-enforcement).

## Determinism requirements

A tool that violates any of these is a bug, not a design choice:

| Requirement | Why |
| --- | --- |
| No `datetime.now()` | The period comes from `ctx`. A clock read makes results irreproducible. |
| No randomness | Nothing to sample. |
| No network or LLM calls | The whole point of the plane. |
| No float in money paths | [C-01](00-corrections.md#c-01-b--money-representation-was-never-specified) |
| Deterministic ordering | Every query that feeds an aggregate has an explicit `ORDER BY` with a unique tiebreaker. |
| Version bump on formula change | `version` is part of the evidence record; changing a formula without bumping it silently rewrites history. |

`version` is semver-ish: `MAJOR.MINOR`. **Bump `MAJOR` when a formula changes**, `MINOR` for
added output fields. Evidence rows store the version that produced them, so an old execution's
provenance stays truthful after a tool changes.

## Registry

```python
class ToolRegistry:
    def register(self, tool: DeterministicTool) -> None: ...
    def resolve(self, name: str, version: str | None = None) -> DeterministicTool: ...
    def describe(self) -> list[ToolSpec]:
        """Machine-readable specs. Feeds plan validation and, in v2, the planner prompt."""
```

Registration happens once at import. `resolve` with no version returns the highest registered
version. The plan validator calls `describe()` — a plan naming a tool that is not registered is
rejected before execution, never at execution time
([05-agent-runtime.md](05-agent-runtime.md#validation)).

## Tool set

Vision §12's registry, with inputs and published metrics made explicit.

### `finance.reconciliation` v1.0

Wraps [03-reconciliation.md](03-reconciliation.md). Every other tool depends on it.

- **In:** `merchant_id`, `period`
- **Out:** `run_id`, counts, `clean_match_rate_ratio`, exception breakdown, exception list
- **Metrics:** `ledger_count`, `bank_count`, `matched_pairs_count`, `clean_match_rate_ratio`,
  `exception_count`, `unresolved_exception_value_paise`

### `finance.revenue_analysis` v1.0

- **In:** `merchant_id`, `period`, `comparison_period`, `run_id`
- **Out:** the revenue bridge for both periods plus the attribution table
- **Metrics:** `gross_payments_paise`, `refunds_paise`, `fees_paise`, `chargebacks_paise`,
  `net_revenue_paise`, `net_revenue_change_ratio`, `attribution[]`

The bridge identity it must satisfy is in [06-trust-layer.md](06-trust-layer.md#bridge-identity).

### `payments.failure_analysis` v1.0

- **In:** `merchant_id`, `period`, `comparison_period`, optional `method`
- **Out:** attempted/succeeded/failed value and count, success rate, per-method breakdown
- **Metrics:** `attempted_value_paise`, `success_rate_ratio`, `success_rate_pp_change`,
  `failed_value_paise`, `by_method[]`

Publishes both the blended rate and the per-method rate. Keeping these as separate metric ids is
the fix for [C-03](00-corrections.md#c-03-m--the-upi-figure-was-disconnected-from-the-headline) —
the explainer can no longer conflate a UPI rate with a portfolio rate.

### `finance.refund_analysis` v1.0

- **Metrics:** `refund_value_paise`, `refund_rate_ratio`, `refund_value_change_paise`,
  `by_reason[]`

### `risk.chargeback_analysis` v1.0

- **Metrics:** `chargeback_value_paise`, `chargeback_count`, `chargeback_rate_ratio`,
  `chargeback_value_change_paise`

## Adding a tool

The registry is the extension point (vision §45 Phase D). A new tool is:

1. `input_model` / `output_model` Pydantic schemas with unit-suffixed field names
2. `execute` reading only through `ctx`
3. `verify` with at least one non-trivial invariant
4. `evidence` with a `Formula` per published metric
5. Metric ids added to the vocabulary in [06-trust-layer.md](06-trust-layer.md#metric-vocabulary)
6. Registration + a golden test against the seeded dataset

No change to the planner, executor, verifier, or UI is required. If a new tool forces a change to
any of those, the contract has been violated somewhere.
