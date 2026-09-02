"""The answer nobody wrote: every verified metric, rendered deterministically.

This is the floor the system will not fall below. With no model configured, or
with a model that could not produce a grounded answer twice, the user still
receives every figure that passed all five verification layers, each one
addressed by the evidence id that supports it. **Degrade the prose, never the
numbers.**

It is assembled from the evidence rows and nothing else, so it needs no
knowledge of revenue, refunds or reconciliation: rows carry a tool, a window, a
metric id and a value, and that is the whole input. A template with a paragraph
per analysis would have to be edited every time a tool published a new metric --
and the failure mode of forgetting is a fallback that silently stops mentioning
something.

Two constraints shape what it may print, both inherited from the grounding gate
it is deliberately subject to (``llm/grounding.py``):

* **every number in the narrative is a claim**, so the template emits one claim
  per line as it writes the line;
* **no other digits**, which is why lines are labelled from the metric id
  rather than from the vocabulary's descriptions -- those cite corrections and
  decisions by number ("rules 1-4", "(D-20)"), and a reader cannot tell a
  citation from a figure by looking at the digits.
"""

from collections.abc import Iterable, Sequence
from itertools import groupby

from evidence.builder import EvidenceSet
from evidence.models import Evidence
from evidence.vocabulary import METRICS, UNIT_SUFFIXES

from .models import Claim, Explanation
from .render import canonical

__all__ = ["PREAMBLE", "compose", "label"]

PREAMBLE = (
    "This answer was assembled from a template rather than written by a language model. "
    "Every figure below passed all five verification layers before it was rendered, and "
    "each one carries the evidence id it can be walked down from."
)

#: Publication order inside one group, taken from the vocabulary's own order.
#: The registry is written in the order a reader would want to read the metrics
#: -- the bridge before its attribution, the blended rate before the rails --
#: so there is nothing to invent here and nothing that can drift.
_ORDER = {metric_id: position for position, metric_id in enumerate(METRICS)}

#: Prefixes that name a family rather than a quantity. ``by_method.`` and
#: ``by_reason.`` are dropped because the slice already appears beside the
#: label; ``attribution.`` is kept, because "volume effect" without it reads
#: like a measurement rather than a decomposition term.
_DROPPED_PREFIXES = ("by_method", "by_reason")

#: What survives when a unit suffix is stripped. Only ``_pp_change`` carries a
#: word rather than a unit: without it ``success_rate_pp_change`` and
#: ``success_rate_ratio`` would both be labelled "Success rate", and a reader
#: looking at two lines with one name would have to read the ids to tell a rate
#: from a move in one.
_KEPT = {"_pp_change": "_change"}


def compose(
    published: EvidenceSet,
    *,
    limitations: Sequence[str] = (),
) -> Explanation:
    """Every verified row, grouped by tool and window, with a claim for each."""
    lines: list[str] = [PREAMBLE]
    claims: list[Claim] = []

    for group in _groups(published):
        lines.append("")
        lines.append(f"{group[0].tool_name}  [{group[0].period_from}, {group[0].period_to})")
        for row in group:
            line = f"- {label(row)} ({row.metric_id}): {canonical(row.value, row.unit)}"
            lines.append(line)
            claims.append(
                Claim(
                    text=line,
                    metric_id=row.metric_id,
                    value=row.value,
                    unit=row.unit,
                    evidence_id=row.id,
                )
            )

    return Explanation(
        narrative="\n".join(lines),
        claims=claims,
        limitations=list(limitations),
    )


def label(row: Evidence) -> str:
    """A digit-free name for a metric, derived from its id.

    ``net_revenue_change_paise`` becomes "Net revenue change";
    ``by_method.success_rate_ratio`` on the UPI row becomes "Success rate, UPI".
    Derived rather than declared so a new metric arrives with a label already,
    and so the vocabulary does not acquire a display field that would then have
    to be kept honest.
    """
    family, _, stem = row.metric_id.rpartition(".")
    for suffix, _unit in UNIT_SUFFIXES:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)] + _KEPT.get(suffix, "")
            break
    words = stem.replace("_", " ")
    if family and family not in _DROPPED_PREFIXES:
        words = f"{family} {words}"
    text = words[:1].upper() + words[1:]
    return text if row.dimension_value is None else f"{text}, {row.dimension_value}"


def _groups(published: EvidenceSet) -> Iterable[tuple[Evidence, ...]]:
    """Rows by tool, then by window with the most recent first.

    The most recent window is the one the question was about; a comparison
    window read before the period it is compared with is a paragraph the reader
    has to hold in their head backwards.
    """
    windows = sorted({(row.tool_name, row.period_from, row.period_to) for row in published})
    for tool_name, group in groupby(windows, key=lambda window: window[0]):
        for _, period_from, period_to in sorted(group, key=lambda window: window[1:], reverse=True):
            rows = [
                row
                for row in published
                if row.tool_name == tool_name
                and row.period_from == period_from
                and row.period_to == period_to
            ]
            yield tuple(sorted(rows, key=_position))


def _position(row: Evidence) -> tuple[int, str, str]:
    return (_ORDER.get(row.metric_id, len(_ORDER)), row.metric_id, row.dimension_value or "")
