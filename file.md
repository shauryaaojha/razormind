# RazorMind

> **Note.** This is the original vision document. Numeric and structural errors found during
> the documentation pass have been corrected inline; every correction is catalogued with its
> reasoning in [`docs/00-corrections.md`](docs/00-corrections.md). Start at
> [`README.md`](README.md), and build from [`docs/10-build-phases.md`](docs/10-build-phases.md).

## Agentic Financial Computation & Reconciliation Platform

> **LLMs decide what needs to be computed. Deterministic systems compute it. Verification establishes what can be trusted. The LLM explains only verified results.**

RazorMind is an **agentic finance operations platform** designed for the **Razorpay AI Finance Controller** problem space.

The platform combines an AI agent runtime with a deterministic financial computation layer, reconciliation engine, verification system, evidence/provenance layer, and finance-focused user interface.

The goal is not to build another AI finance chatbot.

The goal is to build a **trustworthy financial agent** capable of taking a finance-operations question, converting it into a structured execution plan, running deterministic financial tools over transaction and settlement data, identifying and surfacing exceptions, verifying the resulting numbers, tracing those numbers back to evidence, and finally explaining the result in natural language.

---

# 1. Product Vision

Modern LLMs are good at understanding questions, decomposing problems, selecting actions, and explaining results.

They are not the correct source of truth for financial arithmetic.

RazorMind therefore creates a strict boundary:

```text
                    HUMAN
                      │
                      ▼
                NATURAL LANGUAGE
                      │
                      ▼
                  AI AGENT
                      │
             "What should happen?"
                      │
                      ▼
             STRUCTURED EXECUTION
                      │
                      ▼
            DETERMINISTIC TOOLS
                      │
             "What is the answer?"
                      │
                      ▼
                 VERIFICATION
                      │
             "Can we trust it?"
                      │
                      ▼
                 EVIDENCE
                      │
             "Why is it true?"
                      │
                      ▼
                  AI EXPLAINER
                      │
             "What does it mean?"
                      │
                      ▼
                    HUMAN
```

The central principle is:

> **The LLM is an orchestrator and explainer, never the financial authority.**

---

# 2. The Problem RazorMind Solves

Finance teams routinely work across multiple sources of financial truth:

* Payment transaction records
* Settlement records
* Refunds
* Chargebacks
* Fees
* Bank-side settlement data
* Internal ledgers
* Reconciliation reports

The practical problems are not merely:

> "Can AI answer a finance question?"

They are:

* Which records actually match?
* Which settlements are missing?
* Which amounts differ?
* Which discrepancies are timing-related?
* Which numbers are verified?
* Where did a particular number come from?
* Can an AI agent investigate the problem without inventing a conclusion?
* What happens when a tool fails or data is incomplete?

RazorMind addresses these problems through a combination of **reconciliation, deterministic computation, agentic investigation, and evidence-backed explanation**.

---

# 3. Core Product

RazorMind has two tightly connected layers.

## Layer 1 — Financial Control Loop

The system ingests two sides of financial activity:

```text
Your Transaction Ledger
          │
          │
          ▼
   Reconciliation Engine
          ▲
          │
          │
Bank / Settlement File
```

The engine produces:

* Matched records
* Match rate
* Unmatched records
* Amount mismatches
* Timing-lag exceptions
* Duplicate candidates
* Fee discrepancies
* Missing counterparts

This closes the core finance-operations loop.

---

## Layer 2 — AI Financial Investigation

Once the financial state has been reconciled, the AI agent can answer questions such as:

> Why did revenue decline?

> What caused payment failures?

> How much did refunds cost us?

> Which settlements are unresolved?

> What changed compared with the previous period?

> Show me the source of this number.

The agent uses deterministic tools over verified financial data and exceptions.

---

# 4. North-Star Workflow

The primary demonstration workflow is:

> **"Why did revenue decrease this month?"**

The system performs:

```text
User Question
     │
     ▼
Intent Detection
     │
     ▼
Execution Plan
     │
     ▼
Validation
     │
     ▼
Reconciliation
     │
     ├──────────────┬──────────────┐
     ▼              ▼              ▼
Revenue         Payment        Refund /
Analysis        Failure        Chargeback
                Analysis        Analysis
     │              │              │
     └──────────────┼──────────────┘
                    ▼
             Result Verification
                    │
                    ▼
                Evidence
                    │
                    ▼
             Grounded Explanation
                    │
                    ▼
                   User
```

The final answer could be:

> Net revenue declined by 18.00% (₹8,99,532) compared with the previous period. The decline decomposes fully: ₹5,69,246 from an 11.03% drop in attempted payment volume, ₹3,07,554 from a 6.49 pp fall in the blended payment success rate, ₹24,000 from higher refunds and ₹7,500 from higher chargebacks, offset by ₹8,768 of lower fees. The success-rate fall is concentrated in UPI (96.8% → 82.9%, −13.9 pp on 46.66% of attempted value). Separately, ₹18,400 across three unresolved settlement exceptions bounds the confidence of these figures at ±0.45%.

