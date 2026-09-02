# 07 — API Surface

Base path `/api/v1`. All responses `application/json` except the SSE stream.

## Auth

`Authorization: Bearer <supabase_jwt>` on every endpoint except `/health`.

The API forwards the caller's JWT to Postgres rather than using the service key, so row-level
security applies ([02-data-model.md](02-data-model.md#authz)). `merchant_id` is resolved from
`merchant_members` and **never read from the request body for scoping purposes**
([C-13](00-corrections.md#c-13-b--agentexecution-and-the-api-cannot-scope-to-a-merchant)).

> **Where this stands as of Phase 8.** There is no Supabase in the local stack, so the caller
> declares itself with `X-RazorMind-User: <user_id>` and the membership check is real: the role
> comes from `merchant_members`, a caller who is not a member gets `403
> MERCHANT_SCOPE_VIOLATION`, and a `VIEWER` gets `403 INSUFFICIENT_PERMISSION` rather than a run.
> What is missing is *proof that the header is who it says it is*, which is the JWT's job and
> changes one function
> ([D-52](decisions.md#d-52--identity-is-a-header-until-the-jwt-lands-and-the-merchant-is-checked-either-way)).
> Stating the gap is the point: an unauthenticated endpoint that looks authenticated is worse
> than one that says it is not.

## Errors

One shape everywhere:

```json
{
  "error": {
    "code": "OVERLAPPING_PERIODS",
    "message": "Comparison period overlaps the analysis period.",
    "detail": {},
    "execution_id": "exec_01J8XYZ"
  }
}
```

`code` is a stable enum from [05-agent-runtime.md](05-agent-runtime.md#validation). Clients switch
on `code`, never on `message`.

## Agent

Fixes [C-14](00-corrections.md#c-14-m--a-synchronous-endpoint-cannot-drive-the-progressive-ui) —
the original single blocking `POST` could not drive the stage-by-stage UI in vision §6.1.

### `POST /agent/runs`

```json
{
  "merchant_id": "M123",
  "message": "Why did revenue fall this month?",
  "client_request_id": "c_9f2a..."
}
```

`202 Accepted`

```json
{ "execution_id": "exec_01J8XYZ", "status": "PENDING", "replayed": false }
```

The row is inserted **before** the response, not by the background task. A client that polls the id
it was just handed must find something there; "202 Accepted, but ask again in a moment" is an API
that leaks a race into every consumer.

`replayed` is how the client knows it is watching a run that may already be finished.

`client_request_id` is an idempotency key. Replaying it within 24h returns the original
`execution_id` rather than starting a second run — chat UIs retry, and finance runs should not
silently duplicate.

`merchant_id` in the body is **validated against** the caller's memberships, not trusted.
A mismatch is `403 MERCHANT_SCOPE_VIOLATION`.

### `GET /agent/runs/{id}/events`

`text/event-stream`. Replays all events from `seq=0`, then streams live. `Last-Event-ID` resumes.
Because it replays from `execution_events`, a finished run and a live one render identically —
the history page and the chat page share one component.

**Subscribe, then replay.** The handler attaches to the live broadcaster *before* it reads the
table. The other order loses whatever is written in between, and a stream with a hole in it is
worse than one that repeats. What arrives on both paths is deduplicated on `seq`, which is
monotonic per execution, so `Last-Event-ID: 7` yields exactly `8, 9, 10, …` with no gap and no
duplicate
([D-51](decisions.md#d-51--the-event-stream-subscribes-before-it-replays-and-deduplicates-on-seq)).

A stage's rows are not visible to a reader until the stage's transaction commits, so live delivery
comes from an in-process broadcaster the event log publishes to as each row is written. That is
the single-worker constraint from [D-12](decisions.md#d-12--single-uvicorn-worker-redis-deferred)
being spent on purpose rather than discovered.

```text
event: state
data: {"seq":1,"status":"PLANNING","at":"2026-08-26T09:00:01Z"}

event: stage
data: {"seq":2,"stage":"intent_detected","detail":{"intent":"revenue_diagnosis","confidence":0.92}}

event: stage
data: {"seq":3,"stage":"plan_validated","detail":{"nodes":5}}

event: tool
data: {"seq":4,"tool":"finance.reconciliation","status":"COMPLETED","duration_ms":812}

event: tool
data: {"seq":5,"tool":"payments.failure_analysis","status":"UNAVAILABLE","code":"TOOL_TIMEOUT"}

event: state
data: {"seq":9,"status":"COMPLETED","response_source":"LLM"}
```

| `kind` | Payload |
| --- | --- |
| `state` | Status transition |
| `stage` | Named milestone inside a state |
| `tool` | Per-node start/finish/failure |
| `verification` | Check results, and the blocking check on failure |
| `token` | Optional streamed explanation text |
| `error` | Terminal error |

Heartbeat comment every 15s so proxies do not close the connection.

### `GET /executions/{id}`

The record: merchant, period, status, `response_source`, the answer and its claims, error.

A completed execution carries `answer`, `claims` and `grounding_attempts` alongside
`response_source`. The claims are what makes a number in the prose clickable: the UI does not scan
the text for figures, it renders the spans the grounding gate already matched to evidence ids.

```json
{
  "execution_id": "…",
  "status": "COMPLETED",
  "response_source": "TEMPLATE_FALLBACK",
  "grounding_attempts": 0,
  "answer": "This answer was assembled from a template rather than…",
  "claims": [
    {
      "text": "- Net revenue (net_revenue_paise): ₹4,02,092.87",
      "metric_id": "net_revenue_paise",
      "value": 40209287,
      "unit": "paise",
      "evidence_id": "finance.revenue_analysis/1.0/net_revenue_paise/2026-08-01_2026-08-24"
    }
  ],
  "error": null
}
```

A blocked one carries the failing layer instead, and no prose at all:

```json
{
  "execution_id": "…",
  "status": "BLOCKED",
  "response_source": null,
  "error": {
    "code": "VERIFICATION_FAILED",
    "message": "verification stopped at layer FORMULA",
    "detail": { "blocked_at": "FORMULA", "failures": ["FORMULA: …"] }
  }
}
```

`response_source: null` on a blocked execution is the persisted form of "no text was generated"
(Invariant 4).

### `GET /executions?merchant_id=&status=&limit=&cursor=`

Cursor-paginated list, newest first. `cursor` is the previous page's `next_cursor` — the
`created_at` of its last row.

```json
{
  "items": [
    {
      "execution_id": "…",
      "merchant_id": "M123",
      "question": "Why did net revenue fall in August?",
      "status": "COMPLETED",
      "response_source": "TEMPLATE_FALLBACK",
      "created_at": "2026-09-02T11:04:18.212+00:00",
      "period_from": "2026-08-01",
      "period_to": "2026-08-24"
    }
  ],
  "next_cursor": null
}
```

Keyset rather than `OFFSET`: executions are inserted while somebody is paging, and an offset
shows a row twice or skips one.

## The generated contract

`packages/shared-types/openapi.json` and `packages/shared-types/api.ts` are generated from the
running app by `task.py openapi`, and `task.py check` fails if either is stale. The TypeScript is
generated rather than written beside the document for the reason every generated file here exists:
a hand-kept mirror is a second source of truth that nobody notices going stale
([D-53](decisions.md#d-53--the-typescript-contract-is-generated-and-both-halves-are-diffed-in-ci)).

## Reconciliation

The original endpoints took no parameters, which cannot work for a merchant- and period-scoped
resource.

### `GET /reconciliation/runs?merchant_id=&from=&to=`

Returns `{ "items": [...], "next_cursor": null }`; one item has the shape below. A plural
endpoint returning a bare object would have no room for a second run over the same period, which
is exactly what re-running produces.

```json
{
  "run_id": "rec_01J8ABC",
  "period": { "from": "2026-08-01", "to": "2026-08-24" },
  "ledger_count": 342,
  "bank_count": 341,
  "matched_pairs_count": 338,
  "matched_clean_count": 327,
  "matched_with_exception_count": 11,
  "unmatched_ledger_count": 4,
  "unmatched_bank_count": 3,
  "clean_match_rate_ratio": "0.956140",
  "exception_count": 15,
  "exception_breakdown": {
    "TIMING_LAG": 7,
    "NO_COUNTERPART": 3,
    "AMOUNT_MISMATCH": 2,
    "FEE_DISCREPANCY": 2,
    "POSSIBLE_DUPLICATE": 1
  },
  "unresolved_exception_value_paise": 1840000
}
```

Ratios serialize as **strings** to survive JSON's float round-trip. The web client parses them
with a decimal library. Money is an integer; only ratios are strings.

### `GET /reconciliation/runs/{run_id}/exceptions?category=&side=&limit=&cursor=`

```json
{
  "items": [
    {
      "id": "exc_014",
      "category": "NO_COUNTERPART",
      "side": "LEDGER",
      "transaction_id": "TXN_183",
      "settlement_id": null,
      "amount_paise": 840000,
      "currency": "INR",
      "status": "OPEN",
      "detail": {
        "candidates": [
          {
            "settlement_id": "SETTLEMENT_91",
            "rule": "AMOUNT_DATE_CANDIDATE",
            "confidence_ratio": "0.720000",
            "rejected_because": "below 0.85 auto-match threshold; reference absent"
          }
        ]
      }
    }
  ],
  "next_cursor": null
}
```

### `GET /reconciliation/runs/{run_id}/matches/{match_id}`

The rule, confidence, reason, amount delta, lag, and both source records — what the provenance
drawer opens onto.

## Evidence

### `GET /executions/{id}/evidence`

The index: every metric the execution published, with its unit, window, slice and whether it is
derived or a fold. Optional `metric_id` filter.

### `GET /executions/{id}/evidence/{evidence_id}`

One evidence node, its support, and **the whole chain beneath it** — not just its immediate
operands. The original design had the drawer lazy-load level by level; one round trip is better
here for two reasons. The graph is bounded at a handful of nodes (the revenue bridge's deepest
chain is four levels), so N requests buy nothing. And a partially loaded provenance tree *looks
complete*: "is this chain intact?" cannot be answered until the last request returns, which is the
one question the drawer exists to answer.

`source_record_ids` on the response is the flattened, deduplicated set the whole chain reaches.

Two notes on the path. An evidence id contains slashes — it is
`<tool>/<version>/<metric>/<window>` — so the parameter takes the rest of the URL. And a
dimensioned row appends its slice after a **tilde**, `…_2026-08-24~UPI`, because `#` is the
fragment delimiter and would never reach the server: the request would have silently resolved to
the blended row and returned a plausible wrong number with a citation attached
([D-42](decisions.md#d-42--the-evidence-ids-slice-separator-is--not-)).

A blocked execution answers **409 `EXECUTION_BLOCKED`**, naming the layer — not a 404, which would
read as "no such record", and not the evidence, which it never stored.

## Health

### `GET /health`

```json
{
  "status": "ok",
  "checks": {
    "database": "ok",
    "llm_provider": "ok",
    "tool_registry": { "status": "ok", "tools": 5 }
  },
  "version": "0.4.0"
}
```

Returns `200` when degraded, `503` only when the database is unreachable — an LLM outage is a
degraded state the platform is explicitly designed to survive.

## Contract generation

FastAPI emits OpenAPI; CI writes it to `packages/shared-types/openapi.json` and generates the
TypeScript client. **A diff in that file with no corresponding commit fails the build**, so the
web app can never drift from the API.
