"""The gate between a verified number and a sentence about it.

docs/06-trust-layer.md#grounding. Five checks, all of them run, all of them
reported:

```text
1. every numeric token in the prose belongs to a claim
2. every claim names a metric the vocabulary registers
3. every claim's value byte-matches the verified row, and the prose says it
4. every claim's unit is the one the vocabulary declares
5. every claim's evidence id resolves to a row this execution published
```

Unlike the verification layers, these do **not** stop at the first failure.
Verification stops because a later layer reading earlier layers' numbers would
produce a figure nobody should see; grounding has no such coupling, and its
whole output is a list of corrections to hand back to the model on the second
attempt. Naming one problem at a time would make the retry a guessing game.

**Check 3 is the one that matters, and it is two checks wearing one name.**
The declared value must byte-match the verified row -- ``0.958`` is not
``0.958012``, and a claim that quietly drops precision is a claim about a
different number. And the prose must actually *say* that value: a model can
declare the right figure in the structured field and write a rounded one in the
sentence a human reads, which is precisely the original spec's defect (D-11).
So every numeric token inside the claim's own span is matched against the
accepted renderings of the verified value.

**What is deliberately not checked.** Dates the execution itself was scoped to,
and the merchant id, are literals the caller passes in; they are masked out
before tokenising, because "2026-08-01" is not a claim about money and a gate
that failed on it would be a gate nobody could satisfy. Everything else with a
digit in it must be claimed -- including, by design, a number the model was
right about but did not cite.
"""

import re
from collections.abc import Iterable, Sequence
from decimal import Decimal

from evidence.builder import EvidenceSet
from evidence.vocabulary import UnknownMetricError, metric
from narrative.models import Claim, Explanation
from narrative.render import renderings
from verification.models import Checks, VerificationResult

__all__ = ["CHECKS", "check_grounding", "literals_for"]

#: The five, in the order they are reported. Named here as well as used below so
#: a test can assert every one of them ran rather than trusting that it did.
CHECKS: tuple[str, ...] = (
    "every_number_is_claimed",
    "metric_is_registered",
    "value_byte_matches_the_verified_row",
    "unit_matches_the_vocabulary",
    "evidence_id_resolves",
)

#: A number as it appears in prose: an optional sign, an optional rupee sign,
#: digits with Indian grouping, an optional fraction, an optional percent. The
#: sign is admitted on either side of the currency symbol because "-₹1,000" and
#: "₹-1,000" are both written by somebody.
_TOKEN = re.compile(r"-?₹?-?\d[\d,]*(?:\.\d+)?%?")


def literals_for(published: EvidenceSet, *extra: str) -> frozenset[str]:
    """Digit-bearing strings the prose may contain without claiming them.

    Every window any row was published for **and the year of each**, plus
    whatever the caller adds -- in practice the merchant id, which the model is
    told to echo. Derived from the evidence rather than passed in wholesale, so
    the exemption cannot be widened from outside to whatever the last failing
    answer happened to contain.

    The year is here because the ISO form on its own is not how anyone writes a
    period in a sentence. "Net revenue fell in July 2026" is the ordinary way to
    open this answer, and with only ``2026-07-01`` exempt the ``2026`` is an
    unclaimed number and a correct answer goes to the template. Exempting it is
    within the boundary D-48 draws -- grounding checks the figures, not the
    sentence -- because a year is the window this execution already ran on, not
    a quantity anybody computed (D-58).

    Masking is digit-bounded (see :func:`_masked`), so exempting ``2026`` cannot
    reach inside ``20261`` and turn a wrong count into an unremarkable ``1``.
    """
    windows = {row.period_from for row in published} | {row.period_to for row in published}
    years = {window.split("-")[0] for window in windows}
    return frozenset(windows | years | {value for value in extra if value})


def check_grounding(
    explanation: Explanation,
    published: EvidenceSet,
    *,
    literals: Iterable[str] = (),
) -> VerificationResult:
    """Run all five checks over one answer. Never raises for a bad answer."""
    checks = Checks()
    allowed = frozenset(literals)

    _numbers_are_claimed(checks, explanation, allowed)
    for position, claim in enumerate(explanation.claims):
        where = f"claim {position}"
        _metric_is_registered(checks, where, claim)
        _evidence_resolves(checks, where, claim, published)
        _value_and_unit(checks, where, claim, published, allowed)

    return checks.result()


# --------------------------------------------------------------------------
# check 1
# --------------------------------------------------------------------------


