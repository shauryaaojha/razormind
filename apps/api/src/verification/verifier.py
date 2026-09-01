"""The five verification layers, in order, first failure blocks.

docs/06-trust-layer.md#verification. This runs after every tool has executed
and before any prose exists, and it is the thing that decides whether an
execution may be explained at all.

```text
1. TYPE        every output field matches its model; no float anywhere near money
2. RANGE       every published value is inside the range its metric declares
3. CONSISTENCY two tools computing one quantity agree, exactly
4. FORMULA     every derived metric is re-evaluated from its own declared formula
5. SOURCE      every cited record exists, sits inside the period, and re-folds
```

**The order is the contract, and so is stopping.** A layer runs only if every
layer before it passed. That is not an optimisation: a formula re-evaluated
against operands that failed their range check produces a number nobody should
read, and reporting it beside a range failure invites someone to pick the one
they prefer. One failing layer, named, is the whole answer.

**Why layer 4 is worth anything.** It does not ask the tool what it computed.
It reads the tool's declared expression, re-evaluates it through
``evidence/formula.py`` -- a grammar with no calls, so it cannot re-run the
tool -- against the tool's declared operands, and demands the same number. A
tool that reports a figure its own formula does not produce fails here, and
that is the check the entire trust story rests on.

**Where a leaf is checked.** A leaf metric has no arithmetic to re-evaluate, so
layer 4 checks the one identity that is available without the database (a COUNT
is the size of the set it cites) and layer 5 does the rest: the records exist,
they are inside the window, and a SUM re-folds to the published figure from the
records themselves. Re-folding is the leaf's layer 4 and it simply cannot
happen before the records are resolved, which is why it lives at the bottom
(D-41).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ValidationError

from evidence.builder import LITERAL, DuplicateEvidenceError, EvidenceSet
from evidence.formula import FormulaError, evaluate, operand_names
from evidence.models import Evidence
from evidence.vocabulary import EQUIVALENCES, UnknownMetricError, metric
from runtime.money import quantize_paise, quantize_pp, quantize_ratio

from .models import VerificationError
from .sources import SourceRecord, SourceResolver, UnknownRecordSetError

__all__ = [
    "LAYERS",
    "LayerResult",
    "ToolOutcome",
    "VerificationReport",
    "verify_execution",
]

#: In order. Position is meaning: a failure at position *n* means layers after
#: *n* did not run, not that they passed.
LAYERS: tuple[str, ...] = ("TYPE", "RANGE", "CONSISTENCY", "FORMULA", "SOURCE")

#: Scale a value of each unit must already be quantized to. Money and counts are
#: integers; the other two are Decimals rounded exactly once, in runtime.money.
_MAX_EXPONENT: Mapping[str, int] = {"ratio": 6, "pp": 2}


@dataclass(frozen=True)
class ToolOutcome:
    """One tool's contribution to an execution.

    Built by the caller rather than imported from ``tools``: the trust plane
    reads tool *values*, never tool modules, which is what keeps the dependency
    pointing one way (contract 2 in ``.importlinter``).
    """

    tool_name: str
    tool_version: str
    output: BaseModel
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class LayerResult:
    layer: str
    checks: tuple[str, ...]
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class VerificationReport:
    """What the five layers found, and how far they got."""

    layers: tuple[LayerResult, ...]

    @property
    def passed(self) -> bool:
        return len(self.layers) == len(LAYERS) and all(layer.passed for layer in self.layers)

    @property
    def blocked_at(self) -> str | None:
        """The layer that stopped the execution, or ``None`` if none did."""
        for layer in self.layers:
            if not layer.passed:
                return layer.layer
        return None

    @property
    def checks(self) -> tuple[str, ...]:
        return tuple(name for layer in self.layers for name in layer.checks)

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(
            f"{layer.layer}: {failure}" for layer in self.layers for failure in layer.failures
        )

    @property
    def status(self) -> str:
        """The execution state this report implies.

        ``BLOCKED`` is terminal and carries no prose. ``EXPLAINING`` is the
        state a verified execution is handed on in -- the numbers are trusted,
        and nothing has phrased them yet.
        """
        return "EXPLAINING" if self.passed else "BLOCKED"

    def raise_if_failed(self, subject: str) -> None:
        if not self.passed:
            raise VerificationError(subject, self.failures)


class _Layer:
    """Accumulates one layer's checks."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._checks: list[str] = []
        self._failures: list[str] = []

    def require(self, name: str, holds: bool, detail: str) -> None:
        self._checks.append(name)
        if not holds:
            self._failures.append(f"{name}: {detail}")

    def fail(self, name: str, detail: str) -> None:
        self.require(name, False, detail)

    def result(self) -> LayerResult:
        return LayerResult(self.name, tuple(self._checks), tuple(self._failures))


