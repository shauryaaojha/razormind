# 08 — Seed Data and the Golden Story

The synthetic dataset is not filler. It is the specification's test fixture: every headline number
in the product, the demo and the docs is asserted against it.

## Generator rules

Fixes [C-15d/C-15e/C-15i](00-corrections.md#c-15-m--other-fixes-applied-without-further-discussion).

| Rule | Detail |
| --- | --- |
| RNG | `rng = random.Random(42)` — a local instance. Never `random.seed()`, which mutates global state and makes output depend on import order. |
| Output | `data/seed/ledger_side.csv`, `data/seed/bank_settlement.csv`, `data/seed/seed.sql` |
| Money | Integer paise throughout, in the CSV too |
| Timestamps | ISO-8601 with explicit `+05:30` offset |
| Reproducibility | `make seed` then `make verify-seed` recomputes SHA-256 of both CSVs and compares against `data/seed/golden/checksums.json`. A mismatch fails CI. |
| Python | Pinned to 3.13 in both `pyproject.toml` and the API image; `rng.shuffle`/`rng.sample` semantics are stable within a minor release, so the image is part of the fixture ([D-17](decisions.md#d-17--python-is-pinned-to-313-not-312)) |

The file was named `razorpay_side.csv` in the vision doc, which implies a live integration the
project explicitly disclaims (vision §43). It is `ledger_side.csv`.

## Shape

```text
Span             90 days, 2026-05-26 -> 2026-08-24 (IST, half-open)
Merchant         M123, single merchant, INR only
Attempts         ~1,600 payment attempts
Successful       ~1,480
Methods          UPI 46.66% of attempted value, CARD, NETBANKING, WALLET
Analysis window  2026-08-01 -> 2026-08-24   (current, 23 days)
Comparison       2026-07-01 -> 2026-07-24   (prior,   23 days)
Reconciliation   scoped to the analysis window: 342 ledger, 341 bank records
```

The vision doc said "300–500 transactions" while also showing a 342-record reconciliation for a
23-day window; those cannot both hold. The dataset is ~1,600 attempts over 90 days, of which the
current window contributes 342 settlement-eligible ledger records.

## The golden story

A deliberate, coherent operational narrative — not random noise. This is what makes the demo a
diagnosis rather than a statistics readout.

```text
UPI issuer degradation from 2026-08-06
        |
        v
UPI success rate 96.8% -> 82.9%   (-13.9 pp)
        |
        v
blended success rate 96.81% -> 90.32%   (-6.49 pp)
        |
        +-- compounded by an 11.03% drop in attempted volume
        |
        v
gross successful value falls Rs 8,76,800
        |
        +-- refunds up Rs 24,000
        +-- chargebacks up Rs 7,500
        +-- fees down Rs 8,768 (mechanical, follows gross)
        |
        v
net revenue -18.00%
```

Alongside, and deliberately *not* part of the revenue story:

```text
settlement timing lag      7 exceptions
duplicate settlement       1 exception
fee discrepancy            2 exceptions
missing counterpart        3 exceptions, Rs 18,400 unresolved
amount mismatch            2 exceptions
```

## Golden figures

Every number below is asserted by `tests/test_golden_story.py`. Fixes
[C-02](00-corrections.md#c-02-b--the-flagship-demos-revenue-bridge-does-not-close) and
[C-03](00-corrections.md#c-03-m--the-upi-figure-was-disconnected-from-the-headline).

### Revenue bridge

| | Prior (Jul 1–23) | Current (Aug 1–23) | Change |
| --- | ---: | ---: | ---: |
| Attempted value | ₹53,30,000 | ₹47,42,000 | −11.03% |
| Success rate (blended) | 96.81% | 90.32% | −6.49 pp |
| Gross successful | ₹51,60,000 | ₹42,83,200 | −₹8,76,800 |
| Refunds | ₹1,00,000 | ₹1,24,000 | +₹24,000 |
| Fees @ 1.00% | ₹51,600 | ₹42,832 | −₹8,768 |
| Chargebacks | ₹11,000 | ₹18,500 | +₹7,500 |
| **Net revenue** | **₹49,97,400** | **₹40,97,868** | **−₹8,99,532** |
| | | | **−18.00%** |

Fees are exactly 1.00% of gross in both periods, which is what makes `FEE_DISCREPANCY` detectable
as a deviation rather than a modelling artifact.

### Attribution

```text
volume_effect        = rate_prior * (attempted_curr - attempted_prior)
success_rate_effect  = attempted_curr * (rate_curr - rate_prior)
```

| Driver | Contribution | Share |
| --- | ---: | ---: |
| Attempt-volume decline | −₹5,69,246 | 63.3% |
| Payment success-rate decline | −₹3,07,554 | 34.2% |
| Refund increase | −₹24,000 | 2.7% |
| Chargeback increase | −₹7,500 | 0.8% |
| Fee decrease (offset) | +₹8,768 | −1.0% |
| Rounding residual | ₹0 | 0.0% |
| **Total** | **−₹8,99,532** | **100.0%** |

The residual is zero for this fixture but the field is mandatory
([06-trust-layer.md](06-trust-layer.md#bridge-identity)) — the rate/volume split is fractional in
general and the identity must close by construction, not by luck.

### Method mix consistency

The blended rate is not asserted independently; it must *fall out* of the method mix:

```text
UPI share of attempted value        46.66%
UPI success        96.8% -> 82.9%
non-UPI success    96.82% (flat)

blended prior   = 0.4666 * 96.8  + 0.5334 * 96.82 = 96.81%
blended current = 0.4666 * 82.9  + 0.5334 * 96.82 = 90.32%
```

This is the fix for C-03: in the original spec the UPI figure and the headline figure were
unrelated numbers that happened to sit in the same document.

### Reconciliation

| | |
| --- | ---: |
| Ledger records | 342 |
| Bank records | 341 |
| Matched pairs | 338 |
| — clean | 327 |
| — with exception | 11 |
| Unmatched ledger | 4 |
| Unmatched bank | 3 |
| **Clean match rate** | **95.61%** |
| **Exceptions** | **15** |

| Category | Count |
| --- | ---: |
| `TIMING_LAG` | 7 |
| `NO_COUNTERPART` | 3 |
| `AMOUNT_MISMATCH` | 2 |
| `FEE_DISCREPANCY` | 2 |
| `POSSIBLE_DUPLICATE` | 1 |

Unresolved value: `TXN_183` ₹8,400 + `TXN_247` ₹6,200 + `TXN_402` ₹3,800 = **₹18,400**
(0.45% of net revenue, reported as a confidence band).

`SETTLEMENT_91` exists in the bank file as a near-miss for `TXN_183`: same amount, no reference,
4 days outside the window. It matches rule 5 at confidence 0.72 and is therefore recorded as a
**rejected candidate**, not a match.

## Planting the exceptions

Each is injected deterministically at a fixed index so the counts never drift:

| Exception | How it is planted |
| --- | --- |
| `TIMING_LAG` × 7 | Settlement `value_date` pushed 1–3 business days past `settlement_due_date` |
| `AMOUNT_MISMATCH` × 2 | Bank amount differs by ₹1 and ₹250 |
| `FEE_DISCREPANCY` × 2 | Bank fee set to 1.35% and 0.62% instead of 1.00% |
| `NO_COUNTERPART` × 3 | Ledger rows written with no bank row (`TXN_183`, `TXN_247`, `TXN_402`) |
| `POSSIBLE_DUPLICATE` × 1 | A second ledger row duplicating an existing UTR and amount |
| `unmatched_bank` × 3 | Bank rows with no ledger row, one of which is `SETTLEMENT_91` |

## Verification of the fixture itself

`make verify-seed` asserts, before any application code runs:

```text
1. CSV checksums match golden/checksums.json
2. The bridge identity closes to the paise
3. Attribution sums to the net change, residual within tolerance
4. The blended success rate equals the method-mix computation
5. Reconciliation invariants I1-I6 hold (03-reconciliation.md)
6. Exception counts equal the golden breakdown
7. Unresolved value equals 1840000 paise
```

If the fixture is wrong, nothing downstream can be trusted — so these run first, in Phase 1,
before the reconciliation engine exists.
