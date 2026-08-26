# 01 — Architecture

## The one rule

> The LLM decides **what to compute**. Deterministic code decides **what the number is**.
> Verification decides **whether it can be trusted**. The LLM explains only what survived.

Everything below is machinery for enforcing that boundary.

## Planes

```text
+--------------------------------------------------------------+
| APPLICATION      chat . dashboard . exceptions . provenance   |
+--------------------------------------------------------------+
| AGENT CONTROL    intent . plan . validate . execute . recover |
+--------------------------------------------------------------+
| DETERMINISTIC    reconciliation . revenue . payments . risk   |
+--------------------------------------------------------------+
| TRUST            verify . evidence . provenance . grounding   |
+--------------------------------------------------------------+
| DATA             transactions . settlements . refunds . state |
+--------------------------------------------------------------+
```

Dependencies point strictly downward. The trust plane may read tool outputs; the tool plane may
never call the agent plane; nothing below the application plane imports an LLM client except
`llm/` itself, which is reachable only from the agent plane.

## Request lifecycle

```text
POST /agent/runs  ->  202 execution_id
      |
      v
  [PLANNING]     intent parse (LLM, structured output)  ->  Intent
      |
      v
  [PLANNING]     planner (deterministic mapping)        ->  ExecutionPlan (DAG)
      |
      v
  [VALIDATING]   schema . types . dates . currency . permissions . tool availability
      |                                                  |
      |                                                  +--> REJECTED (structured reason)
      v
  [EXECUTING]    topological execution of the DAG, independent nodes concurrent
      |                                                  |
      |                                                  +--> PARTIAL (a tool failed)
      v
  [VERIFYING]    per-tool verify() + cross-tool consistency
      |                                                  |
      |                                                  +--> BLOCKED (verification failed)
      v
  [EXPLAINING]   evidence assembly -> LLM explainer -> grounding check
      |                                                  |
      |                                                  +--> TEMPLATE_FALLBACK
      v
  [COMPLETED]
```

Each transition writes a row to `execution_events` and pushes an SSE frame. That table *is* the
audit trail — there is no separate logging path for execution state.

## Boundary enforcement

Three mechanisms, all cheap, all in CI:

1. **Import lint.** `tools/`, `reconciliation/`, `runtime/`, `verification/`, `evidence/` and
   `provenance/` may not import `llm/` or a vendor SDK. Enforced by `import-linter` contracts, not
   by convention. A layers contract additionally fixes the direction of every plane dependency
   ([D-21](decisions.md#d-21--the-trust-plane-sits-below-tools-in-the-import-contract)).
2. **No float in money paths.** A test walks every tool's declared output schema and asserts no
   `float` field name ends in `_paise`.
3. **Grounding gate.** The explainer's output is parsed back into claims and each claim's value
   must byte-match a verified metric. See [06-trust-layer.md](06-trust-layer.md).

## What the LLM is allowed to touch

| Stage | LLM involved? | Output is authoritative? |
| --- | --- | --- |
| Intent parsing | Yes (structured output, schema-constrained) | No — validated before use |
| Planning | No (v0–v1: deterministic intent→plan map; v2: LLM-proposed, still validated) | No |
| Validation | No | — |
| Tool execution | **Never** | Yes |
| Verification | **Never** | Yes |
| Evidence/provenance | **Never** | Yes |
| Explanation | Yes | No — only re-states verified values |

If a number appears in the final answer that is not in the verified metric set, that is a bug
with a test name, not a quality issue.

## Concurrency and state (v0–v1)

Execution state lives in Postgres; in-flight coordination lives in the FastAPI process.
This pins the API to a **single uvicorn worker** — SSE subscribers and the asyncio task running
an execution must share memory.

**Trigger to add Redis** (deferred per vision §29): the first time we need more than one API
worker, or executions must survive a process restart. At that point `execution_events` becomes
the durable log and Redis pub/sub becomes the fan-out. Nothing else changes.

## Repository layout

Follows vision §30 with corrections applied.

```text
razormind/
  apps/
    web/                      Next.js app router
    api/src/
      main.py
      config/
      routes/                 agent.py  executions.py  reconciliation.py  health.py
      orchestrator/           planner.py  executor.py  state.py  events.py
      intent/                 parser.py  schemas.py
      validation/             plan_validator.py  policy.py
      tools/                  base.py  registry.py  finance/  payments/  risk/
      reconciliation/         models.py  rules.py  engine.py  repository.py
      runtime/                db.py  schema.py  money.py  calendar.py
      verification/           verifier.py  rules.py
      evidence/               builder.py  formula.py
      provenance/             builder.py
      llm/                    provider.py  structured_output.py  explainer.py  grounding.py
  packages/shared-types/      openapi.json  (generated, checked in)
  data/seed/                  generate_seed_data.py  golden/
  docs/
  tests/
```

`runtime/money.py` and `runtime/calendar.py` are additions — they exist because C-01 and C-10
demand exactly one implementation of paise arithmetic and one implementation of the IST business
calendar.