The important property is that **every number in the answer originates from deterministic computation**.

---

# 5. What the Platform Is

RazorMind consists of five major planes.

```text
┌────────────────────────────────────────────────┐
│                 APPLICATION PLANE              │
│                                                │
│ Chat · Dashboard · Reconciliation · Reports   │
│ Execution History · Provenance Drill-down     │
└───────────────────────┬────────────────────────┘
                        │
┌───────────────────────▼────────────────────────┐
│                 AGENT CONTROL PLANE             │
│                                                 │
│ Intent · Planning · Execution Graph · State   │
│ Tool Selection · Clarification · Recovery     │
└───────────────────────┬────────────────────────┘
                        │
┌───────────────────────▼────────────────────────┐
│              DETERMINISTIC TOOL PLANE          │
│                                                 │
│ Reconciliation · Revenue · Payments · Risk   │
└───────────────────────┬────────────────────────┘
                        │
┌───────────────────────▼────────────────────────┐
│                 TRUST PLANE                    │
│                                                 │
│ Verification · Evidence · Provenance          │
│ Grounding · Audit Trail                        │
└───────────────────────┬────────────────────────┘
                        │
┌───────────────────────▼────────────────────────┐
│                DATA PLANE                      │
│                                                 │
│ Transactions · Settlements · Refunds           │
│ Chargebacks · Fees · Execution State           │
└─────────────────────────────────────────────────┘
```

---

# 6. Application Plane

The user-facing application provides four core experiences.

## 6.1 AI Finance Chat

The user can ask natural-language questions:

```text
Why did revenue drop?

What caused the payment failure spike?

Show unresolved settlements.

How much did refunds cost this month?

Why is this settlement unmatched?

Show me how this number was calculated.
```

The chat interface should expose the agent's execution state rather than hiding everything behind a spinner.

Example:

```text
✓ Intent detected
✓ Execution plan generated
✓ Plan validated
✓ Reconciliation loaded
✓ 4 finance tools executed
✓ Results verified
✓ Evidence assembled
✓ Explanation generated
```

---

## 6.2 Reconciliation Dashboard

The dashboard is the primary finance-control surface.

Example:

```text
RECONCILIATION RESULT

Ledger Records                    342
Bank Records                      341
Matched Pairs                     338
Clean Matches                     327
Exceptions                         15
Clean Match Rate                 95.61%
```

Exception breakdown:

```text
Timing Lag                         7
No Counterpart                     3
Amount Mismatch                    2
Possible Duplicate                 1
Fee Discrepancy                    2
```

Users can drill into every exception.

---

## 6.3 Execution History

Every agent run receives a unique execution ID.

Example:

```text
exec_01J8XYZ...
```

The history page should show:

* User request
* Detected intent
* Generated plan
* Tools executed
* Tool status
* Verification status
* Final response
* Failure/recovery events
* Evidence links

This provides an audit-friendly view of how the agent reached its answer.

---

## 6.4 Provenance / Evidence Drawer

When a user asks:

> How did you calculate ₹40,97,868?

RazorMind shows:

```text
NET REVENUE

Gross Payments       ₹42,83,200
Refunds              -₹1,24,000
Payment Fees           -₹42,832
Chargebacks            -₹18,500
────────────────────────────────
Net                   ₹40,97,868
```

Then the user can drill further:

```text
Calculation
    ↓
Input records
    ↓
Matched settlement
    ↓
Source record
    ↓
Verification checks
```

Provenance is therefore a **product feature**, not merely backend metadata.

---

# 7. Agent Control Plane

The agent is responsible for deciding **what should be done**, not performing financial arithmetic itself.

The control plane contains:

* Intent parser
* Planner
* Execution graph
* Tool registry
* State manager
* Clarification engine
* Recovery logic
* Permission checks

---

# 8. Intent Detection

Natural language is transformed into structured intent.

Example:

```json
{
  "intent": "revenue_diagnosis",
  "merchant_id": "M123",
  "period": {
    "from": "2026-08-01",
    "to": "2026-08-23"
  },
  "comparison_period": {
    "from": "2026-07-01",
    "to": "2026-07-23"
  },
  "confidence": 0.92,
  "clarification_needed": false
}
```

The model is never allowed to silently guess required fields.

If the question is ambiguous:

> "How did revenue change?"

The system can respond:

> Which comparison period should I use?

This is preferable to an incorrect assumption.

---

# 9. Execution Planning

The intent becomes an execution graph.

Example:

```text
                    RECONCILIATION
                          │
             ┌────────────┼────────────┐
             ▼            ▼            ▼
        REVENUE       PAYMENT       REFUND /
        ANALYSIS      FAILURE      CHARGEBACK
                      ANALYSIS        ANALYSIS
             │            │            │
             └────────────┼────────────┘
                          ▼
                     DIAGNOSIS
```

Each node represents a deterministic tool.

Each node declares:

* Tool name
* Tool version
* Inputs
* Dependencies
* Permission requirements
* Output type

Independent nodes are executed concurrently.

---

# 10. Execution State

