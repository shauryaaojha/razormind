# 11 — Demo Script

Five minutes, one coherent story, every number traceable. Numbers below come from the generated
ground truth ([08-seed-data.md](08-seed-data.md)) — if the demo shows anything different, the
fixture drifted.

---

## 0:00–0:30 — The problem, and where the data came from

Open on the dashboard.

```text
NET REVENUE   Rs 3,90,122          -17.60%  vs Jul 1-23
```

> "Finance teams can't act on a number an AI generated. They need to know it's right, and where it
> came from. RazorMind never lets the model produce a financial number at all."

Click **Data provenance** before asking anything. It answers the first question a judge will have:

```text
DATA PROVENANCE

Transaction records      Synthetic - seeded (scenario revenue_decline_v1, seed 42)
Aggregate calibration    NPCI UPI statistics - RBI payment system indicators
Parameters               10 CITED - 12 ASSUMED - each tagged, sources.md
Ground truth             Generated deterministically
Checksums                4 artifacts, SHA-256

No production customer data.
```

> "The rows are invented. The *shape* is not — the payment mix, the ticket sizes, the decline rates
> and the fee rules are calibrated against published NPCI and RBI figures, and every parameter says
> whether it is cited or assumed. We are not claiming this is Razorpay's data. We are claiming it
> behaves like the market it models."

Ask: **"Why did revenue fall this month?"**

---

## 0:30–1:15 — The agent works in the open

Stages tick live over SSE — not a spinner:

```text
[x] Intent detected          revenue_diagnosis  (confidence 0.92)
[x] Execution plan generated 5 nodes
[x] Plan validated           periods, permissions, tools
[x] Reconciliation loaded    run rec_01J8ABC
[x] 4 finance tools executed concurrently
[x] Results verified         5 layers passed
[x] Evidence assembled       17 nodes
[x] Explanation generated    grounded
```

> "That's the plan being validated *before* anything runs. An invalid plan is rejected, not
> executed."

---

## 1:15–2:30 — The answer, and the trap it avoids

```text
Net revenue declined 17.60% (-Rs 83,301) versus the prior period.

  Attempt-volume decline        -Rs 77,452
  Payment success rate          -Rs 3,207
  Refund increase               -Rs 2,336
  Chargeback increase           -Rs 724
  Fee decrease (offset)         Rs 418
  Rounding residual             Rs 0
  --------------------------------------------
  Total                         -Rs 83,301

There was a technical-decline incident: UPI at BANK_A, BANK_B, BANK_C,
2026-08-09 to 2026-08-19. Technical declines ran at 9.59%
at those issuers against 0.00% elsewhere.

It is not what moved revenue. Attempt volume is.
```

This is the beat to slow down on.

> "There *is* an incident. It's real, it's dated, it's localised to three named issuers on one
> rail. It is the most conspicuous thing in the window — and it accounts for
> -Rs 3,207 of a -Rs 83,301 decline.
>
> A model reasoning from narrative would blame it. This one can't: the causes are computed and
> they sum to the decline exactly, with a mandatory residual term that is zero. Separating a
> genuine operational incident from the actual revenue driver is the finding."

The two most common failure modes of AI finance answers — attributing only part of a change, and
mistaking the salient event for the cause — are both structurally impossible here.

---

## 2:30–3:15 — Technical versus business declines

```text
                        Prior      Current
Success rate          0.958042     0.944598
Technical declines    0.006993     0.022161     <- tripled
Business declines     0.034965     0.033241     <- flat
```

> "NPCI separates these and publishes both per bank. A technical decline is a bank or NPCI back end
> failing. A business decline is a customer typing the wrong PIN. They moved differently, and that
> asymmetry is what attributes this to the platform rather than to customers.
>
> A system that only tracked 'success rate' could tell you it fell. It could not tell you whose
> fault it was."

---

## 3:15–4:00 — Reconciliation, and a fee that names its rule

```text
RECONCILIATION           Aug 1-23

Ledger records                    342
Bank records                      341
Matched pairs                     338
Clean matches                     327
Exceptions                         15
Clean match rate               95.61%

  Timing lag                        7
  No counterpart                    3
  Amount mismatch                   2
  Fee discrepancy                   2
  Possible duplicate                1
```

