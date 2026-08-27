# Decisions

Architectural decisions with their reasoning and their reversal cost. A decision not written here
was not made deliberately.

---

### D-01 — Money is integer paise everywhere

**Decision.** All monetary values are `int` paise. No float, ever, in any money path.

**Why.** The platform's entire claim is deterministic arithmetic. IEEE-754 breaks associativity,
so `sum(...)` over floats depends on row order, which would make the reconciliation totals
irreproducible — the exact property [D-04](#d-04--matching-is-greedy-one-to-one-with-a-total-tie-break)
works hard to guarantee.

**Alternatives.** `Decimal` throughout — correct, but slower, serializes ambiguously over JSON,
and still permits a stray `float()`. Integer paise makes the illegal state unrepresentable.

**Cost to reverse.** High. It is in every schema, model and API payload. Decided in Phase 0 for
that reason.

---

### D-02 — Ratios serialize as JSON strings

**Decision.** `_ratio` and `_pp` fields are strings on the wire (`"0.956140"`), parsed with a
decimal library in the client.

**Why.** A JSON number round-trips through a float64 in nearly every client. Grounding
byte-matches claim values against verified metrics ([C-04](00-corrections.md#c-04-m--claims-carry-no-units));
a round-trip that changes the last digit would fail valid answers.

**Cost to reverse.** Low, but it would require relaxing the byte-match check, which is the whole
grounding mechanism.

---

### D-03 — Half-open periods `[from, to)` in IST

**Decision.** `2026-08-01 -> 2026-08-24` means Aug 1 through Aug 23.

**Why.** Adjacent periods tile exactly — no overlap, no gap. Closed intervals make
period-over-period comparison off-by-one-prone in precisely the place where a subtle error is
invisible and expensive.

**Trade-off.** It reads oddly to a finance user, so the UI always renders "Aug 1 – Aug 23". The
API is never the presentation layer.

---

### D-04 — Matching is greedy, one-to-one, with a total tie-break

**Decision.** Rules apply in strict priority order; a consumed record is never revisited; ties
break on a five-key total order.

**Why.** [C-07](00-corrections.md#c-07-b--matching-has-no-assignment-rule-so-it-is-not-reproducible).
Without it, two correct implementations produce different match rates.

**Alternatives.** Optimal assignment (Hungarian algorithm) maximizes matches, but the result is
harder to explain to a finance user — "why did this pair, and not that one?" has no local answer.
Greedy-by-rule gives every match a one-line reason, which is what the provenance drawer needs.

**Cost to reverse.** Medium. The invariants and unique constraints stay valid; only the matcher
changes.

---

### D-05 — Auto-match threshold is 0.85

**Decision.** Rules 1–4 auto-match. Rule 5 (confidence 0.72) records a *candidate* on the
exception instead.

**Why.** A false match is worse than an unmatched record. An unmatched record is visible, has a
value, and lands on someone's queue. A false match silently corrupts a revenue figure and its
provenance chain.

**Trade-off.** The headline match rate is lower. That is the correct trade and is worth saying out
loud in the demo.

---

### D-06 — Reconciliation runs are immutable

**Decision.** Re-running a period creates a new `reconciliation_runs` row.

**Why.** "What did we see on the 24th?" must be answerable. Executions reference a `run_id`, so an
old execution's provenance stays truthful after data is corrected.

**Cost.** Storage, which is negligible at this scale.

---

### D-07 — Unresolved exceptions are a confidence band, not a bridge term

**Decision.** `unresolved_exception_value_paise` is reported beside the bridge as `±0.45%`, never
inside it.

**Why.** They are different kinds of fact. A refund increase *caused* revenue to move. An
unmatched settlement means we are *unsure* of a figure. Adding them together — which the original
spec did — produces a number that means nothing.
See [C-02](00-corrections.md#c-02-b--the-flagship-demos-revenue-bridge-does-not-close).

---

### D-08 — Planning is deterministic in v0–v1

**Decision.** Intent type maps to a fixed DAG. The LLM proposes plans only in v2.

**Why.** Ship the trust boundary first. The validator already gates every plan identically, so
swapping in an LLM planner later requires no change to validation, execution or verification.

**Cost to reverse.** Low by construction — that is the point of validating plans rather than
trusting their source.

---

### D-09 — `merchant_id` comes from the session, never the model

**Decision.** The intent parser receives the merchant id as context and may not emit a different
one; a mismatch is `MERCHANT_SCOPE_VIOLATION`.

**Why.** [C-13](00-corrections.md#c-13-b--agentexecution-and-the-api-cannot-scope-to-a-merchant).
An LLM-supplied tenant identifier is a cross-tenant data leak with extra steps.

**Belt and braces.** Postgres RLS on the caller's JWT means an application-layer scoping bug still
cannot return another tenant's rows.

---

### D-10 — Verification re-evaluates formulas rather than trusting tool output

**Decision.** Layer 4 of verification independently evaluates each metric's declared `Formula`
against its declared inputs and compares.

**Why.** Otherwise "verification" only checks types and ranges, and evidence is decorative. This
is what makes a `Formula` a contract rather than a comment.

**Cost.** A restricted arithmetic interpreter (~150 lines). Deliberately too weak to express
anything but arithmetic — no `eval`, no attribute access, no calls.

---

### D-11 — Grounding byte-matches, and falls back to a template

**Decision.** A claim's value must match the verified metric exactly. Two failures → deterministic
template.

**Why.** Rounding "−18.00%" to "−18.2%" is exactly the class of error in the original spec.
Tolerant matching would have accepted it.

**Trade-off.** Occasionally rejects prose a human would accept. The regenerate-once step absorbs
most of that, and the fallback guarantees the user still gets the numbers.

---

### D-12 — Single uvicorn worker; Redis deferred

**Decision.** v0–v1 run one API worker. SSE subscribers and execution tasks share process memory.

**Why.** Vision §29 defers Redis. Honouring that requires making the constraint explicit rather
than discovering it in production.

**Trigger to revisit.** The first of: needing a second worker, or executions needing to survive a
restart. `execution_events` is already the durable log, so the change is Redis pub/sub for fan-out
and nothing else.

---

### D-13 — Reconciliation is a `required` node; everything else degrades

**Decision.** `finance.reconciliation` failing fails the run. Any other tool failing yields
`PARTIAL`.

**Why.** Every other tool reads the reconciled set. Producing revenue figures without it would
mean numbers of unknown provenance — which is the one thing the platform exists to prevent.

---

### D-14 — Metric ids carry mandatory unit suffixes

**Decision.** `_paise`, `_ratio`, `_pp`, `_count`. Unregistered metric ids cannot be published.

**Why.** [C-03](00-corrections.md#c-03-m--the-upi-figure-was-disconnected-from-the-headline) and
[C-04](00-corrections.md#c-04-m--claims-carry-no-units): the original spec conflated a UPI success
rate with a portfolio rate, and a percentage with a percentage point. Distinct ids with declared
units make that a type error instead of a narrative error.

---

### D-15 — The seed fixture is checksummed and verified before anything else

**Decision.** Phase 1 ships `verify-seed` and it is a CI gate.

**Why.** Every later test asserts against the fixture. A drifted fixture makes every downstream
test wrong *and green*, which is the worst available outcome.

---

### D-16 — Every dependency is installed inside a container

**Decision.** Nothing is installed on the host: no virtualenv, no global `pip`, no global `npm`.
`scripts/task.py` detects whether it is inside a container and, if not, re-invokes itself inside
the `tools` service. `make check`, `python scripts/task.py check` and
`docker compose run --rm tools scripts/task.py check` are therefore the same command.

**Why.** The fixture's reproducibility claim ([D-15](#d-15--the-seed-fixture-is-checksummed-and-verified-before-anything-else))
is only as strong as the interpreter that produces it. A pinned minor version in `pyproject.toml`
means nothing if a developer's host Python is a different build; pinning the *image* makes the
toolchain itself part of the artifact. CI runs the same image, so "works on my machine" and
"passes CI" stop being separate claims.

**Alternatives.** A host virtualenv with a pinned Python — lighter, but relies on every machine
having that exact interpreter, which this one did not.

**Cost to reverse.** Low. The task runner would drop its delegation branch; nothing else changes.

---

### D-17 — Python is pinned to 3.13, not 3.12

**Decision.** `requires-python = ">=3.13,<3.14"`, and the API image is `python:3.13-slim`.

**Why.** [12-tech-stack.md](12-tech-stack.md) originally specified 3.12 with the reasoning "not
3.13+ until the ecosystem pins settle." That reasoning has expired — 3.13 is well past settling,
and every dependency in `pyproject.toml` publishes cp313 wheels. The load-bearing half of the
original decision was *pinning to a minor at all*, because `random.Random` stream semantics are
only stable within a minor release and the seed checksums depend on them. That is preserved
exactly; only the number moved.

**Cost to reverse.** Low before Phase 1, high after: changing the minor version changes the RNG
stream, which changes `data/seed/golden/checksums.json`, which is a fixture change.

---

### D-18 — A reconciliation run scopes its two sides on different dates

**Decision.** A run over `[from, to)` scopes the **ledger** side by IST capture date and the
**bank** side by `bank_period(from, to)` — the same window shifted forward by the T+2 SLA and
widened at the far end by the three-business-day timing-lag ceiling. `runtime/calendar.py` owns
that computation.

**Why.** The two sides carry different dates for the same payment. Scoping both to the same
literal dates compares two different cohorts and manufactures exceptions out of the boundary:
captures near the start settled before the window opened, and captures near the end settle after
it closes. Neither is a real discrepancy, and both would show up in the match rate. The far end is
widened by exactly the lag ceiling because a settlement later than that is not a late pair
([03-reconciliation.md](03-reconciliation.md#timing-lag)) — it is no pair at all.

**Alternatives.** Scope the ledger side by `settlement_due_date` as well, which is symmetric but
splits the revenue population from the reconciliation population. Rejected while both tools read
the same window.

**Cost to reverse.** Low. One function, and the run's stored `period_from`/`period_to` are
unchanged either way.

---

### D-19 — The fixture leaves a two-day quiet band before each analysis window

**Decision.** `generate_seed_data.py` writes no captures in the two calendar days immediately
before an analysis window.

**Why.** A capture just before a window — particularly one after the 18:00 cutoff, which rolls
into the next business day — settles *inside* that window's settlement cycle. It would appear on
the bank side with no ledger counterpart in scope: a fabricated `NO_COUNTERPART` born of a
boundary rather than of anything wrong in the data, and it would move the golden match rate. The
quiet band makes the capture cohort and the settlement cohort exactly the same payments, which is
what lets the fixture assert 342 / 341 / 338 exactly.

**Alternatives.** Absorb the spill by scoping the ledger side on `settlement_due_date`
([D-18](#d-18--a-reconciliation-run-scopes-its-two-sides-on-different-dates) discusses this) —
correct for production, unnecessary machinery for a fixture.

**Cost to reverse.** Low, but it changes every checksum, so it is a fixture change.

---

### D-20 — The published exception count is ledger-side

**Decision.** `exception_count` counts **ledger-side** exceptions only: exactly the ledger records
that are not `MATCHED_CLEAN`. Bank rows with no counterpart are written as exceptions with
`side = BANK` and reported separately as `unmatched_bank`.

**Why.** The spec's golden block gives `exceptions 15` alongside `unmatched_bank 3`, and 15 is
reachable two independent ways — `7 + 3 + 2 + 2 + 1` and `ledger_count − matched_clean` — while 18
is reachable neither way. Beyond arithmetic: one missing settlement is *one* discrepancy, and
counting it once from each side would inflate every exception total by the size of the bank
overhang. Verification asserts both identities, so the two definitions cannot silently diverge.

**Cost to reverse.** Low, but it changes a headline number, so it is a documentation change too.

---

### D-21 — The trust plane sits below tools in the import contract

**Decision.** The `import-linter` layers are, top to bottom: `routes`; `orchestrator`/`intent`/
`validation`; `tools`; `verification`/`evidence`/`provenance`; `reconciliation`; `runtime`.

**Why.** A tool implements `verify()` and `evidence()` as part of its contract
([04-tool-contract.md](04-tool-contract.md)), so it must be able to import the vocabulary those
return. The trust plane reads tool *values* — passed in as arguments — never tool modules, which
is what keeps the dependency pointing one way. The earlier ordering put the trust plane above
tools and would have broken on Phase 3's first tool.

**Cost to reverse.** Low now, high later — the ordering is what stops a cycle forming.

---

### D-22 — An empty period is refused, not answered with a zero match rate

**Decision.** `reconcile()` raises `EmptyPeriodError` when there are no ledger records. A period
with ledger records but no bank records reconciles normally, to a rate of zero.

**Why.** "We matched none of them" and "there were none to match" are different facts that a
`0.000000` match rate renders identically. Invariant 6: incomplete data yields an explicit
limitation, never an invented, estimated, or zero value. The second case is not incomplete data —
a bank file that never arrived is a real and reportable answer.

**Cost to reverse.** Low. One guard, and a caller that has to say why.

---

### D-23 — The dataset is market-calibrated, not arbitrary

**Decision.** A three-layer pipeline: public NPCI/RBI statistics → `data/calibration/` →
`data/scenarios/` → generator → ledger, settlements, and `golden/ground_truth.json`. Every
calibration parameter carries a provenance tag — `CITED`, `DERIVED`, or `ASSUMED` — and
`data/calibration/sources.md` redeems each one.

**Why.** "We generated 400 random rows" is not defensible, and neither is a dataset calibrated
against numbers nobody can trace. The tags are what make the difference: a merchant's own payment
mix is not a published statistic and never will be, so it is labelled `ASSUMED` with a rationale
rather than dressed up as an observation. Overstating the claim would be worse than not making it.

**What is and is not claimed.** Transaction-level records are synthetic and seeded; no real
customer, merchant, or bank record is represented. Aggregate distributions and operational
characteristics are calibrated against public statistics. Failure rates are not Razorpay's.

**Cost to reverse.** High — the generator, the fee model and the ground truth all rest on it.

---

### D-24 — Fees are per instrument, and the flat 1% is gone

**Decision.** `runtime/fees.py` holds a fee schedule keyed by **instrument** (the funding source),
not by rail. Bank-account UPI and RuPay debit are zero-MDR by mandate; PPI-funded UPI carries an
interchange above ₹2,000; cards carry a negotiated rate; netbanking is billed flat per transaction.

**Why.** The flat 1% could not represent a mandated zero rate *at all*, which meant a
`FEE_DISCREPANCY` was arithmetic noise — the expected number had no commercial rule behind it for
the actual to violate. Under a schedule, a discrepancy means a *named* rule was misapplied, and
the engine now reports which one (`matches_rule_for`). "This zero-MDR UPI payment was billed under
the credit-card agreement" is actionable; "the fee was ₹200 out" is not.

The schedule lives in `runtime/`, not `data/calibration/`: the reconciliation engine needs it to
know what a settlement should have cost, and the application must never import the fixture. The
calibration layer annotates it with provenance rather than owning it.

**Cost to reverse.** High. It is in the schema, the engine, the fixture and the API.

---

### D-25 — Settlement timing is a scenario parameter, not a law

**Decision.** `settlement_due_date(captured_at, lag_business_days, cutoff)` takes the lag and the
cutoff as parameters with defaults. Scenarios may override them.

**Why.** There is no universal statutory T+2 for Indian payment-gateway settlement; it is a
commercial term varying by acquirer, merchant risk category and instrument. Hard-coding it as a
constant would be inventing a regulation, and would make the reconciliation engine untestable
against any merchant on different terms.

**Cost to reverse.** Low. The defaults preserve every existing caller.

---

### D-26 — Counts are designed; money is derived

**Decision.** The scenario fixes capture counts and the planted anomaly counts. Everything else —
failures, ticket values, fees, success rates, decline rates, and the revenue decline itself —
emerges from the calibration layer. `verify_seed.py` therefore asserts *identities and calibration
bands*, not hard-coded revenue figures.

**Why.** This is the line between choosing the shape of a story and choosing its answer. A check
that asserted `net_revenue == 40_97_868` would only be asserting that somebody wrote the same
number twice; a check that the bridge closes with a zero residual, that baseline technical
declines land inside the published 0.7–0.8% band, and that realised method shares match the
declared mix, is checking something.

It also caught a real defect in the original figures: ₹40L of monthly net revenue over 341
payments implies a **₹12,560 average ticket**, roughly ten times a realistic Indian P2M ticket.
With calibrated ticket sizes this merchant turns over about Rs 3,90,122 a
month, and the unresolved exception value scales with it.

**Cost to reverse.** Medium. The assertions would have to be rewritten around fixed numbers again.

---

### D-27 — The ground truth is checked against its own dataset

**Decision.** `ground_truth.json` carries an `expected_diagnosis`, and `verify-seed` asserts that
the declared primary driver really is the largest term in the generated attribution.

**Why.** A ground truth that disagrees with the data it ships is worse than none: every evaluation
scored against it would be scoring the wrong thing, confidently. The first version of this
scenario declared the technical-decline incident as the primary driver; the generated data said
attempt volume. The check is what surfaced that, and the declared answer moved to match the data.

**The trap this creates is deliberate.** The incident is the salient event in the window, and a
model reasoning from narrative rather than arithmetic will name it as the cause. It is real, it is
localised to three issuers, and it is *not* the primary driver. Separating a genuine operational
incident from the actual revenue driver is the finding.

**Cost to reverse.** Low.

---

### D-28 — The trust plane is a strict order, and `evidence()` receives the context

**Decision.** `verification` → `provenance` → `evidence` are ordered layers rather than
independent siblings, and the tool contract's `evidence()` takes `ctx` alongside `(inp, out)`.

**Why.** Two problems that only appeared once the modules had contents.

The layering was written when all three were empty. Layer 4 of verification re-evaluates a
declared `Formula`, and the provenance walker resolves an `Evidence` graph — so both must import
`evidence`, and import-linter siblings may not import each other. `evidence` is a vocabulary; the
two things that consume it belong above it.

The signature was self-contradictory. [C-15b](00-corrections.md#c-15-m--other-fixes-applied-without-further-discussion)
requires every `Evidence` row to carry `execution_id`, and the documented
`evidence(self, inp, out)` hands the tool nothing that knows the execution — the contract made
its own required field unfillable. Passing the context the tool already receives in `execute` is
the smallest honest fix. The alternative, a second `EvidenceDraft` type stamped later by a
builder, defers the linkage and adds a type for no gain.

**Cost to reverse.** Low for the signature. Medium for the layering, since it is mechanically
enforced and a later module that wants the old shape would have to move.

---

### D-29 — Evidence carries a formula *or* an aggregation, never both, never neither

**Decision.** `Evidence.formula` and `Evidence.aggregation` are mutually exclusive and one is
mandatory. A derived metric (`net = gross - refunds - fees - chargebacks`) declares a `Formula`
in the restricted grammar. A leaf metric (`gross` is the sum of 341 amounts) declares an
`Aggregation` — operation, field, record set, predicate — and cites the records.

**Why.** The docs said "one `Evidence` per metric, each with a `Formula`", and layer 4 recomputes
each metric from its formula. That works for arithmetic and breaks for aggregates: a sum over 341
records has no expression to re-evaluate. Two bad options were available, and both would have
made layer 4 weaker while appearing to satisfy it — write a 341-term expression, or give leaves a
decorative formula that reproduces the value by construction.

Splitting them keeps both checks real. Layer 4 re-evaluates arithmetic; a leaf is verified by
re-summing the ids it cites, which is a genuinely independent computation and which layer 5
already has to reach for.

**Cost to reverse.** Low. Nothing outside the evidence builders reads the distinction yet.

---

### D-30 — A reconciliation run id is derived from the execution, and a replay is idempotent

**Decision.** `run_id = "rec_" + sha256(execution_id | merchant | period)[:20]`. Re-running the
tool inside the same execution returns the existing run instead of writing a second, and refuses
with `RUN_SNAPSHOT_CHANGED` if a fresh reconciliation of the same period disagrees with what is
stored.

**Why.** A tool's contract is that the same inputs against the same snapshot produce
byte-identical output. `uuid4()` broke that for the one field a client is most likely to store,
and it made a retry create a second identical run under a new name.

The refusal matters as much as the reuse. A run is immutable so that "which numbers did we see on
the 24th?" stays answerable; if a replay recomputes different counts, the underlying records moved,
and silently rewriting the row would destroy the one property immutability exists for. This is
also the shape Phase 8's `client_request_id` idempotency needs.

**Cost to reverse.** Low.

---

### D-31 — A refund belongs to the period of the payment it reverses

**Decision.** Refunds and chargebacks are scoped to a window by their **parent transaction**,
never by their own `created_at`. Payments are scoped by IST **attempt** date.

**Why.** A revenue bridge nets one cohort's returns against that cohort's gross. A refund raised
on 26 August against an August payment is August's; counting it in September would deduct one
cohort's returns from another cohort's gross, and the bridge would still close — around the wrong
number.

It is not hypothetical: scoping this fixture's refunds by `created_at` moves one of eighteen into
the wrong window. The rule was checked against the generator before it was written, not after.

Payments scope on `attempted_at` for the reason recorded in Phase 1: a failure has no capture
instant, so scoping on capture drops every failure and every success rate reads 100%.

**Cost to reverse.** Medium — the choice is baked into what `gross_payments_paise` means, and any
stored evidence would describe the old rule.

---

### D-32 — Reconciliation is an input to revenue, not a report published beside it

**Decision.** `finance.revenue_analysis` takes a `run_id`, and the run changes the answer: ledger
rows the run flagged `POSSIBLE_DUPLICATE` are excluded from gross. The run's unresolved value is
carried too, and changes nothing — it is published as `confidence_band_ratio`.

**Why.** The fixture has 342 ledger records and 341 payments; the difference is a second ledger
row carrying an existing UTR and amount. It is a real record and it is not revenue. Only the
reconciliation run knows which one it is, so a revenue figure computed without the run is
overstated by exactly one payment, with nothing to indicate it.

Keeping the two kinds of contribution distinct is the point. One is an adjustment to the number;
the other is a bound on how much of the number the bank has confirmed. Netting the unresolved
value in was the third of [C-02](00-corrections.md#c-02-b--the-flagship-demos-revenue-bridge-does-not-close)'s
three errors, and it stays out (Invariant 7).

The comparison period is deliberately **not** reconciled, and the tool says so in `limitations`
rather than implying a symmetry it does not have.

**Cost to reverse.** Medium. Removing the dependency would silently change `gross_payments_paise`.