Each request is represented by an `AgentExecution`.

```python
class AgentExecution(BaseModel):
    id: str
    user_id: str
    merchant_id: str              # from the session, never inferred by the model
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
    seed: int | None = None

    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
```

Execution states:

```text
PENDING
   ↓
PLANNING
   ↓
VALIDATING
   ↓
EXECUTING
   ↓
VERIFYING
   ↓
EXPLAINING
   ↓
COMPLETED
```

Alternative paths:

```text
NEEDS_CLARIFICATION    low intent confidence, or a required field missing
REJECTED               plan failed validation; nothing executed
PARTIAL                a non-required tool failed; continues to VERIFYING
BLOCKED                verification failed; no explanation is generated
FAILED                 infrastructure failure
```

The full transition table is in `docs/05-agent-runtime.md`.

Nothing should disappear into an untraceable error.

---

# 11. Validation Layer

Every plan and tool input is validated before execution.

```text
Execution Plan
      ↓
Schema Validation
      ↓
Type Validation
      ↓
Required Fields
      ↓
Date Validation
      ↓
Currency Validation
      ↓
Permission Validation
      ↓
Tool Availability
      ↓
Execution
```

Example rules:

```text
merchant_id must exist

period.start < period.end

currency must be supported

tool must exist

tool must be allowed for the user

required parameters must be present
```

An invalid plan becomes a structured rejection.

Example:

```json
{
  "status": "rejected",
  "reason": "INVALID_PERIOD",
  "message": "Comparison period overlaps the current period."
}
```

It is not executed.

---

# 12. Deterministic Tool Plane

All financial calculations occur inside deterministic tools.

Every tool follows one contract.

```python
class DeterministicTool(ABC, Generic[TIn, TOut]):
    name: ClassVar[str]
    version: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]
    output_model: ClassVar[type[BaseModel]]
    required_role: ClassVar[str] = "ANALYST"

    @abstractmethod
    async def execute(self, inp: TIn, ctx: ToolContext) -> TOut: ...

    @abstractmethod
    def verify(self, inp: TIn, out: TOut) -> VerificationResult: ...

    @abstractmethod
    def evidence(self, inp: TIn, out: TOut) -> list[Evidence]: ...

    def validate(self, raw: dict) -> TIn:
        return self.input_model.model_validate(raw)
```

The initial tool registry contains:

```text
finance.reconciliation
finance.revenue_analysis
finance.refund_analysis
payments.failure_analysis
risk.chargeback_analysis
```

The registry is extensible.

Future tools can be added without redesigning the agent.

---

# 13. Reconciliation Engine

The reconciliation engine is the foundation of the platform.

Input:

```text
Your-side transaction ledger
+
Bank / settlement-side records
```

Output:

```text
Matched records
+
Exceptions
+
Match rate
+
Match evidence
```

---

## 13.1 Matching Strategy

Reconciliation uses explicit matching rules.

Example:

```text
1. Exact UTR
2. Reference + exact amount
3. Reference + date window
4. Amount + date window
5. Candidate match → manual review
```

Each match records how it was established.

```json
{
  "match_type": "exact_utr",
  "confidence": 1.0,
  "reason": "UTR and settlement amount matched"
}
```

A weaker match:

```json
{
  "match_type": "amount_date_candidate",
  "confidence": 0.72,
  "reason": "Amount matched but reference was unavailable"
}
```

The system never hides ambiguity.

---

# 14. Reconciliation Exceptions

The platform explicitly categorizes unresolved records.

Initial categories:

```text
NO_COUNTERPART
AMOUNT_MISMATCH
TIMING_LAG
POSSIBLE_DUPLICATE
FEE_DISCREPANCY
```

An exception might look like:

```json
{
  "record_id": "TXN_183",
  "category": "NO_COUNTERPART",
  "side": "LEDGER",
  "amount_paise": 840000,
  "currency": "INR",
  "status": "unresolved",
  "candidates": [
    {
      "settlement_id": "SETTLEMENT_91",
      "rule": "AMOUNT_DATE_CANDIDATE",
      "confidence_ratio": "0.720000",
      "rejected_because": "below 0.85 auto-match threshold; reference absent"
    }
  ]
}
```

Exceptions are not treated as system failures.

They are a legitimate and valuable **financial output**.

---

# 15. Revenue Engine

The revenue engine operates on the reconciled dataset.

It computes:

```text
Gross payment volume
Successful payment value
Failed payment value
Refund value
Chargeback value
Fees
Average order value
Net revenue
Period-over-period changes
```

Example:

```text
Gross Payments       ₹42,83,200
Refunds              -₹1,24,000
Fees                   -₹42,832
Chargebacks            -₹18,500
────────────────────────────────
Net                   ₹40,97,868
```

---

# 16. Payment Failure Engine

The payment engine identifies and explains failure patterns.

It can analyze:

```text
Payment method
Failure reason
Date range
Merchant segment
Issuer / source
Success rate
Failure rate
Failure trend
```

Example result:

