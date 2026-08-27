"""``finance.reconciliation`` v1.0 -- Phase 2's engine behind the tool contract.

Every other tool depends on this one. Revenue analysis needs it not as context
but as *input*: the run is what identifies the duplicated ledger row that must
come out of gross, and what bounds how much of the answer the bank has
confirmed.

This is the one tool that writes. That is a deliberate exception to "a tool is
a pure computation", and it is bounded: a run is immutable once written, so
re-running a period appends a new run rather than changing an old one, and
"which numbers did we see on the 24th?" stays answerable. The run id is derived
from the execution rather than drawn at random, so the same execution replayed
produces the same id instead of a second identical run under a new name.
"""

import hashlib
from datetime import date
from decimal import Decimal
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from evidence.models import Aggregation, Evidence, Formula
from reconciliation.engine import EmptyPeriodError, reconcile
from reconciliation.models import ReconciliationResult
from reconciliation.repository import (
    StoredRun,
    load_bank_records,
    load_ledger_records,
    read_run,
    write_run,
)
from runtime.calendar import bank_period
from runtime.money import ratio
from verification.models import Checks, VerificationResult
from verification.rules import RunVerificationError, verify_run

from ..base import DeterministicTool, Period, ToolContext, ToolError, ToolInput

__all__ = [
    "ReconciliationInput",
    "ReconciliationOutput",
    "ReconciliationTool",
    "deterministic_run_id",
    "run_reconciliation",
]


def deterministic_run_id(
    execution_id: str, merchant_id: str, period_from: date, period_to: date
) -> str:
    """A run id that is a function of the request, not of ``uuid4``.

    A tool's contract is that the same inputs against the same snapshot produce
    byte-identical output. A random id breaks that for the one field a client
    is most likely to store, and it makes replaying a request create a second
    run rather than recognising the first.
    """
    material = f"{execution_id}|{merchant_id}|{period_from.isoformat()}|{period_to.isoformat()}"
    return f"rec_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}"


async def run_reconciliation(
    conn: AsyncConnection,
    merchant_id: str,
    period_from: date,
    period_to: date,
    run_id: str | None = None,
) -> tuple[str, ReconciliationResult]:
    """Load, reconcile, verify, write -- in that order, and never out of it.

    Verification happens *before* the write. A run that fails its invariants
    must not exist in a form anything downstream can read: a half-reconciled
    period is worse than no reconciled period, because it looks like an answer.
    """
    ledger = await load_ledger_records(conn, merchant_id, period_from, period_to)
    bank = await load_bank_records(conn, merchant_id, period_from, period_to)

    result = reconcile(merchant_id, period_from, period_to, ledger, bank)
    verify_run(result, sum(record.amount_paise for record in ledger))

    if run_id is not None:
        existing = await read_run(conn, run_id)
        if existing is not None:
            _refuse_if_the_snapshot_moved(existing, result)
            return run_id, result

    written = await write_run(conn, result, run_id)
    return written, result


def _refuse_if_the_snapshot_moved(existing: StoredRun, result: ReconciliationResult) -> None:
    """Replaying an execution must return the run it produced, or fail loudly.

    The run id is a function of the execution, so a replay lands on the same id.
    If the recomputed run agrees with the stored one, the replay is a no-op and
    the caller gets the original -- which is what idempotency means here.

    If it disagrees, the underlying data changed between the two attempts. That
    is not something to overwrite: a run is immutable precisely so that "which
    numbers did we see on the 24th?" stays answerable, and silently rewriting
    history would be the one thing that makes it unanswerable.
    """
    stored = (
        existing.merchant_id,
        existing.period_from,
        existing.period_to,
        existing.ledger_count,
        existing.bank_count,
        existing.matched_pairs,
        existing.matched_clean,
        existing.matched_with_exception,
        existing.unmatched_ledger,
        existing.unmatched_bank,
        existing.clean_match_rate_ratio,
    )
    recomputed = (
        result.merchant_id,
        result.period_from,
        result.period_to,
        result.ledger_count,
        result.bank_count,
        result.matched_pairs,
        result.matched_clean,
        result.matched_with_exception,
        result.unmatched_ledger,
        result.unmatched_bank,
        result.clean_match_rate_ratio,
    )
    if stored != recomputed:
        raise ToolError(
            "RUN_SNAPSHOT_CHANGED",
            f"run {existing.id} already exists and does not match a fresh reconciliation "
            "of the same period; the underlying records changed between attempts",
            {"run_id": existing.id, "stored": str(stored), "recomputed": str(recomputed)},
        )


