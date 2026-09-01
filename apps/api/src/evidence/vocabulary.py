"""The metric vocabulary. An id not in here cannot be published, cited, or claimed.

docs/06-trust-layer.md#metric-vocabulary, which fixes
[C-04](../../../../docs/00-corrections.md): every metric id ends in a unit suffix, and every claim
carries the unit alongside the value. "Percent of a count", "percent of a value" and "percentage
points" are three different things, and mixing them freely was the root cause of the original
demo's broken narrative.

Two things enforce it, and neither is a convention:

* ``DeterministicTool.__init_subclass__`` checks a tool's declared ``metrics`` against this
  module, so a tool publishing an unregistered id fails **at import**, not at query time.
* ``Evidence`` refuses a row whose ``metric_id`` is unregistered, whose ``unit`` disagrees with
  the suffix, or whose dimension is missing, unexpected, or outside the declared values.

Adding a metric is a code change plus a docs change, deliberately.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

__all__ = [
    "EQUIVALENCES",
    "METRICS",
    "UNIT_SUFFIXES",
    "Metric",
    "Unit",
    "UnknownMetricError",
    "metric",
    "unit_for",
]

type Unit = Literal["paise", "ratio", "pp", "count"]

#: The four units and the suffixes that declare them, longest match first.
#: ``success_rate_pp_change`` shows why: the unit suffix is not always the final
#: token, so a plain "split on the last underscore" would read it as a change
#: rather than as percentage points.
UNIT_SUFFIXES: tuple[tuple[str, Unit], ...] = (
    ("_pp_change", "pp"),
    ("_paise", "paise"),
    ("_ratio", "ratio"),
    ("_count", "count"),
    ("_pp", "pp"),
)


class UnknownMetricError(KeyError):
    """A metric id that is not in the vocabulary.

    Raised rather than tolerated. An unregistered id has no declared unit, so
    nothing downstream can check that a claim about it means what it says.
    """


@dataclass(frozen=True)
class Metric:
    """One registered metric.

    ``dimension`` names the slice a metric is measured over -- ``by_method.*``
    metrics are measured per rail, so every such evidence row carries a
    ``dimension_value``. ``values`` pins the slice when the set is genuinely
    closed (there are four payment rails) and is ``None`` when it is data
    (refund reasons are merchant text, and enumerating them here would make the
    vocabulary a place where facts about the data get invented).
    """

    id: str
    description: str
    dimension: str | None = None
    values: frozenset[str] | None = None
    #: Whether the metric may be negative. Layer 2 of verification (RANGE)
    #: is worth nothing without it: "a ratio is in [0, 1]" is false for
    #: ``net_revenue_change_ratio`` and "money is non-negative" is false for
    #: an attribution effect, so a single blanket rule would have to be
    #: relaxed to the point of checking nothing. Declaring it per metric is
    #: what makes a negative ``gross_payments_paise`` a caught defect
    #: (D-38).
    signed: bool = False

    @property
    def unit(self) -> Unit:
        return unit_for(self.id)

    @property
    def bounded(self) -> bool:
        """Whether the value must lie in [0, 1]. Only unsigned ratios are."""
        return self.unit == "ratio" and not self.signed


def unit_for(metric_id: str) -> Unit:
    """The unit a metric id declares, from its suffix.

    The suffix is load-bearing, not decoration: it is the only thing that stops
    a ratio being rendered as a percentage point or a count being formatted as
    money. An id with no recognised suffix is refused.
    """
    for suffix, unit in UNIT_SUFFIXES:
        if metric_id.endswith(suffix):
            return unit
    raise UnknownMetricError(
        f"metric id {metric_id!r} ends in no unit suffix; it must end in one of "
        + ", ".join(suffix for suffix, _ in UNIT_SUFFIXES)
    )


METHODS = frozenset({"UPI", "CARD", "NETBANKING", "WALLET"})


def _register(*metrics: Metric) -> Mapping[str, Metric]:
    registered: dict[str, Metric] = {}
    for entry in metrics:
        unit_for(entry.id)  # refuses an id with no unit suffix
        if entry.id in registered:
            raise ValueError(f"metric {entry.id!r} is registered twice")
        if entry.values is not None and entry.dimension is None:
            raise ValueError(f"metric {entry.id!r} pins values but declares no dimension")
        registered[entry.id] = entry
    return registered


#: Registered metrics (v1). Ids shared by more than one tool are deliberate --
#: see EQUIVALENCES.
METRICS: Mapping[str, Metric] = _register(
    # ---------------------------------------------------------- reconciliation
    Metric("ledger_count", "Settlement-eligible captures in the analysis window."),
    Metric("bank_count", "Settlement lines in the matching bank window (D-18)."),
    Metric("matched_pairs_count", "One-to-one pairs admitted by rules 1-4."),
    Metric("matched_clean_count", "Matched pairs carrying no exception."),
    Metric("clean_match_rate_ratio", "matched_clean_count / ledger_count."),
    Metric("exception_count", "Ledger-side exceptions only (D-20)."),
    Metric(
        "unresolved_exception_value_paise",
        "Value the bank has not confirmed. A confidence band, never a bridge term.",
    ),
    # ----------------------------------------------------------------- revenue
    Metric("attempted_value_paise", "Value of every payment attempt, successful or not."),
    Metric("gross_payments_paise", "Value of captured payments."),
    Metric("refunds_paise", "Refunds against captures in the window."),
    Metric("fees_paise", "Fees on captures, per instrument (D-24)."),
    Metric("chargebacks_paise", "Chargebacks against captures in the window."),
    Metric("net_revenue_paise", "gross - refunds - fees - chargebacks."),
    Metric(
        "net_revenue_change_paise",
        "Net revenue, current minus comparison period.",
        signed=True,
    ),
    Metric(
        "net_revenue_change_ratio",
        "That change as a proportion of the comparison period.",
        signed=True,
    ),
    Metric(
        "rounding_residual_paise",
        "The attribution plug. Bounded by the term count.",
        signed=True,
    ),
    Metric("confidence_band_ratio", "Unresolved exception value over net revenue."),
    Metric("attribution.attempt_volume_effect_paise", "Volume effect on gross.", signed=True),
    Metric(
        "attribution.success_rate_effect_paise",
        "Rate effect on gross, as the remainder.",
        signed=True,
    ),
    Metric("attribution.refunds_effect_paise", "Change in refunds, negated.", signed=True),
    Metric("attribution.fees_effect_paise", "Change in fees, negated.", signed=True),
    Metric(
        "attribution.chargebacks_effect_paise",
        "Change in chargebacks, negated.",
        signed=True,
    ),
    # ------------------------------------------------------- failure analysis
    Metric("attempt_count", "Payment attempts in the window."),
    Metric("succeeded_count", "Attempts that were captured."),
    Metric("succeeded_value_paise", "Value of attempts that were captured."),
    Metric("failed_value_paise", "Value of attempts that were not captured."),
    Metric("success_rate_ratio", "succeeded_count / attempt_count, blended across rails."),
    Metric(
        "success_rate_pp_change",
        "Blended success rate, in percentage points.",
        signed=True,
    ),
    Metric("technical_decline_ratio", "Attempts failing on a bank or NPCI back end."),
    Metric("business_decline_ratio", "Attempts declined for funds, PIN, or limits."),
    Metric("by_method.attempt_count", "Attempts on one rail.", "method", METHODS),
    Metric("by_method.succeeded_count", "Captures on one rail.", "method", METHODS),
    Metric("by_method.attempted_value_paise", "Attempted value on one rail.", "method", METHODS),
    Metric("by_method.succeeded_value_paise", "Captured value on one rail.", "method", METHODS),
    Metric(
        "by_method.success_rate_ratio",
        "Success rate for one rail. A different metric from the blended rate (C-03).",
        "method",
        METHODS,
    ),
    Metric(
        "by_method.success_rate_pp_change",
        "One rail's success rate change, in percentage points.",
        "method",
        METHODS,
        signed=True,
    ),
    # --------------------------------------------------------------- refunds
    Metric("refund_value_paise", "Refund value. Equal to the bridge's refunds_paise."),
    Metric("refund_count", "Refunds raised against captures in the window."),
    Metric(
        "refund_rate_ratio", "Refund value over gross payments. A value rate, not a count rate."
    ),
    Metric(
        "refund_value_change_paise",
        "Refund value, current minus comparison period.",
        signed=True,
    ),
    Metric("by_reason.refund_value_paise", "Refund value for one reason.", "reason"),
    Metric("by_reason.refund_count", "Refunds for one reason.", "reason"),
    # ------------------------------------------------------------ chargebacks
    Metric("chargeback_value_paise", "Chargeback value. Equal to the bridge's chargebacks_paise."),
    Metric("chargeback_count", "Chargebacks raised against captures in the window."),
    Metric(
        "chargeback_rate_ratio",
        "Chargeback value over gross payments. A value rate; the card networks' count-based "
        "ratio is a different quantity and is deliberately not published under this name.",
    ),
    Metric(
        "chargeback_value_change_paise",
        "Chargeback value, current minus comparison period.",
        signed=True,
    ),
    Metric("by_reason.chargeback_value_paise", "Chargeback value for one reason.", "reason"),
    Metric("by_reason.chargeback_count", "Chargebacks for one reason.", "reason"),
)


#: Quantities that two tools compute independently and must agree on exactly.
#:
#: Where both tools use the same id, the consistency layer finds them without
#: help. Where the framings differ -- the revenue bridge calls it
#: ``gross_payments_paise``, the failure analysis calls the same number
#: ``succeeded_value_paise`` -- nothing else would ever compare them, and two
#: tools quietly disagreeing about the same quantity is the defect this table
#: exists to catch (docs/06-trust-layer.md#cross-tool-consistency).
EQUIVALENCES: tuple[tuple[str, str], ...] = (
    ("gross_payments_paise", "succeeded_value_paise"),
    ("refunds_paise", "refund_value_paise"),
    ("chargebacks_paise", "chargeback_value_paise"),
)


def metric(metric_id: str) -> Metric:
    """The registered metric, or raise."""
    try:
        return METRICS[metric_id]
    except KeyError as error:
        raise UnknownMetricError(
            f"metric id {metric_id!r} is not in the vocabulary; adding one is a code change "
            "plus a docs change (docs/06-trust-layer.md#metric-vocabulary)"
        ) from error
