"""Generate the seeded dataset and its golden expectations.

This is not filler data. It is the specification's test fixture: every headline
number in the product, the demo and the docs is asserted against it
(docs/08-seed-data.md). If it is wrong, every downstream test is wrong *and
green*, which is the worst available outcome -- hence the checksums.

Design notes worth knowing before changing anything here:

* **Totals are exact by construction, not by chance.** Amounts are allocated
  out of a fixed total with the largest-remainder method, so the sum is the
  target to the paise regardless of how the random weights land.
* **Every amount is a whole number of rupees.** That is what makes the 1.00%
  fee exact: for an amount that is a multiple of 100 paise, one percent is an
  integer, so the sum of per-record fees equals one percent of the total with
  no rounding drift.
* **No floats anywhere**, including in the random weights, which are integers.
* **Ids are drawn from a shuffled pool.** Payment ids are not chronological in
  any real system, and a non-chronological id order is also what stops the
  matcher's lexicographic tie-break from accidentally agreeing with time order.
  This is why ``TXN_183`` can sit in the August window.

Run: ``python scripts/task.py seed`` (inside the container, like everything).
"""

import csv
import hashlib
import json
import random
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api" / "src"))

from runtime.calendar import (
    IST,
    add_business_days,
    bank_period,
    ist_date,
    settlement_due_date,
)
from runtime.money import Paise, apply_rate, apply_ratio, ratio

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"

# --------------------------------------------------------------------------
# fixed parameters
# --------------------------------------------------------------------------

SEED = 42
MERCHANT_ID = "M123"
MERCHANT_NAME = "Kabir Retail Pvt Ltd"
CURRENCY = "INR"

SPAN_FROM = date(2026, 5, 26)
SPAN_TO = date(2026, 8, 24)  # half-open; 90 days

PRIOR_FROM, PRIOR_TO = date(2026, 7, 1), date(2026, 7, 24)
CURRENT_FROM, CURRENT_TO = date(2026, 8, 1), date(2026, 8, 24)

FEE_RATE = Decimal("0.0100")
RUPEE = 100  # paise
MIN_PAYMENT_RUPEES = 50

#: Days left empty immediately before each analysis window. See _generate_filler.
QUIET_BAND_DAYS = 2

#: Non-UPI attempted value splits across these methods in these proportions.
NON_UPI_WEIGHTS = {"CARD": 55, "NETBANKING": 30, "WALLET": 15}


@dataclass(frozen=True)
class WindowPlan:
    """The exact totals a window must reproduce, in paise."""

    name: str
    period_from: date
    period_to: date
    attempted_paise: Paise
    gross_paise: Paise
    refunds_paise: Paise
    chargebacks_paise: Paise
    upi_attempted_paise: Paise
    upi_gross_paise: Paise
    successful_count: int
    failed_count: int
    refund_count: int
    chargeback_count: int

    @property
    def non_upi_attempted_paise(self) -> Paise:
        return self.attempted_paise - self.upi_attempted_paise

    @property
    def non_upi_gross_paise(self) -> Paise:
        return self.gross_paise - self.upi_gross_paise

    @property
    def fees_paise(self) -> Paise:
        return apply_rate(self.gross_paise, FEE_RATE)

    @property
    def net_paise(self) -> Paise:
        return self.gross_paise - self.refunds_paise - self.fees_paise - self.chargebacks_paise


# UPI share of attempted value is 46.66% in both windows, so the blended rate
# falls out of the method mix rather than being an unrelated number (C-03).
# Every figure here is a whole number of rupees: that is what makes the 1.00%
# fee exact, and it is why these are the rounded neighbours of the ideal
# products rather than the products themselves. They still round to 46.66%,
# 96.80%, 82.90% and 96.82% -- asserted in tests/test_golden_story.py.
PRIOR = WindowPlan(
    name="prior",
    period_from=PRIOR_FROM,
    period_to=PRIOR_TO,
    attempted_paise=533_000_000,
    gross_paise=516_000_000,
    refunds_paise=10_000_000,
    chargebacks_paise=1_100_000,
    upi_attempted_paise=248_697_800,  # 46.66% of attempted
    upi_gross_paise=240_739_500,  # 96.80% of the above
    successful_count=411,
    failed_count=13,
    refund_count=8,
    chargeback_count=2,
)

CURRENT = WindowPlan(
    name="current",
    period_from=CURRENT_FROM,
    period_to=CURRENT_TO,
    attempted_paise=474_200_000,
    gross_paise=428_320_000,
    refunds_paise=12_400_000,
    chargebacks_paise=1_850_000,
    upi_attempted_paise=221_261_700,  # 46.66% of attempted
    upi_gross_paise=183_426_200,  # 82.90% of the above
    successful_count=341,
    failed_count=37,
    refund_count=10,
    chargeback_count=3,
)

# --------------------------------------------------------------------------
# planted reconciliation exceptions (docs/08-seed-data.md)
# --------------------------------------------------------------------------

