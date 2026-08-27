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
| 3 — Tool framework & revenue | **Done.** `DeterministicTool` ABC + registry, `finance.reconciliation`, `finance.revenue_analysis`, restricted formula interpreter. 225 + 46 tests |
| 4 — Remaining tools | next |
| 5–12 | not started |

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
