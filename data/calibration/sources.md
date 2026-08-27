# Calibration Sources

Every parameter in `parameters.py` carries a provenance tag. This file is where each tag is
redeemed.

> **What is and is not being claimed.** Transaction-level records in this project are **synthetic
> and seeded**. No real customer, merchant, or bank record is represented. What is calibrated
> against public data is the *shape* of the synthetic world — payment-method mix, ticket-size
> distributions, decline taxonomy and rates, and fee rules. The specific merchant's mix, the
> incident, and every individual row are invented.

## Provenance tags

| Tag | Meaning |
| --- | --- |
| `CITED` | Taken from a named public source. URL and retrieval date below. |
| `DERIVED` | Computed from one or more `CITED` figures. The derivation is in the code. |
| `ASSUMED` | A synthetic choice. Anchored on cited facts where possible, but not itself a published figure. Every one carries a rationale. |

An `ASSUMED` parameter is not a weakness — a single merchant's payment mix is not a published
statistic and never will be. What matters is that it is *labelled*, so nobody mistakes a design
choice for an observation.

Retrieved **2026-08-26**. Figures published monthly; re-check before quoting in a live demo.

---

## UPI volume and value

| Figure | Value | Tag |
| --- | --- | --- |
| UPI transactions, May 2026 | 23,201.93 million | `CITED` |
| UPI value, May 2026 | ₹29,90,424.21 crore | `CITED` |
| UPI transactions, June 2026 | 22,716.07 million (−2.09% MoM) | `CITED` |
| UPI volume, FY 2025-26 | 24,162 crore transactions (+30.0% YoY) | `CITED` |
| UPI value, FY 2025-26 | ₹314 lakh crore (+20.59% YoY) | `CITED` |
| Overall UPI average ticket size, 2026 | ≈ ₹1,293 | `CITED` |

Sources:
- NPCI, *UPI Product Statistics* — <https://www.npci.org.in/what-we-do/upi/product-statistics>
  (the page blocks automated fetching; figures above corroborated through secondary reporting)
- PIB, *UPI completes 10 years* — <https://www.pib.gov.in/PressReleasePage.aspx?PRID=2257087>
- Business Today, *10 years of UPI: transaction value surges to ₹314 lakh crore* (2026-08-24) —
  <https://www.businesstoday.in/india/story/10-years-of-upi-transaction-value-surges-4000-fold-to-reach-rs314-lakh-crore-550975-2026-08-24>

## P2M versus P2P — why volume share ≠ value share

| Figure | Value | Tag |
| --- | --- | --- |
| P2M share of UPI **volume** | ≈ 63% | `CITED` |
| P2M share of UPI **value** | ≈ 29% | `CITED` |
| P2P share of UPI volume / value | ≈ 37% / 71% | `CITED` |
| P2M transactions under ₹500 | ≈ 86% of P2M volume | `CITED` |

This is the single most important calibration fact in the project: **UPI is dominant by count and
much less dominant by value**, because its average ticket is small. A generator that assigns one
"share" per method and uses it for both count and value produces a world that cannot exist.

Sources:
- NPCI ecosystem statistics, as reported by productgrowth.in —
  <https://productgrowth.in/insights/india/upi-market-data/>
- Business Standard, *Avg ticket size on UPI dips 10%, rises 22.6% on cards* —
  <https://www.business-standard.com/amp/finance/news/avg-ticket-size-on-upi-dips-10-rises-22-6-on-cards-in-h12023-report-123092600981_1.html>

## Decline taxonomy — TD and BD

NPCI distinguishes **Technical Declines** (back-end failures at a bank or at NPCI — timeouts,
unavailability, system overload) from **Business Declines** (user- or merchant-side — wrong PIN,
insufficient funds, limit exceeded, invalid beneficiary), and publishes per-bank TD/BD and uptime
monthly.

