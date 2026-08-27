# 06 — Trust Layer

Verification, evidence, provenance and grounding. This is the layer that distinguishes RazorMind
from a dashboard with an LLM bolted on.

## Metric vocabulary

Fixes [C-04](00-corrections.md#c-04-m--claims-carry-no-units). Every metric id ends in a unit
suffix, and every claim carries the unit alongside the value. Mixing "percent of a count",
"percent of a value" and "percentage points" was the root cause of the demo's broken narrative.

| Suffix | Type | Range | Rendered as |
| --- | --- | --- | --- |
| `_paise` | `int` | any | `₹3,90,122.95` |
| `_ratio` | `Decimal(scale=6)` | `[0, 1]` for rates; signed for changes | `95.61%` |
| `_pp` | `Decimal(scale=2)` | signed | `−6.49 pp` |
| `_count` | `int` | `>= 0` | `342` |

Registered metrics (v1):

```text
finance.reconciliation      ledger_count, bank_count, matched_pairs_count,
                            matched_clean_count, clean_match_rate_ratio,
                            exception_count, unresolved_exception_value_paise
finance.revenue_analysis    attempted_value_paise, gross_payments_paise,
                            refunds_paise, fees_paise, chargebacks_paise,
                            net_revenue_paise, net_revenue_change_paise,
                            net_revenue_change_ratio, rounding_residual_paise,
                            confidence_band_ratio,
                            attribution.attempt_volume_effect_paise,
                            attribution.success_rate_effect_paise,
                            attribution.refunds_effect_paise,
                            attribution.fees_effect_paise,
                            attribution.chargebacks_effect_paise
payments.failure_analysis   attempted_value_paise, succeeded_value_paise,
                            failed_value_paise, success_rate_ratio,
                            success_rate_pp_change, by_method[]
finance.refund_analysis     refund_value_paise, refund_rate_ratio,
                            refund_value_change_paise
risk.chargeback_analysis    chargeback_value_paise, chargeback_count,
                            chargeback_rate_ratio, chargeback_value_change_paise
```

An id not on this list cannot be published, cited, or claimed. Adding one is a code change plus a
docs change, deliberately.

`attribution[]` is written out as five metric ids rather than left as an array. An array of
unnamed terms cannot be cited: "the attribution says −₹77,452" has no id to resolve, and grounding
check 2 has nothing to look up. `matched_clean_count` is listed because it is the numerator of
`clean_match_rate_ratio`, and an operand that is not itself a metric is where a provenance chain
stops.

`attempted_value_paise` is published by **two** tools, and that is the point: it is the same
quantity computed from the same reconciled set, so the consistency layer has something to compare.
Two tools that disagree about it is a defect nothing else would catch.

## Verification

Runs after execution, before any prose exists. Five layers, in order — the first failure blocks.

```text
1. TYPE        every output field matches output_model; no float in a _paise field
2. RANGE       refunds/fees/chargebacks >= 0; ratios in [0,1]; counts >= 0
3. CONSISTENCY cross-tool: metrics common to two tools agree exactly
4. FORMULA     each published metric recomputed from its Formula and inputs; must match exactly
5. SOURCE      every source_record_id in the evidence exists and is inside the period
```

Layer 4 is what makes evidence meaningful: the verifier does not trust the tool's output, it
re-evaluates the declared formula against the declared inputs and compares. A tool that reports a
number its own formula does not produce fails here.

### Bridge identity

The revenue bridge must close exactly. This is the direct fix for
[C-02](00-corrections.md#c-02-b--the-flagship-demos-revenue-bridge-does-not-close).

```text
net_revenue_paise
  == gross_payments_paise - refunds_paise - fees_paise - chargebacks_paise

delta_net_paise
  == net_current_paise - net_prior_paise

delta_net_paise
  == volume_effect_paise
   + success_rate_effect_paise
   + refund_effect_paise
   + fee_effect_paise
   + chargeback_effect_paise
   + rounding_residual_paise
```

Where the gross decomposition uses the standard rate/volume split:

```text
success_rate_effect_paise = attempted_current * (rate_current - rate_prior)
volume_effect_paise       = rate_prior * (attempted_current - attempted_prior)
```

Rules the verifier enforces:

- Effects are computed in exact `Decimal`/`Fraction` arithmetic, then rounded half-up to paise.
- `rounding_residual_paise` is a **mandatory field**, computed as the plug, and asserted
  `abs(residual) <= number_of_effect_terms`. A larger residual means a formula error, not
  rounding.
- Changes in refunds/fees/chargebacks enter as **deltas**, never gross values — this was error
  #2 in C-02.
- Unresolved reconciliation exceptions are **not** a bridge term. They are reported as a
  confidence band: `unresolved_exception_value_paise / net_revenue_paise`, rendered as
  "±0.45% unverified". This was error #3 in C-02.

### Cross-tool consistency

`finance.revenue_analysis.gross_payments_paise` must equal
`payments.failure_analysis.succeeded_value_paise` for the same period, exactly. Two tools
computing the same quantity from the same reconciled set that disagree is a defect, and the
consistency layer is the only place that catches it.

## Evidence

Fixes [C-15b/C-15c](00-corrections.md#c-15-m--other-fixes-applied-without-further-discussion) —
the original had no execution or tool linkage and an unparseable `calculation: str`.

```python
class Formula(BaseModel):
    expression: str                 # "gross - refunds - fees - chargebacks"
    operands: dict[str, str]        # operand name -> evidence id, cross-tool metric, or literal
    unit: Literal["paise", "ratio", "pp", "count"]

class Aggregation(BaseModel):
    operation: Literal["SUM", "COUNT"]
    field_name: str                 # "amount_paise"
    over: str                       # "transactions"
    predicate: str                  # the record set, in words
    unit: Literal["paise", "ratio", "pp", "count"]

class Evidence(BaseModel):
    id: str
    execution_id: str
    tool_name: str
    tool_version: str

    metric_id: str
    unit: str
    value: int | Decimal
    period_from: str
    period_to: str

    formula: Formula | None         # exactly one of these two
    aggregation: Aggregation | None
    inputs: dict[str, int | Decimal]

    source_record_ids: list[str]
    rules_applied: list[str]
    verification_checks: list[str]
```

`Formula.expression` is a restricted arithmetic grammar — `+ - * /`, parentheses, named operands,
integer literals — evaluated by a small interpreter in `evidence/formula.py`. Not `eval`. There
are no calls, no attribute access, no subscripts, no `**`, no floats, and no globals of any kind;
`__import__` is not special-cased, because it is a call and calls do not exist here. It is
deliberately too weak to express anything but arithmetic, which is what makes layer 4 of
verification a real check instead of a re-run of the tool. The interpreter returns an **exact,
unrounded** `Decimal`; rounding to paise or to a scale-6 ratio is a separate single step in
`runtime.money`, so "the tool and its formula disagree" and "two roundings disagree" stay
distinguishable failures.

**A metric has a formula or an aggregation, never both**
([D-29](decisions.md#d-29--evidence-carries-a-formula-or-an-aggregation-never-both-never-neither)).
A derived metric declares arithmetic and layer 4 re-evaluates it. A leaf — `gross_payments_paise`
is the sum of 341 amounts — has no arithmetic to re-evaluate and declares the fold instead;
verification re-sums the ids it cites, which is an independent computation rather than a formula
that reproduces the value by construction.

Operand names in the expression are short and unit-free (`gross`, `prior`), and `operands` maps
each to the evidence id that supports it. That keeps the C-01 guard — which forbids `/` applied
to a `_paise` name — meaningful rather than something a string literal can trip, and it is what
lets the provenance drawer be a generic recursive renderer: every operand either resolves to more
evidence or terminates.

`period_from` and `period_to` are part of the identity, not decoration. A revenue analysis
publishes `net_revenue_paise` for two windows, and two rows carrying the same `metric_id` with no
way to tell them apart is how a prior-period number ends up cited as a current-period one.

## Provenance

Every authoritative number resolves to source records.

```text
Claim  "Revenue declined 17.60%"
  -> Metric        net_revenue_change_ratio
  -> Verified      -0.175956
  -> Formula       (current - prior) / prior
  -> Operands      current=39012295, prior=47342482
  -> Each operand  -> its own Evidence -> its own Formula
  -> Leaves        transaction ids, settlement ids, refund ids, chargeback ids
  -> Match         reconciliation_matches row (rule, confidence, reason)
  -> Source        transactions / settlements rows
```

The drawer walks this graph. Because every level is an `Evidence` row with a `Formula`, the UI is
a generic recursive renderer — it has no knowledge of revenue, refunds, or reconciliation.

Worked example for the unresolved figure
([C-08](00-corrections.md#c-08-m--18400-is-defined-two-incompatible-ways)):

```text
unresolved_exception_value_paise = 184000         (Rs 1,840)
  |
  +-- TXN_183  Rs 8,400  NO_COUNTERPART
  |     candidate SETTLEMENT_91  rule=AMOUNT_DATE_CANDIDATE  confidence=0.72
  |     rejected: below 0.85 auto-match threshold, reference absent
  +-- TXN_247  Rs 6,200  NO_COUNTERPART
  +-- TXN_402  Rs 3,800  NO_COUNTERPART
```

Showing the *rejected* candidate is the point. "We found something close and deliberately did not
match it, here is why" is a far stronger trust signal than an empty result.

## Grounding

The explainer receives verified metrics, evidence and provenance — nothing else. Its output is
then parsed back and checked.

```python
class Claim(BaseModel):
    text: str
    metric_id: str
    value: int | Decimal
    unit: str
    evidence_id: str
```

Checks, all must pass:

1. Every numeric token in the prose maps to a `Claim`.
2. Every claim's `metric_id` is in the registered vocabulary.
3. Every claim's `value` **byte-matches** the verified metric — no rounding, restating, or
   re-expressing.
4. Every claim's `unit` matches the metric's declared unit.
5. Every `evidence_id` resolves to an `Evidence` row for this execution.

Failure path
([C-15h](00-corrections.md#c-15-m--other-fixes-applied-without-further-discussion)):

```text
grounding fails
   -> increment grounding_attempts, regenerate with the failed claims named
   -> fails again (grounding_attempts == 2)
   -> TEMPLATE_FALLBACK
```

The template renders the verified metrics directly with no generated prose. `response_source` is
persisted so the UI can label it and the eval suite can measure how often it happens.

**The user always receives the verified numbers.** The LLM's only privilege is phrasing them.
