"""Reconciliation against a real Postgres: persistence, constraints, endpoints.

The engine's correctness is proven in `test_reconciliation.py` without a
database. What needs a database is the half of the design that is *delegated*
to it -- the one-to-one guarantee and the auto-match threshold are constraints,
not promises, and a constraint that has never been violated in a test is a
constraint nobody has checked exists.
"""

from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from main import API_PREFIX, create_app
from reconciliation.models import ReconciliationResult
from reconciliation.repository import new_run_id, write_run
from runtime.db import connection
from runtime.schema import reconciliation_matches
from tools.finance.reconciliation import run_reconciliation

pytestmark = pytest.mark.db

MERCHANT = "M123"
PERIOD_FROM = date(2026, 8, 1)
PERIOD_TO = date(2026, 8, 24)


@pytest.fixture
async def persisted_run() -> tuple[str, ReconciliationResult]:
    async with connection() as conn:
        run_id, result = await run_reconciliation(conn, MERCHANT, PERIOD_FROM, PERIOD_TO)
    return run_id, result


@pytest.fixture
async def client() -> httpx.AsyncClient:  # type: ignore[misc]
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


# --------------------------------------------------------------------------
# the run, end to end
# --------------------------------------------------------------------------


async def test_the_golden_run_survives_the_round_trip(
    persisted_run: tuple[str, ReconciliationResult],
) -> None:
    """Loaded from Postgres, reconciled, verified and written back."""
    _, result = persisted_run
    assert result.ledger_count == 342
    assert result.bank_count == 341
    assert result.matched_pairs == 338
    assert result.matched_clean == 327
    assert result.clean_match_rate_ratio == Decimal("0.956140")


# --------------------------------------------------------------------------
# what the database, not the matcher, guarantees
# --------------------------------------------------------------------------


async def test_a_transaction_cannot_be_matched_twice(
    persisted_run: tuple[str, ReconciliationResult],
) -> None:
    """I5, enforced by `uq_matches_run_transaction`.

    The matcher already guarantees this. The constraint exists for the case
    where a future matcher does not -- which is the only case that matters.
    """
    run_id, _ = persisted_run
    async with connection() as conn:
        existing = (
            await conn.execute(
                reconciliation_matches.select()
                .where(reconciliation_matches.c.run_id == run_id)
                .limit(1)
            )
        ).one()

        with pytest.raises(IntegrityError, match="uq_matches_run_transaction"):
            await conn.execute(
                reconciliation_matches.insert().values(
                    id="mat_duplicate_probe",
                    run_id=run_id,
                    transaction_id=existing.transaction_id,
                    settlement_id="SETTLEMENT_91",
                    rule="EXACT_UTR",
                    confidence_ratio=Decimal("1.00"),
                    reason="planted by a test",
                    amount_delta_paise=0,
                    lag_days=0,
                )
            )


async def test_a_settlement_cannot_be_matched_twice(
    persisted_run: tuple[str, ReconciliationResult],
) -> None:
    """I6, enforced by `uq_matches_run_settlement`."""
    run_id, _ = persisted_run
    async with connection() as conn:
        existing = (
            await conn.execute(
                reconciliation_matches.select()
                .where(reconciliation_matches.c.run_id == run_id)
                .limit(1)
            )
        ).one()

        with pytest.raises(IntegrityError, match="uq_matches_run_settlement"):
            await conn.execute(
                reconciliation_matches.insert().values(
                    id="mat_duplicate_settlement_probe",
                    run_id=run_id,
                    transaction_id="TXN_183",
                    settlement_id=existing.settlement_id,
                    rule="EXACT_UTR",
                    confidence_ratio=Decimal("1.00"),
                    reason="planted by a test",
                    amount_delta_paise=0,
                    lag_days=0,
                )
            )