async def verify_execution(
    outcomes: Sequence[ToolOutcome], sources: SourceResolver
) -> VerificationReport:
    """Run the layers in order and stop at the first that fails.

    ``sources`` is required, not optional. A verifier handed no way to reach
    the records would have to skip layer 5, and an execution that skipped a
    layer is not a verified execution -- it is an unverified one with a longer
    report.
    """
    rows = tuple(row for outcome in outcomes for row in outcome.evidence)

    completed: list[LayerResult] = []
    for layer in (_type_layer(outcomes, rows), _range_layer(rows)):
        completed.append(layer)
        if not layer.passed:
            return VerificationReport(tuple(completed))

    try:
        published = EvidenceSet(rows)
    except DuplicateEvidenceError as error:
        clash = _Layer("CONSISTENCY")
        clash.fail("evidence_ids_are_unique", str(error))
        completed.append(clash.result())
        return VerificationReport(tuple(completed))

    for layer in (_consistency_layer(published), _formula_layer(published)):
        completed.append(layer)
        if not layer.passed:
            return VerificationReport(tuple(completed))

    completed.append(await _source_layer(published, sources))
    return VerificationReport(tuple(completed))


# --------------------------------------------------------------------------
# 1. TYPE
# --------------------------------------------------------------------------


def _type_layer(outcomes: Sequence[ToolOutcome], rows: Sequence[Evidence]) -> LayerResult:
    """The output is the shape it declared, and no float is anywhere in it.

    Re-validating an already-validated model looks redundant and is not: a tool
    may construct its output with ``model_construct`` or mutate a field after
    the fact, and either produces an object that passes ``isinstance`` while
    carrying a value its own model forbids.
    """
    layer = _Layer("TYPE")
    for outcome in outcomes:
        subject = f"{outcome.tool_name}.output"
        model = type(outcome.output)
        try:
            model.model_validate(outcome.output.model_dump())
        except ValidationError as error:
            layer.fail(f"{subject}_matches_its_model", f"{error.error_count()} field error(s)")
            continue
        layer.require(f"{subject}_matches_its_model", True, "")

        floats = sorted(_float_fields(outcome.output.model_dump()))
        layer.require(
            f"{subject}_carries_no_float",
            not floats,
            f"float-valued field(s): {', '.join(floats)}",
        )

    for row in rows:
        expected = "int" if row.unit in ("paise", "count") else "Decimal"
        actual = type(row.value).__name__
        layer.require(
            f"{row.id}/value_is_a_{expected}",
            (isinstance(row.value, int) and not isinstance(row.value, bool))
            if expected == "int"
            else isinstance(row.value, Decimal),
            f"{row.metric_id} is measured in {row.unit} but its value is a {actual}",
        )
    return layer.result()