Open **Fee discrepancy**:

```text
TXN_xxxx     UPI - UPI_BANK_ACCOUNT

Expected fee      Rs 0        zero MDR, mandated since Jan 2020
Actual fee        Rs 24
Matches rule for  CREDIT_CARD (1.90%)
```

> "That is not 'the fee was Rs 24 out'. That is 'a zero-MDR UPI payment was billed under the
> credit-card agreement'. The expected number comes from a commercial rule, so the exception names
> the rule that was applied instead. Under a flat 1% fee model this discrepancy could not even be
> represented — a mandated zero rate isn't expressible as a percentage of anything."

Open **No counterpart → TXN_183**:

```text
TXN_183     Rs 840     NO_COUNTERPART

Rejected candidate:
  SETTLEMENT_91   rule AMOUNT_DATE_CANDIDATE   confidence 0.72
  Amount matched. Reference absent. Value date 4 days outside
  the T+2 window. Below the 0.85 auto-match threshold.
```

> "We found something close and deliberately did *not* match it. That's the difference between a
> 95.61% match rate you can defend and a 99% one you can't."

---

## 4:00–4:30 — Provenance, and breaking something

Click **Rs 3,90,122 → Show calculation**, drill to source records.

> "Every level is an evidence node with a formula the verifier re-evaluated independently. The UI
> doesn't know what revenue is — it's walking a graph."

Disable `payments.failure_analysis` and re-ask:

```text
[!] Payment failure analysis   UNAVAILABLE (TOOL_TIMEOUT)

Status: PARTIAL -> COMPLETED

Payment failure analysis is unavailable, so the decline could not be split
between attempt volume and success rate.
```

> "It doesn't estimate. It says which number it can't produce and why, and everything verified
> stays on screen."

---

## 4:30–5:00 — Close

```text
User -> LLM -> Structured Intent -> Execution Graph -> Validation
     -> Deterministic Tools -> Verification -> Evidence -> Provenance
     -> LLM -> Grounded Answer
```

> "Most AI finance tools are user, model, answer. RazorMind puts eight enforced stages in between.
> The model chooses what to investigate and how to say it. It never once touches the arithmetic.
>
> **Synthetic data. Deterministic truth. Explicit provenance.**"

---

## Rehearsal checklist

- [ ] `python scripts/task.py verify-seed` green immediately before the demo (10/10)
- [ ] Data provenance panel loads and shows both CITED and ASSUMED counts
- [ ] Dashboard shows exactly `Rs 3,90,122` and `-17.60%`
- [ ] Reconciliation shows `342 / 341 / 338 / 327 / 15 / 95.61%`
- [ ] The fee discrepancy names an instrument in `matches_rule_for`
- [ ] `TXN_183` drill-down shows the rejected `SETTLEMENT_91` candidate
- [ ] The answer names attempt volume as primary and the incident as secondary
- [ ] Fault-injection toggle works **on the deployed environment**
- [ ] Full run completes end-to-end three times without intervention

## Questions you will be asked

| Question | Answer |
| --- | --- |
| "Where did this data come from?" | Synthetic and seeded. Aggregate behaviour calibrated against public NPCI/RBI statistics, every parameter tagged CITED or ASSUMED, sources in `data/calibration/sources.md`. The provenance panel is one click from the dashboard. |
| "Is this real Razorpay data?" | No, and we don't claim it is. No real customer or merchant record is represented, and the failure rates are not Razorpay's. |
| "Then why should I believe the numbers?" | Because you don't have to believe them — the ground truth was generated before the investigation ran, and `verify-seed` asserts the declared answer is the one the dataset actually supports. |
| "How do you know the LLM isn't doing the math?" | Import-linter contract: `tools/` cannot import `llm/`. Plus grounding byte-matches every number in the prose to a verified metric. |
| "Why 95.61% and not higher?" | Because the rest are real discrepancies we can name and show. A higher rate would mean matching on weaker evidence. |
| "Why isn't the incident the cause?" | Because the arithmetic says so. It contributed -Rs 3,207 of a -Rs 83,301 decline. That it *looks* like the cause is the point. |
| "What breaks at scale?" | Single API worker for SSE fan-out. The documented trigger for Redis is the second worker; `execution_events` is already the durable log. |
