# 06 — Trust Layer

Verification, evidence, provenance and grounding. This is the layer that distinguishes RazorMind
from a dashboard with an LLM bolted on.

## Metric vocabulary

Fixes [C-04](00-corrections.md#c-04-m--claims-carry-no-units). Every metric id ends in a unit
suffix, and every claim carries the unit alongside the value. Mixing "percent of a count",
"percent of a value" and "percentage points" was the root cause of the demo's broken narrative.

| Suffix | Type | Range | Rendered as |
| --- | --- | --- | --- |
| `_paise` | `int` | `>= 0` unless the metric is declared **signed** | `₹3,90,122.95` |
| `_ratio` | `Decimal(scale=6)` | `[0, 1]` unless declared **signed** | `95.61%` |
| `_pp` | `Decimal(scale=2)` | signed | `-6.49 pp` |
| `_count` | `int` | `>= 0` | `342` |

`signed` is a field on the metric, not a convention. "Money is non-negative" is false for an
attribution effect and "a ratio is in [0, 1]" is false for `net_revenue_change_ratio`, so one
blanket rule would have to be weakened until it checked nothing. Declared per metric, a negative
`gross_payments_paise` is a caught defect and a negative attribution effect is not
([D-38](decisions.md#d-38--the-vocabulary-declares-which-metrics-may-be-negative)).

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
payments.failure_analysis   attempt_count, succeeded_count,
                            attempted_value_paise, succeeded_value_paise,
                            failed_value_paise, success_rate_ratio,
                            success_rate_pp_change,
                            technical_decline_ratio, business_decline_ratio,
                            by_method.attempt_count,
                            by_method.succeeded_count,
                            by_method.attempted_value_paise,
                            by_method.succeeded_value_paise,
                            by_method.success_rate_ratio,
                            by_method.success_rate_pp_change
finance.refund_analysis     refund_value_paise, refund_count, refund_rate_ratio,
                            refund_value_change_paise, gross_payments_paise,
                            by_reason.refund_value_paise, by_reason.refund_count
risk.chargeback_analysis    chargeback_value_paise, chargeback_count,
                            chargeback_rate_ratio, chargeback_value_change_paise,
                            gross_payments_paise,
                            by_reason.chargeback_value_paise,
                            by_reason.chargeback_count
```

The list lives in `evidence/vocabulary.py`, and it is **enforced twice**
([D-33](decisions.md#d-33--the-metric-vocabulary-is-enforced-at-import-and-the-unit-comes-from-the-id)):

- `DeterministicTool.__init_subclass__` refuses a tool declaring an unregistered id, so the
  failure happens at class creation — import — and cannot ship.
- `Evidence` refuses a row whose id is unregistered or whose unit disagrees with the suffix.

The unit is never passed alongside a metric; it is **read from the id**. A tool cannot disagree
with itself about what it is publishing, because it only says it once. That closes C-04 properly:
a ratio published under a `_pp` field renders as a plausible number meaning something else, and
every check downstream would pass.

An id not on this list cannot be published, cited, or claimed. Adding one is a code change plus a
docs change, deliberately.

### Dimensions, and when not to use one

`by_method.success_rate_ratio` is **one** metric measured over a `method` dimension, with the four
rails as its permitted values. Each evidence row names its slice, and the evidence id carries it:
`.../by_method.success_rate_ratio/2026-08-01_2026-08-24~UPI`. Enumerating a metric per rail would
put twenty-four entries here for six quantities, and would assert that a UPI success rate and a
card success rate are different *metrics* when they are the same computation over different
records.

`attribution[]` is the opposite case and is deliberately **not** dimensioned. Its five terms have
genuinely different formulas — the volume effect applies a proportion, the refund effect is a
negated delta — so they are five metrics, not five slices of one. A dimension slices one
computation ([D-34](decisions.md#d-34--a-metric-measured-over-a-dimension-is-one-metric-with-a-slice-not-one-per-value)).

An array of unnamed terms cannot be cited either way: "the attribution says −₹77,452" has no id to
resolve, and grounding check 2 has nothing to look up.

`matched_clean_count`, `attempt_count` and `succeeded_count` are registered because they are the
*operands* of published ratios, and an operand that is not itself a metric is where a provenance
chain stops.

`attempted_value_paise` is published by **two** tools and `gross_payments_paise` by **three**.
That is the point: the same quantity computed from the same reconciled set, so the consistency
layer has something to compare. Two tools disagreeing about it is a defect nothing else catches.

## Verification

Runs after execution, before any prose exists. Five layers, in order — the first failure blocks.

```text
1. TYPE        every output matches its model; no float anywhere; the value matches the unit
2. RANGE       every value inside the range its metric declares; ratios quantized to scale 6
3. CONSISTENCY metrics two tools share agree exactly, including declared equivalences
4. FORMULA     every derived metric re-evaluated from its own expression; operands resolve
5. SOURCE      every cited record exists, is inside the period, and a SUM re-folds
```

**The order is the contract, and so is stopping.** A layer runs only if every layer before it
passed. That is not an optimisation: a formula re-evaluated against operands that failed their
range check produces a number nobody should read, and reporting it beside a range failure invites
someone to pick whichever they prefer. One failing layer, named, is the whole answer.

Layer 4 is what makes evidence meaningful: the verifier does not trust the tool's output, it
re-evaluates the declared formula — through `evidence/formula.py`, a grammar with no calls, so it
cannot re-run the tool — against the declared inputs and compares. A tool that reports a number its
own formula does not produce fails here. It also checks that each operand *resolves* to a row in
this execution and that the declared input equals that row's value, because a citation nothing
compares is decoration.

**Where a leaf is checked.** `gross_payments_paise` has no expression to re-evaluate. Layer 4 takes
the one identity available without the database — a `COUNT` is the size of the set it cites — and
layer 5 does the rest: the records exist, they sit inside the window, and summing the declared
column over them lands on the published figure. That re-fold is the leaf's answer to layer 4, and
it cannot happen before the records are resolved
([D-41](decisions.md#d-41--a-leafs-re-fold-is-layer-5s-work-not-layer-4s)).

### Which date is "inside the period"

Layer 5 reads as one check and is four. Four scoping rules are in play, all deliberate:

```text
ATTEMPT_DATE          a payment belongs to the window it was attempted in --
                      a failure has no capture instant
CAPTURE_DATE          the reconciliation ledger is captures; a settlement is
                      due against a capture
PARENT_ATTEMPT_DATE   a refund or chargeback belongs to the window of the
                      payment it reverses, not the one it was raised in (D-31)
VALUE_DATE            a settlement line lands in the bank window, which is the
                      capture window shifted by the cycle (D-18)
```

`Aggregation.scoped_by` names the rule, so layer 5 checks the scoping the tool *declared* rather
than one the verifier assumed. A tool that declares `ATTEMPT_DATE` and scopes by capture date is
caught, which nothing else in the system would notice
([D-37](decisions.md#d-37--evidence-declares-the-date-rule-that-scoped-it)).

It is also why `bank_count` is filed under the **bank** window rather than the analysis window: it
measures the settlement window, the period is part of a row's identity, and the alternative was to
relax layer 5 until it stopped catching real period errors
([D-39](decisions.md#d-39--bank_count-is-filed-under-the-bank-window-not-the-analysis-window)).

### What a failure produces

```text
VERIFYING  -> BLOCKED      a layer failed; error_json names it; no prose, ever
           -> EXPLAINING   every layer passed; the numbers may now be phrased
```

A blocked execution is a **row**, not an absence: "we could not verify this, and layer FORMULA is
why" is an answer, while a missing record is indistinguishable from a request that never arrived.
It stores no evidence at all, because a stored row is something the API serves and the drawer
walks — and serving the support for a number that failed verification is exactly how an unverified
figure reaches a reader with a citation attached
([D-43](decisions.md#d-43--a-blocked-execution-is-a-row-and-it-stores-no-evidence)).

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

Two tools computing the same quantity from the same reconciled set and disagreeing is a defect,
and the consistency layer is the only place that catches it. There are two shapes:

**Same id, two tools.** `attempted_value_paise` and `gross_payments_paise` are published under
their own names by more than one tool. Nothing extra is needed to compare them.

**Different names, one quantity.** The revenue bridge calls a number `gross_payments_paise`; the
failure analysis calls the same number `succeeded_value_paise`. Nothing would ever compare those,
so `EQUIVALENCES` in `evidence/vocabulary.py` declares them equal:

```text
gross_payments_paise  ==  succeeded_value_paise
refunds_paise         ==  refund_value_paise
chargebacks_paise     ==  chargeback_value_paise
```

All three hold exactly on the golden window, which is only possible because every tool scopes its
records through the same function and every one of them takes the reconciliation `run_id`
([D-35](decisions.md#d-35--the-three-analysis-tools-take-a-run_id-which-the-spec-did-not-ask-for)).

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
    scoped_by: Anchor               # the same claim, machine-readable (D-37)

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
    dimension_value: str | None     # "UPI" on a by_method.* row

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

**A derived metric cites operands; a leaf cites records; never both.** A `Formula` row that
also names source records has two accounts of where its number came from, and nothing keeps them in
step: the cited set can drift from the sets its operands cite while every check still passes. It is
not extra provenance either — the walk reaches those same records one level lower, with the fold
that produced them attached
([D-40](decisions.md#d-40--a-derived-metric-cites-operands-a-leaf-cites-records-never-both)).

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

`provenance/builder.py` does the walk. A cycle is **refused**, never truncated: evidence describes
a computation, and a computation whose operands depend on their own result did not happen, so a
depth limit would quietly render half of it as though it had. `source_records()` collapses the
whole chain to the deduplicated record ids at the bottom, which is the answer to "show me the
transactions behind this percentage" — 775 of them under `net_revenue_change_ratio` on the golden
window.

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
    text: str          # the span of the answer that makes the claim
    metric_id: str
    value: int | Decimal
    unit: Unit
    evidence_id: str
```

`text` is a *span*, not an offset pair. The model writes it, and an offset a model computed is one
more field to distrust; a substring either is in the answer or is not, and looking for it costs
nothing.

The same type carries the template's answer. That is deliberate: a fallback judged by a weaker
gate than the thing it replaces is not a fallback but a way around the gate, so `Claim` and
`Explanation` live in `narrative/`, below both producers
([D-50](decisions.md#d-50--the-template-renderer-sits-below-the-model-boundary-not-beside-it)).

Checks, all must pass — and unlike the verification layers, **all of them run**. Verification
stops at the first failure because a later layer reading an earlier layer's numbers produces a
figure nobody should see; grounding has no such coupling, and its whole output is the list of
corrections handed back on the second attempt. Naming one problem at a time would make the retry a
guessing game.

1. Every numeric token in the prose maps to a `Claim`.
2. Every claim's `metric_id` is in the registered vocabulary.
3. Every claim's `value` **byte-matches** the verified metric — no rounding, restating, or
   re-expressing — **and the prose says that value**.
4. Every claim's `unit` matches the metric's declared unit.
5. Every `evidence_id` resolves to an `Evidence` row for this execution.

Check 3 is two checks wearing one name, and the second half is the one that earns the phase. A
model can declare the exact figure in the structured field and write a rounded one in the sentence
a human reads — which is precisely the defect
[D-11](decisions.md#d-11--grounding-byte-matches-and-falls-back-to-a-template) is about. So every
numeric token inside the claim's own span is matched against the accepted renderings of the
verified value.

### What counts as the same number

`narrative/render.py` holds the one list, used in both directions: the template writes the
canonical form, and the gate accepts the spellings that lose no digit.

| Unit | Canonical | Also accepted | Refused |
| --- | --- | --- | --- |
| `paise` | `₹4,06,260.00` | `₹4,06,260` (the paise are zero), the form without `₹` | `₹406260.00`, `₹4,06,260.5` |
| `ratio` | `95.8012%` | `0.958012` | `95.80%`, `95.8%` |
| `pp` | `-1.34` | `1.34` | `-1.34%` — a point is not a percent (C-04) |
| `count` | `13,420` | `13420` | anything with a decimal point |

Stripping a trailing zero is not rounding: `0.958000` and `0.958` are the same number written two
ways, and `0.958012` and `0.958` are not. That is why `95.80%` is accepted for `0.958000` and
refused for `0.958012`.

The unsigned magnitude is accepted for a signed value, because English carries the sign in the
verb. That is a bounded relaxation and it is stated rather than blurred: grounding is a check on
the numbers, not on the sentence, and no byte-match can catch "revenue rose by -17.6%" anyway
([D-48](decisions.md#d-48--grounding-checks-magnitude-and-unit-the-direction-word-goes-unchecked)).

### What is deliberately not claimed

The analysis windows and the merchant id are masked out before tokenising. `2026-08-01` is not a
claim about money, and a gate that failed on it would be a gate nobody could satisfy. The
exemption is derived from the evidence rows themselves rather than passed in wholesale, so it
cannot be widened from outside to whatever the last failing answer happened to contain. Everything
else with a digit in it must be claimed — including, by design, a number the model was right about
but did not cite.

Failure path
([C-15h](00-corrections.md#c-15-m--other-fixes-applied-without-further-discussion)):

```text
grounding fails
   -> increment grounding_attempts, regenerate with the failed claims named
   -> fails again (grounding_attempts == 2)
   -> TEMPLATE_FALLBACK
```

The template renders the verified metrics directly with no generated prose: every row, grouped by
tool and window, each line carrying the evidence id it can be walked down from. `response_source`
is persisted so the UI can label it and the eval suite can measure how often it happens, and
`answer_text` is persisted beside it — the two are tied together by a database constraint, so text
with no declared origin and an origin with no text are both unrepresentable
([D-49](decisions.md#d-49--the-answer-gets-a-column-and-prose-is-tied-to-its-origin)).

A provider failure skips the retry entirely and goes straight to the template. A missing model does
not become present on a second call, and the numbers are already verified.

The template is subject to the same five checks. If it ever failed them the run fails rather than
returning, because there is no floor below a deterministic render of verified rows and unchecked
prose is not one.

**The user always receives the verified numbers.** The LLM's only privilege is phrasing them.