async def test_a_match_below_the_threshold_is_refused_by_the_database(
    persisted_run: tuple[str, ReconciliationResult],
) -> None:
    """Rule 5 produces candidates, never matches -- and not only by convention.

    If a future change let a 0.72 candidate through the assignment loop, this
    constraint is what stops it becoming a number someone acts on.
    """
    run_id, _ = persisted_run
    async with connection() as conn:
        with pytest.raises(
            (IntegrityError, DBAPIError), match="ck_matches_above_auto_match_threshold"
        ):
            await conn.execute(
                reconciliation_matches.insert().values(
                    id="mat_low_confidence_probe",
                    run_id=run_id,
                    transaction_id="TXN_183",
                    settlement_id="SETTLEMENT_91",
                    rule="AMOUNT_DATE_CANDIDATE",
                    confidence_ratio=Decimal("0.72"),
                    reason="planted by a test",
                    amount_delta_paise=0,
                    lag_days=4,
                )
            )


async def test_a_run_whose_counts_do_not_add_up_is_refused(
    persisted_run: tuple[str, ReconciliationResult],
) -> None:
    """I1 and I2 are CHECK constraints on reconciliation_runs."""
    from dataclasses import replace

    _, result = persisted_run
    broken = replace(result, unmatched_ledger=99)
    async with connection() as conn:
        with pytest.raises((IntegrityError, DBAPIError), match="ck_runs_i"):
            await write_run(conn, broken, new_run_id())


# --------------------------------------------------------------------------
# the read endpoints
# --------------------------------------------------------------------------


async def test_the_run_summary_endpoint(
    client: httpx.AsyncClient, persisted_run: tuple[str, ReconciliationResult]
) -> None:
    response = await client.get(
        f"{API_PREFIX}/reconciliation/runs",
        params={"merchant_id": MERCHANT, "from": "2026-08-01", "to": "2026-08-24"},
    )
    assert response.status_code == 200
    summary = response.json()["items"][0]

    assert summary["ledger_count"] == 342
    assert summary["bank_count"] == 341
    assert summary["matched_pairs_count"] == 338
    assert summary["matched_clean_count"] == 327
    assert summary["exception_count"] == 15
    assert summary["unresolved_exception_value_paise"] == 184_000
    assert summary["exception_breakdown"] == {
        "AMOUNT_MISMATCH": 2,
        "FEE_DISCREPANCY": 2,
        "NO_COUNTERPART": 3,
        "POSSIBLE_DUPLICATE": 1,
        "TIMING_LAG": 7,
    }
    # Ratios cross the wire as strings, money as integers (D-02).
    assert summary["clean_match_rate_ratio"] == "0.956140"
    assert isinstance(summary["unresolved_exception_value_paise"], int)


