# 09 — Testing and Evaluation

## Levels

| Level | Scope | Runs in |
| --- | --- | --- |
| Fixture | The seed dataset is the one the docs describe | Phase 1, before everything |
| Unit | Matching rules, formulas, calendar, money, verification rules | Every phase |
| Property | Determinism, invariants under permutation | Phases 2–5 |
| Integration | Intent → plan → validate → execute → verify → explain | Phase 6+ |
| Failure | Each degradation path in [05-agent-runtime.md](05-agent-runtime.md#recovery) | Phase 10 |
| Eval | The four dimensions of vision §39 | Phase 11 |

## Tests that carry real weight

Most of these are cheap and catch the class of bug this architecture exists to prevent.

### Determinism (Phase 2)

```python
def test_reconciliation_is_order_independent(golden_dataset):
    baseline = reconcile(golden_dataset)
    for seed in range(20):
        shuffled = shuffle(golden_dataset, random.Random(seed))
        assert reconcile(shuffled) == baseline
```

Without the assignment rule from
[C-07](00-corrections.md#c-07-b--matching-has-no-assignment-rule-so-it-is-not-reproducible) this
fails, which is exactly the point of writing it.

### Bridge closure (Phase 3)

```python
def test_bridge_closes_exactly(revenue_result):
    r = revenue_result
    assert r.net_paise == r.gross_paise - r.refunds_paise - r.fees_paise - r.chargebacks_paise
    assert sum(e.value_paise for e in r.attribution) == r.delta_net_paise
    assert abs(r.rounding_residual_paise) <= len(r.attribution)
```

### No float anywhere in money (Phase 0)

```python
def test_no_float_in_paise_fields():
    for model in all_pydantic_models():
        for name, field in model.model_fields.items():
            if name.endswith("_paise"):
                assert field.annotation is int, f"{model.__name__}.{name} is not int"
```

### Boundary (Phase 0)

`import-linter` contract, not a test convention:

```ini
[importlinter:contract:trust-boundary]
name = Deterministic and trust planes must not import the LLM plane
type = forbidden
source_modules = tools, verification, evidence, provenance, runtime
forbidden_modules = llm
```

### Grounding (Phase 7)

```python
@pytest.mark.parametrize("bad_output,expected_failure", [
    ("Revenue fell by 18.2%",              "VALUE_MISMATCH"),      # verified is -18.00%
    ("Revenue fell by Rs 5,00,000",        "UNKNOWN_METRIC"),
    ("Success rate fell 6.49%",            "UNIT_MISMATCH"),       # it is pp, not %
    ("Refunds rose 24%",                   "UNKNOWN_METRIC"),
])
def test_grounding_rejects(bad_output, expected_failure): ...
```

The first case is the original spec's own error, kept as a permanent regression test.

### Degradation (Phase 10)

```python
async def test_partial_run_keeps_verified_numbers(disable_tool):
    with disable_tool("payments.failure_analysis"):
        ex = await run_agent("Why did revenue fall this month?")
    assert ex.status == "COMPLETED"
    assert ex.metrics["net_revenue_paise"] == 4097868_00
    assert "payments.failure_analysis" in ex.unavailable_tools
    assert not any(m.startswith("success_rate") for m in ex.metrics)   # no substitution
```

### Blocked runs produce no prose (Phase 5)

```python
async def test_verification_failure_emits_no_text(break_verification):
    ex = await run_agent("Why did revenue fall this month?")
    assert ex.status == "BLOCKED"
    assert ex.final_response is None
```

## Evaluation

Vision §39's dimensions, with the thresholds from
[10-build-phases.md](10-build-phases.md#phase-11--evaluation-suite).

| Dimension | Measures | Target |
| --- | --- | --- |
| Intent accuracy | Correct intent + correct periods over the 30-question set | ≥ 90% |
| Tool selection | Planned tool set equals the expected set | ≥ 90% |
| Computation accuracy | Tool outputs vs golden fixture | 100% |
| Explanation grounding | Runs where every claim passed all five checks | ≥ 95% |
| Reconciliation accuracy | Match rate, classification accuracy, false-match rate | 95.61% / ≥ 95% / 0% |

Computation accuracy is 100% or the build is broken — the tools are deterministic and the fixture
is fixed, so any other value is a defect rather than a score. It is on the dashboard precisely
because a drop is unambiguous.

The 30-question set spans:

- The north-star question, phrased five different ways
- Ambiguous questions that **must** trigger `NEEDS_CLARIFICATION`
- Out-of-range periods that **must** be `REJECTED`
- Questions about unmatched settlements and provenance
- Questions no registered tool can answer, which must produce an honest limitation

`make eval` writes `docs/eval-report.md` with per-dimension scores and the full per-question table.

## CI gates

```text
ruff  ->  mypy --strict  ->  import-linter  ->  no-float grep
      ->  pytest (unit + property + integration)
      ->  make verify-seed
      ->  openapi diff check
```

Every gate is blocking. `make eval` runs nightly rather than per-commit, since it calls a live
LLM.