```text
UPI success rate

Previous period       96.8%
Current period        82.9%

Change               -13.9 pp
```

The LLM does not calculate these values.

The tool does.

---

# 17. Refund and Chargeback Engines

Refund analysis:

```text
Total refunds
Refund rate
Refund amount by segment
Refund reasons
Period-over-period change
```

Chargeback analysis:

```text
Chargeback count
Chargeback value
Chargeback rate
Trend
Affected segment
```

These become supporting evidence for revenue diagnosis.

---

# 18. Deterministic Runtime

The deterministic runtime is the computational core.

It guarantees:

* Reproducibility
* Explicit formulas
* Stable outputs
* Typed inputs
* Typed outputs
* No LLM arithmetic
* No hidden assumptions

A tool execution should produce:

```text
Input
→ Calculation
→ Result
→ Verification metadata
→ Evidence
→ Provenance
```

---

# 19. Verification Layer

No deterministic result should go directly to the explainer.

Pipeline:

```text
Tool Result
     ↓
Type Check
     ↓
Range Check
     ↓
Consistency Check
     ↓
Formula Check
     ↓
Source Check
     ↓
Verified Result
```

Examples:

```text
gross >= net

refunds >= 0

fees >= 0

chargebacks >= 0

match_rate_ratio ∈ [0, 1]        (formatted as a percentage only in the UI)

2 × matched_pairs + unmatched_ledger + unmatched_bank
        == ledger_count + bank_count
```

A failed verification blocks downstream explanation.

---

# 20. Evidence Layer

Each verified result is attached to an evidence object.

```python
class Evidence(BaseModel):
    id: str
    source_records: list[str]

    calculation: str
    inputs: dict
    outputs: dict

    rules_applied: list[str]
    verification_checks: list[str]
```

This creates a chain:

```text
Natural-language answer
        ↓
Claim
        ↓
Metric
        ↓
Verified result
        ↓
Calculation
        ↓
Evidence
        ↓
Source records
```

---

# 21. Provenance

Every financial number must be traceable.

For example:

```text
₹18,400 unresolved  (3 NO_COUNTERPART exceptions)
        │
        ├── TXN_183  ₹8,400
        │     └── rejected candidate SETTLEMENT_91 (confidence 0.72)
        ├── TXN_247  ₹6,200
        └── TXN_402  ₹3,800
```

The user should be able to answer:

> Where did this number come from?

without relying on the AI model's explanation.

---

# 22. LLM Explainer

The LLM receives only:

```text
Verified Results
+
Evidence
+
Provenance
+
Allowed context
```

It does not receive raw unverified assumptions and invent the remainder.

The explainer's responsibility is:

* Summarize
* Explain
* Compare
* Prioritize causes
* Present results
* Recommend analysis steps

Its responsibility is **not**:

* Perform financial arithmetic
* Invent missing data
* Change verified numbers
* Assume unavailable records
* Hide unresolved exceptions

---

# 23. Grounding Enforcement

The platform actively checks whether generated claims are grounded.

Conceptually:

```text
Generated Claim
     ↓
Claim → Metric → Value → Evidence
     ↓
Grounded?
```

Example:

```json
{
  "text": "Net revenue fell by 18.00%",
  "metric_id": "net_revenue_change_ratio",
  "unit": "ratio",
  "value": "-0.180000",
  "evidence_id": "ev_001"
}
```

If the model introduces an unsupported number:

```text
Grounding Failure
        ↓
Regenerate once
        ↓
Still invalid?
        ↓
Template fallback
```

The user must still receive the verified numbers.

---

# 24. Failure & Recovery

Failure recovery is part of the platform design.

## Intent failure

```text
Low confidence
      ↓
Clarifying question
```

No guessing.

---

## Plan failure

```text
Invalid plan
      ↓
Structured rejection
```

No execution.

---

## Tool failure

```text
Tool unavailable
      ↓
Partial result
      ↓
Explicit unavailable flag
```

No fabricated substitute.

---

## Reconciliation exceptions

```text
Unmatched records
      ↓
Exception list
      ↓
Manual review
```

Exceptions are surfaced rather than hidden.

---

## Explainer failure

```text
LLM unavailable
      ↓
Verified results
      ↓
Deterministic template summary
```

The financial answer remains accessible.

---

## Verification failure

```text
Tool output
      ↓
Verification
      ↓
FAILED
      ↓
BLOCK downstream explanation
```

Unverified financial numbers never become authoritative output.

---

# 25. Demo Data

The initial submission uses a fully deterministic synthetic dataset.

The data contains two sides:

```text
ledger_side.csv

bank_settlement.csv
```

The dataset contains approximately:

```text
~1,600 payment attempts (~1,480 successful)
90 days of activity: 2026-05-26 → 2026-08-24 (IST, half-open)
342 settlement-eligible ledger records in the current 23-day window
```

The generator is seeded for reproducibility.

```python
rng = random.Random(42)      # a local instance; never the global seed
```

---

# 26. Embedded Financial Story

The synthetic dataset deliberately contains a coherent operational story.

The story includes:

