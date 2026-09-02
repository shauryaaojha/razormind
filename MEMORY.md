# MEMORY

Working context for this repo. Read this first in a fresh session, then
[`README.md`](README.md), then the phase you are on in
[`docs/10-build-phases.md`](docs/10-build-phases.md).

---

## Standing instructions

These are decisions the owner has made. They are not up for re-litigation each session.

1. **Every dependency is installed inside a container.** No host virtualenv, no global `pip`, no
   global `npm`. If a new tool is needed, add it to `pyproject.toml` (or `apps/web/package.json`)
   and rebuild the image. Never install on the host.
   → [D-16](docs/decisions.md#d-16--every-dependency-is-installed-inside-a-container)
2. **Build phase by phase.** A phase ends when its exit criteria pass, not when the code looks
   done. The "Do not build yet" list in each phase is binding.
3. **Commit as work progresses.** Small, scoped commits with a real message. Do not batch a whole
   phase into one commit unless the phase is genuinely one change.
4. **Ship tests with every phase.** A phase with no test is not complete.
5. **Fix the docs when the code contradicts them.** The docs are the contract; if reality forces a
   change, record it in [`docs/decisions.md`](docs/decisions.md) rather than letting the two drift.

## How to run anything

```bash
docker compose build                 # the only place anything downloads
python scripts/task.py check         # the full gate: lint · types · boundaries · nofloat · test
python scripts/task.py --list        # every target
docker compose up db api web         # :8000/health  ·  :3000
```

`scripts/task.py` is the single implementation of every command. Run from the host it re-invokes
itself inside the `tools` container, so these are identical:

```
make check
python scripts/task.py check
docker compose run --rm tools scripts/task.py check
```

CI (`.github/workflows/ci.yml`) builds and runs the same image.

---

## The one rule this project exists to enforce

> The LLM decides **what to compute**. Deterministic code decides **what the number is**.
> Verification decides **whether it can be trusted**. The LLM explains only what survived.

Three mechanisms enforce it, all in CI, all from Phase 0:

| Mechanism | File | What it stops |
| --- | --- | --- |
| Import contracts | `.importlinter` | `tools/`, `runtime/`, `verification/`, `evidence/`, `provenance/` importing `llm/` or a vendor SDK |
| Money guard | `scripts/check_no_float.py` | `float` in a money path, division on `_paise`, `round()` outside `runtime/money.py` |
| Grounding gate | Phase 7 | A number in the prose that is not a verified metric |

`tests/test_boundaries.py` plants a real violation and asserts the build **fails**. Asserting that
a contract passes proves nothing — a contract with a typo in it also passes.

---

## Non-negotiable invariants

- Money is integer **paise**. Never float, never Decimal at rest. Every field ends in `_paise`.
- Ratios are `Decimal` at scale 6, field suffix `_ratio`. Serialized as JSON **strings**.
- Rounding is `ROUND_HALF_UP`, once per calculation, only in `runtime/money.py`.
- A "date" is always the **IST calendar date** from `runtime/calendar.py`. Never `UTC::date`.
- Periods are half-open `[from, to)`.
- `merchant_id` always comes from the session, never from the model.
- Missing data yields an explicit limitation — never an invented, estimated, or zero value.

---

## The data

**Synthetic records, calibrated aggregates, explicit provenance.** Transaction-level rows are
invented and seeded; the payment mix, ticket sizes, decline rates and fee rules are calibrated
against public NPCI/RBI statistics. Every parameter is tagged `CITED` / `DERIVED` / `ASSUMED` in
`data/calibration/parameters.py`, redeemed in `data/calibration/sources.md`.

**Counts are designed; money is derived.** The scenario fixes capture counts and anomaly counts.
Failures, values, fees, rates and the decline all emerge. So `verify-seed` asserts *identities and
calibration bands*, never hard-coded revenue.

| | Prior | Current |
| --- | ---: | ---: |
| Attempts / captures | 429 / 411 | 361 / 341 |
| Success rate | 0.958042 | 0.944598 |
| Technical declines | 0.006993 | 0.022161 |
| Business declines | 0.034965 | 0.033241 |
| Net revenue | Rs 4,73,424 | Rs 3,90,122 |

Decline **-Rs 83,301 = -0.175956**, residual **0**.
Reconciliation **342 / 341 / 338 /
327 / 15 / 0.956140**,
Rs 1,840 unresolved.

**The primary driver is attempt volume, not the incident.** The incident is real, dated and
localised to BANK_A, BANK_B, BANK_C — and it is a deliberate trap for a model that
reasons from narrative. `verify-seed` check 10 asserts the declared diagnosis matches the data.

Regenerate with `task.py seed`; every number above comes from `golden/ground_truth.json`.
Full detail: [`docs/08-seed-data.md`](docs/08-seed-data.md).

---

## Phase status

| Phase | State |
| --- | --- |
| 0 — Foundations | **Done.** `check` green: ruff, mypy strict, 3 import contracts, money guard, 100% branch coverage on `runtime/` |
| 1 — Data plane & golden fixture | **Done**, then reworked to a market-calibrated pipeline (D-23…D-27). 13 tables + RLS, calibration layer, scenario, ground truth, 10 fixture assertions |
| 2 — Reconciliation engine | **Done.** 5 rules, greedy one-to-one, shuffle test, per-instrument fee rule, 4 read endpoints |
| 3 — Tool framework & revenue | **Done.** `DeterministicTool` ABC + registry, `finance.reconciliation`, `finance.revenue_analysis`, restricted formula interpreter |
| 4 — Remaining tools | **Done.** `payments.failure_analysis`, `finance.refund_analysis`, `risk.chargeback_analysis`, metric vocabulary enforced at import |
| 5 — Trust layer | **Done.** Five verification layers, cross-tool consistency, evidence persistence, provenance walk, `GET /executions/{id}/evidence/{evidence_id}`. 304 + 88 tests |
| 6 — Agent runtime | **Done.** Intent parser + confidence gate, deterministic planner, eleven validation gates, concurrent DAG executor, nine-state machine, event log. 359 + 104 tests |
| 7 — Explainer | **Done.** Five grounding checks, byte-match on value *and* prose, regenerate-once, deterministic template below the model boundary, answer persisted. 396 + 106 tests |
| 8 — API surface | **Done.** `POST /agent/runs` (202 + idempotency), resumable SSE, history listing, generated OpenAPI + TypeScript contract diffed in CI. 396 + 121 tests |
| 9 — Web application | **Done.** Blade throughout. Chat with a live SSE trace, evidence-backed reconciliation scorecard, exception explorer with rejected candidates, recursive provenance drawer, history replay through the same component. 20 web tests |
| 10 — Failure & recovery | next. Fault injection, PARTIAL and BLOCKED surfaces |
| 11–12 | not started |

### Notes from Phase 0 worth not rediscovering

- `python -m importlinter.cli` exits **0 having evaluated nothing** — no `__main__` guard. Use the
  `lint-imports` console script. The planted-violation test is what caught this.
- `main` cannot be an import-linter root package (it is a module, not a package).
- `bool` is an `int` to mypy, so `apply_rate(True, ...)` type-checks. Only the runtime check
  catches it. Same reason the money guard is a textual scan rather than a type check.
- Python is pinned to **3.13** in two places that must agree: `requires-python` in
  `pyproject.toml` and the base image in `apps/api/Dockerfile`. The image is the one that decides.
  → [D-17](docs/decisions.md#d-17--python-is-pinned-to-313-not-312)

### Notes from Phase 1 worth not rediscovering

- **The two reconciliation sides are scoped on different dates.** Ledger by IST capture date, bank
  by `bank_period()` — the same window shifted by T+2 and widened by the lag ceiling. Scoping both
  to the same literal dates invents exceptions at the edges. → [D-18](docs/decisions.md#d-18--a-reconciliation-run-scopes-its-two-sides-on-different-dates)
- **The fixture has a two-day quiet band before each window.** A capture just before a window —
  especially after the 18:00 cutoff — settles *inside* it and would look like an unmatched bank
  row. → [D-19](docs/decisions.md#d-19--the-fixture-leaves-a-two-day-quiet-band-before-each-analysis-window)
- Exact totals come from **largest-remainder apportionment**, not from generating and hoping.
  Every amount is a whole number of rupees, which is what keeps the per-instrument fee schedule
  landing on documented rates rather than on rounding artefacts.
- Scoping *attempts* by capture date silently drops every failure (a failure has no `captured_at`)
  and every success rate reads 100%. Attempts scope on `attempted_at`, ledger records on
  `captured_at`.
- RLS is only meaningful when tested as a **non-owner** role: a table owner is exempt by default.
  The tests `SET ROLE razormind_app` first, and one test asserts the seed actually loaded so the
  isolation tests cannot pass vacuously on an empty database.
- `runtime/schema.py` is omitted from the coverage gate on purpose — "100% coverage" on a
  declarative table list means only that it was imported.

### Notes from Phase 2 worth not rediscovering

- **The tie-break must be total.** Five keys, the last two being settlement id then transaction id
  purely so no two candidate pairs can compare equal. Without them the result depends on the sort
  algorithm, and the shuffle test is what proves it does not.
- **Rules 1 and 2 needed the lag ceiling added.** The spec named it only for rules 3-5, but the
  exception table says a lag beyond three business days means no pair at all.
- **The exception count is ledger-side** (15, not 18). Bank overhang is reported as
  `unmatched_bank`. → [D-20](docs/decisions.md#d-20--the-published-exception-count-is-ledger-side)
- **The trust plane sits BELOW tools** in the import contract, because a tool implements
  `verify()` and `evidence()`. The earlier ordering would have broken on Phase 3's first tool.
  → [D-21](docs/decisions.md#d-21--the-trust-plane-sits-below-tools-in-the-import-contract)
- **An empty ledger side raises**; an empty bank side does not.
  → [D-22](docs/decisions.md#d-22--an-empty-period-is-refused-not-answered-with-a-zero-match-rate)
- `runtime/db.py` caches its engine, so `tests/conftest.py` disposes it after every test —
  otherwise an asyncpg pool outlives its event loop and every db test fails on teardown with
  "Event loop is closed" instead of on anything real.
- The Phase 2 orchestration lived in `scripts/reconcile.py` because `reconciliation/` may not
  import `verification/` — the engine must not decide whether its own output is trustworthy.
  Phase 3 moved it behind `finance.reconciliation`; the script is now a thin CLI.
- **Auth is a stated gap until Phase 8.** The read endpoints connect as the owner role, which is
  exempt from RLS. The policies are proven by `tests/test_rls.py` as the non-owner role, but
  `merchant_id` currently selects rather than enforces. Documented in `routes/__init__.py`.

### Notes from the calibration rework worth not rediscovering

- **Volume share is not value share.** UPI is ~72% of payments and ~39% of the money. Each method
  declares a volume share and a mean ticket; the value share is derived. A generator that used one
  share for both models a world that cannot exist.
- **Fees are per instrument** (`runtime/fees.py`), never flat. Zero-MDR UPI and RuPay debit really
  cost zero — a flat percentage cannot express that, which is why a fee discrepancy used to be
  noise. The schedule lives in `runtime/`, not `data/`, so the engine never imports the fixture.
- **Hierarchical allocation is mandatory.** Apportioning 341 captures across 552 (day × method ×
  issuer) cells in one pass gives every cell a base of zero and lets the remainder pass hand every
  unit to the largest weights — NETBANKING and WALLET vanished entirely. Allocate methods first,
  then days and issuers within a method.
- **Failures must be apportioned across the window, not rounded per cell.** Rounding hundreds of
  expectations each below 0.05 gives all zeroes and a fixture with a 100% success rate.
- **Ticket values must be apportioned, not drawn independently.** ~350 samples from a heavy right
  tail had enough variance to flip the sign of the revenue change.
- **`ADD CONSTRAINT … NOT VALID`** for the decline-type check: rows written before the taxonomy have
  no honest backfill, and picking a default would invent the field the investigation depends on.
- The original ₹40L / ₹18,400 figures implied a **₹12,560 average ticket** — about 10× a realistic
  Indian P2M ticket. Calibration exposed that; the merchant is now ~₹4L/month and the unresolved
  value scales with it.

### Notes from Phase 3 worth not rediscovering

- **`run()` on the base class owns the order** — validate, scope, execute, verify, evidence. Put
  it anywhere else and every caller re-implements it, and one of them gets it wrong. A failing
  `VerificationResult` raises there, before any output leaves the tool.
- **A leaf metric has no formula to re-evaluate.** `gross_payments_paise` is a sum over 341
  records. It carries an `Aggregation` and the verifier re-sums the cited ids; giving it a
  synthetic expression would make layer 4 a check that passes by construction.
  → [D-29](docs/decisions.md#d-29--evidence-carries-a-formula-or-an-aggregation-never-both-never-neither)
- **`evidence()` needs `ctx`.** The documented `(inp, out)` signature could not fill the
  `execution_id` that C-15b requires on every row — the contract made its own required field
  unfillable. → [D-28](docs/decisions.md#d-28--the-trust-plane-is-a-strict-order-and-evidence-receives-the-context)
- **`verification` / `provenance` / `evidence` are now a strict order, not siblings.** Both the
  verifier and the provenance walker must import `evidence`, and import-linter siblings may not
  import each other. This only surfaced once the modules had contents.
- **Formula operand names are short and unit-free** (`gross`, `prior`), with `operands` mapping
  each to an evidence id. A literal expression containing `x_paise / y` would trip the C-01 money
  guard, which scans source text and cannot tell a string from code.
- **The interpreter never rounds.** It returns an exact `Decimal`; `runtime.money.quantize_paise`
  and `quantize_ratio` are the single rounding. Otherwise "the tool disagrees with its formula"
  and "the two roundings disagree" are indistinguishable failures.
- **The run id is derived from the execution**, so a replay returns the existing run instead of
  writing a second — and refuses with `RUN_SNAPSHOT_CHANGED` if a fresh reconciliation of the same
  period disagrees with what is stored. `uuid4()` broke determinism on the field clients store.
  → [D-30](docs/decisions.md#d-30--a-reconciliation-run-id-is-derived-from-the-execution-and-a-replay-is-idempotent)
- **A refund belongs to the period of the payment it reverses**, never to its own `created_at`.
  Scoping this fixture's refunds by `created_at` moves one of eighteen into the wrong window.
  → [D-31](docs/decisions.md#d-31--a-refund-belongs-to-the-period-of-the-payment-it-reverses)
- **Revenue needs the reconciliation run to be correct.** 342 ledger records, 341 payments; only
  the run knows which is the duplicate, so gross computed without it is overstated by exactly one
  payment. → [D-32](docs/decisions.md#d-32--reconciliation-is-an-input-to-revenue-not-a-report-published-beside-it)
- **The output carries its own source record ids.** `evidence(inp, out, ctx)` is handed nothing
  else, and a tool that re-queries to explain itself gets a second chance to disagree with the
  first.
- Pydantic v2 uses `@dataclass_transform`, so a type checker synthesises `__init__` from the field
  annotations — passing a `dict` where a sub-model is declared needs an explicit ignore even
  without the mypy plugin.
- `DeterministicTool` is invariant in its type parameters, so the registry stores
  `DeterministicTool[Any, Any]`. The concrete types are recovered at the call site.

### Notes from Phase 4 worth not rediscovering

- **The unit is read from the metric id, never passed alongside it.** `EvidencePublisher` takes no
  `unit` argument. A tool that cannot state the unit twice cannot state it inconsistently, which
  is what actually closes C-04. → [D-33](docs/decisions.md#d-33--the-metric-vocabulary-is-enforced-at-import-and-the-unit-comes-from-the-id)
- **`__init_subclass__` is the import-time gate.** It runs at class creation, so an unregistered
  metric id is a build failure. Note it runs *before* `ABCMeta` sets `__abstractmethods__`, so it
  cannot check for abstract methods -- that check stays with `ABC` itself.
- **`UnknownMetricError` is a `KeyError`, and pydantic only converts `ValueError`/`AssertionError`
  into a `ValidationError`.** The Evidence validator re-raises it as a `ValueError`, or a KeyError
  escapes from the middle of model construction.
- **`by_method.*` is one metric with a `method` dimension**, not four metrics. `attribution.*` is
  the opposite -- five different formulas, so five metrics. A dimension slices one *computation*.
  → [D-34](docs/decisions.md#d-34--a-metric-measured-over-a-dimension-is-one-metric-with-a-slice-not-one-per-value)
- **All four analysis tools need the `run_id`.** The spec asked for it only on revenue, which makes
  its own consistency check unsatisfiable: without the duplicate set, `succeeded_value_paise`
  exceeds `gross_payments_paise` by exactly one payment.
  → [D-35](docs/decisions.md#d-35--the-three-analysis-tools-take-a-run_id-which-the-spec-did-not-ask-for)
- **Scoping lives in `tools/records.py`, once.** Four tools totalling the same window is only
  consistent if they share the scoping function; two copies would make the cross-tool check a test
  of whether two implementations had drifted.
- **A `_pp_change` must cite the two rates it came from.** Recovering the earlier rate by inverting
  the published change makes layer 4 re-derive the answer from the answer -- a check that cannot
  fail. `failure_analysis` carries both periods' rail breakdowns for exactly this.
- **The blended rate is the summed counts.** It is not the mean of the rail rates, and the two
  differ whenever volumes differ. The exit criterion is the identity, not a figure.
- **Phase 4's quoted figures were pre-calibration** (96.81% -> 90.32%, UPI 96.8% -> 82.9%). The
  live figures are 95.80% -> 94.46% and 96.44% -> 94.62%.
  → [D-36](docs/decisions.md#d-36--phase-4s-quoted-exit-figures-are-superseded-by-the-calibrated-fixture)
- `scripts/check_no_float.py` now blanks string literals and comments with `tokenize` before
  scanning. It was reading an evidence id in a docstring -- `.../net_revenue_paise/2026-08-01_...`
  -- as a division. A guard that cries wolf on documentation gets worked around rather than fixed.

### Notes from Phase 5 worth not rediscovering

- **"Inside the period" is four questions.** Attempt date, capture date, the *parent* payment's
  attempt date, and the settlement value date are all correct for different records, so the
  evidence declares which rule scoped it (`Aggregation.scoped_by`) and layer 5 checks *that*
  rule. A verifier assuming one date rejects three correct rows out of four.
  → [D-37](docs/decisions.md#d-37--evidence-declares-the-date-rule-that-scoped-it)
- **Writing that down immediately found a defect**: `bank_count` was filed under the analysis
  window while citing settlements dated into September. It now carries the bank window, because
  the period is part of a row's identity.
  → [D-39](docs/decisions.md#d-39--bank_count-is-filed-under-the-bank-window-not-the-analysis-window)
- **Layer 2 needs `signed` on the metric.** "Money is non-negative" is false for an attribution
  effect and "a ratio is in [0, 1]" is false for `net_revenue_change_ratio`; one blanket rule has
  to be weakened until it checks nothing.
  → [D-38](docs/decisions.md#d-38--the-vocabulary-declares-which-metrics-may-be-negative)
- **A leaf's re-fold belongs to layer 5, not layer 4.** Layer 4 cannot reach a database, and
  `gross_payments_paise` has no expression -- the only check with content is re-summing the
  column over the records it cites.
  → [D-41](docs/decisions.md#d-41--a-leafs-re-fold-is-layer-5s-work-not-layer-4s)
- **A derived row may not cite records.** `clean_match_rate_ratio` used to do both; the two
  accounts can drift and nothing compares them. The walk reaches the same ids one level lower.
  → [D-40](docs/decisions.md#d-40--a-derived-metric-cites-operands-a-leaf-cites-records-never-both)
- **The slice separator is `~`, not `#`.** The evidence id is the last path segment of an
  endpoint, and a fragment never reaches the server: a request for the UPI row would have
  returned the blended one, verified, with a citation.
  → [D-42](docs/decisions.md#d-42--the-evidence-ids-slice-separator-is--not-)
- **Nullable `JSONB` needs `none_as_null=True`.** SQLAlchemy otherwise stores Python `None` as
  the JSON literal `null`, which is not SQL NULL -- so
  `(formula_json IS NULL) <> (aggregation_json IS NULL)` failed on every row that satisfied it.
- **The `evidence` table was keyed wrong from Phase 1**: a UUID id and `UNIQUE (execution_id,
  metric_id)`, which forbids the two windows and four rails one execution publishes, and gives a
  formula operand nothing to resolve against. Migration 0003 keys it on `(execution_id, id)`
  where the id is the metric's address.
  → [D-43](docs/decisions.md#d-43--a-blocked-execution-is-a-row-and-it-stores-no-evidence)
- **Mutate the published evidence, not the tool.** Patching a tool to return a wrong figure
  tests the patch. `tests/test_verification_db.py` rewrites one evidence row by one paise and
  only layer 4 notices -- the tool's own `verify()` still passes.
- **A blocked execution stores no evidence.** A stored row is one the API serves and the drawer
  walks; serving support for an unverified number is worse than serving nothing, because it
  looks checked.

### Notes from Phase 6 worth not rediscovering

- **`orchestrator` / `intent` / `validation` were siblings and could not stay that way** --
  the same defect as D-28, found the same way. They are now ordered, and `ExecutionPlan` moved
  into a `plan` package because the orchestrator builds one and the validator judges one.
  → [D-44](docs/decisions.md#d-44--the-agent-plane-is-layered-and-the-execution-plan-is-its-own-package)
- **The spec listed ten validation gates; the exit criterion asked for eleven.** The missing one
  is real: a plan needs typed input *references* for the `run_id`, and a reference to a node
  this one does not depend on must be caught before execution starts.
  → [D-45](docs/decisions.md#d-45--the-eleventh-validation-gate-an-input-reference-must-name-a-dependency)
- **Each DAG node opens its own connection.** An asyncpg connection cannot serve two queries at
  once; sharing one would serialise the layer or corrupt the protocol state.
- **The no-float guard's blanket check is now scoped to money-bearing packages.** A network
  timeout and `time.monotonic()` are floats and are not money. The three money-specific checks
  stay universal.
  → [D-46](docs/decisions.md#d-46--the-blanket-float-ban-is-scoped-to-money-bearing-packages)
- **Contract 3 is `allow_indirect_imports = True`, deliberately.** `llm/provider.py` is the one
  module allowed to import the SDK and everything else reaches it *through* that, so a
  transitive check would forbid the design. Contract 1 stays transitive and must.
  → [D-47](docs/decisions.md#d-47--the-vendor-sdk-contract-checks-direct-imports-not-transitive-ones)
- **The ten seeded questions run against a scripted provider.** That tests the parser, not the
  model. Model accuracy is Phase 11's *score*, not a build gate.
- **Concurrency is asserted with sleeping fakes**, not the real tools: timing the real four
  would be timing Postgres.
- **`get_provider()` returning a refusing provider is a supported state.** No key means
  `PROVIDER_UNAVAILABLE`, never a canned intent -- an invented intent answers a question nobody
  asked, verified and cited.
- **There are three providers: `anthropic`, `groq` and `gemini`.** `LLM_PROVIDER` names one; it is
  never inferred from whichever key is present, because two keys in one environment would pick a
  model by accident. Groq and Gemini are `httpx`, not their SDKs -- one vendor SDK in the tree is
  what makes contract 3 enforceable. Groq returns tool arguments as a JSON *string* and rewrites
  `temperature: 0` to `1e-8`; its free tier is 8,000 TPM against an ~8,700-token brief, so it
  always falls back. Gemini has a 1M context and runs both calls, but takes **OpenAPI 3.0, not
  JSON Schema** (`openapi_subset()`; `additionalProperties` is a 400). Settings are
  `ANTHROPIC_MODEL`, `GROQ_MODEL`, `GEMINI_MODEL`; the old `LLM_MODEL` is gone.
  → [D-57](docs/decisions.md#d-57--a-second-provider-and-why-a-weaker-model-is-a-quality-question-not-a-correctness-one),
  [D-58](docs/decisions.md#d-58--a-third-provider-and-the-two-defects-a-real-model-found)
- **The evidence brief carries the value twice**, raw and rendered, because grounding checks two
  spellings. It carried only the rendering until Phase 9, which made the system prompt
  self-contradictory and every real model's explanation malformed.
- **The permitted-literal set includes the window's *year*, and masking is digit-bounded.**
  "fell in July 2026" failed check 1 otherwise. Digit-bounded because blanking `2026` inside
  `20261` leaves `1` -- a wrong count grounding as a right one.
- **`task.py` grew argument pass-through** for `ask`, checked before the unknown-target scan so
  a question is not read as a list of targets.

### Notes from Phase 7 worth not rediscovering

- **The template renderer is a package below `llm`, not a module inside it.** A fallback that
  could call a model fails at the one moment it exists for. `narrative/` is in contract 1 and
  below `llm` in contract 2.
  → [D-50](docs/decisions.md#d-50--the-template-renderer-sits-below-the-model-boundary-not-beside-it)
- **Check 3 is two checks.** The declared value must byte-match the row, *and* the prose must
  write it. A model that declares `0.958012` and writes `95.8%` passes the first and fails the
  second, and only the second reaches a reader.
- **`agent_executions` had `response_source` and no column for the answer** since 0001.
  Migration 0004 adds `answer_text` + `claims_json` with a bidirectional constraint.
  → [D-49](docs/decisions.md#d-49--the-answer-gets-a-column-and-prose-is-tied-to-its-origin)
- **Digits in prose that are not claims:** only the execution's own windows and the merchant
  id, masked before tokenising, derived from the evidence rather than passed in. This is also
  why template lines are labelled from the metric id and not from the vocabulary descriptions,
  which cite corrections by number (`rules 1-4`, `(D-20)`).
- **The unsigned magnitude is accepted for a signed value.** English puts the sign in the verb,
  and no byte-match can catch "revenue rose by -17.6%" anyway.
  → [D-48](docs/decisions.md#d-48--grounding-checks-magnitude-and-unit-the-direction-word-goes-unchecked)
- **`EVENT_KINDS` is a closed list and it caught the new event.** Adding
  `explanation.grounded` was a required edit, not an optional one -- which is the point of the
  registry.
- **Scripted providers refuse the explanation call** (`ask.py`, `test_agent_db.py`): scripting a
  grounded answer over 123 real evidence rows would mean writing the explainer in the test.
  Refusing exercises the template path, which is what a deployment with no key does anyway.

### Notes from Phase 8 worth not rediscovering

- **Subscribe to the broadcaster BEFORE reading the log.** Read-then-subscribe loses whatever
  is written in between and the gap is undetectable; subscribe-then-read only duplicates, and
  a duplicate is detectable by `seq`.
  → [D-51](docs/decisions.md#d-51--the-event-stream-subscribes-before-it-replays-and-deduplicates-on-seq)
- **httpx's `ASGITransport` buffers the whole response.** It runs the app to completion and
  hands back the collected body, so nothing measured through it can tell a streaming endpoint
  from a buffering one. The progressive test drives `event_frames` directly.
- **The stream does not poll `request.is_disconnected()`.** The ASGI server cancels the
  generator on disconnect, earlier and more reliably; and under `ASGITransport` the check
  returns true immediately and kills the stream.
- **`open_execution` inserts `PENDING` and the route calls it before returning 202.** The
  runtime takes `reserved=True` to continue rather than open. Two inserts of one primary key
  is a crash; skipping the insert unconditionally leaves every other caller rowless.
- **Auth is deliberately half-built and says so** in three places. The membership check is
  real; the header's authenticity is not proven until the JWT.
  → [D-52](docs/decisions.md#d-52--identity-is-a-header-until-the-jwt-lands-and-the-merchant-is-checked-either-way)
- **`task.py openapi` regenerates `openapi.json` AND `api.ts`;** `check` diffs both. The TS
  generator raises on an unknown schema shape rather than emitting `any`.
  → [D-53](docs/decisions.md#d-53--the-typescript-contract-is-generated-and-both-halves-are-diffed-in-ci)

### Notes from Phase 9 worth not rediscovering

- **Blade forces React 18.** `@razorpay/blade` needs `styled-components@^5`, which does not
  support React 19, so the web app is Next 14.2 + React 18.3 and `next.config` is `.mjs`
  (Next 14 does not load a `.ts` config).
  → [D-55](docs/decisions.md#d-55--the-web-app-is-pinned-to-react-18-because-blade-is)
- **Install web deps with `--legacy-peer-deps`.** Blade declares its React Native peers as
  required rather than optional; without the flag npm installs react-native into a web app.
  `task.py webinstall` does it.
- **Blade components take `testID`, not `data-testid`.** Arbitrary `data-*` props are dropped
  by `Box`. Status is asserted through visible text (the badge, the spinner accessibility
  label), which is the better assertion anyway.
- **Blade's `Box` will not render as a `button`.** `components/Clickable.tsx` is a real button
  with its appearance stripped; everything inside it is still Blade.
- **styled-components v5 needs `app/registry.tsx`** to get its stylesheet into the streamed
  HTML, or the page flashes unstyled.
- **httpx-style buffering has a browser twin:** the stream is read with `fetch` + a reader
  rather than `EventSource`, because `EventSource` reconnects when the server closes a
  finished stream (replaying forever) and cannot send the caller header.
- **The API serves a `display` string for every metric value**, so the web app formats no
  money. The drift this prevents is not the grouping -- `Intl` gets that right -- it is a
  scale-6 ratio rounded to three fraction digits.
  → [D-54](docs/decisions.md#d-54--the-api-serves-the-rendered-figure-the-web-app-formats-nothing)
- **The dashboard reads evidence, not `reconciliation_runs`**, because only evidence rows
  carry an id a tile can open.
  → [D-56](docs/decisions.md#d-56--the-dashboard-is-built-on-evidence-not-on-the-reconciliation-table)
- **CORS had to be added** for the browser to reach the API, with `Last-Event-ID` in the
  allowed headers -- without it a dropped SSE stream cannot resume, because the preflight
  refuses the header the browser sends itself.
