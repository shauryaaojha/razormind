# RazorMind

**Agentic Financial Computation & Reconciliation Platform**

> LLMs decide what needs to be computed. Deterministic systems compute it. Verification
> establishes what can be trusted. The LLM explains only verified results.

RazorMind turns a natural-language finance question into a validated execution plan, runs
deterministic tools over reconciled transaction and settlement data, verifies every number,
traces it back to source records, and only then lets a model put it into words.

The model never produces a financial number. That boundary is enforced by an import contract, a
formula re-evaluation step, and a grounding check that byte-matches every number in the prose
against a verified metric.

---

## Documentation

| Doc | What's in it |
| --- | --- |
| [00-corrections.md](docs/00-corrections.md) | **Read first.** Defects found in the original spec and the correction adopted for each |
| [01-architecture.md](docs/01-architecture.md) | Planes, request lifecycle, boundary enforcement, repo layout |
| [02-data-model.md](docs/02-data-model.md) | Money, time, tables, authz |
| [03-reconciliation.md](docs/03-reconciliation.md) | Matching rules, assignment, exceptions, invariants |
| [04-tool-contract.md](docs/04-tool-contract.md) | The deterministic tool ABC, registry, tool set |
| [05-agent-runtime.md](docs/05-agent-runtime.md) | Intent, planning, validation, execution, state machine, recovery |
| [06-trust-layer.md](docs/06-trust-layer.md) | Verification, evidence, provenance, grounding |
| [07-api.md](docs/07-api.md) | Endpoints, SSE events, error shape |
| [08-seed-data.md](docs/08-seed-data.md) | The seeded dataset and the golden story |
| [09-testing-and-eval.md](docs/09-testing-and-eval.md) | Test levels, the tests that matter, eval targets |
| [10-build-phases.md](docs/10-build-phases.md) | **The build plan.** 13 phases with exit criteria |
| [11-demo-script.md](docs/11-demo-script.md) | Five-minute demo, beat by beat |
| [12-tech-stack.md](docs/12-tech-stack.md) | Every stack choice, its reasoning, and what was excluded |
| [decisions.md](docs/decisions.md) | Architectural decisions with reasoning and reversal cost |
| [file.md](file.md) | The original vision document (corrections applied inline) |

---

## Build order

Phases 0–5 contain **no LLM at all**. The deterministic core has to be correct and provable
before anything non-deterministic touches it.

```text
 0  Foundations         scaffold, money/calendar primitives, CI boundary gates  [DONE]
 1  Data plane          schema, seed generator, golden fixture      [DONE]
 2  Reconciliation      matcher, exceptions, invariants             [DONE]
 3  Tool framework      the contract + revenue analysis
 4  Remaining tools     failure, refund, chargeback
 5  Trust layer         verification, evidence, provenance
------------------------------------------------------------------  first LLM call
 6  Agent runtime       intent, plan, validate, execute, state
 7  Explainer           grounding, template fallback
 8  API surface         SSE streaming, OpenAPI contract
 9  Web application     chat, dashboard, exceptions, provenance
10  Failure & recovery  fault injection, graceful degradation
11  Evaluation          intent/tool/computation/grounding accuracy
12  Deployment & demo
```

Full detail, exit criteria and "do not build yet" lists: [10-build-phases.md](docs/10-build-phases.md).

---

## The golden story

Every headline number is asserted against a checksummed synthetic dataset
([08-seed-data.md](docs/08-seed-data.md)).

| | Prior (Jul 1–23) | Current (Aug 1–23) |
| --- | ---: | ---: |
| Gross successful | ₹51,60,000 | ₹42,83,200 |
| Refunds | ₹1,00,000 | ₹1,24,000 |
| Fees @ 1.00% | ₹51,600 | ₹42,832 |
| Chargebacks | ₹11,000 | ₹18,500 |
| **Net revenue** | **₹49,97,400** | **₹40,97,868** |

Decline ₹8,99,532 = **exactly −18.00%**, fully attributed:

```text
Attempt-volume decline (-11.03%)   -Rs 5,69,246   63.3%
Payment success rate (-6.49 pp)    -Rs 3,07,554   34.2%
Refund increase                       -Rs 24,000    2.7%
Chargeback increase                    -Rs 7,500    0.8%
Fee decrease (offset)                  +Rs 8,768   -1.0%
Rounding residual                          Rs 0     0.0%
-------------------------------------------------------
Total                              -Rs 8,99,532  100.0%
```

Reconciliation over the same window: 342 ledger / 341 bank records, 338 pairs, 327 clean,
15 exceptions, **95.61%** clean match rate, ₹18,400 unresolved across 3 records — reported as a
±0.45% confidence band, never folded into the bridge.

---

## Stack

| Layer | Choice | Host |
| --- | --- | --- |
| Web | Next.js (App Router) · React · TypeScript · Tailwind · shadcn/ui | Vercel |
| API | Python 3.13 · FastAPI · Pydantic v2 · asyncio | Railway / Render |
| Data | PostgreSQL 16 + Auth via Supabase, with row-level security | Supabase |
| LLM | Provider abstraction; Claude (`claude-opus-5`) as the default | Anthropic API |
| Contract | OpenAPI generated from FastAPI → typed TS client | CI gate |

Two choices carry more weight than the rest:

- **`import-linter` is part of the stack, not the tooling.** A CI contract stops `tools/`,
  `verification/`, `evidence/` and `provenance/` from importing `llm/`. Invariant 1 is only worth
  something if it is mechanically enforced.