```text
Payment method degradation
        ↓
Increased payment failures
        ↓
Lower successful transaction value
        ↓
Revenue decline
```

And:

```text
Settlement timing lag
Duplicate settlement
Fee discrepancy
Missing counterpart records
```

Secondary signals:

```text
Refund rate increases
Chargeback rate increases
```

This ensures that the system demonstrates meaningful diagnosis rather than merely producing random statistics.

---

# 27. Reconciliation Scorecard

The main dashboard should expose:

```text
RECONCILIATION

Ledger Records                 342
Bank Records                   341
Matched Pairs                  338
Clean Matches                  327
Exceptions                      15
Clean Match Rate              95.61%
```

Then:

```text
EXCEPTION BREAKDOWN

Timing Lag                       7   (matched, flagged)
Amount Mismatch                  2   (matched, flagged)
Fee Discrepancy                  2   (matched, flagged)
No Counterpart                   3   (unmatched)
Possible Duplicate               1   (unmatched)
```

The user can select any category to inspect the underlying records.

---

# 28. Example End-to-End Interaction

User:

> Why did revenue fall this month?

### Step 1 — Intent

```text
revenue_diagnosis
```

### Step 2 — Planning

```text
reconciliation
revenue_analysis
failure_analysis
refund_analysis
chargeback_analysis
```

### Step 3 — Validation

```text
✓ merchant
✓ dates
✓ permissions
✓ tools
```

### Step 4 — Execution

```text
✓ reconciliation
✓ revenue analysis
✓ payment analysis
✓ refund analysis
✓ chargeback analysis
```

### Step 5 — Verification

```text
✓ calculations valid
✓ sources valid
✓ consistency checks passed
```

### Step 6 — Evidence

```text
Revenue decline
    ↓
Payment failures
    ↓
Affected transactions
    ↓
Settlement evidence
```

### Step 7 — Explanation

```text
Net revenue declined 18.00% (₹8,99,532).

  Attempt-volume decline (-11.03%)   -₹5,69,246   63.3%
  Payment success rate (-6.49 pp)    -₹3,07,554   34.2%
  Refund increase                       -₹24,000    2.7%
  Chargeback increase                    -₹7,500    0.8%
  Fee decrease (offset)                  +₹8,768   -1.0%
  ---------------------------------------------------------
  Total                              -₹8,99,532  100.0%

The success-rate fall is concentrated in UPI:
96.8% -> 82.9% (-13.9 pp) on 46.66% of attempted value.

₹18,400 across three unresolved settlement exceptions
is reported separately as a +/-0.45% confidence band,
not as a driver of the decline.
```

---

# 29. Technology Stack

## Frontend

```text
Next.js
React
TypeScript
Tailwind CSS
shadcn/ui
```

Responsibilities:

* Chat interface
* Reconciliation dashboard
* Execution trace
* Evidence drawer
* Exception explorer
* Reports

---

## Backend

```text
Python
FastAPI
Pydantic
asyncio
```

Responsibilities:

* Agent runtime
* Intent parsing
* Planning
* Validation
* Tool execution
* Reconciliation
* Deterministic calculations
* Verification
* Provenance
* LLM provider integration

---

## Database / Authentication

```text
Supabase
├── PostgreSQL
└── Auth
```

This minimizes infrastructure for a solo build.

---

## LLM

Use an abstraction:

```python
class LLMProvider:
    async def structured_output(...): ...
    async def explain(...): ...
```

Supported providers can include:

```text
OpenAI
Anthropic
Gemini
```

The application must not be architecturally dependent on one provider.

---

## Deployment

```text
Frontend → Vercel
Backend  → Railway / Render
Database → Supabase
```

Redis is intentionally excluded from the first implementation unless performance requirements justify introducing it.

---

# 30. Repository Structure

```text
razormind/
│
├── apps/
│   ├── web/
│   │   └── ...
│   │
│   └── api/
│       └── src/
│           ├── main.py
│           │
│           ├── config/
│           │
│           ├── routes/
│           │   ├── agent.py
│           │   ├── executions.py
│           │   └── health.py
│           │
│           ├── orchestrator/
│           │   ├── planner.py
│           │   ├── executor.py
│           │   └── state.py
│           │
│           ├── intent/
│           │   ├── parser.py
│           │   └── schemas.py
│           │
│           ├── validation/
│           │   ├── plan_validator.py
│           │   └── policy.py
│           │
│           ├── tools/
│           │   ├── base.py
│           │   ├── registry.py
│           │   ├── finance/
│           │   │   ├── reconciliation.py
│           │   │   ├── revenue_analysis.py
│           │   │   └── refund_analysis.py
│           │   │
│           │   ├── payments/
│           │   │   └── failure_analysis.py
│           │   │
│           │   └── risk/
│           │       └── chargeback_analysis.py
│           │
│           ├── runtime/
│           │   └── db_queries.py
│           │
│           ├── verification/
│           │   └── verifier.py
│           │
│           ├── evidence/
│           │   └── builder.py
│           │
│           ├── provenance/
│           │   └── builder.py
│           │
│           └── llm/
│               ├── provider.py
│               ├── structured_output.py
│               └── grounding.py
│
├── packages/
│   └── shared-types/
│       └── openapi.json
│
├── data/
│   ├── seed/
│   │   ├── generate_seed_data.py
│   │   └── seed.sql
│   └── fixtures/
│
├── docs/
│   ├── problem.md
│   ├── architecture.md
│   ├── workflows.md
│   ├── decisions.md
│   ├── tools.md
│   ├── demo-script.md
│   └── api.md
│
├── tests/
│
├── docker-compose.yml
├── README.md
└── .env.example
```

