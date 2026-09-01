# 10 — Build Phases

Vision §34 is right: never ask an agent to "build the whole application." This is the controlled
vertical-slice plan.

**Rules for every phase**

1. A phase ends when its exit criteria pass, not when the code "looks done."
2. Contracts frozen in a phase are not renegotiated in a later one without a note in
   [decisions.md](decisions.md).
3. Every phase ships tests. A phase with no test is not complete.
4. The **Do not build yet** list is binding — it is what keeps scope from collapsing inward.

Phases 0–5 have no LLM in them at all. That is deliberate: the deterministic core must be
correct and provable before anything non-deterministic touches it.

---

## Phase 0 — Foundations

**Goal.** A repo that runs, lints, tests and enforces the boundaries from
[01-architecture.md](01-architecture.md#boundary-enforcement).

**Build**
- Monorepo scaffold per [01-architecture.md](01-architecture.md#repository-layout)
- FastAPI app with `GET /health` only; Next.js app with one page
- `.env.example`, `docker-compose.yml` (local Postgres), `Makefile`
- `runtime/money.py` — `Paise`, `apply_rate`, `ratio` ([02-data-model.md](02-data-model.md#money))
- `runtime/calendar.py` — IST business dates, 18:00 cutoff, T+2, holiday list
- CI: ruff, mypy strict, pytest, `import-linter` contracts, the no-float-in-`_paise` grep

**Exit criteria**
- `make check` green from a clean clone
- `runtime/money.py` and `runtime/calendar.py` at 100% branch coverage
- Import-linter fails a deliberate `from llm import ...` added inside `tools/`

**Do not build yet.** Any domain logic. Any table. Any tool.

---

## Phase 1 — Data plane and golden fixture

**Goal.** The dataset exists and is provably the one the docs describe.

**Build**
- Migrations for every table in [02-data-model.md](02-data-model.md#tables), including RLS policies
- `data/seed/generate_seed_data.py` per [08-seed-data.md](08-seed-data.md)
- `data/seed/golden/checksums.json`
- `tests/test_golden_story.py` — the fixture assertions

**Exit criteria**
- `make seed && make verify-seed` green, twice in a row, on two machines
- The bridge closes to the paise; attribution residual is `0`
- RLS proven: a user in merchant B reading merchant A's transactions gets zero rows

**Do not build yet.** Reconciliation. Any tool. Any API beyond `/health`.

> This is the phase people skip. Do not. Every number in every later phase is asserted against
> this fixture; if it is wrong, every downstream test is wrong and green.

---

## Phase 2 — Reconciliation engine

**Goal.** The financial control loop closes, with no agent anywhere near it.

**Build**
- Matcher: five rules, greedy one-to-one assignment, total tie-break
  ([03-reconciliation.md](03-reconciliation.md#assignment))
- Exception classifier: five categories, fee tolerance, timing-lag windows
- `verification/rules.py` — invariants I1–I6
- Unique constraints on `(run_id, transaction_id)` and `(run_id, settlement_id)`
- `GET /reconciliation/runs`, `.../exceptions`, `.../matches/{id}`

**Exit criteria**
- Golden reconciliation reproduced exactly: 342 / 341 / 338 / 327 / 15 / 95.61%
- Exception breakdown exactly 7 / 3 / 2 / 2 / 1
- Unresolved value exactly `184000` paise across `TXN_183`, `TXN_247`, `TXN_402`
- `SETTLEMENT_91` appears as a rejected candidate at confidence 0.72, not a match
- **Shuffle test**: reconciling with input rows in 20 different random orders produces byte-identical output
- Attempting to insert a duplicate match violates the unique constraint

**Do not build yet.** Revenue. The tool base class. Any UI.

---

## Phase 3 — Tool framework and revenue

**Goal.** The contract exists, and the hardest tool proves it is usable.

**Build**
- `tools/base.py` — the ABC from [04-tool-contract.md](04-tool-contract.md#the-contract)
- `tools/registry.py` — register, resolve, `describe()`
- Wrap Phase 2 as `finance.reconciliation` v1.0
- `finance.revenue_analysis` v1.0 including the bridge and rate/volume attribution
- `evidence/formula.py` — the restricted arithmetic interpreter

**Exit criteria**
- Revenue tool reproduces the golden bridge and attribution table exactly
- `rounding_residual_paise` present and within `abs(residual) <= term_count`
- Formula interpreter rejects `__import__`, attribute access, and calls
- A tool missing an `@abstractmethod` fails to instantiate

**Do not build yet.** The other three tools. Verification beyond the tools' own `verify()`.

---

## Phase 4 — Remaining tools

**Goal.** Full metric coverage for the diagnosis.

**Build**
- `payments.failure_analysis` — blended and per-method rates as distinct metric ids
- `finance.refund_analysis`
- `risk.chargeback_analysis`
- The metric vocabulary registry ([06-trust-layer.md](06-trust-layer.md#metric-vocabulary))

**Exit criteria**
- Blended success rate falls out of the method mix — the rails' counts sum to the blended counts
  exactly, and the blended rate is that ratio rather than an average of the rail rates
- The UPI rate is a *different metric id* from the blended rate
- `revenue.gross_payments_paise == failure.succeeded_value_paise`, exactly, and every declared
  equivalence in the vocabulary holds
- Publishing an unregistered metric id raises at import time

> **The figures this phase originally quoted are superseded.** It asked for a blended rate of
> 96.81% → 90.32% and a UPI rate of 96.8% → 82.9%; those describe the fixture before it was
> market-calibrated. The generated dataset gives blended **95.80% → 94.46% (−1.34 pp)** and UPI
> **96.44% → 94.62% (−1.82 pp)**. Asserting the old numbers would mean either testing a figure the
> generator does not produce, or tuning the generator until it produced one somebody wrote down in
> advance — which is what [D-26](decisions.md#d-26--counts-are-designed-money-is-derived) exists to
> prevent. The identities above are what the figures were expressing, and they are stronger
> ([D-36](decisions.md#d-36--phase-4s-quoted-exit-figures-are-superseded-by-the-calibrated-fixture)).

---

## Phase 5 — Trust layer

**Goal.** Nothing reaches prose unverified.

**Build**
- `verification/verifier.py` — the five layers, in order, first failure blocks
- Cross-tool consistency checks
- `evidence/builder.py`, `provenance/builder.py`
- `GET /executions/{id}/evidence/{evidence_id}`

**Exit criteria**
- A tool mutated to report a number its formula does not produce is caught by layer 4
- A tool mutated to cite a record outside the period is caught by layer 5
- Provenance from `net_revenue_change_ratio` walks down to real transaction ids
- Verification failure produces `BLOCKED` and **zero** generated text

All four hold, in `tests/test_verification_db.py`, against the real fixture. The mutations are
applied to the *published evidence* rather than to a tool: patching `finance.revenue_analysis` to
return a wrong figure would prove the patch worked, whereas what needs proving is that the verifier
takes no tool's word for anything — including a tool whose own `verify()` passed.

Layer 4's mutation is one paise on `net_revenue_paise`. Every operand still agrees with the row it
cites, the bridge identity in the tool's own `verify()` still passed, and only the re-evaluation
notices.

Three things this phase changed that the earlier docs had wrong, each with a decision entry:
`Aggregation` now declares which date scoped it ([D-37](decisions.md#d-37--evidence-declares-the-date-rule-that-scoped-it)),
the vocabulary declares which metrics may be negative ([D-38](decisions.md#d-38--the-vocabulary-declares-which-metrics-may-be-negative)),
and the `evidence` table is keyed on the metric's address rather than a surrogate id
([D-43](decisions.md#d-43--a-blocked-execution-is-a-row-and-it-stores-no-evidence)).

**Do not build yet.** Any LLM call. Seriously — the next phase is the first one.

---

## Phase 6 — Agent runtime

**Goal.** Natural language in, validated plan out, executed and persisted.

**Build**
- `intent/parser.py` — structured output, confidence threshold, clarification
- `llm/provider.py` — the provider abstraction, one implementation
- `orchestrator/planner.py` — deterministic intent→DAG map
- `validation/plan_validator.py` + `policy.py` — all eleven checks
- `orchestrator/executor.py` — layered concurrent execution, per-node persistence
- `orchestrator/state.py`, `events.py` — the nine-state machine, `execution_events`

**Exit criteria**
- Ten seeded questions produce the correct intent; ambiguous ones return
  `NEEDS_CLARIFICATION` rather than guessing
- Each of the eleven validation failures is reachable and returns its own `code`
- An intent naming a foreign `merchant_id` is rejected as `MERCHANT_SCOPE_VIOLATION`
- Independent nodes demonstrably run concurrently (wall time < sum of node times)
- Every state transition has an `execution_events` row with a monotonic `seq`

All five hold. Three notes on how, because each involved a judgement:

**The ten questions run against a scripted provider**, not a live model, and seven route while
three ask. That tests the parser — validation, the confidence gate, the three clarification
reasons, the merchant check, the retry — deterministically and completely. Whether a real model
routes these correctly is a different question with a different answer, and it belongs in Phase
11's eval suite as a *score*: a model right 29 times out of 30 has not broken the build. A live
run is available through `task.py ask` whenever a key is configured.

**The eleventh gate did not exist.** The table in
[05-agent-runtime.md](05-agent-runtime.md#validation) listed ten, and the missing one is real:
every analysis tool takes a `run_id` that does not exist when the plan is written, so a plan needs
typed input *references*, and a reference to a node this one does not depend on has to be caught
before execution starts
([D-45](decisions.md#d-45--the-eleventh-validation-gate-an-input-reference-must-name-a-dependency)).

**Concurrency is asserted with sleeping fakes.** Four nodes of 0.4s each finish in well under the
1.6s a serial run would take. Timing the four real analyses would be timing Postgres.

**Do not build yet.** The explainer. The UI.

---

## Phase 7 — Explainer and grounding

**Goal.** Prose that cannot contain an ungrounded number.

**Build**
- `llm/explainer.py` — receives verified metrics, evidence, provenance; nothing else
- `llm/grounding.py` — claim extraction and the five checks
- Regenerate-once, then `TEMPLATE_FALLBACK`
- The deterministic template renderer

**Exit criteria**
- A stub LLM that invents `₹5,00,000` is caught, regenerated, then falls back
- A stub that restates the verified decline ratio to one decimal place fails check 3
  (byte-match)
- With the LLM provider disabled entirely, the run still `COMPLETED`s with the full verified
  bridge via template
- `response_source` is persisted on every execution

---

## Phase 8 — API surface

**Goal.** Everything the UI needs, streaming included.

**Build**
- `POST /agent/runs` (202 + idempotency), `GET /agent/runs/{id}/events` (SSE)
- `GET /executions/{id}`, `GET /executions`
- OpenAPI generation into `packages/shared-types/openapi.json` + TS client
- Single-worker uvicorn pinned, with the constraint documented in the deploy config

**Exit criteria**
- A client sees stage events arrive progressively, not in one burst at the end
- `Last-Event-ID` resumes a dropped stream without gaps or duplicates
- Replaying the same `client_request_id` returns the original `execution_id`
- Regenerated OpenAPI matching the committed file is a CI gate

---

## Phase 9 — Web application

**Goal.** The four experiences from vision §6.

**Build**
- Chat with the live execution trace (SSE)
- Reconciliation dashboard — scorecard + exception breakdown
- Exception explorer with drill-down, including rejected candidates
- Provenance drawer — the generic recursive evidence renderer
- Execution history, replaying `execution_events` through the same component as live

**Exit criteria**
- Chat shows stages ticking, not a spinner
- Every number in the dashboard is clickable down to source records
- History and live chat share one trace component (asserted by a test, not by inspection)
- The exception explorer shows *why* `SETTLEMENT_91` was rejected

---

## Phase 10 — Failure and recovery

**Goal.** Every degradation path in [05-agent-runtime.md](05-agent-runtime.md#recovery) is real
and demonstrable.

**Build**
- Fault-injection switches: kill a tool, time out the LLM, break verification, drop the DB
- `PARTIAL` rendering — unavailable metrics shown as unavailable, never blank or zero
- `BLOCKED` rendering — an explicit "cannot be verified" surface with no numbers

**Exit criteria**
- A test for each of the seven recovery rows
- Disabling `payments.failure_analysis` still yields verified reconciliation and revenue
- Nothing anywhere substitutes a default, estimate, or `0` for missing data

> This phase is a demo dependency, not a nicety — the flagship moment is breaking a tool live.

---

## Phase 11 — Evaluation suite

**Goal.** Vision §39's four dimensions, measured.

**Build**
- 30+ question set with expected intents and expected tool sets
- Intent accuracy, tool-selection accuracy, computation accuracy, grounding rate
- Reconciliation accuracy: match rate, classification accuracy, false-match rate
- `make eval` writing a report to `docs/eval-report.md`

**Exit criteria**
- Intent accuracy ≥ 90%, tool selection ≥ 90%
- Computation accuracy 100% (deterministic — anything less is a bug, not a score)
- Grounding rate ≥ 95%, false-match rate 0% on the fixture

---

## Phase 12 — Deployment and demo

**Build**
- Vercel (web), Railway/Render (API, single worker), Supabase (DB + auth)
- Seeded production-demo database
- README, architecture docs, [11-demo-script.md](11-demo-script.md), the 5-minute pitch

**Exit criteria**
- Cold-load to first answer under 10s on the deployed environment
- The full demo script runs end-to-end three times without intervention
- The fault-injection moment works on the deployed environment, not just locally

---

## Mapping to the vision doc

| Vision | Phases |
| --- | --- |
| §35 MVP / V0 | 0 → 7 (chat through explanation, minimal UI) |
| §36 V1 | 8 → 11 |
| §37 V2 (dynamic planning) | post-v1; the planner swap is the only change, since validation already gates LLM-proposed plans |
| §50 build order 01–27 | 0 → 12 |

## Sequencing risks

| Risk | Mitigation |
| --- | --- |
| Building the UI before the trust layer | Phases 0–5 have no UI and no LLM. The gate is structural. |
| Fixture drift silently invalidating tests | Checksums in CI (Phase 1) |
| LLM creeping into a tool | Import-linter contract from Phase 0 |
| Float creeping into money | CI grep from Phase 0, plus `_paise` naming |
| Match rate changing between runs | Shuffle test in Phase 2 |
| Web/API contract drift | OpenAPI diff gate in Phase 8 |
