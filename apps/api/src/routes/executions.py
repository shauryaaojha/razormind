"""Execution and evidence read endpoints (docs/07-api.md).

The endpoint that matters here is
``GET /executions/{id}/evidence/{evidence_id}``: it is what a claim in the prose
resolves to, and what the provenance drawer opens onto. It returns the row and
the whole chain beneath it, so the drawer can be a generic recursive renderer
with no knowledge of revenue, refunds or reconciliation.

Two shapes in the path deserve a note. An evidence id contains slashes -- it is
``<tool>/<version>/<metric>/<window>`` -- so the parameter is declared
``:path`` and takes the rest of the URL. And the slice separator on a
dimensioned row is ``~``, not ``#``: a fragment never reaches the server, so
asking for the UPI row would have quietly returned the blended one (D-42).

**A blocked execution serves no evidence.** Not a 404, which would read as "we
have no record of this", but a 409 naming the layer that stopped it. The
distinction is the whole of Invariant 4: verification failure blocks downstream
explanation *entirely*, and a reader who asks anyway is told why rather than
handed the support for a number nobody verified.
"""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from evidence.models import Evidence
from evidence.repository import load_evidence
from narrative.render import canonical
from provenance.builder import (
    MAX_DEPTH,
    Operand,
    ProvenanceCycleError,
    ProvenanceNode,
    source_records,
    walk,
)
from runtime.db import connection
from verification.repository import list_executions, read_execution

__all__ = ["router"]

router = APIRouter(prefix="/executions", tags=["executions"])

MAX_PAGE = 500


class AnswerClaim(BaseModel):
    """One span of the answer, and the evidence id it resolves to.

    This is what makes a number in the prose clickable: the UI does not parse
    the text looking for figures, it renders the spans the grounding gate
    already matched.
    """

    text: str
    metric_id: str
    value: int | str
    unit: str
    evidence_id: str


class ExecutionSummary(BaseModel):
    execution_id: str
    merchant_id: str
    period_from: str | None
    period_to: str | None
    status: str
    #: ``None`` until an explainer has written something. A blocked execution
    #: keeps it ``None`` forever, which is the persisted form of "no text was
    #: generated" (Invariant 4).
    response_source: str | None
    #: The answer, and the claims grounding checked it against. Served together
    #: with ``response_source`` because a reader deciding how much to trust a
    #: sentence needs to know whether a model wrote it.
    answer: str | None
    claims: list[AnswerClaim]
    grounding_attempts: int
    error: dict[str, Any] | None


class ExecutionLine(BaseModel):
    """One row of the history list. The question, and how it ended."""

    execution_id: str
    merchant_id: str
    question: str
    status: str
    response_source: str | None
    created_at: str
    period_from: str | None
    period_to: str | None


class ExecutionPage(BaseModel):
    items: list[ExecutionLine]
    #: The ``created_at`` of the last item, to pass back as ``cursor``. Keyset
    #: rather than an offset: rows are inserted while somebody is paging, and an
    #: offset shows a row twice or skips one.
    next_cursor: str | None


class EvidenceLine(BaseModel):
    """One published metric, without its support. The index the drawer lists."""

    evidence_id: str
    tool_name: str
    tool_version: str
    metric_id: str
    unit: str
    #: Money and counts are integers; ratios and percentage points are strings,
    #: because JSON's only numeric type is a float and a scale-6 ratio would not
    #: survive the round trip (D-02).
    value: int | str
    #: The value as it is written -- ``₹4,06,260.00``, ``95.8012%``, ``-1.34``.
    #: Served rather than re-derived by the client, because ``narrative/render.py``
    #: is the one place that decides how a number is spelled and grounding
    #: byte-matches against it. A second implementation in TypeScript would be a
    #: second answer to "what does this number look like", and the two would
    #: disagree the first time one of them was edited (D-54).
    display: str
    period_from: str
    period_to: str
    dimension_value: str | None
    support: Literal["FORMULA", "AGGREGATION"]


class EvidenceIndex(BaseModel):
    execution_id: str
    items: list[EvidenceLine]


class ProvenanceOperand(BaseModel):
    name: str
    reference: str
    value: int | str
    display: str
    node: "ProvenanceLevel | None"


class ProvenanceLevel(BaseModel):
    evidence_id: str
    tool_name: str
    tool_version: str
    metric_id: str
    unit: str
    value: int | str
    display: str
    period_from: str
    period_to: str
    dimension_value: str | None
    support: Literal["FORMULA", "AGGREGATION"]
    detail: str
    rules_applied: list[str]
    operands: list[ProvenanceOperand]
    source_record_ids: list[str]


class EvidenceDetail(BaseModel):
    """One row, its support, and everything beneath it."""

    execution_id: str
    evidence_id: str
    metric_id: str
    unit: str
    value: int | str
    display: str
    period_from: str
    period_to: str
    dimension_value: str | None
    inputs: dict[str, int | str]
    rules_applied: list[str]
    verification_checks: list[str]
    provenance: ProvenanceLevel
    #: Every source record the chain reaches, however deep. This is the answer
    #: to "show me the transactions behind this percentage".
    source_record_ids: list[str]


ProvenanceOperand.model_rebuild()


def _error(
    code: str, message: str, status: int, detail: dict[str, Any] | None = None
) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


