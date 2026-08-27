# 02 — Data Model

## Money

Fixes [C-01](00-corrections.md#c-01-b--money-representation-was-never-specified).

| Rule | Detail |
| --- | --- |
| Storage | Integer **paise**. Postgres `BIGINT`, Python `int`, JSON integer. |
| Naming | Every money field ends in `_paise`. No exceptions. |
| Float | Never, anywhere, in any code path that touches a money value. |
| Rates | `Decimal` with explicit scale. Fee rate is `Decimal("0.0100")`. |
| Ratios | `Decimal` in `[0, 1]`, scale 6. Field suffix `_ratio`. |
| Rounding | `ROUND_HALF_UP`, applied **once** per calculation at the documented point. |
| Display | Formatting to `₹3,90,122.95` happens only in the web layer. |

`runtime/money.py` is the only module allowed to round:

```python
from decimal import Decimal, ROUND_HALF_UP

Paise = int

def apply_rate(amount_paise: Paise, rate: Decimal) -> Paise:
    """Multiply a paise amount by a rate, rounding half-up to whole paise."""
    return int(
        (Decimal(amount_paise) * rate).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )

def ratio(numerator: Paise, denominator: Paise) -> Decimal:
    """Exact ratio at scale 6. Denominator of zero is a caller error, not a zero result."""
    if denominator == 0:
        raise ZeroDenominatorError("ratio denominator is zero")
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.000001"))
```

Callers never write `round()`, `/`, or `float()` on money. A CI grep enforces this.

## Time

Fixes [C-10](00-corrections.md#c-10-b--no-timezone-or-settlement-cutoff).

| Rule | Detail |
| --- | --- |
| Storage | `TIMESTAMPTZ`, always UTC. |
| Business calendar | `Asia/Kolkata` (IST, UTC+05:30). No DST, which is why this is safe. |
| "Date" | Always the **IST calendar date**, derived in `runtime/calendar.py`. Never `UTC::date`. |
| Capture cutoff | 18:00 IST. Captures after the cutoff settle on the next business day's cycle. |
| Settlement SLA | T+2 business days from the cutoff-adjusted capture date. |
| Business days | Mon–Fri, minus a fixed holiday list in `data/seed/holidays_2026.json`. |
| Period bounds | Half-open `[from, to)` in IST. `2026-08-01 -> 2026-08-24` covers Aug 1–23. |

Half-open intervals are chosen so adjacent periods tile without overlap or gap — vision §11's
`period.start < period.end` rule is kept and joined by an overlap check between the analysis
period and the comparison period.

## Currency

Single currency, `INR`. The column exists on every money-bearing table so the constraint is
visible and so multi-currency is a migration rather than a rewrite. Validation rejects anything
else as `UNSUPPORTED_CURRENCY` ([C-15f](00-corrections.md#c-15-m--other-fixes-applied-without-further-discussion)).

## Tables

Vision §32 plus `reconciliation_runs` ([C-15a](00-corrections.md#c-15-m--other-fixes-applied-without-further-discussion))
and `execution_events`.

### Domain

```text
merchants          id, name, currency, created_at
transactions       id, merchant_id, external_ref, utr,
                   method, instrument, issuer, status,
                   decline_type, decline_reason,
                   amount_paise, fee_paise, currency,
                   attempted_at, captured_at, settlement_due_date, created_at
settlements        id, merchant_id, bank_ref, utr,
                   amount_paise, fee_paise, currency, value_date, created_at
refunds            id, merchant_id, transaction_id, amount_paise, reason, created_at
chargebacks        id, merchant_id, transaction_id, amount_paise, reason, created_at
```

`transactions.status` ∈ `{ATTEMPTED, FAILED, CAPTURED, SETTLED, REFUNDED}`.

`transactions.method` is the **rail** ∈ `{UPI, CARD, NETBANKING, WALLET}`.
`transactions.instrument` is the **funding source**, and the funding source is what decides the
fee ∈ `{UPI_BANK_ACCOUNT, UPI_PPI_WALLET, UPI_RUPAY_CREDIT, RUPAY_DEBIT, OTHER_DEBIT, CREDIT_CARD,
NETBANKING, WALLET}`. Bank-account UPI carries no MDR; the same rail funded from a prepaid wallet
carries an interchange ([D-24](decisions.md#d-24--fees-are-per-instrument-and-the-flat-1-is-gone)).

`transactions.decline_type` ∈ `{TECHNICAL_DECLINE, BUSINESS_DECLINE}`, null on a success. NPCI
distinguishes these and publishes both per bank; a `CHECK` makes a failure without a type
impossible, because the split degrading into "some rows have it" would make every decline rate
computed from it quietly wrong.

`transactions.issuer` is the bank. Without it an incident cannot be localised, and "UPI is failing"
is as far as any investigation can get.

`transactions.utr` is nullable — a missing UTR is precisely what forces the weaker matching rules.

### Reconciliation

```text
reconciliation_runs        id, merchant_id, period_from, period_to,
                           ledger_count, bank_count, matched_pairs,
                           clean_match_rate_ratio, status, created_at
reconciliation_matches     id, run_id, transaction_id, settlement_id,
                           rule, confidence_ratio, reason,
                           amount_delta_paise, lag_days
reconciliation_exceptions  id, run_id, category, side,
                           transaction_id, settlement_id,
                           amount_paise, status, detail_json
```

`reconciliation_matches` has a **unique constraint on `(run_id, transaction_id)` and on
`(run_id, settlement_id)`** — this is the one-to-one guarantee from
[C-07](00-corrections.md#c-07-b--matching-has-no-assignment-rule-so-it-is-not-reproducible)
enforced by the database rather than trusted to the matcher.

### Agent

```text
agent_executions   id, user_id, merchant_id, input,
                   intent_json, plan_json,
                   period_from, period_to,
                   status, error_json,
                   grounding_attempts, seed,
                   created_at, updated_at, completed_at
tool_executions    id, execution_id, tool_name, tool_version,
                   input_json, output_json, status, error_json,
                   started_at, finished_at, duration_ms
evidence           id, execution_id, tool_name, tool_version,
                   metric_id, unit, value_json,
                   formula_json, inputs_json,
                   source_record_ids, rules_applied, verification_checks,
                   created_at
execution_events   id, execution_id, seq, kind, payload_json, created_at
```

`execution_events` is append-only and monotonically sequenced per execution. It backs both the
SSE stream and the execution-history UI, so replaying a finished run and watching a live one use
the same code path.

## Authz

Fixes [C-15k](00-corrections.md#c-15-m--other-fixes-applied-without-further-discussion).
Vision §11 requires permission validation but defines no model.

```text
users              id, email, created_at
merchant_members   user_id, merchant_id, role
```

`role` ∈ `{OWNER, ANALYST, VIEWER}`.

| Capability | OWNER | ANALYST | VIEWER |
| --- | :-: | :-: | :-: |
| Read dashboards, exceptions, provenance | yes | yes | yes |
| Run the agent | yes | yes | no |
| Resolve / annotate an exception | yes | yes | no |
| Manage members | yes | no | no |

**`merchant_id` always comes from the session, never from the model**
([C-13](00-corrections.md#c-13-b--agentexecution-and-the-api-cannot-scope-to-a-merchant)).
The intent parser receives the merchant id as *context* and is forbidden from emitting a
different one; the validator rejects any mismatch as `MERCHANT_SCOPE_VIOLATION`.

Postgres row-level security is enabled on every merchant-scoped table with the policy
`merchant_id IN (SELECT merchant_id FROM merchant_members WHERE user_id = auth.uid())`. The API
uses the caller's Supabase JWT rather than the service key for all read paths, so a scoping bug
in application code cannot leak another tenant's data.

## Indexes that matter

```sql
CREATE INDEX ON transactions (merchant_id, captured_at);
CREATE INDEX ON transactions (merchant_id, utr) WHERE utr IS NOT NULL;
CREATE INDEX ON settlements  (merchant_id, value_date);
CREATE INDEX ON settlements  (merchant_id, utr) WHERE utr IS NOT NULL;
CREATE INDEX ON execution_events (execution_id, seq);
```

The partial UTR indexes exist because rule 1 of the matcher is an exact UTR join and it runs
against the whole period on every reconciliation.
