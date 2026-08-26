# 11 — Demo Script

Five minutes, one coherent story, every number traceable. Numbers below are the golden fixture
([08-seed-data.md](08-seed-data.md)) — if the demo shows anything different, the fixture drifted.

---

## 0:00–0:30 — The problem

Open on the dashboard.

```text
NET REVENUE   Rs 40,97,868          -18.00%  vs Jul 1-23
```

> "Finance teams can't act on a number an AI generated. They need to know it's right, and where
> it came from. RazorMind never lets the model produce a financial number at all."

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

## 1:15–2:15 — The answer, and the bridge

```text
Net revenue declined 18.00% (Rs 8,99,532) versus the prior period.

  Attempt-volume decline (-11.03%)      -Rs 5,69,246    63.3%
  Payment success rate (-6.49 pp)       -Rs 3,07,554    34.2%
  Refund increase                          -Rs 24,000     2.7%
  Chargeback increase                       -Rs 7,500     0.8%
  Fee decrease (offset)                     +Rs 8,768    -1.0%
  ----------------------------------------------------------
  Total                                 -Rs 8,99,532   100.0%

The success-rate decline is concentrated in UPI: 96.8% -> 82.9% (-13.9 pp),
against 46.66% of attempted value.

Rs 18,400 across 3 unresolved settlement exceptions is not included above;
it bounds the confidence of these figures at +/- 0.45%.
```

> "The causes sum to exactly the decline. That's an enforced identity, not a coincidence — the
> bridge has a mandatory residual term and the verifier rejects the result if it doesn't close."

The point worth landing: the two most common failure modes of AI finance answers — attributing
only part of a change, and counting a gross figure as if it were a change — are both structurally
impossible here.

---

## 2:15–3:00 — Reconciliation and exceptions

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

Open **No counterpart → TXN_183**:

```text
TXN_183     Rs 8,400     NO_COUNTERPART

Rejected candidate:
  SETTLEMENT_91   rule AMOUNT_DATE_CANDIDATE   confidence 0.72
  Amount matched. Reference absent. Value date 4 days outside
  the T+2 window. Below the 0.85 auto-match threshold.
```

> "We found something close and deliberately did *not* match it. That's the difference between a
> 95.61% match rate you can defend and a 99% match rate you can't."

---

## 3:00–3:45 — Provenance

Click **Rs 40,97,868 → Show calculation**:

```text
Gross payments        Rs 42,83,200
Refunds                -Rs 1,24,000
Fees @ 1.00%             -Rs 42,832
Chargebacks              -Rs 18,500
------------------------------------
Net                   Rs 40,97,868
```

Keep drilling: `Gross payments` → the matched settlement records → one `reconciliation_matches`
row (rule `EXACT_UTR`, confidence 1.00) → the source transaction and bank rows.

> "Every level here is an evidence node with a formula the verifier re-evaluated independently.
> The UI doesn't know what revenue is — it's just walking the graph."

---

## 3:45–4:30 — Break something

Disable `payments.failure_analysis`. Re-ask the same question.

```text
[x] Reconciliation loaded
[x] Revenue analysis
[!] Payment failure analysis   UNAVAILABLE (TOOL_TIMEOUT)
[x] Refund analysis
[x] Chargeback analysis

Status: PARTIAL -> COMPLETED
```

```text
Net revenue declined 18.00% (Rs 8,99,532).

Refund increase        -Rs 24,000
Chargeback increase     -Rs 7,500
Fee decrease            +Rs 8,768

Payment failure analysis is unavailable, so Rs 8,76,800 of the decline
(gross payment volume) could not be attributed to volume versus
success rate.
```

> "It doesn't estimate. It doesn't interpolate. It says which number it can't produce and why,
> and everything verified stays on screen."

If time allows, kill the LLM provider entirely and re-ask — the same verified bridge renders
through the deterministic template, labelled as such.

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
> **AI controls the investigation. Deterministic systems control the numbers. Evidence controls
> trust.**"

---

## Rehearsal checklist

- [ ] `make verify-seed` green immediately before the demo
- [ ] Dashboard shows exactly `Rs 40,97,868` and `-18.00%`
- [ ] Reconciliation shows `342 / 341 / 338 / 327 / 15 / 95.61%`
- [ ] `TXN_183` drill-down shows the rejected `SETTLEMENT_91` candidate
- [ ] Fault-injection toggle works **on the deployed environment**
- [ ] LLM-disabled fallback renders the full bridge
- [ ] Full run completes end-to-end three times without intervention

## Questions you will be asked

| Question | Answer |
| --- | --- |
| "How do you know the LLM isn't doing the math?" | Import-linter contract: `tools/` cannot import `llm/`. Plus grounding byte-matches every number in the prose to a verified metric. |
| "What if the model hallucinates a number anyway?" | Grounding catches it, regenerates once, then falls back to a deterministic template. Live-demonstrable. |
| "Why 95.61% and not higher?" | Because the remaining 4.39% are real discrepancies we can name and show. A higher rate would mean matching on weaker evidence. |
| "Is this real Razorpay data?" | No — a seeded synthetic dataset with a deliberate embedded story, checksummed for reproducibility. The reconciliation engine is source-agnostic. |
| "What breaks at scale?" | Single API worker for SSE fan-out. The documented trigger for Redis is the second worker; `execution_events` is already the durable log. |
