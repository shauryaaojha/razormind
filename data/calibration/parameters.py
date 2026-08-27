"""Calibration parameters, each carrying its own provenance.

The rule this module exists to enforce: **no constant in the generator without a
tag**. A number that cannot say where it came from is a number nobody can
defend, and "calibrated against public statistics" is a claim that a single
invented constant turns into a lie.

Read `sources.md` for the citations. Read `Provenance` below for what the tags
mean, and note that `ASSUMED` is not an apology -- one merchant's payment mix is
not a published statistic and never will be. What matters is that it is labelled.
"""

from dataclasses import dataclass
from decimal import Decimal

from runtime.fees import FEE_SCHEDULE, Instrument, Provenance

__all__ = [
    "BASELINE_DECLINES",
    "BUSINESS_DECLINE_REASONS",
    "FEE_SCHEDULE",
    "MERCHANT_MIX",
    "SETTLEMENT_POLICY",
    "TECHNICAL_DECLINE_REASONS",
    "UPI_ECOSYSTEM",
    "DeclineProfile",
    "Instrument",
    "MethodProfile",
    "Parameter",
    "Provenance",
    "SettlementPolicy",
    "provenance_summary",
]


# `Provenance`, `Instrument` and `FEE_SCHEDULE` live in `runtime/fees.py`: the
# reconciliation engine needs the schedule to know what a settlement should have
# cost, and the application must not import the fixture. This module annotates
# them and owns everything the application does not need.


@dataclass(frozen=True)
class Parameter[T]:
    """One calibrated value and its justification."""

    value: T
    provenance: Provenance
    note: str

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.value} [{self.provenance}]"


# --------------------------------------------------------------------------
# ecosystem anchors
# --------------------------------------------------------------------------

UPI_ECOSYSTEM: dict[str, Parameter[object]] = {
    "monthly_volume_millions": Parameter(
        Decimal("23201.93"),
        Provenance.CITED,
        "NPCI UPI product statistics, May 2026.",
    ),
    "monthly_value_crore": Parameter(
        Decimal("2990424.21"),
        Provenance.CITED,
        "NPCI UPI product statistics, May 2026.",
    ),
    "average_ticket_paise": Parameter(
        129_300,
        Provenance.CITED,
        "Overall UPI average ticket size 2026, approx Rs 1,293.",
    ),
    "p2m_volume_share": Parameter(
        Decimal("0.63"),
        Provenance.CITED,
        "P2M is 63% of UPI volume but only 29% of value -- the anchor for "
        "modelling volume share and value share as separate quantities.",
    ),
    "p2m_value_share": Parameter(
        Decimal("0.29"),
        Provenance.CITED,
        "See above. A generator that uses one share for both is modelling a "
        "world that cannot exist.",
    ),
}


# --------------------------------------------------------------------------
# payment mix -- volume share and ticket size, never one 'share'
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MethodProfile:
    """One rail's share of *attempts* and its ticket distribution.

    Value share is **derived**, never declared: it falls out of
    ``volume_share x mean_ticket``. Declaring both independently is how a
    dataset ends up internally inconsistent in a way no test would catch.
    """

    method: str
    instrument_mix: dict[Instrument, Decimal]
    volume_share: Decimal
    mean_ticket_paise: int
    ticket_spread: Decimal
    provenance: Provenance
    note: str


#: This merchant's mix. ASSUMED as a whole -- no such statistic is published for
#: a single merchant -- but its *shape* is anchored: UPI dominant by count with a
#: small ticket, cards a minority of attempts carrying a much larger one.
MERCHANT_MIX: tuple[MethodProfile, ...] = (
    MethodProfile(
        method="UPI",
        instrument_mix={
            Instrument.UPI_BANK_ACCOUNT: Decimal("0.94"),
            Instrument.UPI_PPI_WALLET: Decimal("0.04"),
            Instrument.UPI_RUPAY_CREDIT: Decimal("0.02"),
        },
        volume_share=Decimal("0.72"),
        mean_ticket_paise=64_000,  # Rs 640
        ticket_spread=Decimal("0.80"),
        provenance=Provenance.ASSUMED,
        note="Anchored on UPI's volume dominance and low P2M ticket "
        "(86% of P2M volume under Rs 500). Merchant-specific share is synthetic.",
    ),
    MethodProfile(
        method="CARD",
        instrument_mix={
            Instrument.CREDIT_CARD: Decimal("0.62"),
            Instrument.OTHER_DEBIT: Decimal("0.26"),
            Instrument.RUPAY_DEBIT: Decimal("0.12"),
        },
        volume_share=Decimal("0.16"),
        mean_ticket_paise=285_000,  # Rs 2,850
        ticket_spread=Decimal("0.70"),
        provenance=Provenance.ASSUMED,
        note="Cards carry a much larger ticket than UPI -- the reason card "
        "value share far exceeds card volume share.",
    ),
    MethodProfile(
        method="NETBANKING",
        instrument_mix={Instrument.NETBANKING: Decimal("1.00")},
        volume_share=Decimal("0.06"),
        mean_ticket_paise=420_000,  # Rs 4,200
        ticket_spread=Decimal("0.65"),
        provenance=Provenance.ASSUMED,
        note="Low count, highest ticket. Typically used for large baskets.",
    ),
    MethodProfile(
        method="WALLET",
        instrument_mix={Instrument.WALLET: Decimal("1.00")},
        volume_share=Decimal("0.06"),
        mean_ticket_paise=52_000,  # Rs 520
        ticket_spread=Decimal("0.75"),
        provenance=Provenance.ASSUMED,
        note="Small ticket, small share. Present so the mix is not a duopoly.",
    ),
)


