# 08 — Seed Data, Calibration, and the Ground Truth

The synthetic dataset is not filler. It is the specification's test fixture: every headline number
in the product, the demo and the docs is asserted against it.

## What is claimed, and what is not

> **Transaction-level records are synthetic and seeded.** No real customer, merchant, or bank
> record is represented. Aggregate distributions and operational characteristics are **calibrated
> against public NPCI/RBI statistics**. Failure rates are not Razorpay's; the incident is invented.

Every calibration parameter carries a provenance tag — `CITED`, `DERIVED` or `ASSUMED` — and
[`data/calibration/sources.md`](../data/calibration/sources.md) redeems each one with a URL and a
retrieval date. `ASSUMED` is not an apology: a single merchant's payment mix is not a published
statistic and never will be. What matters is that a design choice is never mistaken for an
observation ([D-23](decisions.md#d-23--the-dataset-is-market-calibrated-not-arbitrary)).

The API serves this at `GET /api/v1/provenance`, generated from the calibration layer rather than
written by hand — a provenance statement maintained separately from the parameters it describes
goes stale in a week.

## The pipeline

```text
public NPCI / RBI statistics
        |
        v
calibration parameters          data/calibration/   every one tagged
        |
        v
scenario definition             data/scenarios/     the hidden world
        |
        v
synthetic generator             data/seed/generate_seed_data.py
        |
        +--> ledger_side.csv
        +--> bank_settlement.csv
        +--> seed.sql
        +--> golden/ground_truth.json
        +--> golden/checksums.json
```

## Counts are designed. Money is derived.

The scenario fixes the **capture counts** and the **planted anomaly counts**. Everything else —
failures, ticket values, fees, success rates, decline rates, and the revenue decline itself —
emerges from the calibration layer ([D-26](decisions.md#d-26--counts-are-designed-money-is-derived)).

That is the line between choosing the shape of a story and choosing its answer, and it changes what
the fixture assertions can be: they check identities and calibration bands, not hard-coded revenue.

| Rule | Detail |
| --- | --- |
| RNG | `rng = random.Random(42)` — a local instance. Never `random.seed()`, which mutates global state and makes output depend on import order. |
| Output | `ledger_side.csv`, `bank_settlement.csv`, `seed.sql`, `golden/ground_truth.json`, `golden/checksums.json` |
| Money | Integer paise throughout, in the CSV too |
| Timestamps | ISO-8601 with explicit `+05:30` offset |
| Totals | Exact **by construction** — largest-remainder apportionment, so the sum is the target to the paise whatever the random weights do |
| Amounts | Whole rupees, with each method's realised mean ticket equal to its calibrated one |
| Ids | Drawn from a seeded shuffle, not assigned chronologically — realistic, and it stops the matcher's lexicographic tie-break from accidentally agreeing with time order. It is why `TXN_183` sits in the August window. |
| Python | Pinned to 3.13 in both `pyproject.toml` and the API image ([D-17](decisions.md#d-17--python-is-pinned-to-313-not-312)) |
| Reproducibility | `make verify-seed` recomputes SHA-256 of every artifact **and rebuilds the dataset in-process** to compare |

The file was named `razorpay_side.csv` in the vision doc, which implies a live integration the
project explicitly disclaims (vision §43). It is `ledger_side.csv`.

## Payment mix — volume share is not value share

The single most important calibration fact. UPI is dominant by **count** and much less dominant by
**value**, because its ticket is small: NPCI's figures put P2M at ~63% of UPI volume but ~29% of
its value, with ~86% of P2M volume under ₹500.

A generator that assigns one "share" per method and uses it for both count and value is modelling a
world that cannot exist. So each method declares a **volume share** and a **mean ticket**, and the
value share is *derived*:

| Method | Volume share | Value share (derived) | Mean ticket |
| --- | ---: | ---: | ---: |
| `UPI` | 0.720222 | 0.387535 | Rs 640 |
| `CARD` | 0.160665 | 0.378821 | Rs 2,850 |
| `NETBANKING` | 0.058172 | 0.206764 | Rs 4,200 |
| `WALLET` | 0.060942 | 0.026879 | Rs 520 |

`verify-seed` asserts UPI's value share stays *below* its volume share. If that ever inverts, the
low-ticket property has been lost and the dataset no longer resembles Indian payments.

## Fees — per instrument, and the flat 1% is gone

`method` is the rail; **`instrument` is the funding source, and the funding source decides the
fee** ([D-24](decisions.md#d-24--fees-are-per-instrument-and-the-flat-1-is-gone)).

| Instrument | Rule | Provenance |
| --- | --- | --- |
| `UPI_BANK_ACCOUNT` | **0%** — zero MDR by mandate since January 2020 | `CITED` |
| `RUPAY_DEBIT` | **0%** — zero MDR by mandate | `CITED` |
| `UPI_PPI_WALLET` | 1.10% above ₹2,000 | `CITED` |
| `UPI_RUPAY_CREDIT` | 1.50% above ₹2,000 (MDR applies from 01 Jun 2026) | `CITED` |
| `OTHER_DEBIT` | 0.90% | `ASSUMED` |
| `CREDIT_CARD` | 1.90% | `ASSUMED` |
| `NETBANKING` | ₹12 flat per transaction | `ASSUMED` |
| `WALLET` | 1.65% | `ASSUMED` |

The blended effective rate that falls out of this mix is **0.006420** —
nothing like 1%, because the volume-dominant rail is free. `verify-seed` asserts it stays below 1%.

This is what makes a `FEE_DISCREPANCY` a finding rather than noise: the engine reports
`matches_rule_for`, naming the instrument whose rule would have produced the fee the bank actually
charged. "This zero-MDR UPI payment was billed under the credit-card agreement" is actionable.

## Declines — technical versus business

NPCI separates **technical declines** (a bank or NPCI back end failing — timeouts, unavailability,
overload) from **business declines** (the customer's side — wrong PIN, insufficient funds, limit
exceeded), and publishes both per bank, monthly. Ecosystem TD sits at 0.7–0.8% against a target
under 1%; the BD target is under 5% (circular OC-149).

An investigation that cannot separate them can only report that a success rate moved, which is a
symptom rather than a finding. So every failed attempt carries `decline_type` and `decline_reason`,
and a `CHECK` constraint makes a failure without a type impossible.

| | Prior | Current |
| --- | ---: | ---: |
| Attempts | 429 | 361 |
| Captures | 411 | 341 |
| Success rate | 0.958042 | 0.944598 |
| **Technical declines** | **0.006993** | **0.022161** |
| Business declines | 0.034965 | 0.033241 |

Technical declines roughly triple. Business declines stay flat — that asymmetry is the whole basis
for attributing the movement to the platform rather than to customers, and `verify-seed` fails if
business declines drift by more than a point.

## The incident

```text
upi_issuer_degradation
    2026-08-09 -> 2026-08-19
    method    UPI
    issuers   BANK_A, BANK_B, BANK_C

technical declines, affected issuers    0.095890
technical declines, everyone else       0.000000
```

A spike everywhere is weather. A spike at three named issuers, on one rail, inside a dated window,
is a finding.

## The revenue bridge

| | Prior (2026-07-01 → 2026-07-24) | Current (2026-08-01 → 2026-08-24) |
| --- | ---: | ---: |
| Attempted value | Rs 5,12,930 | Rs 4,31,340 |
| Gross successful | Rs 4,86,920 | Rs 4,06,260 |
| Refunds | Rs 9,446 | Rs 11,782 |
| Fees | Rs 3,026 | Rs 2,608 |
| Chargebacks | Rs 1,023 | Rs 1,747 |
| **Net revenue** | **Rs 4,73,424** | **Rs 3,90,122** |

Decline **-Rs 83,301 = -0.175956**, fully attributed with
a **zero** rounding residual:

| Driver | Contribution |
| --- | ---: |
| Attempt-volume decline | -Rs 77,452 |
| Payment success rate | -Rs 3,207 |
| Refund increase | -Rs 2,336 |
| Chargeback increase | -Rs 724 |
| Fee decrease (offset) | Rs 418 |
| Rounding residual | Rs 0 |
| **Total** | **-Rs 83,301** |

**The primary driver is attempt volume, not the incident.** The incident is real and localised, and
it is *not* what moved revenue. `verify-seed` asserts the declared `expected_diagnosis` really is
the largest term in the generated attribution
([D-27](decisions.md#d-27--the-ground-truth-is-checked-against-its-own-dataset)), because a ground
truth that disagrees with its own dataset is worse than none.

That makes the scenario a deliberate trap: the incident is the salient event, and a model reasoning
from narrative rather than arithmetic will name it as the cause.

## Reconciliation

Scoped to the analysis window. Ledger by IST capture date; bank by `bank_period()`
([D-18](decisions.md#d-18--a-reconciliation-run-scopes-its-two-sides-on-different-dates)).

| | |
| --- | ---: |
| Ledger records | 342 |
| Bank records | 341 |
| Matched pairs | 338 |
| — clean | 327 |
| — with exception | 11 |
| Unmatched ledger | 4 |
| Unmatched bank | 3 |
| **Clean match rate** | **0.956140** |
| **Exceptions** (ledger-side) | **15** |

| Category | Count | How it is planted |
| --- | ---: | --- |
| `TIMING_LAG` | 7 | Settlement `value_date` pushed 1–3 business days past the SLA |
| `NO_COUNTERPART` | 3 | Ledger rows with no bank row (`TXN_183`, `TXN_247`, `TXN_402`) |
| `AMOUNT_MISMATCH` | 2 | Bank amount differs by ₹1 and ₹250 |
| `FEE_DISCREPANCY` | 2 | The bank bills under the **wrong instrument's rule** — a zero-MDR UPI payment charged at the credit-card rate |
| `POSSIBLE_DUPLICATE` | 1 | A second ledger row duplicating an existing UTR and amount |

Unresolved `NO_COUNTERPART` value: **Rs 1,840** across
`TXN_183`, `TXN_247`, `TXN_402` — reported as a confidence band on the figures, never netted into
any of them (I7).

`SETTLEMENT_91` exists in the bank file as a near miss for `TXN_183`: same amount, no reference,
four business days outside the window. It reaches rule 5 at confidence 0.72 and is therefore
recorded as a **rejected candidate**, not a match.

## Verification of the fixture itself

`python scripts/task.py verify-seed` asserts, before any application code runs:

```text
 1. Every artifact matches checksums.json, and regenerates identically
 2. The bridge identity closes to the paise, in both windows
 3. Attribution sums to the net change, with a zero rounding residual
 4. Volume share and value share are different numbers, both calibrated
 5. Technical and business declines exist and behave differently
 6. Fees follow the instrument, and zero-MDR really means zero
 7. Reconciliation invariants I1-I4 hold, and identifiers are unique
 8. Exception counts equal the golden breakdown
 9. Unresolved value is exactly 184000 paise
10. The declared diagnosis is the one the dataset actually supports
```

I5 and I6 are database unique constraints and belong to Phase 2, when match rows exist. What
Phase 1 proves is that the fixture handed to the matcher is arithmetically capable of satisfying
them.
