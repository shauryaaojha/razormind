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

## Golden numbers

Every headline figure is asserted against the seeded fixture. If any of these change, the fixture
drifted and something downstream is wrong *and green*.

| | Prior (Jul 1–23) | Current (Aug 1–23) |
| --- | ---: | ---: |
| Attempted value | ₹53,30,000 | ₹47,42,000 |
| Blended success rate | 96.81% | 90.32% |
| Gross successful | ₹51,60,000 | ₹42,83,200 |
| Refunds | ₹1,00,000 | ₹1,24,000 |
| Fees @ 1.00% | ₹51,600 | ₹42,832 |
| Chargebacks | ₹11,000 | ₹18,500 |
| **Net revenue** | **₹49,97,400** | **₹40,97,868** |

Decline **−₹8,99,532 = exactly −18.00%**, and the attribution closes with **zero residual**.
Reconciliation: **342 / 341 / 338 / 327 / 15 / 95.61%**, ₹18,400 unresolved across 3 records.

Full detail: [`docs/08-seed-data.md`](docs/08-seed-data.md).

---

## Phase status

| Phase | State |
| --- | --- |
| 0 — Foundations | **Done.** `check` green: ruff, mypy strict, 3 import contracts, money guard, 100% branch coverage on `runtime/` |
| 1 — Data plane & golden fixture | **Done.** 13 tables + RLS, seed generator, 4 checksummed artifacts, 7 fixture assertions, 91 + 12 tests |
| 2 — Reconciliation engine | **Done.** 5 rules, greedy one-to-one, shuffle test, 3 read endpoints, 111 + 23 tests |
| 3 — Tool framework & revenue | next |
| 4–12 | not started |

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
  Every amount is a whole number of rupees, which is what makes the 1.00% fee exact.
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
- The Phase 2 orchestration lives in `scripts/reconcile.py`, not in `reconciliation/`: that
  package may not import `verification/`, because the engine must not be able to decide whether
  its own output is trustworthy. Phase 3 moves it behind the tool contract.
- **Auth is a stated gap until Phase 8.** The read endpoints connect as the owner role, which is
  exempt from RLS. The policies are proven by `tests/test_rls.py` as the non-owner role, but
  `merchant_id` currently selects rather than enforces. Documented in `routes/__init__.py`.