---

# 31. File Responsibility Principle

Every file should have one clearly defined responsibility.

Examples:

| File                    | Responsibility                                  |
| ----------------------- | ----------------------------------------------- |
| `main.py`               | Application entry point                         |
| `planner.py`            | Convert intent into execution graph             |
| `executor.py`           | Execute graph nodes and manage parallelism      |
| `state.py`              | Persist execution state                         |
| `parser.py`             | Structured LLM intent extraction                |
| `plan_validator.py`     | Validate execution graph                        |
| `registry.py`           | Resolve deterministic tools                     |
| `reconciliation.py`     | Match two financial datasets                    |
| `verifier.py`           | Verify deterministic outputs                    |
| `builder.py`            | Build evidence/provenance objects               |
| `provider.py`           | LLM abstraction                                 |
| `grounding.py`          | Verify generated claims                         |
| `generate_seed_data.py` | Generate reproducible synthetic financial story |

---

# 32. Database Model

Initial schema:

```text
users
merchants
merchant_members
transactions
settlements
refunds
chargebacks
agent_executions
tool_executions
execution_events
reconciliation_runs
reconciliation_matches
reconciliation_exceptions
evidence
```

Core relationship:

```text
Merchant
   │
   ├── Transactions
   ├── Settlements
   ├── Refunds
   └── Chargebacks

AgentExecution
   │
   ├── ToolExecutions
   └── Evidence

Reconciliation
   │
   ├── Matches
   └── Exceptions
```

---

# 33. API Surface

Primary endpoint (asynchronous — the UI streams execution state):

```http
POST /api/v1/agent/runs
```

Request:

```json
{
  "merchant_id": "M123",
  "message": "Why did revenue fall this month?",
  "client_request_id": "c_9f2a..."
}
```

Response `202 Accepted`:

```json
{
  "execution_id": "exec_01J8XYZ",
  "status": "PENDING"
}
```

Live execution state (SSE, replays from seq 0 then streams):

```http
GET /api/v1/agent/runs/{id}/events
```

Execution detail and history:

```http
GET /api/v1/executions/{id}
GET /api/v1/executions?merchant_id=&status=&limit=&cursor=
```

Reconciliation (merchant- and period-scoped):

```http
GET /api/v1/reconciliation/runs?merchant_id=&from=&to=
GET /api/v1/reconciliation/runs/{run_id}/exceptions?category=&side=
GET /api/v1/reconciliation/runs/{run_id}/matches/{match_id}
```

Evidence:

```http
GET /api/v1/executions/{id}/evidence/{evidence_id}
```

Health:

```http
GET /api/v1/health
```

---

# 34. Build Strategy

The platform must be developed incrementally.

Never ask an AI coding agent to:

> "Build the whole application."

Development proceeds through controlled vertical slices.

```text
Architecture
   ↓
Contract
   ↓
Module
   ↓
Implementation
   ↓
Tests
   ↓
Integration
   ↓
Review
   ↓
Next module
```

---

# 35. MVP / V0

The first working vertical slice contains only:

```text
Chat
  ↓
Intent parser
  ↓
Planner
  ↓
Validator
  ↓
Reconciliation
  ↓
Revenue analysis
  ↓
Verification
  ↓
LLM explanation
```

This proves the core concept end-to-end.

---

# 36. V1

Add:

```text
Reconciliation dashboard
Exception explorer
Payment failure analysis
Refund analysis
Chargeback analysis
Provenance drawer
Execution history
```

---

# 37. V2

Add dynamic agent behavior:

```text
Multi-step planning
Execution graph
Parallel tool execution
Dependency resolution
Dynamic investigation
```

Example:

```text
Revenue declined
      │
      ├── Payment failures
      │       └── Method breakdown
      │              └── Time window analysis
      │
      ├── Refunds
      │       └── Refund reason analysis
      │
      └── Chargebacks
              └── Segment analysis
```

---

# 38. Future Action Layer

The submission does not need automatic financial actions.

The architecture is designed to support them later.

Future flow:

```text
Agent
  ↓
Action Plan
  ↓
Policy Check
  ↓
Risk Classification
  ↓
Human Approval
  ↓
Execution
```

This allows RazorMind to eventually move from:

```text
Observe
```

to:

```text
Investigate
```

to:

```text
Recommend
```

to:

```text
Act
```

without compromising financial control.

---

# 39. Evaluation Framework

RazorMind should evaluate itself on four dimensions.