async def test_a_reversed_period_is_rejected_with_a_stable_code(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(
        f"{API_PREFIX}/reconciliation/runs",
        params={"merchant_id": MERCHANT, "from": "2026-08-24", "to": "2026-08-01"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "INVALID_PERIOD"


async def test_the_exception_endpoint_shows_the_rejected_candidate(
    client: httpx.AsyncClient, persisted_run: tuple[str, ReconciliationResult]
) -> None:
    """What the exception explorer opens onto for TXN_183."""
    run_id, _ = persisted_run
    response = await client.get(
        f"{API_PREFIX}/reconciliation/runs/{run_id}/exceptions",
        params={"category": "NO_COUNTERPART", "side": "LEDGER"},
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 3

    txn_183 = next(item for item in items if item["transaction_id"] == "TXN_183")
    assert txn_183["amount_paise"] == 84_000
    assert txn_183["status"] == "OPEN"
    candidate = txn_183["detail"]["candidates"][0]
    assert candidate["settlement_id"] == "SETTLEMENT_91"
    assert candidate["rule"] == "AMOUNT_DATE_CANDIDATE"
    assert candidate["confidence_ratio"] == "0.72"


async def test_exceptions_paginate_with_a_stable_cursor(
    client: httpx.AsyncClient, persisted_run: tuple[str, ReconciliationResult]
) -> None:
    run_id, _ = persisted_run
    first = await client.get(
        f"{API_PREFIX}/reconciliation/runs/{run_id}/exceptions", params={"limit": 5}
    )
    assert first.status_code == 200
    page_one = first.json()
    assert len(page_one["items"]) == 5
    assert page_one["next_cursor"] is not None

    second = await client.get(
        f"{API_PREFIX}/reconciliation/runs/{run_id}/exceptions",
        params={"limit": 5, "cursor": page_one["next_cursor"]},
    )
    ids_one = {item["id"] for item in page_one["items"]}
    ids_two = {item["id"] for item in second.json()["items"]}
    assert ids_one.isdisjoint(ids_two)


async def test_an_unknown_run_is_a_stable_error_code(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(f"{API_PREFIX}/reconciliation/runs/rec_does_not_exist/exceptions")
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "RUN_NOT_FOUND"


async def test_the_match_endpoint_returns_both_source_records(
    client: httpx.AsyncClient, persisted_run: tuple[str, ReconciliationResult]
) -> None:
    """The provenance drawer needs the pairing *and* what it was drawn from."""
    run_id, _ = persisted_run
    async with connection() as conn:
        row = (
            await conn.execute(
                reconciliation_matches.select()
                .where(
                    reconciliation_matches.c.run_id == run_id,
                    reconciliation_matches.c.rule == "EXACT_UTR",
                )
                .limit(1)
            )
        ).one()

    response = await client.get(f"{API_PREFIX}/reconciliation/runs/{run_id}/matches/{row.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["rule"] == "EXACT_UTR"
    assert body["confidence_ratio"] == "1.000000"
    assert body["transaction"]["id"] == row.transaction_id
    assert body["settlement"]["id"] == row.settlement_id
    assert body["transaction"]["utr"] == body["settlement"]["utr"]
    assert body["transaction"]["amount_paise"] == body["settlement"]["amount_paise"]


# --------------------------------------------------------------------------
# data provenance
# --------------------------------------------------------------------------


async def test_the_provenance_endpoint_answers_where_the_data_came_from(
    client: httpx.AsyncClient,
) -> None:
    """The claim has to be narrow, and it has to be checkable.

    Synthetic records, calibrated aggregates, tagged parameters. Both CITED and
    ASSUMED must be present: all-CITED would be a lie about a single merchant's
    payment mix, and all-ASSUMED would mean the calibration layer is decoration.
    """
    response = await client.get(f"{API_PREFIX}/provenance")
    assert response.status_code == 200
    body = response.json()

    assert body["transaction_records"] == "synthetic, seeded"
    assert "NPCI" in body["aggregate_calibration"]
    assert body["sources_document"] == "data/calibration/sources.md"
    assert body["scenario_id"] == "revenue_decline_v1"
    assert "synthetic" in body["disclaimer"].lower()
    assert body["parameter_counts"]["CITED"] > 0
    assert body["parameter_counts"]["ASSUMED"] > 0
    assert set(body["checksums"]) >= {"ledger_side.csv", "bank_settlement.csv"}


async def test_the_provenance_endpoint_publishes_the_fee_schedule(
    client: httpx.AsyncClient,
) -> None:
    """Zero-MDR rails are visible as zero, with their citation attached.

    This is what makes a FEE_DISCREPANCY defensible: a reader can see the rule
    the expected fee came from rather than being asked to trust a percentage.
    """
    body = (await client.get(f"{API_PREFIX}/provenance")).json()
    by_instrument = {rule["instrument"]: rule for rule in body["fee_schedule"]}

    assert by_instrument["UPI_BANK_ACCOUNT"]["mdr_rate"] == "0"
    assert by_instrument["UPI_BANK_ACCOUNT"]["provenance"] == "CITED"
    assert by_instrument["RUPAY_DEBIT"]["mdr_rate"] == "0"
    # A commercial agreement is not a published statistic, and says so.
    assert by_instrument["CREDIT_CARD"]["provenance"] == "ASSUMED"
    assert by_instrument["UPI_PPI_WALLET"]["threshold_paise"] == 200_000