| Figure | Value | Tag |
| --- | --- | --- |
| Ecosystem technical-decline rate, 2025 | 0.7–0.8% | `CITED` |
| Technical-decline rate, 2016 | 8–10% | `CITED` |
| NPCI target, TD | < 1% | `CITED` |
| NPCI target, BD | < 5% (circular OC-149, June 2022) | `CITED` |
| Overall UPI success rate | ≈ 99.2% | `CITED` |

Sources:
- NPCI, *UPI Ecosystem Statistics* (BD/TD & uptime) —
  <https://www.npci.org.in/what-we-do/upi/upi-ecosystem-statistics>
- NPCI circular OC-149A, *Reduction of business declines in UPI* —
  <https://www.npci.org.in/PDF/npci/upi/circular/2022/OC149-A-Addendum-to-OC-149-Reduction-of-business-declines-in-UPI.pdf>
- D91 Labs, *Why UPI Success Rate matters* — <https://d91labs.substack.com/p/why-upi-success-rate-matters>

## Fee rules — MDR

| Rule | Tag |
| --- | --- |
| Zero MDR on bank-account-funded UPI and on RuPay debit, mandated since January 2020 | `CITED` |
| PPI-funded UPI ("wallet on UPI") carries an interchange of up to **1.1%** above ₹2,000 | `CITED` |
| RuPay credit on UPI: MDR applies above ₹2,000, ≈1.1%–2%, from 01 June 2026 | `CITED` |
| Taxation and Other Laws (Amendment) Bill 2026 amends the PSS Act 2007 to permit fees on UPI / RuPay debit; proposals discuss up to 0.4% above ₹2,000 for large merchants | `CITED` |
| **Zero MDR ≠ zero platform fee.** A payment gateway may charge its own fee where MDR is nil | `CITED` |

This is why the original flat 1% fee had to go: it is not merely imprecise, it is the wrong
*shape*. Under a flat rate a fee discrepancy is arithmetic noise. Under an instrument-dependent
schedule, a fee discrepancy means a specific commercial rule was applied wrongly — which is a
finding an analyst can act on.

Sources:
- Razorpay, *UPI MDR for merchants explained* —
  <https://razorpay.com/blog/upi-mdr-for-merchants-in-payment-gateway-explained/>
- Razorpay, *Debit card MDR in payment gateway explained* —
  <https://razorpay.com/blog/debit-card-mdr-in-payment-gateway-explained/>
- Business Today, *How much MDR could be charged on UPI and RuPay* (2026-08-11) —
  <https://www.businesstoday.in/latest/economy/story/heres-how-much-mdr-could-be-charged-on-upi-and-rupay-transactions-548523-2026-08-11>
- PIB, *Advancing Cashless India* — <https://www.pib.gov.in/PressReleasePage.aspx?PRID=2114335>

## Settlement timing

No universal statutory T+2 exists for Indian payment-gateway settlement; it is a commercial term
that varies by acquirer, merchant risk category, and instrument. The project therefore treats it
as a **scenario parameter**, not a law
([D-25](../../docs/decisions.md#d-25--settlement-timing-is-a-scenario-parameter-not-a-law)).
The fixture uses T+2 business days from an 18:00 IST cutoff, tagged `ASSUMED`.

## What could not be sourced

| Wanted | Status |
| --- | --- |
| A single online merchant's split across UPI / cards / netbanking / wallet | Not a published statistic. `ASSUMED`, anchored on the ecosystem facts above. |
| Per-issuer TD rates for named banks | NPCI publishes these per bank monthly; the fixture uses synthetic issuer names, so real per-bank figures would be misleading here. `ASSUMED`. |
| RBI Payment System Indicators, machine-readable series | <https://statistics.rbi.org.in/> publishes these; not ingested. Card and netbanking mix is `ASSUMED`. |

Nothing in this table is fabricated to look sourced. Where a figure could not be obtained, the
parameter says `ASSUMED` and this file says why.
