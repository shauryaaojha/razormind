"""The merchant fee schedule, per instrument.

This is **application configuration, not seed data**: the reconciliation engine
needs it to know what a settlement *should* have cost, so it lives here and the
calibration layer annotates it with provenance rather than owning it. Pointing
the dependency the other way would make the engine import the fixture.

Why per instrument and not a flat percentage — the correction that matters most
in this file:

* Bank-account-funded UPI and RuPay debit carry **zero MDR**, mandated since
  January 2020. A flat 1% model cannot represent that at all.
* PPI-funded UPI carries an interchange above Rs 2,000; RuPay credit on UPI
  carries MDR above the same threshold.
* Credit cards carry a commercially negotiated rate an order of magnitude
  above UPI.
* Netbanking is conventionally billed per transaction, not ad valorem.

Under a flat rate, a fee discrepancy is arithmetic noise. Under this schedule it
means a specific commercial rule was applied wrongly — "a zero-MDR UPI payment
was billed at the credit-card rate" is a finding an analyst can act on.

Citations and provenance tags: ``data/calibration/sources.md``.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from runtime.money import Paise, apply_rate

__all__ = ["FEE_SCHEDULE", "FeeRule", "Instrument", "Provenance"]


class Provenance(StrEnum):
    """Where a parameter came from. Every one must declare it.

    ``ASSUMED`` is not an apology — one merchant's commercial agreement is not
    a published statistic and never will be. What matters is that a design
    choice is never mistaken for an observation.
    """

    CITED = "CITED"
    DERIVED = "DERIVED"
    ASSUMED = "ASSUMED"


class Instrument(StrEnum):
    """The *funding source*, which is what decides the fee.

    Distinct from the rail (``method``). Collapsing the two is precisely what
    makes a flat fee model unable to represent a real discrepancy.
    """

    UPI_BANK_ACCOUNT = "UPI_BANK_ACCOUNT"
    UPI_PPI_WALLET = "UPI_PPI_WALLET"
    UPI_RUPAY_CREDIT = "UPI_RUPAY_CREDIT"
    RUPAY_DEBIT = "RUPAY_DEBIT"
    OTHER_DEBIT = "OTHER_DEBIT"
    CREDIT_CARD = "CREDIT_CARD"
    NETBANKING = "NETBANKING"
    WALLET = "WALLET"


@dataclass(frozen=True)
class FeeRule:
    """What the merchant is charged for one payment on one instrument.

    ``platform_fee_rate`` exists separately from ``mdr_rate`` because **zero MDR
    does not mean free** — a gateway may charge its own fee where MDR is nil,
    a distinction Razorpay's own material makes explicitly.

    ``threshold_paise`` is the value below which the MDR does not apply at all.
    That threshold is what makes small-ticket UPI free in practice, and it is a
    rule, not a rounding artefact.
    """

    instrument: Instrument
    mdr_rate: Decimal
    platform_fee_rate: Decimal
    threshold_paise: int
    flat_fee_paise: int
    provenance: Provenance
    note: str

    def fee_paise(self, amount_paise: Paise) -> Paise:
        """The expected fee. One rounding, in ``runtime/money.py``, as always."""
        rate = self.mdr_rate if amount_paise > self.threshold_paise else Decimal(0)
        return apply_rate(amount_paise, rate + self.platform_fee_rate) + self.flat_fee_paise


FEE_SCHEDULE: dict[Instrument, FeeRule] = {
    Instrument.UPI_BANK_ACCOUNT: FeeRule(
        instrument=Instrument.UPI_BANK_ACCOUNT,
        mdr_rate=Decimal("0"),
        platform_fee_rate=Decimal("0"),
        threshold_paise=0,
        flat_fee_paise=0,
        provenance=Provenance.CITED,
        note="Zero MDR on bank-account-funded UPI, mandated since January 2020.",
    ),
    Instrument.UPI_PPI_WALLET: FeeRule(
        instrument=Instrument.UPI_PPI_WALLET,
        mdr_rate=Decimal("0.0110"),
        platform_fee_rate=Decimal("0"),
        threshold_paise=200_000,  # Rs 2,000
        flat_fee_paise=0,
        provenance=Provenance.CITED,
        note="PPI-funded UPI interchange, up to 1.1% above Rs 2,000.",
    ),
    Instrument.UPI_RUPAY_CREDIT: FeeRule(
        instrument=Instrument.UPI_RUPAY_CREDIT,
        mdr_rate=Decimal("0.0150"),
        platform_fee_rate=Decimal("0"),
        threshold_paise=200_000,
        flat_fee_paise=0,
        provenance=Provenance.CITED,
        note="RuPay credit on UPI: MDR above Rs 2,000 from 01 June 2026, "
        "reported in the 1.1%-2% range. 1.50% chosen inside that band.",
    ),
    Instrument.RUPAY_DEBIT: FeeRule(
        instrument=Instrument.RUPAY_DEBIT,
        mdr_rate=Decimal("0"),
        platform_fee_rate=Decimal("0"),
        threshold_paise=0,
        flat_fee_paise=0,
        provenance=Provenance.CITED,
        note="Zero MDR on RuPay debit, mandated since January 2020.",
    ),
    Instrument.OTHER_DEBIT: FeeRule(
        instrument=Instrument.OTHER_DEBIT,
        mdr_rate=Decimal("0.0090"),
        platform_fee_rate=Decimal("0"),
        threshold_paise=0,
        flat_fee_paise=0,
        provenance=Provenance.ASSUMED,
        note="Non-RuPay debit MDR is capped and merchant-category dependent. "
        "0.90% is a plausible online rate; not a published figure.",
    ),
    Instrument.CREDIT_CARD: FeeRule(
        instrument=Instrument.CREDIT_CARD,
        mdr_rate=Decimal("0.0190"),
        platform_fee_rate=Decimal("0"),
        threshold_paise=0,
        flat_fee_paise=0,
        provenance=Provenance.ASSUMED,
        note="Credit card MDR is a commercial agreement, not a published rate. "
        "1.90% is typical for online; this merchant's agreement is synthetic.",
    ),
    Instrument.NETBANKING: FeeRule(
        instrument=Instrument.NETBANKING,
        mdr_rate=Decimal("0"),
        platform_fee_rate=Decimal("0"),
        threshold_paise=0,
        flat_fee_paise=1_200,  # Rs 12 flat
        provenance=Provenance.ASSUMED,
        note="Netbanking is conventionally billed per transaction rather than "
        "ad valorem. Rs 12 flat; bank- and gateway-specific in reality.",
    ),
    Instrument.WALLET: FeeRule(
        instrument=Instrument.WALLET,
        mdr_rate=Decimal("0.0165"),
        platform_fee_rate=Decimal("0"),
        threshold_paise=0,
        flat_fee_paise=0,
        provenance=Provenance.ASSUMED,
        note="Closed-loop wallet acceptance, commercially negotiated.",
    ),
}