## Intent Accuracy

Did the system understand the question correctly?

## Tool Selection Accuracy

Did it choose the correct deterministic tools?

## Computation Accuracy

Did deterministic execution produce the correct result?

## Explanation Grounding

Did the final answer contain only claims supported by verified results?

Additional metric:

## Reconciliation Accuracy

```text
match_rate
+
exception classification accuracy
+
false-match rate
+
unresolved record accuracy
```

The platform should be able to demonstrate these metrics over the synthetic dataset.

---

# 40. Testing Strategy

Testing occurs at multiple levels.

## Unit tests

Test:

* Matching rules
* Revenue formulas
* Date comparisons
* Currency handling
* Verification rules
* Exception classification
* Grounding checks

## Integration tests

Test:

```text
Intent
→ Plan
→ Validation
→ Tool
→ Verification
→ Explanation
```

## Failure tests

Explicitly simulate:

* Invalid intent
* Invalid plan
* Database timeout
* Missing record
* LLM timeout
* Grounding failure
* Verification failure

The platform should demonstrate graceful degradation for each.

---

# 41. Demo Workflow

The final demo should focus on one coherent story.

## Opening

Show the financial dashboard:

```text
Net revenue Rs 40,97,868  -  down 18.00%
```

Ask:

> Why?

## Agent

Show:

```text
Intent detected
Execution graph created
Plan validated
```

## Reconciliation

Show:

```text
342 records
327 matched
15 exceptions
95.61% match rate
```

## Investigation

Show:

```text
Blended success rate  96.81% -> 90.32%  (-6.49 pp)
UPI success rate      96.8%  -> 82.9%   (-13.9 pp)
```

Then:

```text
Refunds     +Rs 24,000
Chargebacks  +Rs 7,500
```

## Provenance

Click:

> Show calculation

Reveal the actual records and formulas.

## Exception

Open:

> 3 unresolved settlements — ₹18,400

Show exactly why they remain unresolved.

## Failure Recovery

Intentionally make one downstream tool unavailable.

Show:

```text
Payment analysis unavailable.

Verified reconciliation and revenue
results remain available.
```

## Closing

Deliver the thesis:

> **RazorMind doesn't ask an LLM to calculate financial truth. It asks the LLM to orchestrate a verified computational system.**

---

# 42. Five-Minute Pitch Structure

```text
0:00–0:30
Problem
```

Finance teams cannot blindly trust generated financial numbers.

```text
0:30–3:00
Demo
```

Revenue diagnosis → reconciliation → exceptions → provenance.

```text
3:00–4:00
Architecture
```

LLM plans → deterministic tools compute → verification checks → evidence proves → LLM explains.

```text
4:00–4:45
Failure recovery
```

Break one tool and demonstrate graceful degradation.

```text
4:45–5:00
Closing
```

Match rate, exception handling, deterministic computation, and future agentic financial actions.

---

# 43. What RazorMind Is Not

RazorMind is intentionally **not**:

* A generic ChatGPT wrapper
* A finance chatbot that guesses answers
* A spreadsheet replacement
* An autonomous financial transaction executor
* A live Razorpay production integration
* A generic RAG application
* A dashboard with an LLM bolted on
* A system where generated numbers become authoritative

The system is designed around **financial trust and verification**.

---

# 44. Non-Goals for the Initial Submission

The initial build intentionally excludes:

```text
Live Razorpay API integration
Complex RBAC
Multi-currency support
Automatic financial actions
Redis
Large-scale distributed architecture
Production-scale merchant onboarding
```

These can be added later.

The goal of the initial submission is to build a **small but complete financial control loop** rather than a large collection of unfinished features.

---

# 45. Future Roadmap

## Phase A — Financial Intelligence

```text
Reconciliation
Revenue diagnosis
Payment analysis
Refund analysis
Chargeback analysis
```

## Phase B — Proactive Intelligence

```text
Anomaly detection
Alerts
Scheduled financial checks
Exception prioritization
```

## Phase C — Agentic Actions

```text
Recovery plans
Approval workflows
Bounded remediation
Automated follow-up
```

## Phase D — Expanded Financial Runtime

The same deterministic tool framework can support:

```text
Finance
Risk
Payments
Revenue Recovery
Forecasting
Analytics
Fraud
```

The tool registry remains the extension point.

---

# 46. Architectural Differentiator

Most AI finance applications follow:

```text
User
 ↓
LLM
 ↓
Answer
```

RazorMind follows:

```text
User
 ↓
LLM
 ↓
Structured Intent
 ↓
Execution Graph
 ↓
Validation
 ↓
Deterministic Tools
 ↓
Verification
 ↓
Evidence
 ↓
Provenance
 ↓
LLM
 ↓
Grounded Answer
```

That distinction defines the entire platform.

---

# 47. Core Engineering Invariants

These rules must never be violated.

### Invariant 1

> **The LLM never produces authoritative financial numbers.**

### Invariant 2

> **Every authoritative number has provenance.**

### Invariant 3

> **Every execution plan is validated before execution.**