- **No LangChain, no RAG, no task queue.** The LLM makes two narrow calls — parse an intent,
  phrase verified numbers. A framework that abstracts planning, tool calling and output parsing
  into one layer would hide the exact boundary this project exists to make visible.

Redis is deliberately excluded until the API needs a second worker
([D-12](docs/decisions.md#d-12--single-uvicorn-worker-redis-deferred)). Full reasoning for every
choice, and what was excluded, in [12-tech-stack.md](docs/12-tech-stack.md).

---

## Running it

Every dependency is installed **inside a container** — no virtualenv, no global `pip`, no global
`npm` ([D-16](docs/decisions.md#d-16--every-dependency-is-installed-inside-a-container)). All you
need on the host is Docker.

```bash
docker compose build              # the only place anything downloads
python scripts/task.py check      # lint · types · boundaries · money guard · tests
docker compose up db api web      # http://localhost:8000/health  ·  http://localhost:3000
```

`scripts/task.py` is the single implementation of every command; run from the host it re-invokes
itself inside the `tools` container, so `make check`, `python scripts/task.py check` and
`docker compose run --rm tools scripts/task.py check` are the same command. CI runs the same
image, which is why "works on my machine" and "passes CI" are not separate claims here.

| Command | What it does |
| --- | --- |
| `task.py check` | The full gate, in CI's order |
| `task.py lint` / `fmt` | ruff |
| `task.py types` | mypy --strict |
| `task.py boundaries` | import-linter — the trust boundary |
| `task.py nofloat` | the C-01 money guard |
| `task.py seed` | regenerate the fixture, expectations and checksums |
| `task.py verify-seed` | the seven fixture assertions |
| `task.py migrate` / `loadseed` | Alembic, then load `seed.sql` |
| `task.py reconcile` | reconcile the golden window and persist the run |
| `task.py test` | pytest, 100% branch coverage required on `runtime/` |
| `task.py dbtest` | row-level security, against a real Postgres |
| `task.py dev` / `web` / `psql` | containers, foreground |

---

## Status

**Phases 0, 1 and 2 complete.** `check` is green: ruff, mypy `--strict`, three import-linter
contracts, the no-float guard, the seven fixture assertions, and 111 tests with 100% branch
coverage on `runtime/money.py` and `runtime/calendar.py`. A further 23 integration tests run
against a real Postgres.

The three boundary mechanisms exist before any domain logic does, which is the point of the phase:

- `tools/`, `runtime/`, `verification/`, `evidence/` and `provenance/` cannot import `llm/` or a
  vendor SDK. `tests/test_boundaries.py` plants a violating import, runs the linter for real, and
  asserts the build fails — asserting that a contract *passes* would also pass with a typo in it.
- `scripts/check_no_float.py` rejects a `float`-typed `_paise` field, a division on a `_paise`
  value, and any `round()` outside `runtime/money.py`.
- `runtime/money.py` rejects a `float` rate at runtime, and `bool` as an amount — `bool` is an
  `int` to the type checker, so only the runtime check catches it.

Phase 1 added the data plane. Thirteen tables with the one-to-one match constraint and the
half-open period constraint enforced by the database rather than by the matcher; a seeded
generator whose totals are exact **by construction** — apportioned out of a fixed total by
largest remainder, in whole rupees so the 1.00% fee is exact — and four checksummed artifacts
that regenerate byte-identically. Row-level security is proven the only way it can be: a user
belonging to another merchant runs `SELECT count(*) FROM transactions` with no filter at all and
gets zero.

Phase 2 built the reconciliation engine. Five rules in strict priority order, greedy one-to-one
assignment with a five-key tie-break that is *total* — so no two candidate pairs can compare
equal and the result cannot depend on the sort algorithm or on the order rows arrived in. The
shuffle test reconciles the same records in twenty random orders and demands byte-identical
output. `SETTLEMENT_91` is found, scored at 0.72, and deliberately not taken; it is recorded as a
rejected candidate, which is the difference between a 95.61% match rate that can be defended and
a 99% one that cannot.

Half the design is delegated to the database and tested there: the one-to-one guarantee is a
unique constraint, the 0.85 auto-match threshold is a `CHECK`, and I1–I3 are `CHECK`s on the run
row. Each has a test that violates it on purpose — a constraint nobody has tried to break is a
constraint nobody has checked exists.

**Next: Phase 3 — the tool contract and revenue analysis.** The deterministic tool ABC, the
registry, the revenue bridge, and the restricted arithmetic interpreter.

---

## Engineering invariants

Violating any of these is a bug with a test name, not a quality discussion.

1. The LLM never produces an authoritative financial number.
2. Every authoritative number has provenance down to source records.
3. Every execution plan is validated before execution.
4. Verification failure blocks downstream explanation entirely — no prose, no partial numbers.
5. Exceptions are surfaced, never silently discarded.
6. Incomplete data yields an explicit limitation, never an invented, estimated or zero value.
7. Every agent execution is traceable through an execution id and an append-only event log.
8. Every tool follows the same deterministic contract.

---

## What this is not

Not a chatbot over finance data. Not a dashboard with an LLM bolted on. Not a live Razorpay
integration. Not a system where a generated number becomes authoritative.

> **AI controls the investigation. Deterministic systems control the numbers. Evidence controls
> trust.**
