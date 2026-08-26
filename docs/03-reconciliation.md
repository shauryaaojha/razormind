# 03 — Reconciliation Engine

The foundation of the platform. Everything else consumes its output.

## Inputs and outputs

```text
transactions (ledger side)  +  settlements (bank side)
              |
              v
      ReconciliationRun
              |
     +--------+--------+
     |                 |
  matches         exceptions
```

Scope is always `(merchant_id, period_from, period_to)`. A run is immutable once written; re-running
a period creates a new `reconciliation_runs` row. This is what makes "which numbers did we see on
the 24th?" answerable.

The two sides are scoped on **different dates**, because they carry different dates for the same
payment: the ledger side by IST capture date, the bank side by `bank_period(from, to)` — the same
window shifted forward by the T+2 SLA and widened at the far end by the timing-lag ceiling
([D-18](decisions.md#d-18--a-reconciliation-run-scopes-its-two-sides-on-different-dates)).

## Record outcomes

Fixes [C-06](00-corrections.md#c-06-b--matched--exceptions--total_records-is-false-for-two-sided-reconciliation).
Every ledger record lands in exactly one bucket:

| Outcome | Meaning |
| --- | --- |
| `MATCHED_CLEAN` | Paired, no discrepancy |
| `MATCHED_WITH_EXCEPTION` | Paired, but flagged (`TIMING_LAG`, `AMOUNT_MISMATCH`, `FEE_DISCREPANCY`) |
| `UNMATCHED` | Not paired (`NO_COUNTERPART`, `POSSIBLE_DUPLICATE`) |

Bank records are either paired or `unmatched_bank` (side = `BANK`, category `NO_COUNTERPART`).

### Invariants

```text
I1  matched_clean + matched_with_exception + unmatched_ledger == ledger_count
I2  2 * matched_pairs + unmatched_ledger + unmatched_bank == ledger_count + bank_count
I3  matched_pairs == matched_clean + matched_with_exception
I4  clean_match_rate_ratio == matched_clean / ledger_count,  in [0, 1]
I5  every transaction_id appears in at most one match row per run
I6  every settlement_id appears in at most one match row per run
I7  sum(exception.amount_paise) is reported, never silently netted into any revenue figure
```

The published `exception_count` is **ledger-side**: exactly the ledger records that are not
`MATCHED_CLEAN`. Bank rows with no counterpart are written with `side = BANK` and reported as
`unmatched_bank` — one missing settlement is one discrepancy, not two
([D-20](decisions.md#d-20--the-published-exception-count-is-ledger-side)). Verification asserts
both `exception_count == ledger_count - matched_clean` and
`len(bank exceptions) == unmatched_bank`, so the two readings cannot diverge.

An **empty ledger side raises** rather than reporting a zero match rate: "we matched none" and
"there were none" are different facts
([D-22](decisions.md#d-22--an-empty-period-is-refused-not-answered-with-a-zero-match-rate)).

I5 and I6 are database unique constraints, not assertions
([02-data-model.md](02-data-model.md#reconciliation)).

## Assignment

Fixes [C-07](00-corrections.md#c-07-b--matching-has-no-assignment-rule-so-it-is-not-reproducible).
The original spec listed five rules but never said how candidates are consumed, so two correct
implementations could disagree on the match rate.

**Algorithm: greedy, strict rule order, one-to-one, total tie-break.**

```text
for rule in RULES (in priority order 1..5):
    candidates = [(txn, stl) for unconsumed txn, unconsumed stl if rule.matches(txn, stl)]
    sort candidates by rule.tie_break_key          # total order, see below
    for (txn, stl) in candidates:
        if txn unconsumed and stl unconsumed:
            emit match(txn, stl, rule, confidence, reason)
            mark both consumed
```

A rule never revisits a record consumed by a higher-priority rule. This makes the result a pure
function of `(ledger set, bank set)` — no dependence on database row order, dict iteration order,
or concurrency.

### Rules

| # | Rule | Predicate | Confidence |
| :-: | --- | --- | :-: |
| 1 | `EXACT_UTR` | `utr` equal, both non-null, `amount_paise` equal, `lag_days <= 3` | 1.00 |
| 2 | `REF_AMOUNT` | `external_ref == bank_ref`, `amount_paise` equal, `lag_days <= 3` | 0.98 |
| 3 | `REF_DATE_WINDOW` | `external_ref == bank_ref`, `\|lag_days\| <= 3` | 0.90 |
| 4 | `AMOUNT_DATE_WINDOW` | `amount_paise` equal, `\|lag_days\| <= 2`, amount unique among candidates | 0.85 |
| 5 | `AMOUNT_DATE_CANDIDATE` | `amount_paise` equal, `\|lag_days\| <= 5` | 0.72 |

**Auto-match threshold is `0.85`.** Rules 1–4 auto-match. Rule 5 produces a *candidate* recorded
on the exception, not a match — it is what the provenance drawer shows when a user asks "why is
this unmatched?" ([C-08](00-corrections.md#c-08-m--18400-is-defined-two-incompatible-ways)).

Rules 1 and 2 inherit the three-business-day ceiling that the exception table states for
everything else. The spec left it implicit for them; without it an exactly-matching UTR would pair
records a month apart, and `TIMING_LAG` would be unreachable for the rules that produce most of
the pairs.

### Tie-break key

Applied within a single rule, in order, first difference wins:

```text
1. abs(amount_delta_paise)     ascending
2. abs(lag_days)               ascending
3. settlement.value_date       ascending
4. settlement.id               lexicographic ascending
5. transaction.id              lexicographic ascending
```

Steps 4–5 are the guarantee of totality: no two distinct candidate pairs can compare equal, so
the sort is stable regardless of the sorting algorithm.

## Exception categories

Fixes [C-09](00-corrections.md#c-09-m--exception-category-names-are-inconsistent).
Canonical `UPPER_SNAKE_CASE`; display labels live in one map in the web app.

| Category | Side | Raised when | Paired? |
| --- | --- | --- | :-: |
| `TIMING_LAG` | LEDGER | Matched, `0 < lag_days <= 3` beyond the T+2 SLA | yes |
| `AMOUNT_MISMATCH` | LEDGER | Matched, `amount_delta_paise != 0` | yes |
| `FEE_DISCREPANCY` | LEDGER | Matched, fee outside tolerance (below) | yes |
| `NO_COUNTERPART` | LEDGER or BANK | No candidate at or above 0.85, or lag > 3 days | no |
| `POSSIBLE_DUPLICATE` | LEDGER | Would match a settlement already consumed by a higher-priority pair | no |

`POSSIBLE_DUPLICATE` sits in the `UNMATCHED` bucket rather than being a second match — that is a
direct consequence of the one-to-one rule (I5/I6) and is why the duplicate story in the demo
works at all.

### Fee tolerance

Fixes [C-15g](00-corrections.md#c-15-m--other-fixes-applied-without-further-discussion).

```text
expected_fee_paise = apply_rate(amount_paise, Decimal("0.0100"))     # half-up
tolerance_paise    = max(100, apply_rate(expected_fee_paise, Decimal("0.005")))
FEE_DISCREPANCY  <=>  abs(actual_fee_paise - expected_fee_paise) > tolerance_paise
```

The ₹1.00 floor exists so that half-up rounding on small transactions never trips a false
discrepancy.

### Timing lag

```text
lag_days = business_days_between(settlement_due_date, settlement.value_date)
```

`settlement_due_date` is computed at capture time by `runtime/calendar.py`:
cutoff-adjust the capture instant to an IST business date, then add 2 business days
([02-data-model.md](02-data-model.md#time)).

- `lag_days <= 0` — on time or early, no exception
- `0 < lag_days <= 3` — `TIMING_LAG`
- `lag_days > 3` — the pair is not formed at all; the ledger record becomes `NO_COUNTERPART`

## Verification of the run

Before a run is written, `verification/rules.py` asserts I1–I6 and:

```text
clean_match_rate_ratio in [0, 1]
every exception references at least one real record id
every match confidence in [0.72, 1.00]
no match with confidence < 0.85 exists            # rule 5 must not produce matches
sum of exception amounts <= sum of ledger amounts
```

A failed assertion sets the run `status = FAILED` and blocks every downstream tool. It never
writes a partial run — see [06-trust-layer.md](06-trust-layer.md).

## Golden expectation

The seeded dataset must reproduce exactly this
([08-seed-data.md](08-seed-data.md)):

```text
ledger_count             342        bank_count       341
matched_pairs            338        unmatched_bank     3
MATCHED_CLEAN            327
MATCHED_WITH_EXCEPTION    11        TIMING_LAG          7
UNMATCHED                  4        AMOUNT_MISMATCH     2
                                    FEE_DISCREPANCY     2
clean_match_rate_ratio  0.956140    NO_COUNTERPART      3
                                    POSSIBLE_DUPLICATE  1
                                    ------------------ --
                                    exceptions         15
```

Unresolved `NO_COUNTERPART` value: `TXN_183` ₹8,400 + `TXN_247` ₹6,200 + `TXN_402` ₹3,800
= **₹18,400**.