@router.get("", response_model=ExecutionPage)
async def list_history(
    merchant_id: str,
    status: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: datetime | None = None,
) -> ExecutionPage:
    """Newest first. What the history page renders before anything is opened."""
    async with connection() as conn:
        rows = await list_executions(conn, merchant_id, status=status, limit=limit, cursor=cursor)
    return ExecutionPage(
        items=[
            ExecutionLine(
                execution_id=str(row.id),
                merchant_id=row.merchant_id,
                question=row.question,
                status=row.status,
                response_source=row.response_source,
                created_at=row.created_at.isoformat() if row.created_at else "",
                period_from=row.period_from.isoformat() if row.period_from else None,
                period_to=row.period_to.isoformat() if row.period_to else None,
            )
            for row in rows
        ],
        next_cursor=(
            rows[-1].created_at.isoformat()
            if len(rows) == limit and rows and rows[-1].created_at
            else None
        ),
    )


@router.get("/{execution_id}", response_model=ExecutionSummary)
async def get_execution(execution_id: UUID) -> ExecutionSummary:
    async with connection() as conn:
        stored = await read_execution(conn, execution_id)
    if stored is None:
        raise _error("EXECUTION_NOT_FOUND", f"No execution {execution_id}.", 404)
    return ExecutionSummary(
        execution_id=str(stored.id),
        merchant_id=stored.merchant_id,
        period_from=stored.period_from.isoformat() if stored.period_from else None,
        period_to=stored.period_to.isoformat() if stored.period_to else None,
        status=stored.status,
        response_source=stored.response_source,
        answer=stored.answer,
        claims=[AnswerClaim.model_validate(claim) for claim in stored.claims],
        grounding_attempts=stored.grounding_attempts,
        error=stored.error,
    )


@router.get("/{execution_id}/evidence", response_model=EvidenceIndex)
async def list_evidence(
    execution_id: UUID,
    metric_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = MAX_PAGE,
) -> EvidenceIndex:
    async with connection() as conn:
        await _require_verified(conn, execution_id)
        published = await load_evidence(conn, execution_id)

    rows = [row for row in published if metric_id is None or row.metric_id == metric_id]
    return EvidenceIndex(
        execution_id=str(execution_id),
        items=[_line(row) for row in sorted(rows, key=lambda row: row.id)[:limit]],
    )


@router.get("/{execution_id}/evidence/{evidence_id:path}", response_model=EvidenceDetail)
async def get_evidence(execution_id: UUID, evidence_id: str) -> EvidenceDetail:
    async with connection() as conn:
        await _require_verified(conn, execution_id)
        published = await load_evidence(conn, execution_id)

    row = published.get(evidence_id)
    if row is None:
        raise _error(
            "EVIDENCE_NOT_FOUND",
            f"No evidence {evidence_id} in execution {execution_id}.",
            404,
        )
    try:
        node = walk(published, evidence_id)
    except ProvenanceCycleError as error:
        # A broken chain is reported, never truncated. A drawer that renders
        # half a chain looks complete, which is worse than one that says the
        # provenance is unusable.
        raise _error(
            "PROVENANCE_UNWALKABLE",
            str(error),
            409,
            {"evidence_id": evidence_id, "max_depth": MAX_DEPTH},
        ) from error

    return EvidenceDetail(
        execution_id=str(execution_id),
        evidence_id=row.id,
        metric_id=row.metric_id,
        unit=row.unit,
        value=_scalar(row.value),
        display=canonical(row.value, row.unit),
        period_from=row.period_from,
        period_to=row.period_to,
        dimension_value=row.dimension_value,
        inputs={name: _scalar(value) for name, value in sorted(row.inputs.items())},
        rules_applied=list(row.rules_applied),
        verification_checks=list(row.verification_checks),
        provenance=_level(node),
        source_record_ids=list(source_records(node)),
    )


async def _require_verified(conn: Any, execution_id: UUID) -> None:
    stored = await read_execution(conn, execution_id)
    if stored is None:
        raise _error("EXECUTION_NOT_FOUND", f"No execution {execution_id}.", 404)
    if stored.status == "BLOCKED":
        blocked_at = (stored.error or {}).get("detail", {}).get("blocked_at")
        raise _error(
            "EXECUTION_BLOCKED",
            f"Execution {execution_id} failed verification at layer {blocked_at} "
            "and published no evidence.",
            409,
            {"blocked_at": blocked_at},
        )


def _scalar(value: object) -> int | str:
    return value if isinstance(value, int) else str(value)


def _line(row: Evidence) -> EvidenceLine:
    return EvidenceLine(
        evidence_id=row.id,
        tool_name=row.tool_name,
        tool_version=row.tool_version,
        metric_id=row.metric_id,
        unit=row.unit,
        value=_scalar(row.value),
        display=canonical(row.value, row.unit),
        period_from=row.period_from,
        period_to=row.period_to,
        dimension_value=row.dimension_value,
        support="FORMULA" if row.formula is not None else "AGGREGATION",
    )


def _level(node: ProvenanceNode) -> ProvenanceLevel:
    return ProvenanceLevel(
        evidence_id=node.evidence_id,
        tool_name=node.tool_name,
        tool_version=node.tool_version,
        metric_id=node.metric_id,
        unit=node.unit,
        value=_scalar(node.value),
        display=canonical(node.value, node.unit),
        period_from=node.period_from,
        period_to=node.period_to,
        dimension_value=node.dimension_value,
        support=node.support,
        detail=node.detail,
        rules_applied=list(node.rules_applied),
        operands=[_operand(operand) for operand in node.operands],
        source_record_ids=list(node.source_record_ids),
    )


def _operand(operand: Operand) -> ProvenanceOperand:
    return ProvenanceOperand(
        name=operand.name,
        reference=operand.reference,
        value=_scalar(operand.value),
        # A literal operand has no row and therefore no unit of its own; it is
        # the ``100`` in a percentage-point conversion, and it is written as it
        # appears in the expression.
        display=(
            str(operand.value)
            if operand.node is None
            else canonical(operand.value, operand.node.unit)
        ),
        node=None if operand.node is None else _level(operand.node),
    )
