"""Data provenance.

A judge, an auditor, or a finance controller asking *"where did this data come
from?"* should not have to ask twice, and should not get a different answer
depending on who they ask. This endpoint is the single answer, generated from
the calibration layer rather than written by hand -- a provenance statement
maintained separately from the parameters it describes goes stale in a week.

The claim being made is narrow on purpose:

* transaction-level records are **synthetic and seeded** -- no real customer,
  merchant, or bank record is represented
* aggregate distributions and operational characteristics are **calibrated
  against public NPCI/RBI statistics**
* every parameter is tagged `CITED`, `DERIVED`, or `ASSUMED`, and the counts
  are reported here so nobody has to take the word "calibrated" on trust

Overstating this would be worse than not claiming it at all.
"""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from narrative.render import canonical
from runtime.fees import FEE_SCHEDULE

__all__ = ["router"]

router = APIRouter(prefix="/provenance", tags=["provenance"])

ROOT = Path(__file__).resolve().parents[4]
GROUND_TRUTH = ROOT / "data" / "seed" / "golden" / "ground_truth.json"
CHECKSUMS = ROOT / "data" / "seed" / "golden" / "checksums.json"


class ParameterCounts(BaseModel):
    CITED: int = 0
    DERIVED: int = 0
    ASSUMED: int = 0


class FeeRuleView(BaseModel):
    """One row of the fee schedule, with its money already rendered.

    ``*_display`` exists for the same reason every metric carries one: the web
    app formats no money, so a rate table it can only render by dividing paise
    by 100 is a second money formatter smuggled in through a page nobody
    thought of as a money page (D-54).
    """

    instrument: str
    mdr_rate: str
    mdr_display: str
    platform_fee_rate: str
    threshold_paise: int
    threshold_display: str
    flat_fee_paise: int
    flat_fee_display: str
    provenance: str
    note: str


class DataProvenance(BaseModel):
    """What the Data Provenance panel renders."""

    transaction_records: str
    aggregate_calibration: str
    sources_document: str
    scenario_id: str
    seed: int
    ground_truth: str
    parameter_counts: ParameterCounts
    fee_schedule: list[FeeRuleView]
    checksums: dict[str, str]
    disclaimer: str


@router.get("", response_model=DataProvenance)
async def get_provenance() -> DataProvenance:
    if not GROUND_TRUTH.exists() or not CHECKSUMS.exists():
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "code": "FIXTURE_NOT_GENERATED",
                    "message": "Run `task.py seed` to generate the dataset.",
                    "detail": {},
                }
            },
        )

    truth: dict[str, Any] = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    provenance = truth["provenance"]

    return DataProvenance(
        transaction_records=provenance["transaction_records"],
        aggregate_calibration=provenance["aggregate_calibration"],
        sources_document=provenance["sources"],
        scenario_id=truth["scenario_id"],
        seed=truth["seed"],
        ground_truth="generated deterministically",
        parameter_counts=ParameterCounts(**provenance["parameter_counts"]),
        fee_schedule=[
            FeeRuleView(
                instrument=rule.instrument.value,
                mdr_rate=str(rule.mdr_rate),
                mdr_display=canonical(rule.mdr_rate, "ratio"),
                platform_fee_rate=str(rule.platform_fee_rate),
                threshold_paise=rule.threshold_paise,
                threshold_display=canonical(rule.threshold_paise, "paise"),
                flat_fee_paise=rule.flat_fee_paise,
                flat_fee_display=canonical(rule.flat_fee_paise, "paise"),
                provenance=rule.provenance.value,
                note=rule.note,
            )
            for rule in FEE_SCHEDULE.values()
        ],
        checksums=json.loads(CHECKSUMS.read_text(encoding="utf-8")),
        disclaimer=provenance["disclaimer"],
    )
