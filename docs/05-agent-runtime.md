# 05 — Agent Runtime

The control plane decides *what to compute*. It computes nothing itself.

## Execution record

Fixes [C-13](00-corrections.md#c-13-b--agentexecution-and-the-api-cannot-scope-to-a-merchant) —
the original had no `merchant_id`, making every query either cross-tenant or dependent on the LLM
inventing a tenant id.

```python
class AgentExecution(BaseModel):
    id: str
    user_id: str
    merchant_id: str              # from the session, never from the model
    input: str

    intent: Intent | None = None
    plan: ExecutionPlan | None = None
    period: Period | None = None
    comparison_period: Period | None = None

    tool_calls: list[ToolExecution] = Field(default_factory=list)
    results: list[ToolResult] = Field(default_factory=list)

    verification: VerificationResult | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    provenance: Provenance | None = None

    final_response: str | None = None
    response_source: Literal["LLM", "TEMPLATE_FALLBACK"] | None = None
    grounding_attempts: int = 0

    status: ExecutionStatus
    error: ExecutionError | None = None
    seed: int | None = None       # set when running against a fixture, for reproducibility

    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
```

`error` is structured, never a string — the UI renders it and the failure tests assert on its
`code`.

## State machine

Fixes [C-12](00-corrections.md#c-12-m--execution-state-machine-is-incomplete). The original
omitted validation and explanation despite both being first-class stages, and named `PARTIAL` /
`BLOCKED` with no transitions.

```text
PENDING
   |
   v
PLANNING ------------------> NEEDS_CLARIFICATION   (terminal, resumable)
   |
   v
VALIDATING -----------------> REJECTED             (terminal)
   |
   v
EXECUTING ------------------> FAILED               (terminal)
   |    \
   |     \--> PARTIAL --\
   v                     |
VERIFYING -------------> |--> BLOCKED              (terminal)
   |                     |
   v                     |
EXPLAINING <-------------/
   |
   v
COMPLETED                                          (terminal)
```

| State | Meaning | Next |
| --- | --- | --- |
| `PENDING` | Accepted, queued | `PLANNING` |
| `PLANNING` | Intent parse + plan build | `VALIDATING`, `NEEDS_CLARIFICATION`, `FAILED` |
| `NEEDS_CLARIFICATION` | Confidence below threshold or a required field is missing | resumed as a new execution linked by `parent_id` |
| `VALIDATING` | Plan checked against schema, policy, registry | `EXECUTING`, `REJECTED` |
| `REJECTED` | Structured rejection; **nothing executed** | terminal |
| `EXECUTING` | DAG running | `VERIFYING`, `PARTIAL`, `FAILED` |
| `PARTIAL` | Some tools failed, enough succeeded to answer | `VERIFYING` |
| `VERIFYING` | Per-tool + cross-tool checks | `EXPLAINING`, `BLOCKED` |
| `BLOCKED` | Verification failed; **no explanation is generated** | terminal |
| `EXPLAINING` | Evidence assembly, LLM, grounding | `COMPLETED`, `FAILED` |
| `COMPLETED` | Answer delivered (possibly `TEMPLATE_FALLBACK`) | terminal |
| `FAILED` | Infrastructure failure | terminal |

`PARTIAL` proceeds to verification rather than terminating — a run where the failure tool died but
reconciliation and revenue succeeded still produces a useful, honest answer. That is the graceful
degradation the demo depends on ([11-demo-script.md](11-demo-script.md)).

`BLOCKED` is terminal and produces **no prose**. This is
[Invariant 4](../file.md) made operational.

Every transition appends to `execution_events` and emits an SSE frame
([07-api.md](07-api.md#get-agentrunsidevents)).

## Intent

```json
{
  "intent": "revenue_diagnosis",
  "merchant_id": "M123",
  "period": { "from": "2026-08-01", "to": "2026-08-24" },
  "comparison_period": { "from": "2026-07-01", "to": "2026-07-24" },
  "confidence_ratio": 0.92,
  "clarification_needed": false,
  "clarification": null
}
```

`confidence_ratio`, not `confidence`: it is a number in `[0, 1]` and the unit suffix costs nothing
here. It is deliberately **not** a metric in the vocabulary and never will be — it is a property of
the parse, not of the merchant's money, and nothing may ever claim it in prose.

The response is obtained through a **forced tool call**, not a "reply in JSON" instruction: the
schema is generated from the model class and sent as the tool's input schema, so the output is
constrained rather than requested. It is parsed from the raw JSON *text*, so `0.92` becomes
`Decimal("0.92")` exactly instead of arriving through a binary float.

Notes on the corrected version:

- Periods are **half-open** ([02-data-model.md](02-data-model.md#time)), so `to` is exclusive.
  `2026-08-24` means "through Aug 23".
- `merchant_id` is echoed from context. If the model emits a different one, the validator raises
  `MERCHANT_SCOPE_VIOLATION`.
- Extraction uses the provider's structured-output mode against the Pydantic schema. A parse
  failure is a retry (once), then `FAILED` — never a free-text fallback.

**Clarification threshold: `confidence < 0.75`, or any required field absent.** The system asks
rather than assumes:

> "How did revenue change?" -> *Which period should I compare against? The previous 23 days
> (Jul 1–23), or the same period last month?*

Guessing a comparison period is the single easiest way to produce a confidently wrong finance
answer, which is why this is a hard gate rather than a heuristic.

## Planning

v0–v1: **deterministic**. Intent type maps to a fixed DAG. No LLM.

```text
revenue_diagnosis:

              finance.reconciliation
                        |
        +---------------+---------------+
        v               v               v
  finance.revenue  payments.failure  finance.refund
     _analysis       _analysis        _analysis
        |               |               |
        |               |         risk.chargeback
        |               |            _analysis
        +---------------+---------------+
                        |
                        v
                   (diagnosis)
```

Each node declares `tool`, `version`, `inputs`, `references`, `depends_on`, `required_role` and
`required`. Independent nodes run concurrently via `asyncio.gather`.

`references` exists because every analysis tool needs the reconciliation `run_id`
([D-35](decisions.md#d-35--the-three-analysis-tools-take-a-run_id-which-the-spec-did-not-ask-for)),
and that value does not exist when the plan is written:

```json
{ "id": "revenue", "tool": "finance.revenue_analysis", "version": "1.0",
  "references": { "run_id": { "from_node": "reconcile", "field": "run_id" } },
  "depends_on": ["reconcile"] }
```

A typed reference rather than string interpolation, so the validator can check that it resolves
*and* that the node it names is actually a dependency
([D-45](decisions.md#d-45--the-eleventh-validation-gate-an-input-reference-must-name-a-dependency)).

`ExecutionPlan` lives in its own `plan` package rather than beside the planner: the orchestrator
builds and runs a plan, the validator judges one, and neither may import the other
([D-44](decisions.md#d-44--the-agent-plane-is-layered-and-the-execution-plan-is-its-own-package)).

v2 lets the LLM *propose* a plan from `registry.describe()`. The validator does not soften — an
LLM-proposed plan passes exactly the same gates. This is why planning can be handed to the model
later without re-auditing the trust boundary.

## Validation

Fires before any tool runs. A rejection is a structured object, not an exception message.

| Check | Failure code |
| --- | --- |
| Plan matches `ExecutionPlan` schema | `INVALID_PLAN_SCHEMA` |
| Every node's tool+version is registered | `UNKNOWN_TOOL` |
| DAG is acyclic and every `depends_on` resolves | `INVALID_DAG` |
| `period.from < period.to` | `INVALID_PERIOD` |
| Analysis and comparison periods do not overlap | `OVERLAPPING_PERIODS` |
| Period is within the dataset's available range | `PERIOD_OUT_OF_RANGE` |
| `currency == "INR"` | `UNSUPPORTED_CURRENCY` |
| Intent `merchant_id` equals session `merchant_id` | `MERCHANT_SCOPE_VIOLATION` |
| Caller's role satisfies every node's `required_role` | `INSUFFICIENT_PERMISSION` |
| Required tool inputs all present and typed | `MISSING_TOOL_INPUT` |
| Every input reference names a node this one depends on | `UNRESOLVED_INPUT_REFERENCE` |

The eleventh was not in the original table, and the phase's own exit criterion asked for eleven.
It is the gate that makes "`REJECTED` is terminal and nothing executed" true rather than
conditional: a reference to a node that is not a dependency resolves to nothing at execution time
and would surface as a tool error deep in a running DAG
([D-45](decisions.md#d-45--the-eleventh-validation-gate-an-input-reference-must-name-a-dependency)).

Two nodes sharing an id is refused by `ExecutionPlan` itself rather than by a twelfth code: the
graph a validator would walk is already not the graph the author wrote.

**Every check is evaluated, not short-circuited.** "Your period is backwards" and "your period is
backwards *and* names another merchant" call for different responses, and a validator that stopped
at the first would make the second invisible until the user fixed the first and resubmitted. The
*reported* rejection is the first in `REJECTION_CODES` order, so the same broken plan always
reports the same headline reason.

```json
{
  "status": "rejected",
  "code": "OVERLAPPING_PERIODS",
  "message": "Comparison period overlaps the analysis period.",
  "detail": {
    "period":            { "from": "2026-08-01", "to": "2026-08-24" },
    "comparison_period": { "from": "2026-08-10", "to": "2026-08-20" }
  }
}
```

## Execution

```python
async def run(plan: ExecutionPlan, ctx: ToolContext) -> list[ToolResult]:
    for layer in plan.topological_layers():
        results = await asyncio.gather(
            *(execute_node(n, ctx) for n in layer),
            return_exceptions=True,
        )
        record(results)
        if any_required_node_failed(layer, results):
            return partial(results)
    return results
```

Rules:

- A node's failure marks it `UNAVAILABLE`; **dependents are skipped, siblings still run**.
- A skipped or failed node never yields a substituted, estimated, or interpolated value
  ([Invariant 6](../file.md)).
- `finance.reconciliation` is marked `required: true`. Its failure fails the run — every other
  tool reads the reconciled set, so proceeding would produce numbers of unknown provenance.
- Per-node timeout 30s, whole-run timeout 120s. A timeout is a node failure, not a hang.
- Each node writes a `tool_executions` row with input, output, status and duration before the
  next layer starts.
- **Each node gets its own database connection.** An asyncpg connection cannot serve two queries
  at once, so nodes sharing one would either serialise — defeating the concurrency the layering
  exists for — or corrupt each other's protocol state. Layer boundaries are transaction
  boundaries, which is also what makes the reconciliation run visible to the analyses that read it.

On the golden window the four analyses finish in about the time of the slowest one rather than the
sum of all four, which is the property `tests/test_agent_db.py` asserts with sleeping fakes rather
than with the real tools — timing the real ones would be timing Postgres.

## Recovery

| Failure | Response | Resulting state |
| --- | --- | --- |
| Intent confidence < 0.75 | Ask one clarifying question | `NEEDS_CLARIFICATION` |
| Plan invalid | Structured rejection, nothing runs | `REJECTED` |
| Reconciliation fails | Whole run fails; no downstream numbers exist | `FAILED` |
| Non-required tool fails | Continue; mark metric unavailable in the answer | `PARTIAL` -> `COMPLETED` |
| Verification fails | Block explanation entirely | `BLOCKED` |
| No LLM configured at intent time | Refuse; never invent an intent | `FAILED` + `PROVIDER_UNAVAILABLE` |
| LLM unavailable / times out | Deterministic template summary of verified metrics | `COMPLETED` + `TEMPLATE_FALLBACK` |
| Grounding fails twice | Same template fallback | `COMPLETED` + `TEMPLATE_FALLBACK` |

The pattern throughout: **degrade the prose, never the numbers**. A user who loses the LLM still
sees the verified revenue bridge. A user whose verification failed sees no numbers at all, which
is the correct outcome.

The two LLM rows are not the same case, and the difference matters. Losing the model at
*explanation* time costs phrasing, and the template renders the verified metrics without it.
Losing it at *intent* time costs the question itself — there is nothing to fall back to, because
the only thing that knows which analysis was asked for is the model. So `get_provider()` returns a
provider that refuses every call, the parser turns that into `PROVIDER_UNAVAILABLE`, and the run
fails. A canned intent would answer a question nobody asked, verified and cited, with nothing
anywhere indicating that no model was consulted.
