"""One question, all the way through the agent runtime.

```text
python scripts/task.py ask "Why did net revenue fall in August?"
python scripts/task.py ask --canned revenue_diagnosis "why did revenue fall?"
```

Without `--canned` this calls the configured model. With no `ANTHROPIC_API_KEY`
or `LLM_ENABLED=false` that is a `PROVIDER_UNAVAILABLE` failure, which is the
honest outcome and worth seeing once: the system refuses rather than inventing
an intent.

`--canned` substitutes a scripted response for the model's, so the deterministic
half -- plan, eleven gates, concurrent DAG, five verification layers, evidence,
provenance -- can be exercised with no key and no spend. It says so in the
output, loudly, every time. A harness that quietly stood in for a model would be
the one thing `DisabledProvider` exists to prevent.
"""

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from config.settings import get_settings  # noqa: E402
from llm.provider import Completion, get_provider  # noqa: E402
from orchestrator.runtime import answer  # noqa: E402

MERCHANT = "M123"
#: The seeded analyst. Phase 8 takes this from the authenticated caller.
ANALYST = uuid.UUID("22222222-2222-4222-8222-222222222222")
TODAY = date(2026, 8, 24)

CANNED_PERIODS: dict[str, Any] = {
    "period": {"from": "2026-08-01", "to": "2026-08-24"},
    "comparison_period": {"from": "2026-07-01", "to": "2026-07-24"},
}


class CannedProvider:
    """A stand-in for the model, and it says so."""

    name = "canned"

    def __init__(self, intent: str) -> None:
        body: dict[str, Any] = {
            "intent": intent,
            "merchant_id": MERCHANT,
            "confidence_ratio": "0.95",
            "clarification_needed": False,
            **CANNED_PERIODS,
        }
        if intent == "reconciliation_status":
            body.pop("comparison_period")
        self._body = json.dumps(body)

    async def structured(
        self,
        *,
        system: str,
        prompt: str,
        schema: Mapping[str, Any],
        max_tokens: int,
        timeout_seconds: int,
    ) -> Completion:
        del system, prompt, schema, max_tokens, timeout_seconds
        return Completion(text=self._body, model="canned", input_tokens=0, output_tokens=0)


async def main(question: str, canned: str | None) -> int:
    settings = get_settings()
    provider: Any = CannedProvider(canned) if canned else get_provider(settings)

    print(f"question    {question}")
    print(f"provider    {provider.name}")
    if canned:
        print("            ** NO MODEL WAS CONSULTED. The intent is scripted. **")
    print()

    result = await answer(
        question,
        merchant_id=MERCHANT,
        user_id=ANALYST,
        provider=provider,
        today=TODAY,
        threshold=settings.intent_confidence_threshold,
    )

    print(f"execution   {result.execution_id}")
    print(f"status      {result.status}")
    print()

    if result.intent is not None:
        print("INTENT")
        print(f"  {result.intent.intent}  confidence {result.intent.confidence_ratio}")
        print(f"  period      {result.intent.period}")
        if result.intent.comparison_period is not None:
            print(f"  comparison  {result.intent.comparison_period}")
        print()

    if result.clarification is not None:
        print("CLARIFICATION")
        print(f"  {result.clarification.reason}")
        print(f"  {result.clarification.question}")
        return 0

    if result.rejection is not None:
        print("REJECTED")
        print(f"  {result.rejection.code}: {result.rejection.message}")
        print(f"  {json.dumps(result.rejection.detail, indent=2, default=str)}")
        return 1

    if result.plan is not None:
        print("PLAN")
        for depth, layer in enumerate(result.plan.topological_layers()):
            names = ", ".join(node.tool for node in layer)
            print(f"  layer {depth}   {names}")
        print()

    if result.outcome is not None:
        print("EXECUTION")
        for node in result.outcome.results:
            mark = "ok  " if node.succeeded else "FAIL"
            detail = "" if node.error is None else f"  {node.error['code']}"
            print(f"  {mark} {node.node_id:<14}{node.duration_ms:>6} ms{detail}")
        for limitation in result.outcome.limitations():
            print(f"       {limitation}")
        print()

    if result.report is not None:
        print("VERIFICATION")
        for checked in result.report.layers:
            mark = "ok  " if checked.passed else "FAIL"
            print(f"  {mark} {checked.layer:<12} {len(checked.checks)} checks")
            for failure in checked.failures[:5]:
                print(f"       {failure}")
        print()

    if result.error is not None:
        print("ERROR")
        print(f"  {result.error['code']}: {result.error['message']}")

    if result.status == "EXPLAINING":
        print("Verified. Phase 7 is what turns this into a sentence.")
        return 0
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="+")
    parser.add_argument(
        "--canned",
        choices=[
            "revenue_diagnosis",
            "reconciliation_status",
            "failure_analysis",
            "refund_analysis",
            "chargeback_analysis",
        ],
        help="skip the model and script the intent; prints a warning that it did",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(" ".join(args.question), args.canned)))