#: Ledger rows written with no bank counterpart. Their ids and amounts are
#: fixed because the demo script names them.
NO_COUNTERPART = (
    ("TXN_183", 840_000, "UPI"),
    ("TXN_247", 620_000, "CARD"),
    ("TXN_402", 380_000, "NETBANKING"),
)
UNRESOLVED_PAISE = sum(amount for _, amount, _ in NO_COUNTERPART)

#: A second ledger row duplicating an existing UTR and amount. One of the two
#: must lose the settlement to the one-to-one rule and become an exception.
DUPLICATE_ID = "TXN_511"

TIMING_LAG_COUNT = 7
AMOUNT_MISMATCH_DELTAS = (100, 25_000)  # Rs 1 and Rs 250, on the bank side
FEE_DISCREPANCY_RATES = (Decimal("0.0135"), Decimal("0.0062"))

#: Bank rows with no ledger counterpart. SETTLEMENT_91 is the near miss for
#: TXN_183: same amount, no reference, and far enough outside the window that
#: it can only reach rule 5 (0.72) -- below the 0.85 auto-match threshold.
NEAR_MISS_ID = "SETTLEMENT_91"
NEAR_MISS_LAG_BUSINESS_DAYS = 4
UNMATCHED_BANK_EXTRA = (("SETTLEMENT_318", 731_100), ("SETTLEMENT_1204", 456_300))


# --------------------------------------------------------------------------
# records
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Transaction:
    id: str
    merchant_id: str
    external_ref: str
    utr: str | None
    method: str
    status: str
    amount_paise: Paise
    fee_paise: Paise
    currency: str
    attempted_at: datetime
    captured_at: datetime | None
    settlement_due_date: date | None


@dataclass(frozen=True)
class Settlement:
    id: str
    merchant_id: str
    bank_ref: str | None
    utr: str | None
    amount_paise: Paise
    fee_paise: Paise
    currency: str
    value_date: date


@dataclass(frozen=True)
class Movement:
    """A refund or a chargeback. Same shape, different table."""

    id: str
    merchant_id: str
    transaction_id: str
    amount_paise: Paise
    reason: str
    created_at: datetime


@dataclass
class Dataset:
    transactions: list[Transaction] = field(default_factory=list)
    settlements: list[Settlement] = field(default_factory=list)
    refunds: list[Movement] = field(default_factory=list)
    chargebacks: list[Movement] = field(default_factory=list)
    expectations: dict[str, object] = field(default_factory=dict)


# --------------------------------------------------------------------------
# exact allocation
# --------------------------------------------------------------------------


