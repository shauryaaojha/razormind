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
 3  Tool framework      the contract + revenue analysis            [DONE]
 4  Remaining tools     failure, refund, chargeback                [DONE]
 5  Trust layer         verification, evidence, provenance          [DONE]
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

## The data, and what is claimed about it

> **Transaction-level records are synthetic and seeded.** No real customer, merchant, or bank
> record is represented. Aggregate distributions and operational characteristics are **calibrated
> against public NPCI/RBI statistics**; failure rates are not Razorpay's.

```text
public NPCI / RBI statistics  ->  calibration parameters  ->  scenario  ->  generator
                                  (every one tagged)          (the world)     |
                                                                              v
                                            ledger + settlements + ground_truth.json
```

Every calibration parameter carries a provenance tag — `CITED`, `DERIVED` or `ASSUMED` — redeemed
with a URL and a retrieval date in [`data/calibration/sources.md`](data/calibration/sources.md).
`ASSUMED` is not an apology: one merchant's payment mix is not a published statistic and never will
be. What matters is that a design choice is never mistaken for an observation. `GET /api/v1/provenance`
serves the whole picture, generated from the calibration layer rather than written by hand.

**Counts are designed; money is derived.** The scenario fixes capture counts and planted anomaly
counts. Failures, ticket values, fees, success rates and the revenue decline itself all emerge
([D-26](docs/decisions.md#d-26--counts-are-designed-money-is-derived)).

### Volume share is not value share

The most important calibration fact, and the one an arbitrary generator always gets wrong:

| Method | Volume share | Value share | Mean ticket |
| --- | ---: | ---: | ---: |
| `UPI` | 0.720222 | 0.387535 | Rs 640 |
| `CARD` | 0.160665 | 0.378821 | Rs 2,850 |
| `NETBANKING` | 0.058172 | 0.206764 | Rs 4,200 |
| `WALLET` | 0.060942 | 0.026879 | Rs 520 |

UPI is 72% of the payments and 39% of the money, because its ticket is small.

### Fees follow the instrument

Bank-account UPI and RuPay debit are **zero-MDR by mandate**; PPI-funded UPI carries an interchange
above ₹2,000; cards carry a negotiated rate; netbanking is billed flat. The blended effective rate
that falls out is **0.006420** — nothing like the flat 1% this replaced,
because the volume-dominant rail is free
([D-24](docs/decisions.md#d-24--fees-are-per-instrument-and-the-flat-1-is-gone)).

That is what makes a `FEE_DISCREPANCY` a finding: the engine names the instrument whose rule would
have produced the fee the bank actually charged.

### The story

| | Prior (Jul 1–23) | Current (Aug 1–23) |
| --- | ---: | ---: |
| Attempts | 429 | 361 |
| Success rate | 0.958042 | 0.944598 |
| **Technical declines** | **0.006993** | **0.022161** |
| Business declines | 0.034965 | 0.033241 |
| Gross successful | Rs 4,86,920 | Rs 4,06,260 |
| Fees | Rs 3,026 | Rs 2,608 |
| **Net revenue** | **Rs 4,73,424** | **Rs 3,90,122** |

Decline **-Rs 83,301 = -0.175956**, fully attributed with a
**zero** rounding residual. Technical declines roughly triple while business declines stay flat —
that asymmetry is what attributes the movement to the platform rather than to customers.

There is a real incident: `upi_issuer_degradation`, 2026-08-09 to 2026-08-19, UPI at
BANK_A, BANK_B, BANK_C, running **0.095890**
technical declines against **0.000000** everywhere else.

**And it is not what moved revenue.** Attempt volume is. The incident is the salient event in the
window, and a model reasoning from narrative rather than arithmetic will name it as the cause —
separating a genuine operational incident from the actual revenue driver is the finding
([D-27](docs/decisions.md#d-27--the-ground-truth-is-checked-against-its-own-dataset)).

Reconciliation over the same window: 342 ledger / 341 bank
records, 338 pairs, 327 clean, 15
exceptions, **0.956140** clean match rate,
Rs 1,840 unresolved across 3 records — reported as a confidence band,
never folded into the bridge.

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
| `task.py verify-seed` | the ten fixture assertions |
| `task.py migrate` / `loadseed` | Alembic, then load `seed.sql` |
| `task.py reconcile` | reconcile the golden window and persist the run |
| `task.py revenue` | the golden revenue bridge, through both v1 tools |
| `task.py diagnose` | every v1 tool, plus the cross-tool equivalences |
| `task.py verify` | the same, through the five verification layers, then the provenance walk |
| `task.py test` | pytest, 100% branch coverage required on `runtime/` |
| `task.py dbtest` | row-level security, against a real Postgres |
| `task.py dev` / `web` / `psql` | containers, foreground |

---

## Status

**Phases 0 through 5 complete.** `check` is green: ruff, mypy `--strict`, three import-linter
contracts, the no-float guard, the ten fixture assertions, and 304 tests with 100% branch
coverage on `runtime/`. A further 88 integration tests run against a real Postgres.

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
largest remainder, in whole rupees — and checksummed artifacts
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

Phase 3 put both of those behind the tool contract and added the hard one. Every financial
number in the system is now produced by a `DeterministicTool`, and the contract is enforced
rather than described: a subclass missing an `@abstractmethod` fails to instantiate, which is the
direct fix for C-11 — the original ABC had none, so a tool that forgot `verify` silently
inherited a no-op body and published unverified numbers.

`run()` owns the order — validate, scope, execute, verify, evidence — so no caller can get it
wrong, and a failing `VerificationResult` raises before any output leaves the tool.

### The bridge closes, and the largest term is not the story

`finance.revenue_analysis` reproduces the golden bridge to the paise, with a **zero** rounding
residual, and the attribution table agrees with `ground_truth.json` term for term:

```text
                          prior          current
attempts                    429              361
success rate           0.958042         0.944598
gross payments   Rs 4,86,920.00   Rs 4,06,260.00
net revenue      Rs 4,73,424.82   Rs 3,90,122.95

net change       -Rs 83,301.87   (-0.175956)
  ATTEMPT_VOLUME    -Rs 77,452.68     0.929783
  SUCCESS_RATE       -Rs 3,207.32     0.038502
  REFUNDS            -Rs 2,336.00     0.028043
  FEES                  Rs 418.13    -0.005019
  CHARGEBACKS          -Rs 724.00     0.008691
  residual                      0 paise
```

The volume and rate effects are one rounding and its exact remainder rather than two independent
roundings — rounding both is how a bridge stops closing, and C-02's stated causes summed to 51%
of the decline they claimed. Refunds, fees and chargebacks enter as **deltas**, negated. The
unresolved ₹1,840 is nowhere in the table: it is a `confidence_band_ratio` of `0.004716`, a bound
on the answer rather than a driver of it.

Reconciliation is an *input* to this, not a report beside it. The fixture has 342 ledger records
and 341 payments; only the run knows which one is the duplicate, so a revenue figure computed
without it is overstated by exactly one payment with nothing to indicate it
([D-32](docs/decisions.md#d-32--reconciliation-is-an-input-to-revenue-not-a-report-published-beside-it)).

### A formula language too weak to be the tool

Layer 4 of verification will re-evaluate each metric's declared formula and demand the same
number. That check is only worth something if the language cannot re-run the tool, so
`evidence/formula.py` parses to an AST and admits named operands, integer literals, unary minus,
`+ - * /` and parentheses. Nothing else. No calls, no attribute access, no subscripts, no `**`,
no floats, no globals — `__import__` is not special-cased, because it is a call and calls do not
exist here. It returns an exact unrounded `Decimal`; the single rounding stays in
`runtime/money.py`.

The integration suite already runs that check for real: every published formula is re-evaluated
through the interpreter and must land on the published value.

Leaf metrics carry an `Aggregation` instead — operation, field, record set, predicate — because a
sum over 341 records has no arithmetic to re-evaluate, and giving it a decorative formula would
make layer 4 a check that passes by construction
([D-29](docs/decisions.md#d-29--evidence-carries-a-formula-or-an-aggregation-never-both-never-neither)).

Phase 4 finished the metric coverage: `payments.failure_analysis`,
`finance.refund_analysis`, `risk.chargeback_analysis`, and the vocabulary that decides what any
of them may say.

### A name is not allowed to mean two things

`evidence/vocabulary.py` is the authority on which metric ids exist, and it is enforced twice: a
tool declaring an unregistered id fails **at import**, and an evidence row whose unit disagrees
with its id is refused. The unit is never passed alongside a metric — it is read from the id, so
a tool cannot disagree with itself about what it is publishing.

That is what finally closes C-04. A ratio published under a `_pp` field renders as a plausible
number meaning something else, and every check downstream passes.

`by_method.success_rate_ratio` is a different metric id from `success_rate_ratio`, which is the
fix for C-03 — the vision quoted a UPI rate of 96.8% falling to 82.9% beside a portfolio claim of
"14.3% more failures", with no derivation between them and no unit on the second. An explainer
now cannot substitute one for the other, because they do not share a name.

### The blended rate is the summed counts, not an average

```text
                             prior     current    change
blended                     95.80%      94.46%  -1.34 pp
  CARD                      92.75%      93.10%   0.35 pp
  NETBANKING                96.00%      95.24%  -0.76 pp
  UPI                       96.44%      94.62%  -1.82 pp
  WALLET                    96.15%      95.45%  -0.70 pp
technical declines           0.70%       2.22%   1.52 pp
business declines            3.50%       3.32%  -0.17 pp
```

Those two bottom rows are the diagnosis. Technical declines more than triple while business
declines stay flat — that asymmetry is what attributes the movement to the rails rather than to
customers running out of money. Either rate on its own says nothing.

CARD went *up* while the portfolio went down, which is the sort of thing an average of rail rates
hides and a summed-count identity does not.

### Three tools, one number

`revenue.gross_payments_paise == failure.succeeded_value_paise`, exactly, along with the other two
declared equivalences:

```text
ok  gross_payments_paise == succeeded_value_paise   {40626000} / {40626000}
ok  refunds_paise        == refund_value_paise      {1178200}  / {1178200}
ok  chargebacks_paise    == chargeback_value_paise  {174700}   / {174700}
```

That holds by construction rather than by luck: every tool scopes its records through one shared
function, and all four take the reconciliation `run_id` — which the spec asked for only on
revenue, making its own consistency requirement unsatisfiable
([D-35](docs/decisions.md#d-35--the-three-analysis-tools-take-a-run_id-which-the-spec-did-not-ask-for)).

Phase 5 turned all of that from something the tools assert about themselves into something a
separate layer re-derives.

### Nothing is believed, including the tool that just checked itself

```text
  ok   TYPE         133 checks
  ok   RANGE        161 checks
  ok   CONSISTENCY   10 checks
  ok   FORMULA      189 checks
  ok   SOURCE       225 checks

status      EXPLAINING
```

Five layers, in order, and a layer runs only if every layer before it passed. That is not an
optimisation: a formula re-evaluated against operands that failed their range check produces a
number nobody should read, and reporting it beside a range failure invites someone to pick
whichever they prefer.

Layer 4 does not ask a tool what it computed. It reads the tool's own declared expression,
re-evaluates it through the restricted interpreter — a grammar with no calls, so it cannot re-run
the tool — and demands the same number. Change `net_revenue_paise` by **one paise** and every other
check in the system still passes: the operands each still agree with the row they cite, the bridge
identity in the tool's own `verify()` is untouched, and only the re-evaluation notices.

Layer 5 is where a leaf is checked, because a leaf has no arithmetic. `gross_payments_paise` is
re-summed from the 341 records it names, straight out of the table, and must land on the published
figure.

### "Inside the period" is four questions, not one

Layer 5 has to know *which date* selects a record, and there is no single answer:

```text
ATTEMPT_DATE          a payment belongs to the window it was attempted in
CAPTURE_DATE          the ledger is captures; a settlement is due against one
PARENT_ATTEMPT_DATE   a refund belongs to the window of the payment it reverses
VALUE_DATE            a settlement lands in the bank window, not the capture one
```

So the evidence declares the rule it used, and layer 5 checks *that* rule
([D-37](docs/decisions.md#d-37--evidence-declares-the-date-rule-that-scoped-it)). A tool that
declares one scoping and applies another is now caught — nothing else in the system would notice.
Writing it down immediately found a real defect: `bank_count` was filed under the analysis window
while citing 341 settlements with September value dates, and layer 5 refused it, correctly
([D-39](docs/decisions.md#d-39--bank_count-is-filed-under-the-bank-window-not-the-analysis-window)).

### A number walks down to the records

```text
net_revenue_change_ratio = -0.175956
  (current - prior) / prior
    net_revenue_paise = 39012295          gross - refunds - fees - chargebacks
      gross_payments_paise = 40626000     -> 341 transactions
      refunds_paise        =  1178200     -> 10 refunds
      fees_paise           =   260805     -> 341 transactions
      chargebacks_paise    =   174700     -> 3 chargebacks
    net_revenue_paise = 47342482          (the July window, the same way down)

reaches 775 source records
```

`provenance/builder.py` knows nothing about revenue. Every level is an `Evidence` row that either
declares a formula — so its operands are references to more rows — or declares a fold, so it cites
records and the walk stops. That is what lets the drawer be one recursive renderer instead of a
component per metric, and it is why a derived row may no longer cite records directly: a node with
both has two accounts of where its number came from and nothing keeps them in step
([D-40](docs/decisions.md#d-40--a-derived-metric-cites-operands-a-leaf-cites-records-never-both)).

A cycle is refused rather than truncated. A half-rendered provenance tree looks complete, which is
worse than one that says the chain is broken.

### BLOCKED is a row, and it carries nothing

```text
VERIFYING  -> BLOCKED      a layer failed; error_json names it; no prose, ever
           -> EXPLAINING   every layer passed; the numbers may now be phrased
```

A blocked execution stores **no evidence at all**, and `GET /executions/{id}/evidence/{id}` answers
409 naming the layer rather than 404. A stored row is something the API serves and the drawer
walks; serving the support for a number that failed verification is exactly how an unverified
figure reaches a reader *with a citation attached*
([D-43](docs/decisions.md#d-43--a-blocked-execution-is-a-row-and-it-stores-no-evidence)).

The evidence id is also the URL: `.../evidence/finance.revenue_analysis/1.0/net_revenue_change_ratio/2026-08-01_2026-08-24`.
A dimensioned row appends its slice after a **tilde**, not a `#` — a fragment never reaches the
server, so a request for the UPI rate would have silently returned the blended one
([D-42](docs/decisions.md#d-42--the-evidence-ids-slice-separator-is--not-)).

**Next: Phase 6 — the agent runtime, and the first LLM call in the project.** Intent parsing with a
confidence threshold, the deterministic intent-to-DAG planner, eleven plan validation checks, and
the nine-state machine over an append-only event log.

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