def _float_fields(value: object, path: str = "") -> Iterable[str]:
    """Every path in a dumped model whose value is a float."""
    if isinstance(value, float):
        yield path or "<root>"
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _float_fields(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            yield from _float_fields(item, f"{path}[{index}]")


# --------------------------------------------------------------------------
# 2. RANGE
# --------------------------------------------------------------------------


def _range_layer(rows: Sequence[Evidence]) -> LayerResult:
    """Every value is inside the range its own metric declares.

    The vocabulary says which metrics may be negative, because a blanket rule
    cannot: "money is non-negative" is false for an attribution effect and
    "a ratio is in [0, 1]" is false for a change ratio, so one rule covering
    both would have to be weakened until it checked nothing (D-38).
    """
    layer = _Layer("RANGE")
    for row in rows:
        try:
            declared = metric(row.metric_id)
        except UnknownMetricError as error:
            layer.fail(f"{row.id}/metric_is_registered", str(error))
            continue

        layer.require(
            f"{row.id}/sign_is_declared",
            declared.signed or row.value >= 0,
            f"{row.metric_id} is unsigned but the value is {row.value}",
        )
        if declared.bounded:
            layer.require(
                f"{row.id}/ratio_is_a_proportion",
                Decimal(0) <= Decimal(row.value) <= Decimal(1),
                f"{row.value} is outside [0, 1]",
            )
        limit = _MAX_EXPONENT.get(row.unit)
        if limit is not None and isinstance(row.value, Decimal):
            exponent = row.value.as_tuple().exponent
            layer.require(
                f"{row.id}/is_quantized_to_scale_{limit}",
                isinstance(exponent, int) and -exponent <= limit,
                f"{row.value} carries more than {limit} decimal places",
            )
    return layer.result()


# --------------------------------------------------------------------------
# 3. CONSISTENCY
# --------------------------------------------------------------------------


def _consistency_layer(published: EvidenceSet) -> LayerResult:
    """Two tools computing one quantity must agree, exactly.

    Two shapes, and the second is the one nothing else would ever catch. Where
    both tools use the same metric id, finding the pair is trivial. Where the
    framings differ -- the revenue bridge says ``gross_payments_paise`` and the
    failure analysis says ``succeeded_value_paise`` for the same number --
    ``EQUIVALENCES`` is what makes them comparable at all.
    """
    layer = _Layer("CONSISTENCY")

    grouped: dict[tuple[str, str, str, str | None], list[Evidence]] = {}
    for row in published:
        key = (row.metric_id, row.period_from, row.period_to, row.dimension_value)
        grouped.setdefault(key, []).append(row)

    for (metric_id, period_from, _, dimension), group in sorted(grouped.items()):
        tools = {row.tool_name for row in group}
        if len(tools) < 2:
            continue
        values = {row.value for row in group}
        slice_of = f"#{dimension}" if dimension else ""
        layer.require(
            f"{metric_id}{slice_of}@{period_from}/agrees_across_tools",
            len(values) == 1,
            f"{sorted(tools)} publish {sorted(str(value) for value in values)}",
        )

    for left, right in EQUIVALENCES:
        periods = {row.period_from for row in published.by_metric(left)} & {
            row.period_from for row in published.by_metric(right)
        }
        for period_from in sorted(periods):
            left_values = {
                row.value for row in published.by_metric(left) if row.period_from == period_from
            }
            right_values = {
                row.value for row in published.by_metric(right) if row.period_from == period_from
            }
            layer.require(
                f"{left}=={right}@{period_from}",
                left_values == right_values,
                f"{sorted(str(v) for v in left_values)} against "
                f"{sorted(str(v) for v in right_values)}",
            )
    return layer.result()


# --------------------------------------------------------------------------
# 4. FORMULA
# --------------------------------------------------------------------------


def _formula_layer(published: EvidenceSet) -> LayerResult:
    """Re-derive every number that can be re-derived without the database."""
    layer = _Layer("FORMULA")
    for row in published:
        if row.formula is not None:
            _check_formula(layer, published, row)
        elif row.aggregation is not None and row.aggregation.operation == "COUNT":
            layer.require(
                f"{row.id}/count_is_the_size_of_the_set_it_cites",
                row.value == len(row.source_record_ids),
                f"published {row.value} over {len(row.source_record_ids)} cited record(s)",
            )
    return layer.result()


def _check_formula(layer: _Layer, published: EvidenceSet, row: Evidence) -> None:
    formula = row.formula
    assert formula is not None  # narrowing; the caller checked

    try:
        names = operand_names(formula.expression)
    except FormulaError as error:
        layer.fail(f"{row.id}/expression_is_in_the_grammar", str(error))
        return

    layer.require(
        f"{row.id}/operands_are_declared",
        names == frozenset(formula.operands) == frozenset(row.inputs),
        f"expression reads {sorted(names)}, declares {sorted(formula.operands)}, "
        f"supplies {sorted(row.inputs)}",
    )
    if names != frozenset(formula.operands) or names != frozenset(row.inputs):
        return

    for operand, reference in sorted(formula.operands.items()):
        if reference == LITERAL:
            continue
        cited = published.resolve(reference, row.period_from)
        if cited is None:
            layer.fail(
                f"{row.id}/operand_{operand}_resolves",
                f"{reference!r} names no evidence in this execution",
            )
            continue
        # The declared input and the cited row must be the same number. Without
        # this a tool could cite a row and then evaluate against something else
        # entirely, and the citation would be decoration.
        layer.require(
            f"{row.id}/operand_{operand}_matches_its_evidence",
            Decimal(row.inputs[operand]) == Decimal(cited.value),
            f"formula uses {row.inputs[operand]}, {cited.id} publishes {cited.value}",
        )

    try:
        exact = evaluate(formula.expression, row.inputs)
    except FormulaError as error:
        layer.fail(f"{row.id}/formula_evaluates", str(error))
        return

    recomputed = _quantize(row.unit, exact)
    layer.require(
        f"{row.id}/reproduces_its_own_formula",
        recomputed == row.value,
        f"{formula.expression!r} over {dict(sorted(row.inputs.items()))} gives {recomputed}, "
        f"but {row.metric_id} was published as {row.value}",
    )


def _quantize(unit: str, exact: Decimal) -> int | Decimal:
    """The single rounding, taken from ``runtime.money`` rather than repeated."""
    if unit in ("paise", "count"):
        return quantize_paise(exact)
    if unit == "pp":
        return quantize_pp(exact)
    return quantize_ratio(exact)


# --------------------------------------------------------------------------
# 5. SOURCE
# --------------------------------------------------------------------------


async def _source_layer(published: EvidenceSet, sources: SourceResolver) -> LayerResult:
    """Every cited record exists, sits inside the period, and re-folds.

    The re-fold is the leaf's answer to layer 4: ``gross_payments_paise`` has no
    expression to re-evaluate, so the check that means anything is summing the
    column over the records it cites and landing on the published figure. It is
    an independent computation -- the tool's query is not consulted -- which is
    what a formula reproducing a value by construction would not have been.
    """
    layer = _Layer("SOURCE")
    for row in published:
        fold = row.aggregation
        if fold is None:
            continue
        try:
            resolved = await sources.resolve(fold.over, fold.scoped_by, row.source_record_ids)
        except UnknownRecordSetError as error:
            layer.fail(f"{row.id}/record_set_is_resolvable", str(error))
            continue

        missing = [record_id for record_id in row.source_record_ids if record_id not in resolved]
        layer.require(
            f"{row.id}/cited_records_exist",
            not missing,
            f"{len(missing)} of {len(row.source_record_ids)} cited record(s) do not exist: "
            f"{', '.join(missing[:5])}",
        )
        if missing:
            continue

        opens, closes = date.fromisoformat(row.period_from), date.fromisoformat(row.period_to)
        outside = sorted(
            f"{record.id}@{record.anchor}"
            for record in resolved.values()
            if not opens <= record.anchor < closes
        )
        layer.require(
            f"{row.id}/cited_records_are_inside_the_period",
            not outside,
            f"{len(outside)} record(s) outside [{opens}, {closes}) by {fold.scoped_by}: "
            f"{', '.join(outside[:5])}",
        )
        if outside:
            continue

        if fold.operation == "SUM":
            refolded = _refold(fold.field_name, resolved.values())
            if refolded is None:
                layer.fail(
                    f"{row.id}/re_folds_from_its_records",
                    f"{fold.field_name!r} is not a field this verifier can re-sum",
                )
                continue
            layer.require(
                f"{row.id}/re_folds_from_its_records",
                refolded == row.value,
                f"summing {fold.field_name} over {len(resolved)} record(s) gives {refolded}, "
                f"but {row.metric_id} was published as {row.value}",
            )
    return layer.result()


def _refold(field_name: str, records: Iterable[SourceRecord]) -> int | None:
    if field_name == "amount_paise":
        return sum(record.amount_paise for record in records)
    if field_name == "fee_paise":
        return sum(record.fee_paise for record in records)
    return None