# --------------------------------------------------------------------------
# declines -- the TD / BD taxonomy
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DeclineProfile:
    """Technical and business decline rates for one rail.

    NPCI distinguishes these and publishes both per bank, monthly. The
    distinction is the whole reason this project can say *why* a success rate
    moved instead of only that it did:

    * a **technical** decline is the platform's problem -- a bank or NPCI
      back-end failing, and it spikes during an incident
    * a **business** decline is the customer's -- wrong PIN, insufficient
      funds, limit exceeded -- and it is roughly flat

    An investigation that cannot separate them can only report "success rate
    fell", which is a symptom, not a finding.
    """

    method: str
    technical_decline_rate: Decimal
    business_decline_rate: Decimal
    provenance: Provenance
    note: str


TECHNICAL_DECLINE_REASONS = (
    "BANK_TIMEOUT",
    "BANK_UNAVAILABLE",
    "NETWORK_ERROR",
    "PSP_ERROR",
)

BUSINESS_DECLINE_REASONS = (
    "INSUFFICIENT_FUNDS",
    "LIMIT_EXCEEDED",
    "AUTHENTICATION_FAILURE",
    "INVALID_BENEFICIARY",
)

#: Baseline, non-incident rates.
BASELINE_DECLINES: tuple[DeclineProfile, ...] = (
    DeclineProfile(
        method="UPI",
        technical_decline_rate=Decimal("0.007"),
        business_decline_rate=Decimal("0.028"),
        provenance=Provenance.CITED,
        note="Ecosystem TD is 0.7-0.8% (NPCI target <1%). BD target is <5% "
        "(OC-149); 2.8% sits inside it.",
    ),
    DeclineProfile(
        method="CARD",
        technical_decline_rate=Decimal("0.011"),
        business_decline_rate=Decimal("0.052"),
        provenance=Provenance.ASSUMED,
        note="Cards decline more than UPI, largely on authentication. No "
        "directly comparable published rate.",
    ),
    DeclineProfile(
        method="NETBANKING",
        technical_decline_rate=Decimal("0.019"),
        business_decline_rate=Decimal("0.041"),
        provenance=Provenance.ASSUMED,
        note="Netbanking redirects are the least reliable leg in practice.",
    ),
    DeclineProfile(
        method="WALLET",
        technical_decline_rate=Decimal("0.009"),
        business_decline_rate=Decimal("0.036"),
        provenance=Provenance.ASSUMED,
        note="Between UPI and cards; no published figure.",
    ),
)


# --------------------------------------------------------------------------
# settlement
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SettlementPolicy:
    """When the bank is expected to pay.

    A **commercial term**, not a law. It varies by acquirer, merchant risk
    category and instrument, so it is a scenario parameter rather than a
    constant baked into the calendar (D-25). Hard-coding T+2 as a universal
    Indian rule would be inventing a regulation.
    """

    expected_delay_business_days: int
    cutoff_hour_ist: int
    weekend_behavior: str
    holiday_behavior: str
    provenance: Provenance
    note: str


SETTLEMENT_POLICY = SettlementPolicy(
    expected_delay_business_days=2,
    cutoff_hour_ist=18,
    weekend_behavior="next_business_day",
    holiday_behavior="next_business_day",
    provenance=Provenance.ASSUMED,
    note="T+2 from an 18:00 IST cutoff is a common gateway term, not a "
    "statutory one. Scenarios may override it.",
)


def provenance_summary() -> dict[str, int]:
    """How many parameters rest on published data, and how many on judgement.

    Surfaced in the Data Provenance panel. A reader is entitled to know the
    ratio without reading the source.
    """
    counts = dict.fromkeys(Provenance, 0)
    for rule in FEE_SCHEDULE.values():
        counts[rule.provenance] += 1
    for profile in MERCHANT_MIX:
        counts[profile.provenance] += 1
    for decline in BASELINE_DECLINES:
        counts[decline.provenance] += 1
    for anchor in UPI_ECOSYSTEM.values():
        counts[anchor.provenance] += 1
    counts[SETTLEMENT_POLICY.provenance] += 1
    return {str(key): value for key, value in counts.items()}
