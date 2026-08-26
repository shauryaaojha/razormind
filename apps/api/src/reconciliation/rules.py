"""The five matching rules, in priority order.

docs/03-reconciliation.md#rules. Each rule is a pure predicate over one ledger
record and one bank record; the assignment loop in ``engine.py`` decides what
to do with the candidates a rule proposes.

One clarification the spec leaves implicit and this module makes explicit: the
exception table says a lag beyond three business days means "the pair is not
formed at all", but rules 1 and 2 name no lag condition. They inherit the same
ceiling here -- otherwise an exactly-matching UTR would pair records a month
apart and the timing-lag category would be unreachable for them.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal

from runtime.calendar import MAX_TIMING_LAG_BUSINESS_DAYS, business_day_lag

from .models import BankRecord, Candidate, LedgerRecord

__all__ = ["RULES", "Rule", "amount_delta", "lag_days", "propose"]


def amount_delta(ledger: LedgerRecord, bank: BankRecord) -> int:
    """What the bank says minus what the ledger says."""
    return bank.amount_paise - ledger.amount_paise


def lag_days(ledger: LedgerRecord, bank: BankRecord) -> int:
    """Business days late. Negative means the bank paid early."""
    return business_day_lag(ledger.settlement_due_date, bank.value_date)


def _pairable(lag: int) -> bool:
    """Beyond the ceiling there is no pair to form, only a missing counterpart."""
    return lag <= MAX_TIMING_LAG_BUSINESS_DAYS


@dataclass(frozen=True)
class Rule:
    """One matching rule.

    ``needs_unique_amount`` is rule 4's extra condition: an amount may only
    identify a pair when it identifies exactly one record on each side. Without
    it, two unrelated payments of the same value on the same day would match
    each other on nothing but coincidence.
    """

    name: str
    confidence_ratio: Decimal
    reason: str
    predicate: Callable[[LedgerRecord, BankRecord, int], bool]
    needs_unique_amount: bool = False

    @property
    def auto_matches(self) -> bool:
        from .models import AUTO_MATCH_THRESHOLD

        return self.confidence_ratio >= AUTO_MATCH_THRESHOLD


def _exact_utr(ledger: LedgerRecord, bank: BankRecord, lag: int) -> bool:
    return (
        ledger.utr is not None
        and bank.utr is not None
        and ledger.utr == bank.utr
        and amount_delta(ledger, bank) == 0
        and _pairable(lag)
    )


def _ref_amount(ledger: LedgerRecord, bank: BankRecord, lag: int) -> bool:
    return (
        bank.bank_ref is not None
        and ledger.external_ref == bank.bank_ref
        and amount_delta(ledger, bank) == 0
        and _pairable(lag)
    )


def _ref_date_window(ledger: LedgerRecord, bank: BankRecord, lag: int) -> bool:
    return (
        bank.bank_ref is not None
        and ledger.external_ref == bank.bank_ref
        and abs(lag) <= MAX_TIMING_LAG_BUSINESS_DAYS
    )


def _amount_date_window(ledger: LedgerRecord, bank: BankRecord, lag: int) -> bool:
    return amount_delta(ledger, bank) == 0 and abs(lag) <= 2


def _amount_date_candidate(ledger: LedgerRecord, bank: BankRecord, lag: int) -> bool:
    return amount_delta(ledger, bank) == 0 and abs(lag) <= 5


RULES: tuple[Rule, ...] = (
    Rule(
        name="EXACT_UTR",
        confidence_ratio=Decimal("1.00"),
        reason="UTR and amount agree exactly",
        predicate=_exact_utr,
    ),
    Rule(
        name="REF_AMOUNT",
        confidence_ratio=Decimal("0.98"),
        reason="Reference and amount agree; no UTR on one side",
        predicate=_ref_amount,
    ),
    Rule(
        name="REF_DATE_WINDOW",
        confidence_ratio=Decimal("0.90"),
        reason="Reference agrees within the settlement window; amount differs",
        predicate=_ref_date_window,
    ),
    Rule(
        name="AMOUNT_DATE_WINDOW",
        confidence_ratio=Decimal("0.85"),
        reason="Amount is unique on both sides and lands inside the window",
        predicate=_amount_date_window,
        needs_unique_amount=True,
    ),
    Rule(
        name="AMOUNT_DATE_CANDIDATE",
        confidence_ratio=Decimal("0.72"),
        reason="Amount agrees but nothing else does",
        predicate=_amount_date_candidate,
    ),
)


def propose(
    rule: Rule, ledger: Iterable[LedgerRecord], bank: Iterable[BankRecord]
) -> list[Candidate]:
    """Every pairing this rule proposes over the records still unconsumed.

    Deliberately quadratic and deliberately dumb. At fixture and demo scale
    this is microseconds, and an index would introduce an ordering dependency
    in the one place the system cannot afford one. If it ever needs to be
    fast, the fix is a pre-bucket by amount and UTR -- not a smarter rule.
    """
    ledger_records = list(ledger)
    bank_records = list(bank)

    unique_ledger_amounts: set[int] = set()
    unique_bank_amounts: set[int] = set()
    if rule.needs_unique_amount:
        unique_ledger_amounts = _amounts_appearing_once(r.amount_paise for r in ledger_records)
        unique_bank_amounts = _amounts_appearing_once(r.amount_paise for r in bank_records)

    candidates: list[Candidate] = []
    for ledger_record in ledger_records:
        for bank_record in bank_records:
            lag = lag_days(ledger_record, bank_record)
            if not rule.predicate(ledger_record, bank_record, lag):
                continue
            if rule.needs_unique_amount and not (
                ledger_record.amount_paise in unique_ledger_amounts
                and bank_record.amount_paise in unique_bank_amounts
            ):
                continue
            candidates.append(
                Candidate(
                    ledger=ledger_record,
                    bank=bank_record,
                    rule=rule.name,
                    confidence_ratio=rule.confidence_ratio,
                    reason=rule.reason,
                    amount_delta_paise=amount_delta(ledger_record, bank_record),
                    lag_days=lag,
                )
            )
    return candidates


def _amounts_appearing_once(amounts: Iterable[int]) -> set[int]:
    seen: dict[int, int] = {}
    for amount in amounts:
        seen[amount] = seen.get(amount, 0) + 1
    return {amount for amount, count in seen.items() if count == 1}