### Invariant 4

> **Verification failure blocks downstream explanation.**

### Invariant 5

> **Exceptions are surfaced, never silently discarded.**

### Invariant 6

> **Incomplete data results in an explicit limitation, never an invented result.**

### Invariant 7

> **Every agent execution is traceable through an execution ID.**

### Invariant 8

> **Every tool follows the same deterministic contract.**

---

# 48. Final Platform Definition

RazorMind is a **deterministic financial execution platform with an agentic control layer**.

Its architecture separates:

```text
REASONING
    ↓
"What should we investigate?"

EXECUTION
    ↓
"What is actually true?"

VERIFICATION
    ↓
"Can we trust the result?"

EVIDENCE
    ↓
"Why is it true?"

EXPLANATION
    ↓
"What does it mean to the user?"
```

This separation is the fundamental design decision of the platform.

The product is therefore not:

> **AI that does finance.**

It is:

> **A financial control system where AI orchestrates verified computation.**

---

# 49. Final One-Line Pitch

> **RazorMind is an agentic finance controller that turns natural-language questions into verified financial computations — reconciling records, detecting exceptions, tracing every number to evidence, and using AI only to orchestrate and explain the result.**

---

# 50. Final Build Order

```text
01. Repository scaffold

02. Synthetic two-sided financial dataset

03. PostgreSQL schema

04. Reconciliation engine

05. Reconciliation verification

06. Tool abstraction + registry

07. Revenue analysis tool

08. Payment failure analysis tool

09. Refund / chargeback tools

10. Intent parser

11. Execution graph

12. Plan validator

13. Agent executor

14. Execution persistence

15. Evidence + provenance

16. LLM explainer

17. Grounding validator

18. Chat UI

19. Reconciliation dashboard

20. Exception explorer

21. Execution history

22. Failure recovery

23. Evaluation suite

24. Deployment

25. README + architecture documentation

26. Demo rehearsal

27. Final 5-minute pitch
```

---

# Final Architecture

```text
                         ┌──────────────────────┐
                         │        USER          │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │     RAZORMIND UI     │
                         │                      │
                         │ Chat                 │
                         │ Dashboard            │
                         │ Exceptions           │
                         │ Provenance           │
                         │ Execution History    │
                         └──────────┬───────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │       AGENT CONTROL PLANE     │
                    │                               │
                    │ Intent Parser                 │
                    │ Planner                      │
                    │ Execution Graph               │
                    │ State Manager                 │
                    │ Recovery                      │
                    └──────────────┬────────────────┘
                                   │
                                   ▼
                    ┌───────────────────────────────┐
                    │        VALIDATION LAYER       │
                    │                               │
                    │ Schema                       │
                    │ Types                        │
                    │ Permissions                  │
                    │ Constraints                  │
                    └──────────────┬────────────────┘
                                   │
                                   ▼
                    ┌───────────────────────────────┐
                    │         TOOL REGISTRY         │
                    └──────────────┬────────────────┘
                                   │
             ┌─────────────────────┼─────────────────────┐
             ▼                     ▼                     ▼
    ┌────────────────┐    ┌────────────────┐    ┌────────────────┐
    │ RECONCILIATION │    │    FINANCE     │    │    PAYMENTS    │
    │     ENGINE     │    │    ENGINE      │    │    / RISK      │
    └───────┬────────┘    └───────┬────────┘    └───────┬────────┘
            │                     │                     │
            └─────────────────────┼─────────────────────┘
                                  ▼
                    ┌───────────────────────────────┐
                    │   DETERMINISTIC RUNTIME       │
                    │                               │
                    │ Calculations                  │
                    │ Matching                      │
                    │ Aggregation                   │
                    │ Rules                        │
                    └──────────────┬────────────────┘
                                   │
                                   ▼
                    ┌───────────────────────────────┐
                    │         VERIFICATION          │
                    │                               │
                    │ Accuracy                     │
                    │ Consistency                  │
                    │ Completeness                 │
                    │ Source validation            │
                    └──────────────┬────────────────┘
                                   │
                                   ▼
                    ┌───────────────────────────────┐
                    │        EVIDENCE LAYER         │
                    │                               │
                    │ Records                      │
                    │ Rules                        │
                    │ Calculations                 │
                    │ Verification checks          │
                    └──────────────┬────────────────┘
                                   │
                                   ▼
                    ┌───────────────────────────────┐
                    │         PROVENANCE            │
                    │                               │
                    │ Source → Match → Formula     │
                    │ → Result → Claim             │
                    └──────────────┬────────────────┘
                                   │
                                   ▼
                    ┌───────────────────────────────┐
                    │          LLM EXPLAINER        │
                    │                               │
                    │ Verified Data Only            │
                    │ Grounded Claims               │
                    └──────────────┬────────────────┘
                                   │
                                   ▼
                              ┌──────────┐
                              │   USER   │
                              └──────────┘
```

**RazorMind's fundamental proposition is simple:**

> **AI controls the investigation. Deterministic systems control the numbers. Evidence controls trust.**
