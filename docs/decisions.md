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

