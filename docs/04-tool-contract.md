# 04 — Deterministic Tool Contract

Every financial number in RazorMind is produced by a tool implementing this contract. Nothing
else is allowed to compute one.

## The contract

Fixes [C-11](00-corrections.md#c-11-m--deterministictool-is-not-actually-abstract) — the original
had no `@abstractmethod`, so subclasses silently inherited no-op bodies.

```python
class DeterministicTool[TIn: BaseModel, TOut: BaseModel](ABC):
    """A pure, reproducible financial computation.

    Same inputs + same database snapshot => byte-identical outputs. No clock reads,
    no randomness, no network, no LLM.
    """

    name: ClassVar[str]
    version: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]
    required_role: ClassVar[str] = "ANALYST"
    metrics: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    async def execute(self, inp: TIn, ctx: ToolContext) -> TOut:
        """Compute the result. Raises ToolError on unrecoverable failure."""

    @abstractmethod
    def verify(self, inp: TIn, out: TOut) -> VerificationResult:
        """Assert the tool's own invariants. Never returns silently on failure."""

    @abstractmethod
    def evidence(self, inp: TIn, out: TOut, ctx: ToolContext) -> list[Evidence]:
        """One Evidence per metric the tool publishes, each with its support."""

    def validate(self, raw: Mapping[str, Any]) -> TIn:
        """Parse and validate raw input. Override only for cross-field rules."""
        return self.input_model.model_validate(dict(raw))

    async def run(self, raw: Mapping[str, Any], ctx: ToolContext) -> ToolRun[TIn, TOut]:
        """validate -> scope -> execute -> verify -> evidence, in that order."""
```

`ClassVar` matters: the original `name: str` was an instance-field annotation that bound nothing,
so `registry[tool.name]` would have raised `AttributeError` at import time.

**`run()` owns the order.** Verification happens before evidence is built and before any output
leaves the tool, and a failing `VerificationResult` raises rather than returning. Putting the
sequence on the base class is what stops each caller re-implementing it and one of them getting
it wrong — the Phase 2 reconciliation script was exactly that caller.

**`evidence()` takes `ctx`**, which the original signature did not. `Evidence` must carry
`execution_id` by [C-15b](00-corrections.md#c-15-m--other-fixes-applied-without-further-discussion),
and a tool handed only `(inp, out)` has no way to fill it — the contract made its own required
field unfillable ([D-28](decisions.md#d-28--the-trust-plane-is-a-strict-order-and-evidence-receives-the-context)).

**`metrics`** is the tool's published metric ids. `describe()` surfaces them so the plan validator
can reject a plan asking for a metric no registered tool produces, before execution.

`ToolContext` carries `merchant_id`, `period`, `execution_id`, a database connection scoped by
RLS, and the `reconciliation_run_id`. It carries **no** LLM client — enforced by the import lint
in [01-architecture.md](01-architecture.md#boundary-enforcement).

The input names the merchant and period too, and that duplication is load-bearing: the input says
what to compute, the context says what the caller is *allowed* to compute, and `run()` refuses
when they disagree with `MERCHANT_SCOPE_VIOLATION` or `PERIOD_SCOPE_VIOLATION`. A plan naming
someone else's merchant fails before it reaches a query rather than depending on row-level
security to catch it.

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
    def register(self, tool: AnyTool) -> None: ...
    def resolve(self, name: str, version: str | None = None) -> AnyTool: ...
    def describe(self) -> list[ToolSpec]:
        """Machine-readable specs. Feeds plan validation and, in v2, the planner prompt."""
```

Registration happens once at import, in `tools/catalog.py`. `resolve` with no version returns the
highest registered version — compared as `(major, minor)` integers, not as a string, because
`"10.0" < "9.0"` lexicographically and the day that matters is the day a tool reaches its tenth
revision and silently resolves to an older formula.

`describe()` returns a sorted list. A dict-iteration order leaking into a planner prompt would
make the planner output depend on import order. The plan validator calls `describe()` — a plan naming a tool that is not registered is
rejected before execution, never at execution time
([05-agent-runtime.md](05-agent-runtime.md#validation)).

## Tool set

Vision §12's registry, with inputs and published metrics made explicit.

### `finance.reconciliation` v1.0

Wraps [03-reconciliation.md](03-reconciliation.md). Every other tool depends on it.

- **In:** `merchant_id`, `period`
- **Out:** `run_id`, counts, `clean_match_rate_ratio`, exception breakdown, exception list, and
  the source record ids behind every count
- **Metrics:** `ledger_count`, `bank_count`, `matched_pairs_count`, `matched_clean_count`,
  `clean_match_rate_ratio`, `exception_count`, `unresolved_exception_value_paise`

This is the one tool that **writes**, which is a bounded exception to "a tool is a pure
computation": a run is immutable once written, and its id is derived from the execution rather
than drawn at random, so replaying an execution returns the run it already produced instead of
appending an identical one ([D-30](decisions.md#d-30--a-reconciliation-run-id-is-derived-from-the-execution-and-a-replay-is-idempotent)).

The output carries its own source ids because `evidence(inp, out, ctx)` is handed nothing else.
A tool whose output cannot support its own evidence has to re-query to explain itself, and a
second query is a second chance to disagree with the first.

### `finance.revenue_analysis` v1.0

- **In:** `merchant_id`, `period`, `comparison_period`, `run_id`
- **Out:** the revenue bridge for both periods, the attribution table, the mandatory
  `rounding_residual_paise`, the confidence band, and stated `limitations`
- **Metrics:** `attempted_value_paise`, `gross_payments_paise`, `refunds_paise`, `fees_paise`,
  `chargebacks_paise`, `net_revenue_paise`, `net_revenue_change_paise`,
  `net_revenue_change_ratio`, the five `attribution.*_effect_paise` terms,
  `rounding_residual_paise`, `confidence_band_ratio`

The bridge identity it must satisfy is in [06-trust-layer.md](06-trust-layer.md#bridge-identity).

`run_id` is not context. Ledger rows the run flagged `POSSIBLE_DUPLICATE` are excluded from gross
— the fixture has 342 ledger records and 341 payments, and only the run knows which one is the
duplicate ([D-32](decisions.md#d-32--reconciliation-is-an-input-to-revenue-not-a-report-published-beside-it)).
The comparison period is deliberately not reconciled, and the tool says so in `limitations`
rather than implying a symmetry it does not have.

The comparison period must not overlap the analysis period — payments in the overlap would be
counted on both sides of the bridge — and the input model refuses one that does.

### `payments.failure_analysis` v1.0

- **In:** `merchant_id`, `period`, `comparison_period`, `run_id`, optional `method`
- **Out:** attempted/succeeded/failed value and count, blended success rate, the decline taxonomy,
  and the per-rail breakdown for **both** periods
- **Metrics:** `attempt_count`, `succeeded_count`, `attempted_value_paise`,
  `succeeded_value_paise`, `failed_value_paise`, `success_rate_ratio`, `success_rate_pp_change`,
  `technical_decline_ratio`, `business_decline_ratio`, and the six `by_method.*` metrics

Publishes both the blended rate and the per-rail rate. Keeping these as separate metric ids is
the fix for [C-03](00-corrections.md#c-03-m--the-upi-figure-was-disconnected-from-the-headline) —
the explainer can no longer conflate a UPI rate with a portfolio rate, because they do not share
a name.

The blended rate is the ratio of the **summed counts**, not an average of the rail rates. Those
are different numbers whenever the rails carry different volumes, which is exactly the situation
the original figures could not reconcile. `verify()` asserts the counts sum, as an identity.

Both periods' rail breakdowns are in the output because a `_pp_change` must cite the two rates it
came from. Recovering the earlier rate by inverting the published change would make layer 4
re-derive the answer from the answer.

`technical_decline_ratio` and `business_decline_ratio` are published together because the
*asymmetry* is the evidence. Technical declines tripling while business declines stay flat is what
attributes a movement to the rails rather than to customers; either rate alone says nothing.

`method` narrows every figure to one rail. A narrowed window is **not** comparable with the
revenue bridge, and the tool says so in `limitations` rather than publishing a partial figure
under a portfolio name.

### `finance.refund_analysis` v1.0

- **In:** `merchant_id`, `period`, `comparison_period`, `run_id`
- **Metrics:** `refund_value_paise`, `refund_count`, `refund_rate_ratio`,
  `refund_value_change_paise`, `gross_payments_paise`, and the two `by_reason.*` metrics

### `risk.chargeback_analysis` v1.0

- **In:** `merchant_id`, `period`, `comparison_period`, `run_id`
- **Metrics:** `chargeback_value_paise`, `chargeback_count`, `chargeback_rate_ratio`,
  `chargeback_value_change_paise`, `gross_payments_paise`, and the two `by_reason.*` metrics

Both rates are **value** rates: reversed value over gross payments. The card networks' chargeback
threshold is a *count* ratio over transactions, which is a different quantity with a different
denominator; it is not published under the same name, because a rate that is sometimes one and
sometimes the other is the ambiguity C-04 exists to remove. `chargeback_count` is published beside
it so a count-based ratio can be built without guessing.

Both tools publish `gross_payments_paise` — the denominator they actually used — so the rate's
operand is a real metric rather than a number taken on trust, and so three tools' idea of gross
can be compared.

The arithmetic for both lives in one module (`tools/reversals.py`). Two implementations of "sum
the refunds against captures in this window" would eventually disagree in some edge each handled
differently, which is precisely the defect cross-tool consistency exists to catch and a poor
thing to hand it.

### Why all four take a `run_id`

The spec originally asked for it only on `finance.revenue_analysis`. That makes its own
consistency requirement unsatisfiable: the fixture has 342 ledger records and 341 payments, and
only the reconciliation run identifies the duplicate. Without it,
`failure_analysis.succeeded_value_paise` includes a payment that
`revenue_analysis.gross_payments_paise` excludes, and the two can never be equal
([D-35](decisions.md#d-35--the-three-analysis-tools-take-a-run_id-which-the-spec-did-not-ask-for)).

## Adding a tool

The registry is the extension point (vision §45 Phase D). A new tool is:

1. `input_model` / `output_model` Pydantic schemas with unit-suffixed field names
2. `execute` reading only through `ctx`
3. `verify` with at least one non-trivial invariant
4. `evidence` with a `Formula` or an `Aggregation` per published metric
   ([D-29](decisions.md#d-29--evidence-carries-a-formula-or-an-aggregation-never-both-never-neither))
5. Metric ids added to the vocabulary in [06-trust-layer.md](06-trust-layer.md#metric-vocabulary)
6. Registration + a golden test against the seeded dataset

No change to the planner, executor, verifier, or UI is required. If a new tool forces a change to
any of those, the contract has been violated somewhere.