def allocate(total: int, weights: Sequence[int], floor: int = 0) -> list[int]:
    """Split ``total`` into ``len(weights)`` integers summing to exactly ``total``.

    Largest-remainder apportionment: each part gets its proportional share
    rounded down, then the shortfall is handed out one unit at a time to the
    largest remainders, ties broken by index. Every step is integer arithmetic,
    so the result is exact and identical on every machine.

    ``floor`` reserves a minimum for each part before apportioning the rest.
    """
    count = len(weights)
    if count == 0:
        raise ValueError("cannot allocate across zero parts")
    if any(weight <= 0 for weight in weights):
        raise ValueError("weights must be positive")
    remaining = total - floor * count
    if remaining < 0:
        raise ValueError(f"total {total} cannot cover a floor of {floor} across {count} parts")

    weight_sum = sum(weights)
    scaled = [remaining * weight for weight in weights]
    parts = [value // weight_sum for value in scaled]
    shortfall = remaining - sum(parts)
    order = sorted(range(count), key=lambda i: (-(scaled[i] % weight_sum), i))
    for index in order[:shortfall]:
        parts[index] += 1
    return [floor + part for part in parts]


def rupee_amounts(rng: random.Random, total_paise: Paise, count: int) -> list[Paise]:
    """``count`` whole-rupee amounts summing to exactly ``total_paise``.

    Weights are squared integers so the distribution is skewed the way payment
    values actually are -- many small, a few large -- without a float in sight.
    """
    if total_paise % RUPEE != 0:
        raise ValueError(f"{total_paise} paise is not a whole number of rupees")
    weights = [rng.randint(1, 70) ** 2 for _ in range(count)]
    rupees = allocate(total_paise // RUPEE, weights, floor=MIN_PAYMENT_RUPEES)
    return [amount * RUPEE for amount in rupees]


# --------------------------------------------------------------------------
# generation
# --------------------------------------------------------------------------


class IdPool:
    """Hands out shuffled ids, with specific ones reservable up front."""

    def __init__(self, prefix: str, size: int, rng: random.Random, reserved: Sequence[str]) -> None:
        reserved_set = set(reserved)
        pool = [f"{prefix}_{n}" for n in range(1, size + 1) if f"{prefix}_{n}" not in reserved_set]
        missing = [name for name in reserved_set if not name.startswith(f"{prefix}_")]
        if missing:
            raise ValueError(f"reserved ids do not belong to {prefix}: {sorted(missing)}")
        rng.shuffle(pool)
        self._pool = pool
        self._taken = 0

    def take(self) -> str:
        if self._taken >= len(self._pool):
            raise RuntimeError("id pool exhausted")
        value = self._pool[self._taken]
        self._taken += 1
        return value


def _capture_instant(rng: random.Random, day: date) -> datetime:
    """A capture time on ``day``, in IST.

    Weighted toward business hours, and deliberately allowed to fall after the
    18:00 cutoff so that the cutoff rule is exercised by real fixture rows
    rather than only by unit tests.
    """
    hour = rng.choice([9, 10, 11, 11, 12, 13, 14, 15, 16, 16, 17, 18, 19, 21])
    minute = rng.randrange(0, 60)
    second = rng.randrange(0, 60)
    return datetime.combine(day, time(hour, minute, second), tzinfo=IST)


def _days(period_from: date, period_to: date) -> list[date]:
    span = (period_to - period_from).days
    return [period_from + timedelta(days=offset) for offset in range(span)]


def _method_totals(plan: WindowPlan) -> dict[str, tuple[Paise, Paise]]:
    """Attempted and gross value per method, exact to the paise.

    UPI carries the whole degradation story; the other three sit flat at the
    same success rate, which is what makes the blended rate a consequence of
    the mix instead of an independent number.
    """
    methods = list(NON_UPI_WEIGHTS)
    weights = [NON_UPI_WEIGHTS[method] for method in methods]
    attempted = allocate(plan.non_upi_attempted_paise // RUPEE, weights)
    gross = allocate(plan.non_upi_gross_paise // RUPEE, weights)
    totals = {"UPI": (plan.upi_attempted_paise, plan.upi_gross_paise)}
    for index, method in enumerate(methods):
        totals[method] = (attempted[index] * RUPEE, gross[index] * RUPEE)
    return totals


def _generate_window(
    rng: random.Random,
    plan: WindowPlan,
    txn_ids: IdPool,
    *,
    planted: Sequence[tuple[str, Paise, str]] = (),
) -> list[Transaction]:
    """Every attempt in one window, hitting the plan's totals exactly."""
    method_totals = _method_totals(plan)
    days = _days(plan.period_from, plan.period_to)

    # Successful and failed counts per method, proportional to value.
    gross_weights = [method_totals[method][1] for method in method_totals]
    failed_values = [
        method_totals[method][0] - method_totals[method][1] for method in method_totals
    ]
    success_counts = allocate(plan.successful_count, gross_weights, floor=1)
    fail_counts = allocate(plan.failed_count, [max(v, 1) for v in failed_values], floor=1)

    planted_by_method: dict[str, list[tuple[str, Paise]]] = {}
    for txn_id, amount, method in planted:
        planted_by_method.setdefault(method, []).append((txn_id, amount))

    records: list[Transaction] = []
    for index, method in enumerate(method_totals):
        attempted_total, gross_total = method_totals[method]
        reserved = planted_by_method.get(method, [])
        reserved_value = sum(amount for _, amount in reserved)

        free_success = success_counts[index] - len(reserved)
        amounts = [amount for _, amount in reserved]
        amounts += rupee_amounts(rng, gross_total - reserved_value, free_success)
        ids = [txn_id for txn_id, _ in reserved] + [txn_ids.take() for _ in range(free_success)]

        for txn_id, amount in zip(ids, amounts, strict=True):
            records.append(_successful(rng, txn_id, method, amount, rng.choice(days)))

        failed_total = attempted_total - gross_total
        for amount in rupee_amounts(rng, failed_total, fail_counts[index]):
            records.append(_failed(rng, txn_ids.take(), method, amount, rng.choice(days)))
    return records


def _successful(
    rng: random.Random, txn_id: str, method: str, amount_paise: Paise, day: date
) -> Transaction:
    captured_at = _capture_instant(rng, day)
    # ~8% of captures carry no UTR, which is precisely what forces the matcher
    # onto its weaker rules (docs/03-reconciliation.md).
    utr = None if rng.randrange(100) < 8 else f"UTR{rng.randrange(10**11, 10**12)}"
    return Transaction(
        id=txn_id,
        merchant_id=MERCHANT_ID,
        external_ref=f"ref_{txn_id.lower()}",
        utr=utr,
        method=method,
        status="CAPTURED",
        amount_paise=amount_paise,
        fee_paise=apply_rate(amount_paise, FEE_RATE),
        currency=CURRENCY,
        attempted_at=captured_at - timedelta(seconds=rng.randrange(5, 90)),
        captured_at=captured_at,
        settlement_due_date=settlement_due_date(captured_at),
    )


def _failed(
    rng: random.Random, txn_id: str, method: str, amount_paise: Paise, day: date
) -> Transaction:
    attempted_at = _capture_instant(rng, day)
    return Transaction(
        id=txn_id,
        merchant_id=MERCHANT_ID,
        external_ref=f"ref_{txn_id.lower()}",
        utr=None,
        method=method,
        status="FAILED",
        amount_paise=amount_paise,
        fee_paise=0,
        currency=CURRENCY,
        attempted_at=attempted_at,
        captured_at=None,
        settlement_due_date=None,
    )


def _generate_filler(rng: random.Random, txn_ids: IdPool) -> list[Transaction]:
    """Attempts outside the two analysis windows.

    No exact totals apply here -- nothing asserts against these -- but they
    exist so that the windows sit inside a plausible 90-day history rather
    than floating in isolation, and so that period filtering has something to
    filter out.
    """
    # The quiet band is not decoration. A capture in the two days before a
    # window -- particularly one after the 18:00 cutoff -- settles inside that
    # window's settlement cycle, and would appear on the bank side with no
    # ledger counterpart in scope: a fabricated exception, from a boundary
    # rather than from anything real. Leaving those days empty makes the
    # capture cohort and the settlement cohort exactly the same payments.
    # A production system resolves this by scoping the ledger side on
    # settlement_due_date instead; the fixture does not need that machinery.
    windows = (
        (PRIOR_FROM - timedelta(days=QUIET_BAND_DAYS), PRIOR_TO),
        (CURRENT_FROM - timedelta(days=QUIET_BAND_DAYS), CURRENT_TO),
    )
    days = [
        day
        for day in _days(SPAN_FROM, SPAN_TO)
        if not any(start <= day < end for start, end in windows)
    ]
    methods = ["UPI", "CARD", "NETBANKING", "WALLET"]
    records: list[Transaction] = []
    for day in days:
        for _ in range(rng.randint(18, 24)):
            method = rng.choices(methods, weights=[47, 29, 16, 8])[0]
            amount = rng.randint(MIN_PAYMENT_RUPEES, 60_000) * RUPEE
            if rng.randrange(100) < 92:
                records.append(_successful(rng, txn_ids.take(), method, amount, day))
            else:
                records.append(_failed(rng, txn_ids.take(), method, amount, day))
    return records


def _settle(stl_id: str, txn: Transaction, *, value_date: date | None = None) -> Settlement:
    """The bank's view of a capture, on time and in agreement unless planted otherwise."""
    if txn.settlement_due_date is None:
        raise ValueError(f"{txn.id} was never captured and cannot settle")
    return Settlement(
        id=stl_id,
        merchant_id=txn.merchant_id,
        bank_ref=txn.external_ref,
        utr=txn.utr,
        amount_paise=txn.amount_paise,
        fee_paise=txn.fee_paise,
        currency=CURRENCY,
        value_date=value_date or txn.settlement_due_date,
    )


def _attempted_in(txn: Transaction, plan: WindowPlan) -> bool:
    """An *attempt* belongs to a window by the IST date it was attempted.

    Scoping attempts by capture date would silently drop every failure, since
    a failure has no capture instant -- and the success rate would then be
    100% in every window, which is exactly the kind of quietly-wrong number
    this fixture exists to make impossible.
    """
    return plan.period_from <= ist_date(txn.attempted_at) < plan.period_to


def _captured_in(txn: Transaction, plan: WindowPlan) -> bool:
    """A *ledger record* belongs to a window by its IST capture date."""
    if txn.captured_at is None:
        return False
    return plan.period_from <= ist_date(txn.captured_at) < plan.period_to


def _movements(
    rng: random.Random,
    prefix: str,
    plan: WindowPlan,
    count: int,
    total_paise: Paise,
    sources: Sequence[Transaction],
    reasons: Sequence[str],
    offset: int = 0,
) -> list[Movement]:
    """Refunds or chargebacks against transactions in a window, summing exactly."""
    # Drawn from the largest captures in the window, and apportioned by their
    # value, so no movement can exceed the payment it refers to.
    chosen = sorted(sources, key=lambda t: (-t.amount_paise, t.id))[offset : offset + count]
    weights = [txn.amount_paise for txn in chosen]
    rupees = allocate(total_paise // RUPEE, weights, floor=MIN_PAYMENT_RUPEES)
    movements: list[Movement] = []
    for index, (txn, amount) in enumerate(zip(chosen, rupees, strict=True), start=1):
        if txn.captured_at is None:  # pragma: no cover - sources are captures
            raise ValueError(f"{txn.id} has no capture instant")
        movements.append(
            Movement(
                id=f"{prefix}_{plan.name}_{index}",
                merchant_id=MERCHANT_ID,
                transaction_id=txn.id,
                amount_paise=amount * RUPEE,
                reason=rng.choice(list(reasons)),
                created_at=txn.captured_at + timedelta(days=rng.randint(1, 5)),
            )
        )
    return movements


def build() -> Dataset:
    """The whole fixture, deterministically."""
    rng = random.Random(SEED)

    reserved_txn = [txn_id for txn_id, _, _ in NO_COUNTERPART] + [DUPLICATE_ID]
    txn_ids = IdPool("TXN", 2400, rng, reserved_txn)
    stl_ids = IdPool(
        "SETTLEMENT",
        2400,
        rng,
        [NEAR_MISS_ID] + [stl_id for stl_id, _ in UNMATCHED_BANK_EXTRA],
    )

    transactions = _generate_window(rng, CURRENT, txn_ids, planted=NO_COUNTERPART)
    transactions += _generate_window(rng, PRIOR, txn_ids)
    transactions += _generate_filler(rng, txn_ids)

    by_id = {txn.id: txn for txn in transactions}
    current_captures = [txn for txn in transactions if _captured_in(txn, CURRENT)]
    current_settleable = sorted(
        (txn for txn in current_captures if txn.status == "CAPTURED"),
        key=lambda t: t.id,
    )

    # ---------------------------------------------------------------- duplicate
    # A second ledger row carrying an existing UTR and amount. It is an extra
    # ledger record, so it lifts ledger_count to 342 -- but it is not revenue,
    # and the one-to-one rule (I5/I6) is what turns it into an exception rather
    # than a second match.
    original = next(
        txn
        for txn in current_settleable
        if txn.utr is not None and txn.id not in {i for i, _, _ in NO_COUNTERPART}
    )
    duplicate = Transaction(
        id=DUPLICATE_ID,
        merchant_id=MERCHANT_ID,
        external_ref=original.external_ref,
        utr=original.utr,
        method=original.method,
        status="CAPTURED",
        amount_paise=original.amount_paise,
        fee_paise=original.fee_paise,
        currency=CURRENCY,
        attempted_at=original.attempted_at + timedelta(seconds=31),
        captured_at=original.captured_at,
        settlement_due_date=original.settlement_due_date,
    )
    transactions.append(duplicate)
    by_id[duplicate.id] = duplicate

    # --------------------------------------------------------------- settlements
    no_counterpart_ids = {txn_id for txn_id, _, _ in NO_COUNTERPART}
    settlements: list[Settlement] = []
    settled_pairs: list[tuple[Transaction, Settlement]] = []
    for txn in sorted(transactions, key=lambda t: t.id):
        if txn.status != "CAPTURED" or txn.id in no_counterpart_ids or txn.id == DUPLICATE_ID:
            continue
        settlement = _settle(stl_ids.take(), txn)
        settlements.append(settlement)
        settled_pairs.append((txn, settlement))

    matched_current = [(txn, stl) for txn, stl in settled_pairs if _captured_in(txn, CURRENT)]
    matched_current.sort(key=lambda pair: pair[0].id)

    settlements = _plant_pair_exceptions(settlements, matched_current)
    settlements += _plant_unmatched_bank(by_id)

    # ------------------------------------------------------- refunds, chargebacks
    refunds: list[Movement] = []
    chargebacks: list[Movement] = []
    for plan in (CURRENT, PRIOR):
        sources = [
            txn
            for txn in transactions
            if txn.status == "CAPTURED" and txn.id != DUPLICATE_ID and _captured_in(txn, plan)
        ]
        refunds += _movements(
            rng,
            "RFND",
            plan,
            plan.refund_count,
            plan.refunds_paise,
            sources,
            ("CUSTOMER_REQUEST", "ITEM_UNAVAILABLE", "DUPLICATE_CHARGE"),
        )
        chargebacks += _movements(
            rng,
            "CBK",
            plan,
            plan.chargeback_count,
            plan.chargebacks_paise,
            sources,
            ("FRAUD", "SERVICE_NOT_RENDERED"),
            offset=plan.refund_count,
        )

    dataset = Dataset(
        transactions=sorted(transactions, key=lambda t: t.id),
        settlements=sorted(settlements, key=lambda s: s.id),
        refunds=sorted(refunds, key=lambda m: m.id),
        chargebacks=sorted(chargebacks, key=lambda m: m.id),
    )
    dataset.expectations = _expectations(dataset)
    return dataset


def _plant_pair_exceptions(
    settlements: list[Settlement], matched_current: list[tuple[Transaction, Settlement]]
) -> list[Settlement]:
    """Plant the eleven exceptions that sit on a *matched* pair.

    Each is injected at a fixed index into the id-sorted list of current-window
    pairs, so the counts never drift between runs.
    """
    replacements: dict[str, Settlement] = {}
    cursor = 0

    for offset in range(TIMING_LAG_COUNT):
        txn, stl = matched_current[cursor]
        cursor += 1
        lag = (offset % 3) + 1  # 1..3 business days past the SLA
        replacements[stl.id] = _settle(
            stl.id, txn, value_date=add_business_days(stl.value_date, lag)
        )

    for delta in AMOUNT_MISMATCH_DELTAS:
        txn, stl = matched_current[cursor]
        cursor += 1
        # The bank says a different number. The UTR still agrees, so the pair
        # is still formed -- by rule 3, since rules 1 and 2 both require the
        # amounts to be equal.
        replacements[stl.id] = Settlement(
            id=stl.id,
            merchant_id=stl.merchant_id,
            bank_ref=stl.bank_ref,
            utr=stl.utr,
            amount_paise=stl.amount_paise + delta,
            fee_paise=stl.fee_paise,
            currency=stl.currency,
            value_date=stl.value_date,
        )

    for rate in FEE_DISCREPANCY_RATES:
        txn, stl = matched_current[cursor]
        cursor += 1
        replacements[stl.id] = Settlement(
            id=stl.id,
            merchant_id=stl.merchant_id,
            bank_ref=stl.bank_ref,
            utr=stl.utr,
            amount_paise=stl.amount_paise,
            fee_paise=apply_rate(stl.amount_paise, rate),
            currency=stl.currency,
            value_date=stl.value_date,
        )

    return [replacements.get(stl.id, stl) for stl in settlements]


def _plant_unmatched_bank(by_id: dict[str, Transaction]) -> list[Settlement]:
    """Bank rows with no ledger counterpart, including the near miss.

    SETTLEMENT_91 carries TXN_183's amount and nothing else: no reference, and
    a value date four business days past that transaction's SLA. It can only
    reach rule 5, at confidence 0.72, which is below the 0.85 auto-match
    threshold -- so it is recorded as a *rejected candidate*, not a match. That
    single row is the difference between a 95.61% match rate that can be
    defended and a 99% one that cannot.
    """
    near_miss_source = by_id["TXN_183"]
    if near_miss_source.settlement_due_date is None:  # pragma: no cover - planted as a capture
        raise ValueError("TXN_183 must be a capture")
    rows = [
        Settlement(
            id=NEAR_MISS_ID,
            merchant_id=MERCHANT_ID,
            bank_ref=None,
            utr=None,
            amount_paise=near_miss_source.amount_paise,
            fee_paise=apply_rate(near_miss_source.amount_paise, FEE_RATE),
            currency=CURRENCY,
            value_date=add_business_days(
                near_miss_source.settlement_due_date, NEAR_MISS_LAG_BUSINESS_DAYS
            ),
        )
    ]
    for index, (stl_id, amount) in enumerate(UNMATCHED_BANK_EXTRA):
        rows.append(
            Settlement(
                id=stl_id,
                merchant_id=MERCHANT_ID,
                bank_ref=None,
                utr=None,
                amount_paise=amount,
                fee_paise=apply_rate(amount, FEE_RATE),
                currency=CURRENCY,
                value_date=date(2026, 8, 12) + timedelta(days=index * 3),
            )
        )
    return rows


# --------------------------------------------------------------------------
# golden expectations
# --------------------------------------------------------------------------


def _window_totals(dataset: Dataset, plan: WindowPlan) -> dict[str, object]:
    attempts = [
        txn for txn in dataset.transactions if txn.id != DUPLICATE_ID and _attempted_in(txn, plan)
    ]
    captures = [txn for txn in attempts if txn.status == "CAPTURED"]

    gross = sum(txn.amount_paise for txn in captures)
    attempted = sum(txn.amount_paise for txn in attempts)
    fees = sum(txn.fee_paise for txn in captures)
    refunds = sum(m.amount_paise for m in dataset.refunds if m.id.split("_")[1] == plan.name)
    chargebacks = sum(
        m.amount_paise for m in dataset.chargebacks if m.id.split("_")[1] == plan.name
    )

    per_method: dict[str, dict[str, object]] = {}
    for method in ("UPI", "CARD", "NETBANKING", "WALLET"):
        method_attempted = sum(t.amount_paise for t in attempts if t.method == method)
        method_gross = sum(t.amount_paise for t in captures if t.method == method)
        per_method[method] = {
            "attempted_paise": method_attempted,
            "gross_paise": method_gross,
            "success_rate_ratio": str(ratio(method_gross, method_attempted)),
            "attempted_share_ratio": str(ratio(method_attempted, attempted)),
        }

    return {
        "period_from": plan.period_from.isoformat(),
        "period_to": plan.period_to.isoformat(),
        "attempted_value_paise": attempted,
        "gross_payments_paise": gross,
        "refunds_paise": refunds,
        "fees_paise": fees,
        "chargebacks_paise": chargebacks,
        "net_revenue_paise": gross - refunds - fees - chargebacks,
        "success_rate_ratio": str(ratio(gross, attempted)),
        "attempt_count": len(attempts),
        "capture_count": len(captures),
        "by_method": per_method,
    }


def _attribution(prior: dict[str, object], current: dict[str, object]) -> dict[str, object]:
    """The revenue bridge, which must close to the paise with zero residual.

    ``volume_effect`` and ``rate_effect`` are defined so their sum is *exactly*
    the change in gross: the rate effect is the residual of the volume effect
    rather than a second independent rounding. That is the whole fix for C-02 --
    the original spec's causes summed to 51% of the decline it claimed.
    """
    attempted_prior = int(prior["attempted_value_paise"])  # type: ignore[call-overload]
    attempted_current = int(current["attempted_value_paise"])  # type: ignore[call-overload]
    gross_prior = int(prior["gross_payments_paise"])  # type: ignore[call-overload]
    gross_current = int(current["gross_payments_paise"])  # type: ignore[call-overload]

    volume_effect = apply_ratio(attempted_current - attempted_prior, gross_prior, attempted_prior)
    rate_effect = (gross_current - gross_prior) - volume_effect

    refund_effect = -(int(current["refunds_paise"]) - int(prior["refunds_paise"]))  # type: ignore[call-overload]
    chargeback_effect = -(
        int(current["chargebacks_paise"]) - int(prior["chargebacks_paise"])  # type: ignore[call-overload]
    )
    fee_effect = -(int(current["fees_paise"]) - int(prior["fees_paise"]))  # type: ignore[call-overload]

    net_change = int(current["net_revenue_paise"]) - int(prior["net_revenue_paise"])  # type: ignore[call-overload]
    terms = {
        "attempt_volume_paise": volume_effect,
        "success_rate_paise": rate_effect,
        "refunds_paise": refund_effect,
        "chargebacks_paise": chargeback_effect,
        "fees_paise": fee_effect,
    }
    residual = net_change - sum(terms.values())
    return {
        "net_change_paise": net_change,
        "net_change_ratio": str(
            ratio(net_change, int(prior["net_revenue_paise"]))  # type: ignore[call-overload]
        ),
        "terms": terms,
        "rounding_residual_paise": residual,
    }


def _reconciliation(dataset: Dataset) -> dict[str, object]:
    bank_from, bank_to = bank_period(CURRENT_FROM, CURRENT_TO)
    ledger = [
        txn
        for txn in dataset.transactions
        if txn.status == "CAPTURED" and _captured_in(txn, CURRENT)
    ]
    bank = [stl for stl in dataset.settlements if bank_from <= stl.value_date < bank_to]

    unmatched_ledger = len(NO_COUNTERPART) + 1  # + the duplicate
    unmatched_bank = 1 + len(UNMATCHED_BANK_EXTRA)
    matched_pairs = len(ledger) - unmatched_ledger
    matched_with_exception = (
        TIMING_LAG_COUNT + len(AMOUNT_MISMATCH_DELTAS) + len(FEE_DISCREPANCY_RATES)
    )
    matched_clean = matched_pairs - matched_with_exception

    return {
        "period_from": CURRENT_FROM.isoformat(),
        "period_to": CURRENT_TO.isoformat(),
        "bank_period_from": bank_from.isoformat(),
        "bank_period_to": bank_to.isoformat(),
        "ledger_count": len(ledger),
        "bank_count": len(bank),
        "matched_pairs": matched_pairs,
        "matched_clean": matched_clean,
        "matched_with_exception": matched_with_exception,
        "unmatched_ledger": unmatched_ledger,
        "unmatched_bank": unmatched_bank,
        "clean_match_rate_ratio": str(ratio(matched_clean, len(ledger))),
        "exception_count": len(ledger) - matched_clean,
        "exceptions_by_category": {
            "TIMING_LAG": TIMING_LAG_COUNT,
            "NO_COUNTERPART": len(NO_COUNTERPART),
            "AMOUNT_MISMATCH": len(AMOUNT_MISMATCH_DELTAS),
            "FEE_DISCREPANCY": len(FEE_DISCREPANCY_RATES),
            "POSSIBLE_DUPLICATE": 1,
        },
        "unresolved_paise": UNRESOLVED_PAISE,
        "unresolved_transaction_ids": [txn_id for txn_id, _, _ in NO_COUNTERPART],
        "duplicate_transaction_id": DUPLICATE_ID,
        "rejected_candidate_settlement_id": NEAR_MISS_ID,
    }


def _expectations(dataset: Dataset) -> dict[str, object]:
    prior = _window_totals(dataset, PRIOR)
    current = _window_totals(dataset, CURRENT)
    return {
        "seed": SEED,
        "merchant_id": MERCHANT_ID,
        "span_from": SPAN_FROM.isoformat(),
        "span_to": SPAN_TO.isoformat(),
        "transaction_count": len(dataset.transactions),
        "settlement_count": len(dataset.settlements),
        "prior": prior,
        "current": current,
        "attribution": _attribution(prior, current),
        "reconciliation": _reconciliation(dataset),
    }


# --------------------------------------------------------------------------
# tenancy fixtures -- fixed uuids so the RLS test can name them
# --------------------------------------------------------------------------

OTHER_MERCHANT_ID = "M999"

USERS = (
    ("11111111-1111-4111-8111-111111111111", "owner@kabirretail.example", MERCHANT_ID, "OWNER"),
    ("22222222-2222-4222-8222-222222222222", "analyst@kabirretail.example", MERCHANT_ID, "ANALYST"),
    ("33333333-3333-4333-8333-333333333333", "viewer@kabirretail.example", MERCHANT_ID, "VIEWER"),
    # Belongs to a different merchant entirely. Row-level security, not
    # application code, is what must stop this user seeing anything above.
    (
        "99999999-9999-4999-8999-999999999999",
        "outsider@othercorp.example",
        OTHER_MERCHANT_ID,
        "OWNER",
    ),
)

LEDGER_COLUMNS = (
    "id",
    "merchant_id",
    "external_ref",
    "utr",
    "method",
    "status",
    "amount_paise",
    "fee_paise",
    "currency",
    "attempted_at",
    "captured_at",
    "settlement_due_date",
)

BANK_COLUMNS = (
    "id",
    "merchant_id",
    "bank_ref",
    "utr",
    "amount_paise",
    "fee_paise",
    "currency",
    "value_date",
)


def _cell(value: object) -> str:
    """Render one field. Instants carry an explicit +05:30; None is empty."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(IST).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[object]) -> None:
    # newline="" plus lineterminator="\n" gives byte-identical output on
    # Windows and Linux, which the checksums depend on.
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            record = asdict(row)  # type: ignore[call-overload]
            writer.writerow([_cell(record[column]) for column in columns])


def _sql_literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, int):
        return str(value)
    return "'" + _cell(value).replace("'", "''") + "'"


def _insert(table: str, columns: Sequence[str], rows: Sequence[object]) -> list[str]:
    if not rows:
        return []
    lines = [f"INSERT INTO {table} ({', '.join(columns)}) VALUES"]
    values = []
    for row in rows:
        record = asdict(row) if not isinstance(row, dict) else row  # type: ignore[call-overload]
        rendered = ", ".join(_sql_literal(record[column]) for column in columns)
        values.append(f"  ({rendered})")
    lines.append(",\n".join(values) + ";")
    lines.append("")
    return lines


def _write_sql(path: Path, dataset: Dataset) -> None:
    lines = [
        "-- Generated by data/seed/generate_seed_data.py. Do not edit by hand.",
        f"-- seed={SEED}  merchant={MERCHANT_ID}  span=[{SPAN_FROM}, {SPAN_TO})",
        "",
        "BEGIN;",
        "",
        "TRUNCATE chargebacks, refunds, settlements, transactions,",
        "         merchant_members, merchants, users RESTART IDENTITY CASCADE;",
        "",
    ]
    lines += _insert(
        "merchants",
        ("id", "name", "currency"),
        [
            {"id": MERCHANT_ID, "name": MERCHANT_NAME, "currency": CURRENCY},
            {"id": OTHER_MERCHANT_ID, "name": "Other Corp Pvt Ltd", "currency": CURRENCY},
        ],
    )
    lines += _insert(
        "users",
        ("id", "email"),
        [{"id": user_id, "email": email} for user_id, email, _, _ in USERS],
    )
    lines += _insert(
        "merchant_members",
        ("user_id", "merchant_id", "role"),
        [
            {"user_id": user_id, "merchant_id": merchant, "role": role}
            for user_id, _, merchant, role in USERS
        ],
    )
    lines += _insert("transactions", LEDGER_COLUMNS, dataset.transactions)
    lines += _insert("settlements", BANK_COLUMNS, dataset.settlements)
    movement_columns = (
        "id",
        "merchant_id",
        "transaction_id",
        "amount_paise",
        "reason",
        "created_at",
    )
    lines += _insert("refunds", movement_columns, dataset.refunds)
    lines += _insert("chargebacks", movement_columns, dataset.chargebacks)
    lines += ["COMMIT;", ""]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


ARTIFACTS = ("ledger_side.csv", "bank_settlement.csv", "seed.sql", "golden/expectations.json")


def write(dataset: Dataset) -> dict[str, str]:
    """Write every artifact and return the checksum manifest."""
    GOLDEN.mkdir(parents=True, exist_ok=True)
    _write_csv(HERE / "ledger_side.csv", LEDGER_COLUMNS, dataset.transactions)
    _write_csv(HERE / "bank_settlement.csv", BANK_COLUMNS, dataset.settlements)
    _write_sql(HERE / "seed.sql", dataset)
    (GOLDEN / "expectations.json").write_text(
        json.dumps(dataset.expectations, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest = {name: _sha256(HERE / name) for name in ARTIFACTS}
    (GOLDEN / "checksums.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main() -> int:
    dataset = build()
    manifest = write(dataset)
    recon = dataset.expectations["reconciliation"]
    current = dataset.expectations["current"]
    assert isinstance(recon, dict)
    assert isinstance(current, dict)
    print(f"transactions {len(dataset.transactions):>6}")
    print(f"settlements  {len(dataset.settlements):>6}")
    print(f"refunds      {len(dataset.refunds):>6}")
    print(f"chargebacks  {len(dataset.chargebacks):>6}")
    print()
    print(f"net revenue (current)  {current['net_revenue_paise']} paise")
    print(f"clean match rate       {recon['clean_match_rate_ratio']}")
    print()
    for name, digest in manifest.items():
        print(f"{digest}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