def _numbers_are_claimed(
    checks: Checks, explanation: Explanation, literals: frozenset[str]
) -> None:
    """No digit in the prose that no claim accounts for.

    Claim spans are located by searching for the text rather than trusting an
    offset the model computed -- an offset is one more field to distrust, and a
    substring either is there or is not.
    """
    narrative = explanation.narrative
    covered = _spans(narrative, explanation.claims)
    for position, claim in enumerate(explanation.claims):
        checks.require(
            f"{CHECKS[0]}: claim {position} appears in the answer",
            claim.text != "" and claim.text in narrative,
            f"the claim text {_trimmed(claim.text)} is not a span of the answer",
        )

    masked = _masked(narrative, literals)
    for token in _TOKEN.finditer(masked):
        inside = any(start <= token.start() and token.end() <= end for start, end in covered)
        checks.require(
            f"{CHECKS[0]}: {token.group()} at {token.start()}",
            inside,
            f"the answer states {token.group()!r} and no claim covers it",
        )


def _spans(narrative: str, claims: Sequence[Claim]) -> tuple[tuple[int, int], ...]:
    """Every occurrence of every claim's text, as half-open index ranges."""
    found: list[tuple[int, int]] = []
    for claim in claims:
        if not claim.text:
            continue
        start = narrative.find(claim.text)
        while start != -1:
            found.append((start, start + len(claim.text)))
            start = narrative.find(claim.text, start + 1)
    return tuple(found)


def _masked(narrative: str, literals: frozenset[str]) -> str:
    """Blank out the permitted literals, preserving every index.

    Longest first, so ``2026-07-01`` is gone before ``2026`` is looked for, and
    only where no digit touches either end. A plain substring replace would let
    the exempt year eat four digits out of the middle of a figure and leave a
    remainder that grounds as something else entirely -- ``20261`` becoming
    ``1`` is a wrong count passing as a right one, which is the one direction
    this gate is not allowed to fail in.
    """
    masked = narrative
    for literal in sorted(literals, key=len, reverse=True):
        masked = re.sub(
            rf"(?<!\d){re.escape(literal)}(?!\d)",
            " " * len(literal),
            masked,
        )
    return masked


# --------------------------------------------------------------------------
# checks 2 to 5
# --------------------------------------------------------------------------


def _metric_is_registered(checks: Checks, where: str, claim: Claim) -> None:
    try:
        metric(claim.metric_id)
    except UnknownMetricError as error:
        checks.require(f"{CHECKS[1]}: {where}", False, str(error))
        return
    checks.require(f"{CHECKS[1]}: {where}", True, "")


def _evidence_resolves(checks: Checks, where: str, claim: Claim, published: EvidenceSet) -> None:
    checks.require(
        f"{CHECKS[4]}: {where}",
        published.get(claim.evidence_id) is not None,
        f"no row with id {claim.evidence_id!r} was published by this execution",
    )


def _value_and_unit(
    checks: Checks,
    where: str,
    claim: Claim,
    published: EvidenceSet,
    literals: frozenset[str],
) -> None:
    """Checks 3 and 4, which both need the verified row to compare against.

    A claim whose evidence id did not resolve is skipped here rather than
    failed twice: check 5 has already said the citation is broken, and
    "the value does not match" is not additional information about a row that
    does not exist.
    """
    row = published.get(claim.evidence_id)
    if row is None:
        return

    checks.require(
        f"{CHECKS[3]}: {where}",
        claim.unit == row.unit,
        f"claims {claim.unit!r} for {claim.metric_id!r}, which is published as {row.unit!r}",
    )
    checks.require(
        f"{CHECKS[2]}: {where} names the right metric",
        claim.metric_id == row.metric_id,
        f"cites evidence for {row.metric_id!r} while claiming {claim.metric_id!r}",
    )
    checks.require(
        f"{CHECKS[2]}: {where} value",
        _exact(claim.value) == _exact(row.value),
        f"claims {_exact(claim.value)} where the verified row is {_exact(row.value)}",
    )

    # The same literals are masked here as in check 1. A claim's span is a
    # sentence, and a sentence that names the window it covers would otherwise
    # be asked to render "2026" as a paise amount.
    accepted = renderings(row.value, row.unit)
    spoken = [token.group() for token in _TOKEN.finditer(_masked(claim.text, literals))]
    checks.require(
        f"{CHECKS[2]}: {where} states a number",
        bool(spoken),
        f"the claim text {_trimmed(claim.text)} contains no number at all",
    )
    for token in spoken:
        checks.require(
            f"{CHECKS[2]}: {where} writes {token}",
            token in accepted,
            f"the answer writes {token!r}; {row.metric_id!r} is {accepted[0]!r}",
        )


def _exact(value: int | Decimal) -> str:
    """The value as text, scale included. This is what "byte-match" means (D-11)."""
    return str(value)


def _trimmed(text: str, limit: int = 80) -> str:
    compact = " ".join(text.split())
    return repr(compact if len(compact) <= limit else compact[:limit] + "...")
