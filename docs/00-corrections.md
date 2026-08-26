# 00 — Spec Corrections

Defects found in the original vision document (`file.md`) that would break a build, and the
correction adopted. Every corrected number in this repo is verified arithmetically; the checks
live in `tests/test_golden_story.py` (Phase 1).

Severity: **B** = blocking (build cannot proceed correctly), **M** = major, **m** = minor.

---

## C-01 (B) — Money representation was never specified

The spec promises reproducibility and deterministic arithmetic but never says how money is
stored. Any implementer defaults to `float`, and `0.1 + 0.2 != 0.3` destroys every invariant in
§19 of the vision doc.

**Correction.** All monetary values are **integer paise** (`int` in Python, `BIGINT` in
Postgres; JSON carries integers, never decimals). Field names carry the unit:
`gross_payments_paise`. Rates and ratios are `Decimal` with an explicit scale, never float.
Rounding is `ROUND_HALF_UP` at a single documented point per calculation. See
[02-data-model.md](02-data-model.md#money).

---

## C-02 (B) — The flagship demo's revenue bridge does not close

Vision §4/§28/§41 claim an 18.2% revenue decline, then attribute it to:

| Claimed cause | Amount |
| --- | ---: |
| Payment failures | ₹3,08,000 |
| Refunds | ₹1,24,000 |
| Chargebacks | ₹18,500 |
| Unresolved exceptions | ₹18,400 |
| **Sum** | **₹4,68,900** |

Net revenue is stated as ₹40,97,868. An 18.2% decline implies a prior-period net of
₹50,09,618.58 — **not a whole-rupee amount**, so the figure is unverifiable against any integer
dataset — and a decline of ₹9,11,750. The stated causes cover **51%** of it.

Three separate errors compound here:

1. The **attempt-volume effect was omitted entirely**. Gross successful volume falls both
   because the success *rate* dropped and because *fewer payments were attempted*. Only the
   first was counted.
2. **Refunds and chargebacks were counted at their gross value, not their change.** A ₹1,24,000
   refund total does not contribute ₹1,24,000 to a *decline*; only the ₹24,000 increase over the
   prior period does.
3. **Unresolved reconciliation exceptions were treated as a bridge term.** They are not a cause
   of revenue movement — they are a bound on how much of the figure is trustworthy.

**Correction.** A revenue bridge is a closed identity with a mandatory residual. See
[08-seed-data.md](08-seed-data.md) for the corrected golden story, restated here:

```text
Prior  (2026-07-01 -> 2026-07-23)     Current (2026-08-01 -> 2026-08-23)
  attempted      Rs 53,30,000           attempted      Rs 47,42,000
  gross success  Rs 51,60,000           gross success  Rs 42,83,200
  refunds        Rs  1,00,000           refunds        Rs  1,24,000
  fees @1.00%    Rs    51,600           fees @1.00%    Rs    42,832
  chargebacks    Rs    11,000           chargebacks    Rs    18,500
  ----------------------------          ----------------------------
  NET            Rs 49,97,400           NET            Rs 40,97,868
```

Decline ₹8,99,532 = **exactly −18.00%**. Attribution:

| Driver | Contribution | Share |
| --- | ---: | ---: |
| Attempt-volume decline (−11.03%) | −₹5,69,246 | 63.3% |
| Payment success-rate decline (−6.49 pp) | −₹3,07,554 | 34.2% |
| Refund increase | −₹24,000 | 2.7% |
| Chargeback increase | −₹7,500 | 0.8% |
| Fee decrease (offset) | +₹8,768 | −1.0% |
| Rounding residual | ₹0 | 0.0% |
| **Total** | **−₹8,99,532** | **100.0%** |

The ₹18,400 of unresolved exceptions is reported separately as a **confidence band**
(±0.45% of net revenue), never as a bridge line.

---

## C-03 (M) — The UPI figure was disconnected from the headline

Vision §16 shows UPI success at 96.8% → 82.9% (−13.9 pp) while §28 claims a "14.3% increase in
payment failures". Neither is derivable from the other, and 14.3% has no stated unit.

**Correction.** UPI is **46.66% of attempted value**, and non-UPI success is flat at 96.82%.
That yields a blended success rate of 96.81% → 90.32% (−6.49 pp), which is exactly the rate used
in the bridge above. The two levels now reconcile. `14.3%` is deleted.

---

## C-04 (M) — Claims carry no units

"14.3% increase", "−13.9 pp", "18.2%" and "₹3.08 lakh" are mixed freely. A percentage of a
count, a percentage of a value, and a percentage *point* are three different things.

**Correction.** Metric identifiers carry a mandatory unit suffix and every claim emits the unit
alongside the value: `_paise`, `_ratio` (0–1), `_pp` (percentage points), `_count`. Percent
formatting happens only in the presentation layer. See
[06-trust-layer.md](06-trust-layer.md#metric-vocabulary).

---

## C-05 (B) — `match_rate ∈ [0, 1]` contradicts the UI's `95.61%`

The verification rule in vision §19 would reject the dashboard value in vision §27.

**Correction.** The stored metric is `clean_match_rate_ratio ∈ [0, 1]`. The UI multiplies by 100.

---

## C-06 (B) — `matched + exceptions == total_records` is false for two-sided reconciliation

Reconciliation has a ledger side and a bank side. A record can be matched-but-flagged (timing
lag, amount mismatch), and orphan bank records belong to neither term. The stated invariant
cannot hold.

**Correction.** Each ledger record resolves to exactly one of three outcomes, and a separate
invariant covers the pair count. The vision doc's headline numbers (342 / 327 / 15 / 95.61%) all
survive under the corrected model:

```text
ledger_count             342
  MATCHED_CLEAN          327
  MATCHED_WITH_EXCEPTION  11   (timing lag 7, amount mismatch 2, fee discrepancy 2)
  UNMATCHED                4   (no counterpart 3, possible duplicate 1)

bank_count               341
matched_pairs            338
unmatched_bank             3

INVARIANT  2 x matched_pairs + unmatched_ledger + unmatched_bank == ledger_count + bank_count
           2 x 338          + 4                + 3               == 683 == 342 + 341   OK

clean_match_rate_ratio  = 327 / 342 = 0.95614      -> 95.61%   (headline preserved)
exception_count         = 11 + 4    = 15                        (headline preserved)
```

---

## C-07 (B) — Matching has no assignment rule, so it is not reproducible

Vision §13.1 lists five cascading rules but never states whether matching is one-to-one, how ties
break, or in what order candidates are consumed. Two correct implementations would produce
different match rates — fatal for a platform whose thesis is determinism.

**Correction.** Matching is **greedy in strict rule order, one-to-one, with a total tie-break
order**. Fully specified in [03-reconciliation.md](03-reconciliation.md#assignment).

---

## C-08 (M) — `₹18,400` is defined two incompatible ways

Vision §14 gives a single exception `TXN_183` with `amount: 18400`. Vision §21/§28/§41 describe
₹18,400 spread across *three* exceptions.

**Correction.** Three `NO_COUNTERPART` exceptions: `TXN_183` ₹8,400 + `TXN_247` ₹6,200 +
`TXN_402` ₹3,800 = ₹18,400. `SETTLEMENT_91` is a rejected *candidate* for `TXN_183`
(confidence 0.72, below the 0.85 auto-match threshold), which is what makes it useful demo
material rather than an inconsistency.

---

## C-09 (m) — Exception category names are inconsistent

`Duplicate` (§6.2), `POSSIBLE_DUPLICATE` (§14), `Possible Duplicate` (§27).

**Correction.** Canonical enum is `UPPER_SNAKE_CASE`; a single display-label map lives in the web
app. Never hand-write a label.

---

## C-10 (B) — No timezone or settlement cutoff

Timing-lag detection compares dates, but "date" is undefined without a timezone, and T+n
settlement is undefined without a cutoff.

**Correction.** All timestamps stored as `TIMESTAMPTZ` in **UTC**. The business calendar is
**Asia/Kolkata**. Settlement is **T+2** against an **18:00 IST** capture cutoff. `TIMING_LAG` is
`0 < lag_days <= 3`; beyond 3 days it escalates to `NO_COUNTERPART`.

---

## C-11 (m) — `DeterministicTool` is not actually abstract

`class DeterministicTool(ABC)` in vision §12 has no `@abstractmethod` decorators, so subclasses
silently inherit no-op bodies, and `name: str` / `version: str` are bare annotations that bind
nothing.

**Correction.** Corrected contract in [04-tool-contract.md](04-tool-contract.md).

---

## C-12 (M) — Execution state machine is incomplete

Vision §10 lists a validation layer as a first-class stage (§11) and a grounded-explanation stage
(§22–23), but neither has a state. `PARTIAL` and `BLOCKED` are named with no transitions.

**Correction.** Nine states with an explicit transition table in
[05-agent-runtime.md](05-agent-runtime.md#state-machine).

---

## C-13 (B) — `AgentExecution` and the API cannot scope to a merchant

`POST /api/v1/agent/run` accepts `{"message": "..."}` only, and `AgentExecution` has no
`merchant_id`. The intent schema *requires* `merchant_id`. As written, either the LLM invents a
merchant id or every query reads across all tenants.

**Correction.** `merchant_id` is supplied by the caller from the authenticated session and is
never inferred by the model. Added to `AgentExecution` along with `period`, `error`,
`updated_at`, and `seed`. See [05-agent-runtime.md](05-agent-runtime.md).

---

## C-14 (M) — A synchronous endpoint cannot drive the progressive UI

Vision §6.1 shows the agent's stages ticking off live, but the only endpoint is a blocking `POST`
that returns the finished answer.

**Correction.** `POST /agent/runs` returns `202` with an `execution_id`; the UI subscribes to
`GET /agent/runs/{id}/events` (SSE). Full surface in [07-api.md](07-api.md).

---

## C-15 (m) — Other fixes applied without further discussion

| # | Issue | Correction |
| --- | --- | --- |
| C-15a | `reconciliation_runs` table implied by vision §32's diagram but missing from the table list | added |
| C-15b | `Evidence` has no `execution_id`, `tool_name`, `tool_version`, or `metric_id`, so the §20 chain cannot be reconstructed | added |
| C-15c | `calculation: str` is an opaque string, making the §19 "formula check" unimplementable | replaced with a structured `Formula` object |
| C-15d | `random.seed(42)` mutates global state and is not reproducible across call order | `rng = random.Random(42)`, plus a SHA-256 golden-fixture assertion |
| C-15e | "300–500 transactions" contradicts a 342-record reconciliation window | dataset is ~1,600 attempts over 90 days; 342 ledger records in the current 23-day window |
| C-15f | §11 validates currency; §44 excludes multi-currency | single currency `INR`, enforced; non-INR rejected as `UNSUPPORTED_CURRENCY` |
| C-15g | `FEE_DISCREPANCY` is a category with no tolerance | fee is 1.00% of gross, half-up to paise; tolerance is `max(Rs 1.00, 0.5% of expected fee)` |
| C-15h | Grounding "regenerate once" has no persisted counter or terminal state | `grounding_attempts` on the execution; terminal marker `TEMPLATE_FALLBACK` |
| C-15i | `razorpay_side.csv` implies a live integration the project explicitly disclaims (§43) | renamed `ledger_side.csv` |
| C-15j | Redis excluded, but SSE + async execution across multiple workers requires shared state | v0–v1 pinned to a single uvicorn worker; documented trigger for adding Redis |
| C-15k | §11 has "permission validation" with no permission model | merchant-scoped roles defined in [02-data-model.md](02-data-model.md#authz) |
