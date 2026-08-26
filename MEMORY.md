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
| 1 — Data plane & golden fixture | in progress |
| 2–12 | not started |

### Notes from Phase 0 worth not rediscovering

- `python -m importlinter.cli` exits **0 having evaluated nothing** — no `__main__` guard. Use the
  `lint-imports` console script. The planted-violation test is what caught this.
- `main` cannot be an import-linter root package (it is a module, not a package).
- `bool` is an `int` to mypy, so `apply_rate(True, ...)` type-checks. Only the runtime check
  catches it. Same reason the money guard is a textual scan rather than a type check.
- Python is pinned to **3.13** in two places that must agree: `requires-python` in
  `pyproject.toml` and the base image in `apps/api/Dockerfile`. The image is the one that decides.
  → [D-17](docs/decisions.md#d-17--python-is-pinned-to-313-not-312)
