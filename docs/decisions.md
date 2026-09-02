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

---

### D-33 — The metric vocabulary is enforced at import, and the unit comes from the id

**Decision.** `evidence/vocabulary.py` is the authority on which metric ids exist.
`DeterministicTool.__init_subclass__` refuses a tool declaring an unregistered id, so the failure
is at class creation — import — rather than at query time. `Evidence` refuses a row whose
`metric_id` is unregistered or whose `unit` disagrees with the suffix, and the evidence publisher
never takes a unit as an argument: it reads it from the id.

**Why.** [C-04](00-corrections.md#c-04-m--claims-carry-no-units) says every metric id ends in a
unit suffix. That was a naming convention, and a naming convention is worth nothing the first time
someone publishes a ratio under a `_pp` field — it renders as a plausible number that means
something else, and every check downstream passes.

Taking the unit *from* the id rather than alongside it removes the class of mistake entirely: a
tool cannot disagree with itself about what it is publishing, because it only says the thing once.

The import-time half matters for a different reason. A metric id with no vocabulary entry has no
declared unit, so grounding has nothing to byte-match a claim against; the claim would be
unverifiable rather than wrong, which is worse. Catching it at import means it cannot ship.

**Cost to reverse.** Low mechanically. The discipline is the point, and relaxing it would quietly
return the system to conventions.

---

### D-34 — A metric measured over a dimension is one metric with a slice, not one per value

**Decision.** `by_method.success_rate_ratio` is a single registered metric carrying
`dimension: "method"` and the four rails as its permitted values. Each evidence row names its
slice in `dimension_value`, and the evidence id carries it (`.../2026-08-01_2026-08-24~UPI`).

The five `attribution.*_effect_paise` terms stay as five separate ids, deliberately.

**Why.** Enumerating `by_method.upi.success_rate_ratio`, `by_method.card...` and so on would put
twenty-four entries in the vocabulary for six quantities, and adding a fifth rail — RuPay credit
on UPI is already a distinct instrument — would mean six more. Worse, it would assert that a UPI
success rate and a card success rate are *different metrics*, when they are the same computation
over different records.

The attribution terms are the opposite case and that is why they are not dimensioned: the volume
effect applies a proportion, the refund effect is a negated delta, and they have genuinely
different formulas. A dimension slices one computation; these are five computations. Writing them
as one metric would make a shared formula impossible to state honestly.

This is still the fix for [C-03](00-corrections.md#c-03-m--the-upi-figure-was-disconnected-from-the-headline):
`success_rate_ratio` and `by_method.success_rate_ratio` are different ids, so an explainer cannot
substitute a rail's rate for the portfolio's. They differ by name, not only by value.

**Cost to reverse.** Medium. Stored evidence would carry the old shape.

---

### D-35 — The three analysis tools take a `run_id`, which the spec did not ask for

**Decision.** `payments.failure_analysis`, `finance.refund_analysis` and
`risk.chargeback_analysis` all require the reconciliation `run_id`, exactly as
`finance.revenue_analysis` does. [04-tool-contract.md](04-tool-contract.md#tool-set) listed it
only for revenue.

**Why.** The spec's own cross-tool consistency check is unsatisfiable without it. The fixture has
342 ledger records and 341 payments; the difference is a duplicated capture that only the
reconciliation run identifies. Without the run's duplicate set,
`failure_analysis.succeeded_value_paise` includes that payment and
`revenue_analysis.gross_payments_paise` does not, so
[06-trust-layer.md](06-trust-layer.md#cross-tool-consistency)'s requirement that the two be equal
*exactly* could never hold — and the consistency layer would report a defect in the tools rather
than the missing input that caused it.

The same applies to the two reversal tools: a refund against a duplicated capture must not reduce
a gross that never included it.

**Cost to reverse.** Low, and reversing it would break the consistency check by construction.

---

### D-36 — Phase 4's quoted exit figures are superseded by the calibrated fixture

**Decision.** [10-build-phases.md](10-build-phases.md#phase-4--remaining-tools) asked for a
blended success rate of 96.81% → 90.32% and a UPI rate of 96.8% → 82.9%. Those numbers describe
the pre-calibration fixture. The exit criteria are restated as the *identities* they were
expressing, and the figures are taken from `ground_truth.json`: blended 95.80% → 94.46%
(−1.34 pp), UPI 96.44% → 94.62% (−1.82 pp).

**Why.** The market-calibration rework ([D-23](#d-23--the-dataset-is-market-calibrated-not-arbitrary),
[D-26](#d-26--counts-are-designed-money-is-derived)) made the story emerge from the data instead of
being written into it, which was the whole point of that work. Keeping a hard-coded figure as an
exit criterion would mean either asserting a number the generator no longer produces, or tuning
the generator until it produced a number somebody wrote down in advance — and the second is
exactly what D-26 exists to prevent.

The structural criteria survive intact and are stronger than the figures were: that the blended
rate is the summed counts rather than an average of rail rates, and that a rail's rate is a
different metric id from the portfolio's. Both are asserted as exact identities.

**What the calibrated story lost, and gained.** The original 13.9-point UPI collapse was
dramatic and implausible; a real issuer incident confined to three banks over eleven days moves a
portfolio UPI rate by under two points. The subtler number is the harder test — a model that
reasons from narrative will still reach for the incident, and the arithmetic still says attempt
volume.

**Cost to reverse.** Low, but it would mean reintroducing figures the data does not produce.

---

### D-37 — Evidence declares the date rule that scoped it

**Decision.** `Aggregation` carries `scoped_by`, one of `ATTEMPT_DATE`, `CAPTURE_DATE`,
`PARENT_ATTEMPT_DATE` or `VALUE_DATE`. Layer 5 resolves every cited record through that rule and
checks the resulting date against the row's own period.

**Why.** Layer 5 is written in the spec as "every `source_record_id` exists and is inside the
period", which sounds like one check and is four. Three different scoping rules are in play, all
three deliberate and all three already load-bearing:

- a payment belongs to the window it was **attempted** in, because a failure has no capture
  instant;
- the reconciliation ledger is captures, scoped by **capture** date, because a settlement is due
  against a capture;
- a refund or chargeback belongs to the window of the payment it **reverses**
  ([D-31](#d-31--a-refund-belongs-to-the-period-of-the-payment-it-reverses)), and this fixture has
  one raised the following month;
- a settlement line lands in the **bank** window, which is the capture window shifted by the
  settlement cycle ([D-18](#d-18--a-reconciliation-run-scopes-its-two-sides-on-different-dates)).

A verifier that assumed a single date for every record type would reject a correct row for three
of those four. The alternative — inferring the rule from the table name — puts the scoping
knowledge in the verifier, where it would silently drift from the tool that actually did the
scoping.

Declaring it makes layer 5 a check on the rule the tool *said* it used. A tool that declares
`ATTEMPT_DATE` and scopes by capture date is now caught, which is a defect nothing else in the
system would notice.

**Cost to reverse.** Medium. Stored evidence carries the field.

---

### D-38 — The vocabulary declares which metrics may be negative

**Decision.** `Metric` carries `signed: bool`. An unsigned metric published negative is refused by
`Evidence` at construction and again by layer 2; an unsigned `_ratio` must additionally lie in
`[0, 1]`.

**Why.** [06-trust-layer.md](06-trust-layer.md#verification) states layer 2 as "refunds/fees/
chargebacks >= 0; ratios in [0,1]; counts >= 0". Written as a blanket rule it is false twice over:
`net_revenue_change_paise` is *supposed* to be negative in the golden window, and
`net_revenue_change_ratio` is `-0.175956`. A single rule covering both cases has to be weakened
until it checks nothing, and a layer that checks nothing passes on any input including a broken
one.

Declaring it per metric is what makes the layer real. A negative `gross_payments_paise` is now a
caught defect and a negative attribution effect is not, which is the distinction that matters.

**Cost to reverse.** Low.

---

### D-39 — `bank_count` is filed under the bank window, not the analysis window

**Decision.** The `bank_count` evidence row carries `period_from`/`period_to` of the **settlement**
window. Every other reconciliation row keeps the analysis window.

**Why.** The two are different date ranges by design ([D-18](#d-18--a-reconciliation-run-scopes-its-two-sides-on-different-dates)):
an August capture window matches settlements dated into September. The row was filed under August
while citing 341 settlements with September value dates, and layer 5 refused it — correctly.

The period is part of an evidence row's *identity*, not a label on it. This row measures the bank
window, so that is the window it is identified by. Relaxing layer 5 to let this one row through
would have been the other option, and it would have removed the check that catches a genuine
period error everywhere else.

**Cost to reverse.** Low.

---

### D-40 — A derived metric cites operands; a leaf cites records; never both

**Decision.** `Evidence` refuses a row that carries a `Formula` and a non-empty
`source_record_ids`. `EvidencePublisher.derived()` no longer takes the argument. A row with an
`Aggregation` and a non-zero value must cite at least one record.

**Why.** `clean_match_rate_ratio` used to do both: it declared `clean / ledger` *and* listed the
327 clean transaction ids. Nothing keeps the two in step. The cited set can drift from the sets its
operands cite, and every check still passes, because no layer compares them.

It is also not more provenance. The walk down through `matched_clean_count` reaches those same 327
ids one level lower, with the fold that produced them attached. The second list is a second version
of the same fact, and the version a reader sees depends on which one the drawer happens to render.

The zero case is deliberately still legal: a window with no refunds folds to `0` over no records,
and that is a true statement rather than missing support.

**Cost to reverse.** Low. Stored evidence would carry the old shape.

---

### D-41 — A leaf's re-fold is layer 5's work, not layer 4's

**Decision.** Layer 4 re-evaluates every `Formula` and checks that a `COUNT` equals the size of the
set it cites. Layer 5 additionally re-sums the declared column over the resolved records and demands
the published figure.

**Why.** [06-trust-layer.md](06-trust-layer.md#evidence) already promised the re-sum — "verification
re-sums the ids it cites, which is an independent computation" — but the layer list puts
recomputation in layer 4, and layer 4 cannot reach a database. `gross_payments_paise` has no
expression to re-evaluate; the only check with any content is summing `amount_paise` over the 341
records it names, and that requires the records.

So the re-fold sits where the records are. Layer 4 keeps what it can do without them, which for a
leaf is exactly one identity: a count is the size of its own citation list. The ordering also makes
each failure unambiguous — "the records do not exist" and "the records do not add up" are different
findings and cannot be reported as the same one.

**Cost to reverse.** Low.

---

### D-42 — The evidence id's slice separator is `~`, not `#`

**Decision.** A dimensioned row's id is `.../2026-08-01_2026-08-24~UPI`.
[D-34](#d-34--a-metric-measured-over-a-dimension-is-one-metric-with-a-slice-not-one-per-value)
originally wrote it with `#`.

**Why.** The id is the last segment of `GET /executions/{id}/evidence/{evidence_id}`, and `#` is the
URI fragment delimiter — a client never sends it to the server. A request for the UPI row would have
arrived as a request for the blended row and returned a plausible, wrong, verified number with a
citation attached. That is the exact failure mode this whole layer exists to prevent, arriving
through the URL rather than through the arithmetic.

`~` is unreserved in RFC 3986, so it needs no encoding and survives a copied link.

**Cost to reverse.** Low now, high once ids are stored anywhere outside this repo.

---

### D-43 — A blocked execution is a row, and it stores no evidence

**Decision.** An execution is written as `VERIFYING` before verification runs. It becomes
`EXPLAINING` if every layer passes and `BLOCKED` if one does not. A blocked execution stores the
failing layer in `error_json` and **no evidence rows at all**. `response_source` stays `NULL`.

The `evidence` table is re-keyed on `(execution_id, id)` where `id` is the metric's address —
tool, version, metric, window and slice — rather than a UUID.

**Why, for the row.** "We could not verify this, and layer FORMULA is why" is an answer. A missing
record is indistinguishable from a request that never arrived, and Invariant 4 needs the difference
to be visible.

**Why, for storing nothing.** A stored evidence row is something the API serves and the drawer
walks. Serving the support for a number that failed verification is precisely how an unverified
figure reaches a reader *with a citation attached to it* — worse than no answer, because it looks
checked.

**Why `EXPLAINING` and not `COMPLETED`.** Phase 5 has no explainer. Writing `COMPLETED` would claim
an answer exists when the only thing that exists is permission to write one.

**Why re-key the table.** The original schema had a UUID key and `UNIQUE (execution_id, metric_id)`,
both written before anything published evidence. One execution publishes `net_revenue_paise` for two
windows and `by_method.success_rate_ratio` for four rails in each, so the constraint made the second
row of every pair a unique-violation. And a formula operand cites the address verbatim, so a
surrogate key gives it nothing to resolve against. The table also had no column for an
`Aggregation` at all — every leaf's support would have been dropped on the way to storage.

**Cost to reverse.** Medium. It is a migration, and stored ids are the addresses citations use.

---

### D-44 — The agent plane is layered, and the execution plan is its own package

**Decision.** `.importlinter` contract 2 now orders `orchestrator` / `validation` / `plan` /
`intent` / `llm` strictly, where the first three were siblings. `ExecutionPlan` and `PlanNode` live
in a `plan` package rather than beside the planner.

**Why.** The same defect as [D-28](#d-28--the-trust-plane-is-a-strict-order-and-evidence-receives-the-context), found
the same way: siblings may not import each other, and the moment those packages had contents they
all needed to. The planner reads an `Intent`, the validator judges a `ExecutionPlan`, and the
orchestrator calls the validator — three edges the sibling arrangement forbids.

Ordering them by the direction the pipeline runs is the honest shape. The one thing that did not
fit is the plan itself: the orchestrator *builds and runs* a plan and the validator *judges* one,
so it cannot live in either without the other importing upward. It is a vocabulary, exactly as
`evidence` is, and vocabularies sit below the things that consume them.

`llm` sits under `intent` because the parser is the only module above the trust boundary that
speaks to a model, and nothing else should acquire that ability by accident.

**Cost to reverse.** Low mechanically; the arrangement is what keeps the dependency direction
checkable at all.

---

### D-45 — The eleventh validation gate: an input reference must name a dependency

**Decision.** A `PlanNode` may declare `references: {input -> NodeRef}` for a value produced by an
earlier node. `UNRESOLVED_INPUT_REFERENCE` rejects a reference to a node that is not in the plan,
or that this node does not depend on. [05-agent-runtime.md](05-agent-runtime.md#validation) listed
ten checks; the exit criterion asked for eleven.

**Why.** The gap is real and this is what fills it. Every analysis tool takes the reconciliation
`run_id` ([D-35](#d-35--the-three-analysis-tools-take-a-run_id-which-the-spec-did-not-ask-for)),
and that value does not exist when the plan is written. Three ways to express it:

- put a placeholder in `inputs` and substitute at execution time — the validator then checks a
  string that is not the value, and `MISSING_TOOL_INPUT` passes on a plan that cannot run;
- string interpolation (`"${reconcile.run_id}"`) — invisible to a schema, so nothing can check it;
- a typed reference, which is checkable.

The dependency half is the part that earns its own code. A reference to a node that exists but is
not a dependency resolves to nothing at execution time — the referenced node may not have run yet —
and would surface as a tool error deep in a DAG rather than as a rejection before anything ran.
`REJECTED` is terminal *and nothing executed*; a check that fires after execution has started is a
different guarantee.

Two nodes sharing an id is refused by `ExecutionPlan` itself rather than by a twelfth code: a plan
with two nodes called `reconcile` has no single meaning to reject, because the graph the validator
would walk is already not the graph the author wrote.

**Cost to reverse.** Low. Removing it would make the spec's own "nothing executed" promise
conditional.

---

### D-46 — The blanket float ban is scoped to money-bearing packages

**Decision.** `scripts/check_no_float.py` check 2 — bare `float(` or a `float` annotation — now
applies to `runtime`, `reconciliation`, `tools`, `evidence`, `verification`, `provenance`, `routes`
and the seed generator. Checks 1, 3 and 4 (`_paise: float`, `/` on a `_paise` name, `round()`)
stay universal.

**Why.** Phase 6 added a plane that legitimately deals in floats: a network timeout, a
`time.monotonic()` duration. Neither is money and neither is near money. Three options were on the
table and two of them were worse:

- write awkward code to dodge the guard, which teaches everyone that the guard is an obstacle;
- add a broad exemption when it next fires, which is how the packages it exists for stop being
  covered.

Scoping it makes the check mean what its own message has always said — "float used in a
money-bearing package" — and leaves the three money-specific checks universal, so a `_paise` field,
a division on one, or a `round()` is still a violation wherever it appears.

**Cost to reverse.** Low, but a future money-bearing package must be added to the list, and that
is the failure mode to watch.

---

### D-47 — The vendor-SDK contract checks direct imports, not transitive ones

**Decision.** `.importlinter` contract 3 sets `allow_indirect_imports = True`. Contract 1 — the
deterministic and trust planes cannot reach `llm` — stays transitive, and must.

**Why.** `llm/provider.py` is the one module permitted to import the SDK, and every agent-plane
module is *expected* to reach it through that abstraction. A transitive check forbids exactly the
design it exists to enforce, so leaving it transitive would mean deleting the contract the first
time the parser was written.

What is banned is a direct `import anthropic` in the agent plane, which is how a retry helper or a
token count quietly becomes a second, unaudited call site with its own timeout and its own idea of
what a failure looks like.

The distinction is worth stating because the two contracts now read similarly and mean different
things. Contract 1 is about a boundary nothing may cross by any route. Contract 3 is about a
boundary that must be crossed at exactly one place.

**Cost to reverse.** Low.

---

### D-48 — Grounding checks magnitude and unit; the direction word goes unchecked

**Decision.** For a signed metric, the unsigned magnitude is an accepted rendering. "Net revenue
fell by ₹79,976.36" grounds against `-7997636` paise, and so does "changed by -₹79,976.36".

**Why.** Two things pushed this, and the second is the one that decides it.

English carries the sign in the verb. Nearly every honest sentence about a decline writes the
magnitude and says "fell", and requiring a minus sign inside the prose would send most correct
answers to the template — which is a real cost, because the template is a table and the model's
version is a paragraph a person can read.

More importantly, requiring it would buy nothing. "Revenue rose by -17.5956%" byte-matches
perfectly and is nonsense; "revenue fell by 17.5956%" fails and is correct. A byte-match cannot
tell those apart, because the thing that differs is a verb. What the gate *can* check is that no
digit was invented, rescaled, rounded, or attached to the wrong unit, and it checks all four
exactly.

So the boundary is stated rather than blurred: **grounding is a check on the numbers, not on the
sentence**. The residual exposure is a model that writes a direction backwards, and the mitigation
is that every claim carries the evidence id — a reader who doubts the sentence opens the row.

**Cost to reverse.** Low; it is one entry in `narrative/render.py`. Tightening it later would make
the template the usual answer, which is worth knowing before doing it.

---

### D-49 — The answer gets a column, and prose is tied to its origin

**Decision.** `agent_executions` gains `answer_text` and `claims_json` (migration 0004), plus
`CHECK ((answer_text IS NULL) = (response_source IS NULL))`.

**Why.** The table carried `response_source` and `grounding_attempts` from 0001 — a label saying
where the answer came from and a counter saying how hard it was to get — and no column for the
answer. Both were written before anything generated text, and the gap only becomes visible when
something does: `response_source = 'LLM'` on a row with no text is a statement about a sentence the
database never saw.

The constraint is bidirectional on purpose. Text with no declared source cannot be labelled, and
"who wrote this" is the first question a reader of a generated financial summary asks. A source
with no text claims something was written when nothing was — which is exactly the shape a
`BLOCKED` execution must never be able to take, and now cannot, at the level below the application.

`claims_json` is stored beside the prose rather than re-derived later. The claims are *what
grounding checked*: each one pins a span of the answer to an evidence id, which is also what makes
a number in the UI clickable. Re-extracting them afterwards would be a second, unverified parse of
the same text, and the two parses would disagree the first time somebody changed a regex.

**Cost to reverse.** Low, but the constraint is the part worth keeping.

---

### D-50 — The template renderer sits below the model boundary, not beside it

**Decision.** `narrative/` is its own package: `render.py`, `models.py`, `template.py`. It sits
below `llm` in contract 2 and is listed in contract 1, so it cannot reach a model by any route.
`llm/explainer.py` and `llm/grounding.py` import *down* into it.

**Why.** The template is what the system falls back to when the model is gone or twice ungrounded.
A fallback that could itself call a model is not a fallback, and the failure would arrive at the
worst possible moment — the model being unavailable is exactly when the fallback runs.

Putting it inside `llm/` would have made that a code-review convention. The build now fails
instead. It costs one package.

Two things follow that are worth having anyway. `Claim` and `Explanation` live below both
producers, so the model's answer and the template's answer are the same type and go through the
same five checks — a fallback judged by a weaker gate is a way around the gate. And
`narrative/render.py` becomes the one place that decides how a number is written, which is what
lets grounding byte-match at all: the template writes the canonical form and the gate accepts the
spellings that lose no digit, from one list.

**Cost to reverse.** Low mechanically. The reason not to is that the arrangement is what makes
"the numbers never depend on a third party" checkable rather than asserted.

---

### D-51 — The event stream subscribes before it replays, and deduplicates on `seq`

**Decision.** `GET /agent/runs/{id}/events` attaches to the in-process broadcaster *first*, then
reads `execution_events` from the requested sequence, then follows the live queue. Anything
arriving on both paths is dropped by sequence number.

**Why.** Two sources are unavoidable and each one alone is wrong.

The table is the truth — append-only, monotonically sequenced, and the reason a finished run and a
live one are the same rendering rather than two. But a stage's rows are not *visible* until the
stage's transaction commits, and the executing stage is the ninety-second one. A stream that read
only the table would show nothing during the DAG and everything at the end, which is exactly the
blocking design [C-14](00-corrections.md#c-14-m--a-synchronous-endpoint-cannot-drive-the-progressive-ui)
replaced.

The broadcaster alone is worse: it has no history, so a client that connects a second late has
missed the beginning permanently, and `Last-Event-ID` would have nothing to resume from.

The *ordering* is the part that is easy to get backwards. Reading first and subscribing second
loses every event written in between, and the gap is invisible — the client sees `…, 4, 7, 8, …`
and has no way to know 5 and 6 existed. Subscribing first can only produce duplicates, and a
duplicate is detectable: `seq` is monotonic, so the follower drops anything at or below what the
replay already emitted. **Prefer the failure you can detect.**

**Cost to reverse.** Low. When a second worker arrives (the D-12 trigger), the broadcaster becomes
a Redis subscription and nothing above it changes, because the durable log is already there.

---

### D-52 — Identity is a header until the JWT lands; the merchant is checked either way

**Decision.** `POST /agent/runs` reads the caller from `X-RazorMind-User` and resolves the role
from `merchant_members`. A non-member gets `403 MERCHANT_SCOPE_VIOLATION` before any row is
written; a `VIEWER` gets `403 INSUFFICIENT_PERMISSION`. There is no JWT yet.

**Why.** Two halves of authentication, and only one of them was available.

The half that could be built is the half [C-13](00-corrections.md#c-13-b--agentexecution-and-the-api-cannot-scope-to-a-merchant)
is about: the merchant in the request body is *validated against* the caller's memberships rather
than trusted for scoping. That check is real, it is tested, and it is what stops one tenant asking
about another's money.

The half that could not is proof that the header is who it claims. That needs Supabase issuing and
signing tokens, which is a Phase 12 deployment concern.

The alternative was to invent a local auth scheme — sessions, a signing key, a login page — and
throw it away in Phase 12. The cost of that is not the wasted work, it is that a hand-rolled auth
scheme built to be discarded is the kind of thing that survives, because it looks finished.

So the gap is stated in the module docstring, in the API doc, and here, and the swap is one
function: `_caller()` verifies a JWT instead of parsing a header, and `_membership()` does not
change at all.

**Cost to reverse.** Low, and the trigger is Phase 12.

---

### D-53 — The TypeScript contract is generated, and both halves are diffed in CI

**Decision.** `scripts/export_openapi.py` writes `packages/shared-types/openapi.json` *and*
`packages/shared-types/api.ts`. `task.py check` fails if either differs from what the app
produces. The generator raises on a schema shape it does not handle rather than emitting `any`.

**Why.** A generated file that is not diffed in CI is wrong within a fortnight: the endpoint
changes, the client keeps its old types, and the mismatch surfaces as an `undefined` in a browser
rather than as a red build. The diff is the whole value; the generation is the easy part.

Generating the TypeScript, rather than writing it beside the document, is the same argument one
level down. A hand-kept mirror of a generated file is a second source of truth that nobody notices
going stale — and it goes stale in the direction that matters, because the person adding a field
to the API is not the person reading the client.

Refusing an unknown schema shape is the part worth defending. Emitting `any` would keep the
generator running and quietly stop the contract being one; a build failure names the shape and
takes ten minutes to support.

**Cost to reverse.** Low. A fuller generator (`openapi-typescript`) is a drop-in replacement, and
the CI gate that makes it worth having is already the part that exists.

---

### D-54 — The API serves the rendered figure; the web app formats nothing

**Decision.** Every value the API returns for a metric carries a `display` string beside it —
`₹4,06,260.00`, `95.8012%`, `-1.34` — produced by `narrative/render.py`. `apps/web` contains no
currency, ratio or percentage-point formatting at all.

**Why.** There is exactly one place in this system that decides how a number is written, and it is
load-bearing in a way a display helper usually is not: the grounding gate *byte-matches* the prose
against those spellings ([D-11](#d-11--grounding-byte-matches-and-falls-back-to-a-template),
[D-48](#d-48--grounding-checks-magnitude-and-unit-the-direction-word-goes-unchecked)). A second
implementation in TypeScript would be a second answer to "what does this number look like", and the
two would disagree the first time one of them was edited — quietly, because both would keep
rendering something plausible.

The disagreement would also be in the worst possible place. `Intl.NumberFormat("en-IN")` groups
Indian digits correctly, so the drift would not show up on ₹4,06,260. It would show up on a
scale-6 ratio, where the browser's default rounds to three fraction digits and prints `95.801%` for
a figure the server refuses to let a model call `95.80%`.

So the server sends the string it already computed. The cost is a few bytes per row.

**Cost to reverse.** Low, and the reason not to is that "the number is written one way" stops being
checkable the moment there are two writers.

---

### D-55 — The web app is pinned to React 18, because Blade is

**Decision.** `apps/web` moves from Next 15 / React 19 to **Next 14.2 / React 18.3**.
`@razorpay/blade` is the UI, and it declares `styled-components@^5`, which does not support React
19.

**Why.** Two coherent options, and only one of them is honest about what is being built.

Keeping React 19 would have meant not using Blade — writing a look-alike interface with the same
spacing and colours and none of the accessibility, keyboard handling or component behaviour that
makes a design system worth adopting. For a Razorpay-facing product, "we reimplemented Blade" is a
worse sentence than "we are one React major behind".

So the design system picks the React version. That is the right direction for the dependency to
run: Blade is the part with an opinion, and the framework is the part that hosts it.

Two consequences worth writing down. Next 14 does not load `next.config.ts`, so the config is
`.mjs`. And styled-components v5 needs its server stylesheet collected explicitly, which is
`app/registry.tsx` — without it the server sends correct markup with no styles and the page flashes
unstyled, which on a page of financial figures reads as numbers that are still loading.

**Trigger to revisit.** Blade moving to styled-components v6. The change is then a version bump and
deleting the registry.

**Update, Phase 9.1.** The framework half of this turned out not to be pinned after all. Next 16
still declares `react: ^18.2.0 || ^19.0.0`, so the app runs Next 16 on React 18 and only *React*
is held back by Blade. The upgrade to Next 16 + TypeScript 7 + framer-motion 13 needed no code
change; `useParams()` in the replay route meant even the async-`params` migration did not apply.
`react-hot-toast` stays at 2.4.1 because Blade pins that version exactly rather than a range,
which is Blade saying it uses internals rather than an API.

---

### D-56 — The dashboard is built on evidence, not on the reconciliation table

**Decision.** The reconciliation scorecard renders the **published evidence** of the most recent
completed execution, not rows from `reconciliation_runs`. The exception explorer still reads the
reconciliation endpoint.

**Why.** Both hold the same figures. Only one of them carries an evidence id, and a number without
one cannot be clicked down to the records it came from.

That matters more than it sounds. The exit criterion is "every number in the dashboard is clickable
down to source records", and the obvious implementation — read `reconciliation_runs`, render seven
tiles — satisfies every part of it except the clicking. A product where the chat answer is
inspectable and the dashboard is inert has two standards of proof in one interface, and a reader
has no way to tell which page they are on.

An exception stays on the reconciliation endpoint because it is not a metric: it is a row with a
category, an amount, and — for the ones that matter — the candidate the matcher found and
deliberately refused. `SETTLEMENT_91` at confidence 0.72 is the strongest single thing this system
can show, and it has no evidence id because it is not a number anybody computed.

**Cost to reverse.** Low. The consequence to keep in mind is that the dashboard is empty until an
investigation has run, which is correct — there is nothing verified to show before then.

---

### D-57 — A second provider, and why a weaker model is a quality question not a correctness one

**Decision.** `llm/provider.py` gains a `GroqProvider`, spoken over `httpx` against Groq's
OpenAI-compatible endpoint, defaulting to `openai/gpt-oss-120b`. Which vendor is in use is a
named setting — `LLM_PROVIDER=anthropic|groq` — not an inference from whichever API key happens to
be present. `LLM_MODEL` becomes `ANTHROPIC_MODEL`, with `GROQ_MODEL` beside it.

**Why a second provider at all.** The first one costs money, and the entire deterministic half of
this system — reconciliation, the eleven gates, verification, evidence, provenance, the template
renderer — needs no model. What needs one is the chat entry point, and a demo where the chat box
returns `PROVIDER_UNAVAILABLE` is a demo of the wrong thing. Groq's free tier makes the model path
runnable by anyone who clones this.

**Why that is safe to do, and the whole point.** Swapping a frontier model for a 70B open-weight
one changes how often an answer is *phrased* well. It changes nothing about whether a figure on
screen is correct, because both places a model is consulted are guarded:

- an intent below `intent_confidence_threshold` asks a clarifying question instead of assuming
  ([05-agent-runtime.md](05-agent-runtime.md#intent));
- an explanation whose prose does not byte-match the verified rows is discarded and the
  deterministic template is rendered instead
  ([D-50](#d-50--the-template-renderer-sits-below-the-model-boundary-not-beside-it)).

A weaker model trips those gates more often. It cannot get past them. If this were not true, the
right response to "use a cheaper model" would be no; the fact that it is merely a quality trade is
the architecture paying out.

The concrete failure to expect is specific enough to name: an 8B model writes a claim whose
structured `value` field is exactly right and whose prose rounds it — `₹4,06,260.00` declared,
"about ₹4.06 lakh" written. Check 3 catches that, because it tokenises the claim's own span rather
than trusting the declared field
([06-trust-layer.md](06-trust-layer.md#grounding), and
[D-48](#d-48--grounding-checks-magnitude-and-unit-the-direction-word-goes-unchecked) on where that
check stops). The user sees the template.
Nobody sees a rounded figure presented as verified.

**Why `httpx` rather than the `groq` SDK.** The whole surface used here is one POST, and `httpx` is
already a dependency — so this costs no image rebuild. That is the small reason. The real one is
contract 3 in `.importlinter`, which forbids the agent plane from importing `anthropic` directly.
That contract is meaningful while there is one vendor SDK in the tree and one module allowed to
touch it. A second SDK means a second name to enumerate, and an enumeration is a thing someone
forgets to extend.

**Why the provider is named rather than sniffed.** Picking whichever key is present reads as
convenience until an environment has both, at which point the model that answered a month-end
question was chosen by import order. `response_source` already records which provider ran; the
setting makes the choice deliberate on the way in as well as legible on the way out.

**Costs.**

- Groq returns tool-call arguments as a JSON *string*, where Anthropic returns an object. Parsed
  and re-dumped inside the provider so that "the model did not emit JSON" arrives as a
  `PROVIDER_UNAVAILABLE` rather than as a confusing schema mismatch downstream.
- Groq rewrites `temperature: 0` to `1e-8`. Reproducibility was never load-bearing — the API offers
  no seed either way — but it is worth knowing the request is not sent as written.
- The free tier rate-limits, and a 4xx body from a model host can echo the request back. The error
  message is truncated to 200 characters, because the request contains the merchant's figures.
- `LLM_MODEL` → `ANTHROPIC_MODEL` is a breaking rename for anyone who set it. With two vendors,
  a single `LLM_MODEL` is a setting whose meaning depends on another setting.

**What the free tier actually buys.** Half the model path, and the honest half. Groq caps every
free model at 8,000 tokens per minute; the intent call is ~1,000 tokens and the explainer's
evidence brief is ~8,700, so the question is parsed by a model and the answer is rendered from the
template. Two things are worth saying about that rather than engineering around it.

It is the degradation this system already has, reached by an ordinary route. Nobody had to build a
rate-limit path — `PROVIDER_UNAVAILABLE` at explanation time was already specified to skip the
retry and render the template, because a missing model does not become present on a second call.

And the brief is large for a reason that should not be traded away cheaply. It is ~100 rows of
`evidence_id | metric | unit | value as written | window | support`, and the id is the biggest
column. The model cites that id, and grounding resolves it — shortening it to a handle would put an
indirection between what the model wrote and what the gate checks, which is the one place in this
system where indirection is not free. Fitting a vendor's free tier is not a good enough reason to
introduce it.

**On the model name.** It is a setting, and it has to be, because Groq's catalogue moves under
it: this was written against `llama-3.3-70b-versatile` and that model was gone from the account by
the time the key was live. A retired model surfaces as a 404 at request time — a
`PROVIDER_UNAVAILABLE` like any other, which the run already degrades through — rather than as a
startup failure, which is the right trade for a vendor whose inventory is not ours to pin.
`GET /openai/v1/models` on your own key is the only authority on what it holds. `groq/compound*`
is not a candidate at any size: it rejects tool calling, and this provider has no unstructured mode
to fall back to.

**Cost to reverse.** Low. Delete the class and the two settings; `get_provider` loses a branch.

---

### D-58 — A third provider, and the two defects a real model found

**Decision.** `GeminiProvider`, over `httpx` against Google AI Studio, defaulting to
`gemini-flash-lite-latest`. It is the free path that reaches `response_source = LLM`. Adding it
required fixing two things that were wrong before it existed, and those are the interesting half of
this entry.

**Why a third one.** Groq's free tier caps every model at 8,000 tokens a minute
([D-57](#d-57--a-second-provider-and-why-a-weaker-model-is-a-quality-question-not-a-correctness-one)),
and the explainer's evidence brief is ~8,700. So on Groq the explanation *always* fell back. Gemini
gives a million-token context on the free tier, so the brief is not a consideration at all.

**Defect one: the brief never carried the value a claim has to declare.** The system prompt said
"claims[].value must be exactly the value column of the brief: an integer for paise and count
metrics" — and the brief's value column held `₹6,38,151.00`, which is not an integer. The raw
`63815100` appeared nowhere. So the rule contradicted itself, and the only way to satisfy it was to
strip the rupee sign and the digit grouping back off, which the *first* rule forbids as a
conversion. Every real model failed, and it failed as `MALFORMED_EXPLANATION` — a validation error
on `int | Decimal` — which reads like the model being stupid rather than the prompt being
impossible.

The fix is that the brief carries both, because grounding checks both: `value` is what the claim
declares and is byte-matched against the stored row, `value as written` is what the prose writes and
is matched against `renderings()`. Two checks, two columns, and the instruction now maps onto them
one to one. This was invisible for two phases because the scripted providers in the tests were
written with the correct raw values already in hand — the fixture answered a question the prompt
never asked.

**Defect two: the window exemption did not survive being written in English.** `literals_for`
exempted the ISO windows, so `2026-07-01` could appear unclaimed. A model opens this answer with
"Net revenue fell in July 2026" — and `2026` was then an unclaimed number, failing check 1 on an
answer that was otherwise perfect. `_value_and_unit` already carried a comment anticipating exactly
this ("a sentence that names the window it covers would otherwise be asked to render 2026 as a
paise amount"); the literals set simply did not contain the form a sentence uses.

The year is now exempt too. That stays inside the boundary D-48 draws — grounding checks the
figures, not the sentence — because a year is the window this execution already ran on, not a
quantity anybody computed.

**And masking became digit-bounded, which is the part that matters.** `_masked` was a plain
substring replace. Exempting `2026` would then have blanked four digits out of the *middle* of
`20261` and left `1` — a wrong count grounding as an unremarkable one. That is the single direction
this gate may never fail in, so masking now requires that no digit touches either end of the
literal. Longest-first ordering already meant `2026-07-01` is consumed before `2026` is looked for.

**The schema had to be translated.** Gemini's `FunctionDeclaration.parameters` is OpenAPI 3.0's
Schema object, not JSON Schema, and it rejects the whole request on an unknown keyword —
`additionalProperties`, which pydantic emits for every `extra="forbid"` model, is a 400.
`openapi_subset()` collapses `anyOf: [X, {"type": "null"}]` to `X` with `nullable: true` and drops
everything outside an allowlist.

Allowlist, not denylist. A denylist passes an unrecognised keyword straight through to a 400 that
only shows up in production, and the set of keywords pydantic emits grows whenever somebody adds a
field. Dropping a constraint is safe in the direction that matters here: the schema *guides*
generation, the pydantic model *validates* the result, so a field the declaration failed to forbid
is a validation error and a correction, never a value anyone believes.

**The retry sits in the provider, not the explainer.** The explainer skips its retry on a provider
failure, because "a missing model does not become present on a second call". That is true of a
missing key and false of a 503 under load, which Google's free tier returns often. Only the layer
that can see the status code can tell those apart, so `GeminiProvider` retries 429 and 503 once,
1.5 seconds later, and everything that reaches the explainer really is not going to fix itself.

**On the model.** `gemini-flash-latest` is the better writer. On the free tier it answered 503 on
three of four calls, and on the fourth it spent its thinking budget before emitting the forced call
and finished `MAX_TOKENS` with no call at all. `-lite` has no thinking to spend and answered four
times out of four. A model that returns an answer beats a better model that returns a capacity
error. Relatedly, the "no structured block" error now carries `finishReason`: `MAX_TOKENS` and a
refusal are different problems with different fixes, and the code alone cannot tell them apart.

**Cost to reverse.** The provider, low — delete the class and two settings. The two grounding fixes
are not reversible and should not be: they were defects, and the only reason they survived to Phase
9 is that no real model had ever been asked to satisfy them.
