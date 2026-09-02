# 12 — Tech Stack

Every choice here is justified against one constraint: **a solo build that must stay provably
deterministic**. Where a more capable option exists, the note says why it was not taken.

Exact version pins are a Phase 0 deliverable ([10-build-phases.md](10-build-phases.md#phase-0--foundations)) —
this document fixes the *choices*, and `pyproject.toml` / `package.json` fix the *versions*.

---

## At a glance

| Layer | Choice | Host |
| --- | --- | --- |
| Web | Next.js (App Router) · React 18 · TypeScript · **Blade** (`@razorpay/blade`) | Vercel |
| API | Python 3.13 · FastAPI · Pydantic v2 · asyncio | Railway or Render |
| Database | PostgreSQL 16 via Supabase, with row-level security | Supabase |
| Auth | Supabase Auth (JWT) | Supabase |
| LLM | Provider abstraction. Three implementations: Claude, open-weight models on Groq, Gemini | Anthropic · Groq · Google AI Studio |
| Contract | OpenAPI generated from FastAPI → typed TS client | CI |
| CI | GitHub Actions, running the same container image as local | — |
| Toolchain | Docker Compose. Nothing is installed on the host | — |

---

## Backend

### Python 3.13

Pinned to a **minor** version, not just major. Two reasons specific to this project:

- `random.Random` stream semantics are stable within a minor release. The seeded fixture's
  checksums ([08-seed-data.md](08-seed-data.md)) would drift across minor versions, and that
  drift would make every downstream test wrong *and green*.
- `zoneinfo` ships in the standard library, so the IST business calendar needs no third-party
  timezone package.

3.13 specifically, and the pin lives in two places that must agree: `requires-python` in
`pyproject.toml` and the `python:3.13-slim` base image in `apps/api/Dockerfile`. The image is the
one that actually decides ([D-16](decisions.md#d-16--every-dependency-is-installed-inside-a-container)) —
a pin in `pyproject.toml` is a declaration, a pinned base image is an enforcement.

### FastAPI + Pydantic v2

Pydantic is doing real work here, not just request parsing. It is the enforcement point for:

- Tool input/output schemas ([04-tool-contract.md](04-tool-contract.md))
- The `_paise` = `int` invariant, checked by walking `model_fields` at test time
- OpenAPI generation, which becomes the web client's contract

Pydantic **v2** matters: v1's `Decimal` handling and JSON serialization are looser, and this
project serializes ratios as strings deliberately
([D-02](decisions.md#d-02--ratios-serialize-as-json-strings)).

FastAPI gives native async (needed for concurrent tool nodes), SSE via `StreamingResponse`, and
dependency injection for the RLS-scoped database session.

### asyncio, no task queue

Tool nodes run concurrently with `asyncio.gather` per topological layer
([05-agent-runtime.md](05-agent-runtime.md#execution)). No Celery, no ARQ, no Redis.

The cost: the API is pinned to a **single uvicorn worker**, because SSE subscribers and the
asyncio task running an execution share process memory
([D-12](decisions.md#d-12--single-uvicorn-worker-redis-deferred)). This is documented in the
deploy config, not discovered in production.

**Trigger to revisit:** the first time we need a second worker, or executions must survive a
restart. `execution_events` is already the durable log, so the change is Redis pub/sub for
fan-out and nothing else.

### Key libraries

| Library | Role | Why this one |
| --- | --- | --- |
| `pydantic` v2 | Schemas, validation, serialization | See above |
| `sqlalchemy` 2.x (Core) | Query building, migrations via Alembic | Core, not the ORM — reconciliation needs explicit `ORDER BY` with unique tiebreakers for determinism, and an ORM's identity map obscures that |
| `alembic` | Migrations | Standard with SQLAlchemy |
| `asyncpg` | Postgres driver | Async, and passes the caller's JWT for RLS |
| `anthropic` | LLM provider (default impl) | Official SDK; see below |
| `httpx` | HTTP client | Async. Also *is* the Groq provider — see below |
| `uvicorn` | ASGI server | Single worker, see above |

### Tooling

| Tool | Role |
| --- | --- |
| `ruff` | Lint + format. One tool, no black/isort/flake8 stack |
| `mypy --strict` | Type checking. Strict from day one — retrofitting is far more expensive |
| `pytest` + `pytest-asyncio` | Tests |
| `import-linter` | **Enforces the trust boundary.** `tools/`, `verification/`, `evidence/`, `provenance/`, `runtime/` may not import `llm/` |
| `testcontainers` | Real Postgres in integration tests, so RLS policies are actually exercised |

`import-linter` is not optional tooling — it is the mechanical proof behind Invariant 1. A
convention that the LLM never touches arithmetic is worth nothing; a CI contract that fails the
build is worth something. See [09-testing-and-eval.md](09-testing-and-eval.md#boundary-phase-0).

---

## Data

### PostgreSQL 16 via Supabase

Supabase is chosen to collapse three services into one for a solo build: Postgres, auth, and
row-level security tied to the same JWT.

Postgres features this design actually depends on:

| Feature | Used for |
| --- | --- |
| `BIGINT` | Paise. Max ~₹92 quadrillion — no overflow concern |
| `NUMERIC` | Ratios at fixed scale. Never `DOUBLE PRECISION` anywhere |
| `TIMESTAMPTZ` | UTC storage; IST derived in application code |
| Row-level security | Merchant scoping that survives an application bug |
| Partial indexes | The UTR indexes that make matching rule 1 fast |
| Unique constraints | The one-to-one match guarantee ([C-07](00-corrections.md#c-07-b--matching-has-no-assignment-rule-so-it-is-not-reproducible)) |
| `JSONB` | `detail_json`, `formula_json`, `error_json` |

**RLS is load-bearing.** The API forwards the caller's Supabase JWT to Postgres instead of using
the service key on read paths, so a scoping bug in application code still cannot return another
tenant's rows ([D-09](decisions.md#d-09--merchant_id-comes-from-the-session-never-the-model)).

### Local development

`docker-compose.yml` runs plain Postgres 16 locally. Supabase-specific SQL is limited to the RLS
policies and the `auth.uid()` call, both of which are shimmed locally. This keeps the test suite
runnable offline and keeps a Supabase outage from blocking development.

**Everything runs in a container** ([D-16](decisions.md#d-16--every-dependency-is-installed-inside-a-container)).
There is no host virtualenv and no host `npm install`. `scripts/task.py` is the single
implementation of every command and delegates itself into the `tools` service when run from the
host, so these are the same thing:

```text
make check
python scripts/task.py check
docker compose run --rm tools scripts/task.py check
```

| Service | Image | Purpose |
| --- | --- | --- |
| `db` | `postgres:16` | Local database, health-gated |
| `api` | built from `apps/api/Dockerfile` | Uvicorn, single worker, repo bind-mounted |
| `tools` | same image, no server | lint · types · boundaries · money guard · tests |
| `web` | `node:22-slim` | `npm install && next dev` inside the container |

---

## LLM layer

The LLM is used for exactly **two** things: parsing a question into a structured intent, and
phrasing verified numbers. It never computes.

### Provider abstraction

The vision doc requires no architectural dependency on one provider (§29). The abstraction is
deliberately narrow — two methods, because that is all the platform needs:

```python
class LLMProvider(Protocol):
    name: str

    async def structured(
        self, *, system: str, prompt: str, schema: Mapping[str, Any],
        max_tokens: int, timeout_seconds: int,
    ) -> Completion: ...
```

Phase 6 narrowed this from the two methods planned here to **one**. The second method was
`explain`, returning prose — and prose is exactly the shape the trust layer cannot check. The
explainer asks for the same schema-constrained structured call as the intent parser and gets back
claims it can byte-match against verified rows
([06-trust-layer.md](06-trust-layer.md#grounding)). One method also means a new provider is one
method to implement and one place to get wrong.

A narrow interface is the point. A provider-agnostic wrapper that exposes every vendor feature
ends up leaking the vendor anyway.

`llm/` is the only package permitted to reach a model vendor, enforced by `import-linter`.

### Default implementation: Claude

| Setting | Value | Reason |
| --- | --- | --- |
| Model | `claude-opus-5` | Default for both calls. 1M context, $5/$25 per MTok |
| SDK | `anthropic` (official Python) | The vendor's own client, not a compatibility shim |
| Structured output | `output_config={"format": {...}}`, or `client.messages.parse()` | Schema-constrained intent extraction. Not prompt-and-hope JSON parsing |
| Thinking | `thinking={"type": "adaptive"}` | Current API. `budget_tokens` is removed on this model and returns 400 |
| Effort | `output_config={"effort": "low"}` for intent, `"medium"` for explanation | Both tasks are small and well-specified; neither needs deep reasoning |
| Prompt caching | `cache_control` on the system prompt + tool/metric vocabulary | The system prompt is large and byte-stable; the question is not. Put volatile content last |
| Streaming | On for the explainer | Feeds the SSE `token` events |
| Prefill | **Not used** | Assistant prefill returns 400 on current models. Format is controlled by `output_config`, not by prefilling |

Two notes for whoever implements Phase 6:

- **Verify caching actually happens.** Check `usage.cache_read_input_tokens` is non-zero across
  repeated requests. A timestamp or a per-request id in the system prompt silently invalidates
  the whole prefix.
- **Parse tool/structured inputs with `json.loads`**, never string matching — JSON string
  escaping varies between models.

### Second implementation: Groq

`LLM_PROVIDER=groq` runs the same two calls against open-weight models on Groq's free tier.

| Setting | Value | Reason |
| --- | --- | --- |
| Model | `openai/gpt-oss-120b` | The largest free model that accepts a forced tool call. Groq's catalogue moves — the Llama models were on it and are not any more — so `GET /openai/v1/models` on your own key is the authority, not this table. `groq/compound*` rejects tool calling outright |
| Client | `httpx` against `https://api.groq.com/openai/v1` | Already a dependency. Adding the `groq` SDK for one POST would put a second vendor SDK in a tree whose boundary contract polices exactly that |
| Structured output | `tools` + `tool_choice: {"type": "function", "function": {"name": "emit"}}` | The same forced tool call, in OpenAI's spelling |
| Arguments | A JSON **string**, unlike Anthropic's object | Parsed inside the provider, so "the model did not emit JSON" is a `PROVIDER_UNAVAILABLE`, not a schema mismatch three frames later |
| Temperature | `0` | Groq rewrites it to `1e-8` rather than rejecting it. As with Anthropic, nothing downstream depends on the run being reproducible |

**The free tier does not fit the explanation call.** Every free model on Groq is capped at 8,000
tokens per minute. Intent parsing is about 1,000 tokens and fits comfortably; the explainer carries
the whole evidence brief, which for a five-tool revenue diagnosis is ~8,700 tokens — evidence ids
and rendered rupee figures tokenise at roughly 2.5 characters per token, so the brief is denser
than its character count suggests. It does not fit at any output budget, because the cap is on
input. The result is that on the free tier **the model parses the question and the template renders
the answer**: exactly the degradation Phase 7 was built for, reached for a boring reason. The
fallback reason in `execution_events` carries the provider's message, so a rate limit is
distinguishable from a missing key.

The provider is **named**, never inferred from whichever key happens to be set. Two keys in one
environment would otherwise pick a model by accident, and "which model answered this" is a
question a finance audit is entitled to a firm answer to
([D-57](decisions.md#d-57--a-second-provider-and-why-a-weaker-model-is-a-quality-question-not-a-correctness-one)).

### Third implementation: Gemini

`LLM_PROVIDER=gemini` runs both calls against Google AI Studio's free tier. This is the free path
that reaches `response_source = LLM` rather than the template.

| Setting | Value | Reason |
| --- | --- | --- |
| Model | `gemini-flash-lite-latest` | `gemini-flash-latest` writes better and, on the free tier, answers 503 roughly three times in four and spends its thinking budget before emitting the forced call. A model that returns an answer beats a better model that returns a capacity error |
| Client | `httpx` against `generativelanguage.googleapis.com/v1beta` | Same reason as Groq: one POST, no second vendor SDK |
| Structured output | `functionDeclarations` + `toolConfig.functionCallingConfig.mode = ANY` with one allowed name | Gemini's spelling of a forced call |
| Schema | Translated — see below | Gemini takes OpenAPI 3.0's Schema object, **not** JSON Schema |
| Context | ~1M tokens | The 8,700-token evidence brief is not a consideration here, which is the whole reason this provider exists |
| Transient errors | One retry on 429/503, 1.5s apart | 503 under load clears; a missing key does not |

**The schema has to be translated.** Gemini rejects the request outright on any keyword outside
OpenAPI 3.0's Schema object — and `additionalProperties`, which pydantic emits for every
`extra="forbid"` model, is a 400. `openapi_subset()` collapses `anyOf: [X, null]` to `X` with
`nullable: true`, and drops everything outside an allowlist. Allowlist rather than denylist,
because an unrecognised keyword passed through is a 400 that only appears in production, and the
set of keywords pydantic emits grows whenever somebody adds a field. Dropping a constraint is safe
in the direction that matters: the schema *guides* generation, the pydantic model *validates* the
result.

**The retry lives in the provider, not the explainer.** The explainer skips its own retry on a
provider failure because "a missing model does not become present on a second call" — true of a
missing key, false of a 503 under load. Only the layer that can see the status code can tell them
apart.

### Cost

Both calls are small: intent parsing is a few hundred tokens in and under a hundred out; the
explainer receives verified metrics and evidence, not raw records. At Opus 5 rates a full agent
run is fractions of a cent. On Groq's free tier it is nothing, and the trade is quality rather
than correctness: a weaker model produces a low-confidence intent (which asks instead of assuming)
or an ungrounded explanation (which is discarded for the template) more often. It cannot produce a
wrong number, because it is never asked for one.

On Gemini's free tier both calls run and the answer is written by the model, grounded, at
`response_source = LLM`.

Swapping the model *or the vendor* is a config change, not a code change. That is the abstraction
earning its keep.

### Failure is a first-class path

The provider layer has an explicit disabled mode used by tests and the demo. With the LLM
unavailable the run still reaches `COMPLETED` via the deterministic template
([06-trust-layer.md](06-trust-layer.md#grounding)). Timeouts are 30s for intent, 60s for
explanation, both counted as tool-style failures rather than exceptions.

---

## Frontend

### Next.js (App Router) + React 18 + TypeScript

Client components throughout: every surface here is stateful or streaming — the chat trace, the
provenance drawer, the dashboard's inspectable tiles — and a server component that has to hand its
data to a client one immediately is a round trip nobody spends.

**React 18, not 19**, because Blade is built on styled-components v5 and v5 does not support React
19. The design system picks the React version, which is the right direction for that dependency to
run ([D-55](decisions.md#d-55--the-web-app-is-pinned-to-react-18-because-blade-is)). Next 14
follows from React 18, and `next.config` is therefore `.mjs` rather than `.ts`.

TypeScript is `strict` with `noUncheckedIndexedAccess`. The API types are **generated** from the
committed `packages/shared-types/openapi.json` and imported, never hand-written — `task.py check`
fails if the regenerated contract differs from the committed one, so the web app cannot drift from
the API ([D-53](decisions.md#d-53--the-typescript-contract-is-generated-and-both-halves-are-diffed-in-ci)).

### Blade — Razorpay's design system

> Supersedes the original Tailwind + shadcn/ui choice. shadcn was picked for a UI with unusual
> surfaces that a component library "would fight", which turned out to be exactly backwards:
> Blade has `Drawer`, `Card`, `Badge`, `Alert`, `EmptyState` and `Spinner`, and the two genuinely
> unusual surfaces — the recursive evidence renderer and the execution trace — are compositions of
> those, not fights with them.

Nothing in `apps/web` defines a colour, a radius, a font size or a spacing value of its own. The
one exception is `components/Clickable.tsx`, a `<button>` stripped of its own appearance: Blade's
`Box` deliberately will not become a button, and a container that could silently be interactive is
how a div ends up with a click handler and no keyboard access. Everything inside it is still Blade.

Styled-components v5 generates its CSS at render time, so the server stylesheet is collected
explicitly in `app/registry.tsx`. Without it the server sends correct markup with no styles and the
page flashes unstyled — on a page of financial figures, a layout that jumps after paint reads as
numbers that are still loading.

### Money and ratio rendering

**There is none in the web app.** Every value the API returns for a metric carries a `display`
string beside it, written by `narrative/render.py` — the same module the grounding gate
byte-matches prose against ([D-54](decisions.md#d-54--the-api-serves-the-rendered-figure-the-web-app-formats-nothing)).

> Supersedes the original `lib/format.ts`. One module owning every conversion was the right
> instinct and the wrong side of the wire. The server already has that module and it is
> load-bearing: a TypeScript copy would be a second answer to "what does this number look like",
> and the two would disagree the first time either was edited. The drift would not even show up on
> the obvious case — `Intl.NumberFormat("en-IN")` groups Indian digits correctly — it would show up
> on a scale-6 ratio, where the browser rounds to three fraction digits and prints `95.801%` for a
> figure the server refuses to let a model call `95.80%`.

The Indian grouping is a real requirement, not cosmetic — `3,90,122` and `390,122` are the same
value written two ways, and a finance user reads the first one faster.

### Streaming

Native `EventSource` against `GET /agent/runs/{id}/events`, with `Last-Event-ID` for resume.
Because the endpoint replays from `execution_events` before streaming live, the history page and
the live chat use the same component — asserted by a test, not by inspection.

---

## Deployment

```text
Vercel        web            preview per PR
Railway       api            single worker, pinned; Docker from apps/api
Supabase      db + auth      migrations via Alembic in the deploy step
GitHub Actions CI            lint -> types -> import-linter -> tests -> verify-seed -> openapi diff
```

Environment variables are documented in `.env.example` and never committed with values. The
service-role Supabase key is used **only** by the seeding job, never by the request path.

---

## Deliberately excluded

| Not used | Why | When to revisit |
| --- | --- | --- |
| Redis | Vision §29 defers it; single worker suffices | Second API worker, or executions must survive restart |
| Celery / ARQ | asyncio covers a 120s worst-case run | Runs exceed a couple of minutes, or need retry semantics |
| An ORM (SQLAlchemy ORM layer) | Determinism needs explicit `ORDER BY`; an identity map hides it | Not planned |
| LangChain / LlamaIndex | Two narrow LLM calls. A framework would add abstraction over the one boundary this project needs to keep visible | Not planned |
| A vector store / RAG | There is no retrieval problem. Numbers come from SQL and deterministic tools | Not planned |
| Multi-currency | Vision §44 excludes it; the `currency` column exists so it is a migration, not a rewrite | Second currency |
| `float` anywhere in a money path | [C-01](00-corrections.md#c-01-b--money-representation-was-never-specified) | Never |

The LangChain omission is worth stating plainly, since it is the default reach for an agent
project: RazorMind's whole thesis is a hard, visible boundary between the model and the
arithmetic. A framework that abstracts planning, tool calling, and output parsing into one
opinionated layer makes that boundary harder to see and much harder to test. The planner,
validator, and executor here are a few hundred lines each, and each one is a place invariants get
enforced.
