"""What a metric's support looks like on the wire.

Fixes C-15b/C-15c: the original had no execution or tool linkage and an
unparseable ``calculation: str``. Here a metric's support is either an
arithmetic :class:`Formula` over named operands, or an :class:`Aggregation`
over a named set of source records -- and never both, never neither.

That split is deliberate. A derived metric ("net = gross - refunds - fees -
chargebacks") is verified by re-evaluating its expression. A leaf metric
("gross is the sum of 341 amounts") has no arithmetic to re-evaluate; it is
verified by re-summing the records it cites. Forcing a leaf to carry a
341-term expression would technically satisfy "every metric has a Formula"
while making the evidence unreadable, and pretending a leaf has a formula it
does not have would make layer 4 a check that always passes.
"""

from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, field_serializer, model_validator

from .vocabulary import Unit, UnknownMetricError, metric

__all__ = ["Aggregation", "Evidence", "Formula", "Unit"]


class Formula(BaseModel):
    """Arithmetic over named operands, in the grammar of ``evidence/formula.py``.

    Operand names are short and unit-free (``gross``, ``prior``); ``operands``
    maps each one to the id of the evidence that supports it, or to
    ``"literal"``. Keeping the unit suffix out of the expression is not
    cosmetic: it keeps the C-01 guard (which forbids ``/`` applied to a
    ``_paise`` name) meaningful rather than something a string literal can
    trip.
    """

    model_config = ConfigDict(frozen=True)

    expression: str
    operands: dict[str, str]
    unit: Unit


class Aggregation(BaseModel):
    """A fold over the cited source records, for a metric with no arithmetic.

    ``predicate`` is the record set in words, and is what a reviewer reads to
    decide whether the right rows were counted. ``source_record_ids`` on the
    evidence is what the verifier re-sums.
    """

    model_config = ConfigDict(frozen=True)

    operation: Literal["SUM", "COUNT"]
    field_name: str
    over: str
    predicate: str
    unit: Unit


class Evidence(BaseModel):
    """One published metric, with everything needed to disbelieve it.

    ``period_from``/``period_to`` are part of the identity, not decoration: a
    revenue analysis publishes ``net_revenue_paise`` for two windows, and two
    rows carrying the same ``metric_id`` with no way to tell them apart is how
    a prior-period number ends up cited as a current-period one.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    execution_id: str
    tool_name: str
    tool_version: str

    metric_id: str
    unit: Unit
    value: int | Decimal
    period_from: str
    period_to: str
    #: The slice this row measures, for a metric the vocabulary declares a
    #: dimension for -- ``"UPI"`` on a ``by_method.*`` row. ``None`` otherwise.
    dimension_value: str | None = None

    formula: Formula | None = None
    aggregation: Aggregation | None = None
    inputs: dict[str, int | Decimal] = {}

    source_record_ids: list[str] = []
    rules_applied: list[str] = []
    verification_checks: list[str] = []

    @model_validator(mode="after")
    def _exactly_one_support(self) -> Self:
        if (self.formula is None) == (self.aggregation is None):
            raise ValueError(
                f"evidence {self.id!r} must carry exactly one of formula or aggregation"
            )
        return self

    @model_validator(mode="after")
    def _metric_is_registered(self) -> Self:
        """The vocabulary decides what may be published (C-04).

        Checked here as well as at import, because a tool declares its metric
        ids as a class attribute and nothing stops it emitting a row for
        something else. The unit check is the one that matters most: a ratio
        published as ``pp`` renders as a plausible number that means something
        else entirely, which is the failure C-04 exists to stop.
        """
        try:
            registered = metric(self.metric_id)
        except UnknownMetricError as error:
            # Re-raised as a ValueError so pydantic reports it as a validation
            # failure on this field rather than letting a KeyError escape from
            # the middle of model construction.
            raise ValueError(str(error)) from error
        if self.unit != registered.unit:
            raise ValueError(
                f"evidence {self.id!r} publishes {self.metric_id!r} as {self.unit!r}, "
                f"but the vocabulary declares {registered.unit!r}"
            )
        if registered.dimension is None and self.dimension_value is not None:
            raise ValueError(
                f"{self.metric_id!r} is not measured over a dimension, but "
                f"{self.id!r} carries the value {self.dimension_value!r}"
            )
        if registered.dimension is not None:
            if self.dimension_value is None:
                raise ValueError(
                    f"{self.metric_id!r} is measured per {registered.dimension}, "
                    f"and {self.id!r} names no {registered.dimension}"
                )
            if registered.values is not None and self.dimension_value not in registered.values:
                raise ValueError(
                    f"{self.dimension_value!r} is not a {registered.dimension}; "
                    f"{self.metric_id!r} admits {sorted(registered.values)}"
                )
        return self

    @field_serializer("value")
    def _serialize_value(self, value: int | Decimal) -> int | str:
        """Ratios go over the wire as strings (D-02); money stays an integer."""
        return value if isinstance(value, int) else str(value)

    @field_serializer("inputs")
    def _serialize_inputs(self, inputs: dict[str, int | Decimal]) -> dict[str, int | str]:
        return {
            name: value if isinstance(value, int) else str(value) for name, value in inputs.items()
        }
