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
 1  Data plane          schema, seed generator, golden fixture      <- do not skip
 2  Reconciliation      matcher, exceptions, invariants
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
| `task.py check` | The full gate, in CI's order. Phase 0's exit criterion |
| `task.py lint` / `fmt` | ruff |
| `task.py types` | mypy --strict |
| `task.py boundaries` | import-linter — the trust boundary |
| `task.py nofloat` | the C-01 money guard |
| `task.py test` | pytest, with 100% branch coverage required on `runtime/` |
| `task.py dev` / `web` / `psql` | containers, foreground |

---

## Status

**Phase 0 — Foundations: complete.** `check` is green: ruff, mypy `--strict`, three import-linter
contracts, the no-float guard, and 57 tests with 100% branch coverage on `runtime/money.py` and
`runtime/calendar.py`.

The three boundary mechanisms exist before any domain logic does, which is the point of the phase:

- `tools/`, `runtime/`, `verification/`, `evidence/` and `provenance/` cannot import `llm/` or a
  vendor SDK. `tests/test_boundaries.py` plants a violating import, runs the linter for real, and
  asserts the build fails — asserting that a contract *passes* would also pass with a typo in it.
- `scripts/check_no_float.py` rejects a `float`-typed `_paise` field, a division on a `_paise`
  value, and any `round()` outside `runtime/money.py`.
- `runtime/money.py` rejects a `float` rate at runtime, and `bool` as an amount — `bool` is an
  `int` to the type checker, so only the runtime check catches it.

**Next: Phase 1 — data plane and golden fixture.** Migrations, `generate_seed_data.py`,
`checksums.json`, and the seven fixture assertions. Nothing downstream can be trusted until the
fixture is provably the one the docs describe.

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