# --------------------------------------------------------------------------
# the contract
# --------------------------------------------------------------------------


class ReconciliationInput(ToolInput):
    """Merchant and period. Nothing else -- the rules are not a parameter."""


class ExceptionItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: str
    side: str
    transaction_id: str | None
    settlement_id: str | None
    amount_paise: int
    detail: dict[str, Any]


class ReconciliationSources(BaseModel):
    """The records behind every count this tool publishes.

    Carried in the output because ``evidence(inp, out)`` is handed nothing else.
    A tool whose output cannot support its own evidence would have to re-query
    to explain itself, and a second query is a second chance to disagree with
    the first.
    """

    model_config = ConfigDict(frozen=True)

    ledger_transaction_ids: list[str]
    bank_settlement_ids: list[str]
    matched_transaction_ids: list[str]
    clean_transaction_ids: list[str]
    exception_transaction_ids: list[str]
    unresolved_transaction_ids: list[str]


class ReconciliationOutput(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    period: Period
    bank_period: Period

    ledger_count: int
    bank_count: int
    matched_pairs_count: int
    matched_clean_count: int
    matched_with_exception_count: int
    unmatched_ledger_count: int
    unmatched_bank_count: int

    clean_match_rate_ratio: str
    exception_count: int
    exception_breakdown: dict[str, int]
    unresolved_exception_value_paise: int

    exceptions: list[ExceptionItem]
    sources: ReconciliationSources


class ReconciliationTool(DeterministicTool[ReconciliationInput, ReconciliationOutput]):
    """Wraps docs/03-reconciliation.md."""

    name: ClassVar[str] = "finance.reconciliation"
    version: ClassVar[str] = "1.0"
    input_model: ClassVar[type[BaseModel]] = ReconciliationInput
    output_model: ClassVar[type[BaseModel]] = ReconciliationOutput
    metrics: ClassVar[tuple[str, ...]] = (
        "ledger_count",
        "bank_count",
        "matched_pairs_count",
        "matched_clean_count",
        "clean_match_rate_ratio",
        "exception_count",
        "unresolved_exception_value_paise",
    )

    async def execute(self, inp: ReconciliationInput, ctx: ToolContext) -> ReconciliationOutput:
        run_id = deterministic_run_id(
            ctx.execution_id, inp.merchant_id, inp.period.from_, inp.period.to
        )
        try:
            written, result = await run_reconciliation(
                ctx.conn, inp.merchant_id, inp.period.from_, inp.period.to, run_id
            )
        except EmptyPeriodError as error:
            # Not a zero match rate. "We matched none of them" and "there were
            # none" are different facts, and Invariant 6 forbids inventing the
            # zero that would make them render identically.
            raise ToolError("EMPTY_PERIOD", str(error), {"period": str(inp.period)}) from error
        except RunVerificationError as error:
            raise ToolError("RUN_FAILED_VERIFICATION", str(error)) from error

        opens, closes = bank_period(inp.period.from_, inp.period.to)
        clean = self._clean_transaction_ids(result)
        return ReconciliationOutput(
            run_id=written,
            period=inp.period,
            bank_period=Period(**{"from": opens, "to": closes}),
            ledger_count=result.ledger_count,
            bank_count=result.bank_count,
            matched_pairs_count=result.matched_pairs,
            matched_clean_count=result.matched_clean,
            matched_with_exception_count=result.matched_with_exception,
            unmatched_ledger_count=result.unmatched_ledger,
            unmatched_bank_count=result.unmatched_bank,
            clean_match_rate_ratio=f"{result.clean_match_rate_ratio:.6f}",
            exception_count=result.exception_count,
            exception_breakdown=result.breakdown(),
            unresolved_exception_value_paise=result.unresolved_value_paise(),
            exceptions=[
                ExceptionItem(
                    category=exc.category,
                    side=exc.side,
                    transaction_id=exc.transaction_id,
                    settlement_id=exc.settlement_id,
                    amount_paise=exc.amount_paise,
                    detail=dict(exc.detail),
                )
                for exc in result.exceptions
            ],
            sources=ReconciliationSources(
                ledger_transaction_ids=sorted(
                    {match.transaction_id for match in result.matches}
                    | {
                        exc.transaction_id
                        for exc in result.ledger_exceptions
                        if exc.transaction_id is not None
                    }
                ),
                bank_settlement_ids=sorted(
                    {match.settlement_id for match in result.matches}
                    | {
                        exc.settlement_id
                        for exc in result.bank_exceptions
                        if exc.settlement_id is not None
                    }
                ),
                matched_transaction_ids=sorted(match.transaction_id for match in result.matches),
                clean_transaction_ids=clean,
                exception_transaction_ids=sorted(
                    exc.transaction_id
                    for exc in result.ledger_exceptions
                    if exc.transaction_id is not None
                ),
                unresolved_transaction_ids=sorted(
                    exc.transaction_id
                    for exc in result.ledger_exceptions
                    if exc.category == "NO_COUNTERPART" and exc.transaction_id is not None
                ),
            ),
        )

    @staticmethod
    def _clean_transaction_ids(result: ReconciliationResult) -> list[str]:
        """Matched, and carrying no exception. The numerator of the headline rate."""
        flagged = {
            exc.transaction_id for exc in result.ledger_exceptions if exc.transaction_id is not None
        }
        return sorted(
            match.transaction_id for match in result.matches if match.transaction_id not in flagged
        )

    def verify(self, inp: ReconciliationInput, out: ReconciliationOutput) -> VerificationResult:
        """The identities the published counts must satisfy.

        ``verification/rules.py`` already checked the engine's own invariants
        before the run was written. What is checked here is different: that the
        *published* shape agrees with itself, including the source id lists that
        the evidence is built from. A count that no longer matches the ids it
        cites is a broken provenance chain, and nothing else would notice.
        """
        checks = Checks()
        sources = out.sources

        checks.equal(
            "ledger_count_matches_sources", len(sources.ledger_transaction_ids), out.ledger_count
        )
        checks.equal("bank_count_matches_sources", len(sources.bank_settlement_ids), out.bank_count)
        checks.equal(
            "matched_pairs_matches_sources",
            len(sources.matched_transaction_ids),
            out.matched_pairs_count,
        )
        checks.equal(
            "clean_matches_sources", len(sources.clean_transaction_ids), out.matched_clean_count
        )
        checks.equal(
            "exception_count_matches_sources",
            len(sources.exception_transaction_ids),
            out.exception_count,
        )
        checks.equal(
            "pairs_split_into_clean_and_flagged",
            out.matched_clean_count + out.matched_with_exception_count,
            out.matched_pairs_count,
        )
        checks.equal(
            "exceptions_are_ledger_records_that_are_not_clean",
            out.exception_count,
            out.ledger_count - out.matched_clean_count,
        )
        checks.equal(
            "breakdown_sums_to_exception_count",
            sum(out.exception_breakdown.values()),
            out.exception_count,
        )
        checks.equal(
            "clean_match_rate_is_what_it_claims",
            out.clean_match_rate_ratio,
            f"{ratio(out.matched_clean_count, out.ledger_count):.6f}",
        )
        checks.require(
            "unresolved_value_is_not_negative",
            out.unresolved_exception_value_paise >= 0,
            f"unresolved value is {out.unresolved_exception_value_paise}",
        )
        checks.require(
            "period_is_the_requested_one",
            out.period == inp.period,
            f"published {out.period}, requested {inp.period}",
        )
        return checks.result()

    def evidence(
        self, inp: ReconciliationInput, out: ReconciliationOutput, ctx: ToolContext
    ) -> list[Evidence]:
        window = f"{out.period.from_.isoformat()}_{out.period.to.isoformat()}"

        def identifier(metric_id: str) -> str:
            return f"{self.name}/{self.version}/{metric_id}/{window}"

        checked = list(self.verify(inp, out).checks)

        def counted(
            metric_id: str,
            value: int,
            record_ids: list[str],
            over: str,
            predicate: str,
            operation: Literal["SUM", "COUNT"] = "COUNT",
            field_name: str = "id",
            unit: Literal["paise", "count"] = "count",
        ) -> Evidence:
            """A leaf metric: a fold over the records it cites, with no arithmetic.

            It carries an ``Aggregation`` rather than a ``Formula`` because
            there is no expression to re-evaluate -- the verifier re-sums the
            cited ids instead. Handing it a synthetic formula would make
            layer 4 a check that passes by construction.
            """
            return Evidence(
                id=identifier(metric_id),
                execution_id=ctx.execution_id,
                tool_name=self.name,
                tool_version=self.version,
                metric_id=metric_id,
                unit=unit,
                value=value,
                period_from=out.period.from_.isoformat(),
                period_to=out.period.to.isoformat(),
                aggregation=Aggregation(
                    operation=operation,
                    field_name=field_name,
                    over=over,
                    predicate=predicate,
                    unit=unit,
                ),
                inputs={"record_count": len(record_ids)},
                source_record_ids=record_ids,
                rules_applied=[f"reconciliation rules v{self.version}"],
                verification_checks=checked,
            )

        ledger_predicate = (
            f"status = CAPTURED and IST capture date in [{out.period.from_}, {out.period.to})"
        )
        bank_predicate = (
            f"value_date in [{out.bank_period.from_}, {out.bank_period.to}) -- the settlement "
            "window for that capture window, not the same literal dates (D-18)"
        )

        return [
            counted(
                "ledger_count",
                out.ledger_count,
                out.sources.ledger_transaction_ids,
                "transactions",
                ledger_predicate,
            ),
            counted(
                "bank_count",
                out.bank_count,
                out.sources.bank_settlement_ids,
                "settlements",
                bank_predicate,
            ),
            counted(
                "matched_pairs_count",
                out.matched_pairs_count,
                out.sources.matched_transaction_ids,
                "reconciliation_matches",
                "one-to-one pairs admitted by rules 1-4 at confidence >= 0.85",
            ),
            counted(
                "matched_clean_count",
                out.matched_clean_count,
                out.sources.clean_transaction_ids,
                "reconciliation_matches",
                "matched pairs carrying no exception",
            ),
            counted(
                "exception_count",
                out.exception_count,
                out.sources.exception_transaction_ids,
                "reconciliation_exceptions",
                "ledger-side exceptions only; bank-side rows are reported separately "
                "so one discrepancy is not counted twice (D-20)",
            ),
            counted(
                "unresolved_exception_value_paise",
                out.unresolved_exception_value_paise,
                out.sources.unresolved_transaction_ids,
                "reconciliation_exceptions",
                "NO_COUNTERPART on the ledger side; a confidence band, never a bridge term",
                operation="SUM",
                field_name="amount_paise",
                unit="paise",
            ),
            Evidence(
                id=identifier("clean_match_rate_ratio"),
                execution_id=ctx.execution_id,
                tool_name=self.name,
                tool_version=self.version,
                metric_id="clean_match_rate_ratio",
                unit="ratio",
                value=Decimal(out.clean_match_rate_ratio),
                period_from=out.period.from_.isoformat(),
                period_to=out.period.to.isoformat(),
                formula=Formula(
                    expression="clean / ledger",
                    operands={
                        "clean": identifier("matched_clean_count"),
                        "ledger": identifier("ledger_count"),
                    },
                    unit="ratio",
                ),
                inputs={"clean": out.matched_clean_count, "ledger": out.ledger_count},
                source_record_ids=out.sources.clean_transaction_ids,
                rules_applied=["clean match rate = matched_clean / ledger_count (D-20)"],
                verification_checks=["clean_match_rate_is_what_it_claims"],
            ),
        ]
