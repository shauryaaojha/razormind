"""Generate the seeded dataset, its ground truth, and its provenance.

The pipeline, and the reason it has this shape:

```text
public NPCI / RBI statistics        data/calibration/sources.md
        |
        v
calibration parameters              every one tagged CITED / DERIVED / ASSUMED
        |
        v
scenario definition                 data/scenarios/*.json
        |
        v
synthetic generator                 this file
        |
        v
ledger + settlements + ground truth
```

Two lines are worth stating plainly, because the credibility of the dataset
rests on them:

* **Transaction-level records are synthetic and seeded.** No real customer,
  merchant, or bank record is represented, and none is claimed to be.
* **Capture counts are scenario design parameters. Everything else emerges.**
  Failures, values, fees, success rates, and the revenue decline itself are
  derived from the calibration layer -- we chose the shape of the story, not
  the answer.

Design constraints that have not changed:

* Totals are exact by construction, via largest-remainder apportionment.
* Every amount is a whole number of rupees.
* No floats anywhere, including the random weights, which are integers.
* Ids come from a seeded shuffle, so id order carries no chronological meaning.

Run: ``python scripts/task.py seed``
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from data.calibration.parameters import (  # noqa: E402
    BASELINE_DECLINES,
    BUSINESS_DECLINE_REASONS,
    MERCHANT_MIX,
    TECHNICAL_DECLINE_REASONS,
    DeclineProfile,
    MethodProfile,
    provenance_summary,
)
from runtime.calendar import (  # noqa: E402
    IST,
    add_business_days,
    bank_period,
    ist_date,
    settlement_due_date,
)
from runtime.fees import FEE_SCHEDULE, Instrument  # noqa: E402
from runtime.money import Paise, ratio  # noqa: E402

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
SCENARIO_PATH = ROOT / "data" / "scenarios" / "revenue_decline_v1.json"

RUPEE = 100
MIN_PAYMENT_RUPEES = 20


def _d(value: object) -> Decimal:
    """Parse a scenario rate. Always via str, never via float."""
    return Decimal(str(value))


def _seq(value: object) -> list[object]:
    """Narrow one JSON value to a list.

    The scenario is untyped JSON. This is the single place it becomes typed --
    scattering casts across every read would mean the boundary is nowhere in
    particular, and a malformed scenario would surface as an AttributeError
    somewhere deep in generation rather than here.
    """
    if not isinstance(value, list):
        raise TypeError(f"expected a list in the scenario, got {type(value).__name__}")
    return value


def _obj(value: object) -> dict[str, object]:
    """Narrow one JSON value to an object. See :func:`_seq`."""
    if not isinstance(value, dict):
        raise TypeError(f"expected an object in the scenario, got {type(value).__name__}")
    return value


# --------------------------------------------------------------------------
# scenario
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Scenario:
    """The hidden definition of the world. Everything is derived from this."""

    raw: dict[str, object]

    def _section(self, name: str) -> dict[str, object]:
        return _obj(self.raw[name])

    @property
    def span(self) -> tuple[date, date]:
        span = self._section("span")
        return date.fromisoformat(str(span["from"])), date.fromisoformat(str(span["to"]))

    def window(self, name: str) -> tuple[date, date]:
        entry = _obj(self._section("windows")[name])
        return date.fromisoformat(str(entry["from"])), date.fromisoformat(str(entry["to"]))

    @property
    def capture_counts(self) -> dict[str, int]:
        return {
            key: int(str(value))
            for key, value in self._section("capture_counts").items()
            if not key.startswith("_")
        }

    @property
    def issuers(self) -> tuple[tuple[str, Decimal], ...]:
        return tuple(
            (str(_obj(item)["id"]), _d(_obj(item)["share"])) for item in _seq(self.raw["issuers"])
        )

    def anomaly(self, name: str) -> dict[str, object]:
        return _obj(self._section("anomalies")[name])


def load_scenario(path: Path = SCENARIO_PATH) -> Scenario:
    return Scenario(json.loads(path.read_text(encoding="utf-8")))


SCENARIO = load_scenario()
RAW = SCENARIO.raw

MERCHANT_ID = str(RAW["merchant_id"])
MERCHANT_NAME = str(RAW["merchant_name"])
CURRENCY = str(RAW["currency"])
SEED = int(str(RAW["seed"]))
SCENARIO_ID = str(RAW["id"])

SPAN_FROM, SPAN_TO = SCENARIO.span
CURRENT_FROM, CURRENT_TO = SCENARIO.window("current")
PRIOR_FROM, PRIOR_TO = SCENARIO.window("prior")
QUIET_BAND_DAYS = int(str(RAW["quiet_band_days"]))

_POLICY = SCENARIO._section("settlement_policy")
SETTLEMENT_LAG = int(str(_POLICY["expected_delay_business_days"]))
CUTOFF = time(int(str(_POLICY["cutoff_hour_ist"])), 0)

ISSUERS = SCENARIO.issuers

_NC = SCENARIO.anomaly("no_counterpart")
NO_COUNTERPART = tuple(
    zip(
        [str(i) for i in _seq(_NC["transaction_ids"])],
        [int(str(a)) for a in _seq(_NC["amounts_paise"])],
        strict=True,
    )
)
UNRESOLVED_PAISE = sum(amount for _, amount in NO_COUNTERPART)

DUPLICATE_ID = str(SCENARIO.anomaly("possible_duplicate")["transaction_id"])
TIMING_LAG_COUNT = int(str(SCENARIO.anomaly("timing_lag")["count"]))
TIMING_LAG_DAYS = tuple(
    int(str(d)) for d in _seq(SCENARIO.anomaly("timing_lag")["lag_business_days"])
)
AMOUNT_MISMATCH_DELTAS = tuple(
    int(str(d)) for d in _seq(SCENARIO.anomaly("amount_mismatch")["deltas_paise"])
)
FEE_MISAPPLIED_RULES = tuple(
    Instrument(str(r)) for r in _seq(SCENARIO.anomaly("fee_discrepancy")["misapplied_rules"])
)

_UB = SCENARIO.anomaly("unmatched_bank")
_NEAR_MISS = _obj(_UB["near_miss"])
NEAR_MISS_ID = str(_NEAR_MISS["settlement_id"])
NEAR_MISS_SHADOWS = str(_NEAR_MISS["shadows_transaction_id"])
NEAR_MISS_LAG_BUSINESS_DAYS = int(str(_NEAR_MISS["lag_business_days"]))
UNMATCHED_BANK_EXTRA = tuple(
    (str(_obj(item)["settlement_id"]), int(str(_obj(item)["amount_paise"])))
    for item in _seq(_UB["extra"])
)

MIX_BY_METHOD: dict[str, MethodProfile] = {p.method: p for p in MERCHANT_MIX}
DECLINE_BY_METHOD: dict[str, DeclineProfile] = {p.method: p for p in BASELINE_DECLINES}
METHODS = tuple(p.method for p in MERCHANT_MIX)


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
    instrument: str
    issuer: str
    status: str
    decline_type: str | None
    decline_reason: str | None
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
    ground_truth: dict[str, object] = field(default_factory=dict)


# --------------------------------------------------------------------------
# exact allocation
# --------------------------------------------------------------------------


def allocate(total: int, weights: Sequence[int], floor: int = 0) -> list[int]:
    """Split ``total`` into ``len(weights)`` integers summing to exactly ``total``.

    Largest-remainder apportionment: each part gets its proportional share
    rounded down, then the shortfall is handed out one unit at a time to the
    largest remainders, ties broken by index. Every step is integer arithmetic,
    so the result is exact and identical on every machine.
    """
    count = len(weights)
    if count == 0:
        raise ValueError("cannot allocate across zero parts")
    if any(weight < 0 for weight in weights):
        raise ValueError("weights must be non-negative")
    weight_sum = sum(weights)
    if weight_sum == 0:
        raise ValueError("weights must not all be zero")
    remaining = total - floor * count
    if remaining < 0:
        raise ValueError(f"total {total} cannot cover a floor of {floor} across {count} parts")

    scaled = [remaining * weight for weight in weights]
    parts = [value // weight_sum for value in scaled]
    shortfall = remaining - sum(parts)
    order = sorted(range(count), key=lambda i: (-(scaled[i] % weight_sum), i))
    for index in order[:shortfall]:
        parts[index] += 1
    return [floor + part for part in parts]


def _as_weights(values: Sequence[Decimal]) -> list[int]:
    """Decimal weights as integers, so allocation stays integer arithmetic."""
    return [max(0, int(value * 1_000_000)) for value in values]


# --------------------------------------------------------------------------
# ticket sizes
# --------------------------------------------------------------------------


def _skew_floor(spread: Decimal) -> int:
    return max(1, 1000 - int(spread * 1000))


def _skew_normaliser(low: int) -> int:
    """The exact mean of the skew draw, so the realised mean ticket is the declared one.

    Computed, not fitted. The draw is a squared uniform; its mean over the
    range is something we can simply evaluate once.
    """
    values = [(draw * draw) // 1000 for draw in range(low, 1001)]
    return max(1, sum(values) // len(values))


_SKEW: dict[str, tuple[int, int]] = {
    profile.method: (
        _skew_floor(profile.ticket_spread),
        _skew_normaliser(_skew_floor(profile.ticket_spread)),
    )
    for profile in MERCHANT_MIX
}


def _ticket_paise(rng: random.Random, method: str) -> Paise:
    """A whole-rupee ticket, right-skewed, with the declared mean.

    Payment values are not normally distributed -- many small, a few large --
    and a uniform draw would put the median at the mean, which is exactly wrong
    for a world where 86% of P2M volume sits under Rs 500.
    """
    profile = MIX_BY_METHOD[method]
    low, normaliser = _SKEW[method]
    draw = rng.randint(low, 1000)
    skewed = (draw * draw) // 1000
    mean_rupees = profile.mean_ticket_paise // RUPEE
    rupees = (mean_rupees * skewed) // normaliser
    return max(MIN_PAYMENT_RUPEES, rupees) * RUPEE


# --------------------------------------------------------------------------
# the incident
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Incident:
    start: date
    end: date
    method: str
    issuers: frozenset[str]
    technical_multiplier: Decimal
    business_multiplier: Decimal

    def affects(self, day: date, method: str, issuer: str) -> bool:
        return self.start <= day < self.end and method == self.method and issuer in self.issuers


def _incident() -> Incident:
    spec = SCENARIO._section("incident")
    return Incident(
        start=date.fromisoformat(str(spec["start"])),
        end=date.fromisoformat(str(spec["end"])),
        method=str(spec["affected_method"]),
        issuers=frozenset(str(i) for i in _seq(spec["affected_issuers"])),
        technical_multiplier=_d(spec["technical_decline_multiplier"]),
        business_multiplier=_d(spec["business_decline_multiplier"]),
    )


INCIDENT = _incident()


def decline_rates(day: date, method: str, issuer: str) -> tuple[Decimal, Decimal]:
    """(technical, business) decline rates in force for one cell.

    The incident multiplies the *technical* rate and leaves business declines
    essentially alone. That asymmetry is the finding: a customer typing the
    wrong PIN does not become likelier because a bank's back end is struggling,
    and an investigation that cannot separate the two can only report that a
    success rate moved.
    """
    profile = DECLINE_BY_METHOD[method]
    technical = profile.technical_decline_rate
    business = profile.business_decline_rate
    if INCIDENT.affects(day, method, issuer):
        technical *= INCIDENT.technical_multiplier
        business *= INCIDENT.business_multiplier
    return technical, business


# --------------------------------------------------------------------------
# ids
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


# --------------------------------------------------------------------------
# generation
# --------------------------------------------------------------------------


def _days(period_from: date, period_to: date) -> list[date]:
    return [period_from + timedelta(days=n) for n in range((period_to - period_from).days)]


def _capture_instant(rng: random.Random, day: date) -> datetime:
    """A capture time on ``day``, in IST.

    Deliberately allowed to fall after the cutoff, so the cutoff rule is
    exercised by real fixture rows and not only by unit tests.
    """
    hour = rng.choice([9, 10, 11, 11, 12, 13, 14, 15, 16, 16, 17, 18, 19, 21])
    return datetime.combine(day, time(hour, rng.randrange(60), rng.randrange(60)), tzinfo=IST)


def _pick_instrument(rng: random.Random, method: str) -> Instrument:
    profile = MIX_BY_METHOD[method]
    instruments = list(profile.instrument_mix)
    weights = _as_weights([profile.instrument_mix[i] for i in instruments])
    return instruments[_weighted_index(rng, weights)]


def _weighted_index(rng: random.Random, weights: Sequence[int]) -> int:
    """A weighted draw using only integer arithmetic."""
    total = sum(weights)
    point = rng.randrange(total)
    running = 0
    for index, weight in enumerate(weights):
        running += weight
        if point < running:
            return index
    return len(weights) - 1  # pragma: no cover - unreachable when total > 0


def _make_capture(
    rng: random.Random,
    txn_id: str,
    method: str,
    issuer: str,
    day: date,
    amount: Paise | None = None,
) -> Transaction:
    instrument = _pick_instrument(rng, method)
    amount_paise = amount if amount is not None else _ticket_paise(rng, method)
    captured_at = _capture_instant(rng, day)
    # ~8% of captures carry no UTR, which is what forces the matcher onto its
    # weaker rules (docs/03-reconciliation.md).
    utr = None if rng.randrange(100) < 8 else f"UTR{rng.randrange(10**11, 10**12)}"
    return Transaction(
        id=txn_id,
        merchant_id=MERCHANT_ID,
        external_ref=f"ref_{txn_id.lower()}",
        utr=utr,
        method=method,
        instrument=instrument.value,
        issuer=issuer,
        status="CAPTURED",
        decline_type=None,
        decline_reason=None,
        amount_paise=amount_paise,
        fee_paise=FEE_SCHEDULE[instrument].fee_paise(amount_paise),
        currency=CURRENCY,
        attempted_at=captured_at - timedelta(seconds=rng.randrange(5, 90)),
        captured_at=captured_at,
        settlement_due_date=settlement_due_date(captured_at, SETTLEMENT_LAG, CUTOFF),
    )


def _make_decline(
    rng: random.Random,
    txn_id: str,
    method: str,
    issuer: str,
    day: date,
    technical: bool,
    amount_paise: Paise | None = None,
) -> Transaction:
    instrument = _pick_instrument(rng, method)
    reasons = TECHNICAL_DECLINE_REASONS if technical else BUSINESS_DECLINE_REASONS
    return Transaction(
        id=txn_id,
        merchant_id=MERCHANT_ID,
        external_ref=f"ref_{txn_id.lower()}",
        utr=None,
        method=method,
        instrument=instrument.value,
        issuer=issuer,
        status="FAILED",
        decline_type="TECHNICAL_DECLINE" if technical else "BUSINESS_DECLINE",
        decline_reason=rng.choice(list(reasons)),
        amount_paise=amount_paise if amount_paise is not None else _ticket_paise(rng, method),
        # A declined payment is never charged for.
        fee_paise=0,
        currency=CURRENCY,
        attempted_at=_capture_instant(rng, day),
        captured_at=None,
        settlement_due_date=None,
    )


@dataclass(frozen=True)
class Cell:
    """One (day, method, issuer) bucket, with its captures and derived failures."""

    day: date
    method: str
    issuer: str
    captures: int
    technical_failures: int
    business_failures: int


def _plan_cells(days: Sequence[date], capture_total: int) -> list[Cell]:
    """Captures per cell, and the failures those captures imply.

    Allocation is **hierarchical, and has to be**: methods first, then days and
    issuers within a method. Apportioning across every (day, method, issuer)
    cell in one pass gives each cell a base of zero and lets the remainder pass
    decide everything -- which hands every unit to the highest-weighted cells
    and erases the small methods from the dataset altogether.

    Within a method, a cell's weight is ``issuer_share x success_rate``. That
    success-rate factor is what makes the incident visible *in the data* rather
    than annotated on top of it: when a bank's technical declines multiply,
    fewer of its attempts become captures.

    Failures are then derived, not designed. For ``c`` captures at decline rate
    ``d``, the attempts that must have been made is ``c / (1 - d)``, so the
    failures are ``c * d / (1 - d)``. Those expectations are fractional and are
    apportioned back to whole records across the window, never rounded cell by
    cell -- rounding hundreds of numbers each below 0.05 gives all zeroes and a
    fixture with a 100% success rate.
    """
    method_weights: list[Decimal] = []
    for method in METHODS:
        survival = Decimal(0)
        for issuer, issuer_share in ISSUERS:
            for day in days:
                technical, business = decline_rates(day, method, issuer)
                survival += issuer_share * (Decimal(1) - technical - business)
        method_weights.append(MIX_BY_METHOD[method].volume_share * survival / len(days))
    method_captures = allocate(capture_total, _as_weights(method_weights))

    cells: list[Cell] = []
    for method, total in zip(METHODS, method_captures, strict=True):
        keys: list[tuple[date, str]] = []
        weights: list[Decimal] = []
        for day in days:
            for issuer, issuer_share in ISSUERS:
                technical, business = decline_rates(day, method, issuer)
                keys.append((day, issuer))
                weights.append(issuer_share * (Decimal(1) - technical - business))
        counts = allocate(total, _as_weights(weights))

        technical_expected: list[Decimal] = []
        business_expected: list[Decimal] = []
        for (day, issuer), count in zip(keys, counts, strict=True):
            technical, business = decline_rates(day, method, issuer)
            survival = Decimal(1) - technical - business
            technical_expected.append(Decimal(count) * technical / survival)
            business_expected.append(Decimal(count) * business / survival)

        technical_counts = _apportion_failures(technical_expected)
        business_counts = _apportion_failures(business_expected)

        cells.extend(
            Cell(day, method, issuer, count, td, bd)
            for (day, issuer), count, td, bd in zip(
                keys, counts, technical_counts, business_counts, strict=True
            )
        )

    cells.sort(key=lambda cell: (cell.day, cell.method, cell.issuer))
    return cells


def _apportion_failures(expected: Sequence[Decimal]) -> list[int]:
    """Whole failure records from fractional expectations, total preserved."""
    total = int(sum(expected, Decimal(0)).to_integral_value())
    if total <= 0:
        return [0] * len(expected)
    return allocate(total, _as_weights(expected))


def _skewed_weights(rng: random.Random, method: str, count: int) -> list[int]:
    """Right-skewed apportionment weights for one method's amounts."""
    low, _ = _SKEW[method]
    weights = []
    for _ in range(count):
        draw = rng.randint(low, 1000)
        weights.append(max(1, (draw * draw) // 1000))
    return weights


def _amounts_for(
    rng: random.Random, method: str, count: int, reserved: Sequence[Paise] = ()
) -> list[Paise]:
    """Amounts for the ``count - len(reserved)`` records that are not named.

    The method's total is ``count x mean_ticket`` exactly, with the named
    records' values subtracted, so the realised mean ticket is the calibrated
    one rather than whatever a few hundred draws happened to give. The shape is
    right-skewed: payment values are many-small-few-large, and a uniform draw
    would put the median at the mean -- wrong for a world where 86% of P2M
    volume sits under Rs 500.

    Only the free amounts come back. A named record carries its own value and
    must not consume one of these, or it would appear twice.
    """
    free = count - len(reserved)
    if free <= 0:
        return []
    mean_rupees = MIX_BY_METHOD[method].mean_ticket_paise // RUPEE
    remaining = mean_rupees * count - sum(amount // RUPEE for amount in reserved)
    remaining = max(remaining, MIN_PAYMENT_RUPEES * free)
    rupees = allocate(remaining, _skewed_weights(rng, method, free), floor=MIN_PAYMENT_RUPEES)
    return [value * RUPEE for value in rupees]


def _generate_window(
    rng: random.Random,
    period_from: date,
    period_to: date,
    capture_total: int,
    txn_ids: IdPool,
    planted: Sequence[tuple[str, Paise]] = (),
) -> list[Transaction]:
    """Every attempt in one window.

    Capture counts are the scenario's design parameter. Failures, values, fees
    and the success rate all follow from the calibration layer.
    """
    cells = _plan_cells(_days(period_from, period_to), capture_total)

    # Capture slots, in emission order, so a named record can be pinned to a
    # position rather than sampled. The demo script names these rows; they
    # cannot depend on a draw.
    slots: list[tuple[int, str]] = []
    for index, cell in enumerate(cells):
        slots.extend((index, cell.method) for _ in range(cell.captures))

    planted_at: dict[int, tuple[str, Paise]] = {}
    upi_positions = [position for position, (_, method) in enumerate(slots) if method == "UPI"]
    if planted and upi_positions:
        stride = max(1, len(upi_positions) // (len(planted) + 1))
        for offset, named in enumerate(planted, start=1):
            slot = upi_positions[min(offset * stride, len(upi_positions) - 1)]
            planted_at[slot] = named

    # Amounts are apportioned per method, so each method's realised mean ticket
    # is its calibrated one rather than whatever ~350 draws happened to give.
    capture_amounts: dict[str, list[Paise]] = {}
    for method in METHODS:
        positions = [position for position, (_, m) in enumerate(slots) if m == method]
        reserved = [planted_at[position][1] for position in positions if position in planted_at]
        capture_amounts[method] = _amounts_for(rng, method, len(positions), reserved)

    failure_counts: dict[str, int] = {
        method: sum(
            cell.technical_failures + cell.business_failures
            for cell in cells
            if cell.method == method
        )
        for method in METHODS
    }
    failure_amounts = {
        method: _amounts_for(rng, method, failure_counts[method]) for method in METHODS
    }

    records: list[Transaction] = []
    capture_cursor = dict.fromkeys(METHODS, 0)
    failure_cursor = dict.fromkeys(METHODS, 0)
    position = 0

    for cell in cells:
        for _ in range(cell.captures):
            pinned = planted_at.get(position)
            position += 1
            if pinned is not None:
                # A named record brings its own value and does not draw from
                # the apportioned pool -- otherwise its amount appears twice.
                txn_id, amount = pinned
            else:
                txn_id = txn_ids.take()
                amount = capture_amounts[cell.method][capture_cursor[cell.method]]
                capture_cursor[cell.method] += 1
            records.append(_make_capture(rng, txn_id, cell.method, cell.issuer, cell.day, amount))

        for technical in (True, False):
            count = cell.technical_failures if technical else cell.business_failures
            for _ in range(count):
                amount = failure_amounts[cell.method][failure_cursor[cell.method]]
                failure_cursor[cell.method] += 1
                records.append(
                    _make_decline(
                        rng, txn_ids.take(), cell.method, cell.issuer, cell.day, technical, amount
                    )
                )

    return records


def _generate_filler(rng: random.Random, txn_ids: IdPool) -> list[Transaction]:
    """Attempts outside the two analysis windows.

    No totals are asserted here. The quiet band before each window is load
    bearing: a capture in the two days before a window -- especially after the
    cutoff -- settles inside that window's cycle and would appear on the bank
    side with no ledger counterpart, a fabricated exception born of a boundary
    (D-19).
    """
    counts = SCENARIO.capture_counts
    blocked = (
        (PRIOR_FROM - timedelta(days=QUIET_BAND_DAYS), PRIOR_TO),
        (CURRENT_FROM - timedelta(days=QUIET_BAND_DAYS), CURRENT_TO),
    )
    days = [
        day
        for day in _days(SPAN_FROM, SPAN_TO)
        if not any(start <= day < end for start, end in blocked)
    ]
    method_weights = _as_weights([MIX_BY_METHOD[m].volume_share for m in METHODS])
    issuer_weights = _as_weights([share for _, share in ISSUERS])

    records: list[Transaction] = []
    for day in days:
        for _ in range(rng.randint(counts["filler_per_day_min"], counts["filler_per_day_max"])):
            method = METHODS[_weighted_index(rng, method_weights)]
            issuer = ISSUERS[_weighted_index(rng, issuer_weights)][0]
            technical, business = decline_rates(day, method, issuer)
            roll = Decimal(rng.randrange(100_000)) / Decimal(100_000)
            if roll < technical:
                records.append(_make_decline(rng, txn_ids.take(), method, issuer, day, True))
            elif roll < technical + business:
                records.append(_make_decline(rng, txn_ids.take(), method, issuer, day, False))
            else:
                records.append(_make_capture(rng, txn_ids.take(), method, issuer, day))
    return records


# --------------------------------------------------------------------------
# settlements and planted anomalies
# --------------------------------------------------------------------------


def _captured_in(txn: Transaction, period_from: date, period_to: date) -> bool:
    """A ledger record belongs to a window by its IST capture date."""
    if txn.captured_at is None:
        return False
    return period_from <= ist_date(txn.captured_at) < period_to


def _attempted_in(txn: Transaction, period_from: date, period_to: date) -> bool:
    """An attempt belongs to a window by the IST date it was attempted.

    Scoping attempts by capture date would silently drop every failure, because
    a failure has no capture instant -- and every success rate would then read
    100%, which is exactly the kind of quietly-wrong number this fixture exists
    to make impossible.
    """
    return period_from <= ist_date(txn.attempted_at) < period_to


def _settle(stl_id: str, txn: Transaction, *, value_date: date | None = None) -> Settlement:
    """The bank's view of a capture: on time and in agreement unless planted otherwise."""
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


def _plant_pair_exceptions(
    settlements: list[Settlement], pairs: list[tuple[Transaction, Settlement]]
) -> list[Settlement]:
    """The eleven exceptions that sit on a matched pair, at fixed indices."""
    replacements: dict[str, Settlement] = {}
    cursor = 0

    for offset in range(TIMING_LAG_COUNT):
        txn, stl = pairs[cursor]
        cursor += 1
        lag = TIMING_LAG_DAYS[offset % len(TIMING_LAG_DAYS)]
        replacements[stl.id] = _settle(
            stl.id, txn, value_date=add_business_days(stl.value_date, lag)
        )

    for delta in AMOUNT_MISMATCH_DELTAS:
        _, stl = pairs[cursor]
        cursor += 1
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

    for wrong_rule in FEE_MISAPPLIED_RULES:
        txn, stl = pairs[cursor]
        cursor += 1
        # Not a random perturbation: the bank billed this payment under the
        # WRONG INSTRUMENT'S rule. A zero-MDR UPI payment charged at the credit
        # card rate is a finding with a named cause, which is the whole point of
        # modelling fees per instrument instead of flat.
        replacements[stl.id] = Settlement(
            id=stl.id,
            merchant_id=stl.merchant_id,
            bank_ref=stl.bank_ref,
            utr=stl.utr,
            amount_paise=stl.amount_paise,
            fee_paise=FEE_SCHEDULE[wrong_rule].fee_paise(txn.amount_paise),
            currency=stl.currency,
            value_date=stl.value_date,
        )

    return [replacements.get(stl.id, stl) for stl in settlements]


def _plant_unmatched_bank(by_id: dict[str, Transaction]) -> list[Settlement]:
    """Bank rows with no ledger counterpart, including the near miss.

    SETTLEMENT_91 carries TXN_183's amount and nothing else: no reference, and a
    value date four business days past that transaction's SLA. It can only reach
    rule 5, at 0.72, below the 0.85 auto-match threshold -- so it is recorded as
    a rejected candidate rather than a match. That single row is the difference
    between a match rate that can be defended and one that cannot.
    """
    source = by_id[NEAR_MISS_SHADOWS]
    if source.settlement_due_date is None:
        raise ValueError(f"{NEAR_MISS_SHADOWS} must be a capture")
    rows = [
        Settlement(
            id=NEAR_MISS_ID,
            merchant_id=MERCHANT_ID,
            bank_ref=None,
            utr=None,
            amount_paise=source.amount_paise,
            fee_paise=source.fee_paise,
            currency=CURRENCY,
            value_date=add_business_days(source.settlement_due_date, NEAR_MISS_LAG_BUSINESS_DAYS),
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
                fee_paise=0,
                currency=CURRENCY,
                value_date=CURRENT_FROM + timedelta(days=11 + index * 3),
            )
        )
    return rows


def _movements(
    rng: random.Random,
    prefix: str,
    window: str,
    count: int,
    total_paise: Paise,
    sources: Sequence[Transaction],
    reasons: Sequence[str],
    offset: int,
) -> list[Movement]:
    """Refunds or chargebacks, apportioned so none exceeds its payment."""
    chosen = sorted(sources, key=lambda t: (-t.amount_paise, t.id))[offset : offset + count]
    if not chosen:
        return []
    weights = [txn.amount_paise for txn in chosen]
    rupees = allocate(total_paise // RUPEE, weights, floor=MIN_PAYMENT_RUPEES)
    movements: list[Movement] = []
    for index, (txn, amount) in enumerate(zip(chosen, rupees, strict=True), start=1):
        if txn.captured_at is None:
            raise ValueError(f"{txn.id} has no capture instant")
        movements.append(
            Movement(
                id=f"{prefix}_{window}_{index}",
                merchant_id=MERCHANT_ID,
                transaction_id=txn.id,
                amount_paise=amount * RUPEE,
                reason=rng.choice(list(reasons)),
                created_at=txn.captured_at + timedelta(days=rng.randint(1, 5)),
            )
        )
    return movements


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------


def build() -> Dataset:
    """The whole fixture, deterministically."""
    rng = random.Random(SEED)
    counts = SCENARIO.capture_counts

    reserved_txn = [txn_id for txn_id, _ in NO_COUNTERPART] + [DUPLICATE_ID]
    txn_ids = IdPool("TXN", 4000, rng, reserved_txn)
    stl_ids = IdPool("SETTLEMENT", 4000, rng, [NEAR_MISS_ID] + [i for i, _ in UNMATCHED_BANK_EXTRA])

    transactions = _generate_window(
        rng, CURRENT_FROM, CURRENT_TO, counts["current"], txn_ids, planted=NO_COUNTERPART
    )
    transactions += _generate_window(rng, PRIOR_FROM, PRIOR_TO, counts["prior"], txn_ids)
    transactions += _generate_filler(rng, txn_ids)

    by_id = {txn.id: txn for txn in transactions}
    current_captures = sorted(
        (
            t
            for t in transactions
            if t.status == "CAPTURED" and _captured_in(t, CURRENT_FROM, CURRENT_TO)
        ),
        key=lambda t: t.id,
    )

    # ---------------------------------------------------------------- duplicate
    # A second ledger row carrying an existing UTR and amount. It lifts
    # ledger_count by one, but it is not revenue -- and the one-to-one rule is
    # what turns it into an exception rather than a second match.
    no_counterpart_ids = {txn_id for txn_id, _ in NO_COUNTERPART}
    original = next(
        t for t in current_captures if t.utr is not None and t.id not in no_counterpart_ids
    )
    duplicate = Transaction(
        id=DUPLICATE_ID,
        merchant_id=MERCHANT_ID,
        external_ref=original.external_ref,
        utr=original.utr,
        method=original.method,
        instrument=original.instrument,
        issuer=original.issuer,
        status="CAPTURED",
        decline_type=None,
        decline_reason=None,
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
    settlements: list[Settlement] = []
    pairs: list[tuple[Transaction, Settlement]] = []
    for txn in sorted(transactions, key=lambda t: t.id):
        if txn.status != "CAPTURED" or txn.id in no_counterpart_ids or txn.id == DUPLICATE_ID:
            continue
        settlement = _settle(stl_ids.take(), txn)
        settlements.append(settlement)
        if _captured_in(txn, CURRENT_FROM, CURRENT_TO):
            pairs.append((txn, settlement))

    pairs.sort(key=lambda pair: pair[0].id)
    settlements = _plant_pair_exceptions(settlements, pairs)
    settlements += _plant_unmatched_bank(by_id)

    # ------------------------------------------------------- refunds, chargebacks
    refunds: list[Movement] = []
    chargebacks: list[Movement] = []
    refund_spec = SCENARIO._section("refunds")
    chargeback_spec = SCENARIO._section("chargebacks")
    for window, (start, end) in (
        ("current", (CURRENT_FROM, CURRENT_TO)),
        ("prior", (PRIOR_FROM, PRIOR_TO)),
    ):
        sources = [
            t
            for t in transactions
            if t.status == "CAPTURED" and t.id != DUPLICATE_ID and _captured_in(t, start, end)
        ]
        gross = sum(t.amount_paise for t in sources)
        refund_count = int(str(refund_spec[f"{window}_count"]))
        chargeback_count = int(str(chargeback_spec[f"{window}_count"]))
        refund_total = _rate_of(gross, _d(refund_spec[f"{window}_rate_of_gross"]))
        chargeback_total = _rate_of(gross, _d(chargeback_spec[f"{window}_rate_of_gross"]))

        refunds += _movements(
            rng,
            "RFND",
            window,
            refund_count,
            refund_total,
            sources,
            ("CUSTOMER_REQUEST", "ITEM_UNAVAILABLE", "DUPLICATE_CHARGE"),
            0,
        )
        chargebacks += _movements(
            rng,
            "CBK",
            window,
            chargeback_count,
            chargeback_total,
            sources,
            ("FRAUD", "SERVICE_NOT_RENDERED"),
            refund_count,
        )

    dataset = Dataset(
        transactions=sorted(transactions, key=lambda t: t.id),
        settlements=sorted(settlements, key=lambda s: s.id),
        refunds=sorted(refunds, key=lambda m: m.id),
        chargebacks=sorted(chargebacks, key=lambda m: m.id),
    )
    dataset.ground_truth = _ground_truth(dataset)
    return dataset


def _rate_of(gross_paise: Paise, rate: Decimal) -> Paise:
    """A whole-rupee amount at the given rate of gross."""
    rupees = int((Decimal(gross_paise // RUPEE) * rate).to_integral_value())
    return rupees * RUPEE


# --------------------------------------------------------------------------
# ground truth
# --------------------------------------------------------------------------


def _window_truth(dataset: Dataset, window: str, start: date, end: date) -> dict[str, object]:
    attempts = [
        t for t in dataset.transactions if t.id != DUPLICATE_ID and _attempted_in(t, start, end)
    ]
    captures = [t for t in attempts if t.status == "CAPTURED"]

    gross = sum(t.amount_paise for t in captures)
    attempted = sum(t.amount_paise for t in attempts)
    fees = sum(t.fee_paise for t in captures)
    refunds = sum(m.amount_paise for m in dataset.refunds if m.id.split("_")[1] == window)
    chargebacks = sum(m.amount_paise for m in dataset.chargebacks if m.id.split("_")[1] == window)

    technical = [t for t in attempts if t.decline_type == "TECHNICAL_DECLINE"]
    business = [t for t in attempts if t.decline_type == "BUSINESS_DECLINE"]

    per_method: dict[str, dict[str, object]] = {}
    for method in METHODS:
        method_attempts = [t for t in attempts if t.method == method]
        method_captures = [t for t in method_attempts if t.status == "CAPTURED"]
        if not method_attempts:
            continue
        method_value = sum(t.amount_paise for t in method_captures)
        per_method[method] = {
            "attempt_count": len(method_attempts),
            "capture_count": len(method_captures),
            # Volume share and value share are different numbers. UPI is
            # dominant by count and much less so by value, because its ticket
            # is small -- the single most important calibration fact here.
            "volume_share_ratio": str(ratio(len(method_attempts), len(attempts))),
            "value_share_ratio": str(ratio(method_value, gross)) if gross else "0.000000",
            "gross_paise": method_value,
            "fees_paise": sum(t.fee_paise for t in method_captures),
            "success_rate_ratio": str(ratio(len(method_captures), len(method_attempts))),
            "mean_ticket_paise": method_value // max(1, len(method_captures)),
            "technical_decline_ratio": str(
                ratio(
                    sum(1 for t in method_attempts if t.decline_type == "TECHNICAL_DECLINE"),
                    len(method_attempts),
                )
            ),
            "business_decline_ratio": str(
                ratio(
                    sum(1 for t in method_attempts if t.decline_type == "BUSINESS_DECLINE"),
                    len(method_attempts),
                )
            ),
        }

    return {
        "period_from": start.isoformat(),
        "period_to": end.isoformat(),
        "attempt_count": len(attempts),
        "capture_count": len(captures),
        "attempted_value_paise": attempted,
        "gross_payments_paise": gross,
        "refunds_paise": refunds,
        "fees_paise": fees,
        "chargebacks_paise": chargebacks,
        "net_revenue_paise": gross - refunds - fees - chargebacks,
        "success_rate_ratio": str(ratio(len(captures), len(attempts))),
        "technical_decline_ratio": str(ratio(len(technical), len(attempts))),
        "business_decline_ratio": str(ratio(len(business), len(attempts))),
        "effective_fee_rate_ratio": str(ratio(fees, gross)) if gross else "0.000000",
        "by_method": per_method,
    }


def _attribution(prior: dict[str, object], current: dict[str, object]) -> dict[str, object]:
    """The revenue bridge, which must close to the paise with a zero residual.

    ``volume_effect`` and ``rate_effect`` are defined so their sum is *exactly*
    the change in gross: the rate effect is the remainder of the volume effect
    rather than a second independent rounding. That is the fix for C-02, whose
    stated causes summed to 51% of the decline they claimed.
    """
    from runtime.money import apply_ratio

    attempted_prior = int(str(prior["attempted_value_paise"]))
    attempted_current = int(str(current["attempted_value_paise"]))
    gross_prior = int(str(prior["gross_payments_paise"]))
    gross_current = int(str(current["gross_payments_paise"]))

    volume_effect = apply_ratio(attempted_current - attempted_prior, gross_prior, attempted_prior)
    rate_effect = (gross_current - gross_prior) - volume_effect

    terms = {
        "attempt_volume_paise": volume_effect,
        "success_rate_paise": rate_effect,
        "refunds_paise": -(int(str(current["refunds_paise"])) - int(str(prior["refunds_paise"]))),
        "chargebacks_paise": -(
            int(str(current["chargebacks_paise"])) - int(str(prior["chargebacks_paise"]))
        ),
        "fees_paise": -(int(str(current["fees_paise"])) - int(str(prior["fees_paise"]))),
    }
    net_change = int(str(current["net_revenue_paise"])) - int(str(prior["net_revenue_paise"]))
    return {
        "net_change_paise": net_change,
        "net_change_ratio": str(ratio(net_change, int(str(prior["net_revenue_paise"])))),
        "terms": terms,
        "rounding_residual_paise": net_change - sum(terms.values()),
    }


def _reconciliation_truth(dataset: Dataset) -> dict[str, object]:
    opens, closes = bank_period(CURRENT_FROM, CURRENT_TO)
    ledger = [
        t
        for t in dataset.transactions
        if t.status == "CAPTURED" and _captured_in(t, CURRENT_FROM, CURRENT_TO)
    ]
    bank = [s for s in dataset.settlements if opens <= s.value_date < closes]

    unmatched_ledger = len(NO_COUNTERPART) + 1
    unmatched_bank = 1 + len(UNMATCHED_BANK_EXTRA)
    matched_pairs = len(ledger) - unmatched_ledger
    flagged = TIMING_LAG_COUNT + len(AMOUNT_MISMATCH_DELTAS) + len(FEE_MISAPPLIED_RULES)
    clean = matched_pairs - flagged

    return {
        "period_from": CURRENT_FROM.isoformat(),
        "period_to": CURRENT_TO.isoformat(),
        "bank_period_from": opens.isoformat(),
        "bank_period_to": closes.isoformat(),
        "ledger_count": len(ledger),
        "bank_count": len(bank),
        "matched_pairs": matched_pairs,
        "matched_clean": clean,
        "matched_with_exception": flagged,
        "unmatched_ledger": unmatched_ledger,
        "unmatched_bank": unmatched_bank,
        "clean_match_rate_ratio": str(ratio(clean, len(ledger))),
        "exception_count": len(ledger) - clean,
        "exceptions_by_category": {
            "TIMING_LAG": TIMING_LAG_COUNT,
            "NO_COUNTERPART": len(NO_COUNTERPART),
            "AMOUNT_MISMATCH": len(AMOUNT_MISMATCH_DELTAS),
            "FEE_DISCREPANCY": len(FEE_MISAPPLIED_RULES),
            "POSSIBLE_DUPLICATE": 1,
        },
        "unresolved_paise": UNRESOLVED_PAISE,
        "unresolved_transaction_ids": [txn_id for txn_id, _ in NO_COUNTERPART],
        "duplicate_transaction_id": DUPLICATE_ID,
        "rejected_candidate_settlement_id": NEAR_MISS_ID,
    }


def _technical_ratio(records: list[Transaction]) -> str:
    if not records:
        return "0.000000"
    return str(
        ratio(sum(1 for t in records if t.decline_type == "TECHNICAL_DECLINE"), len(records))
    )


def _incident_truth(dataset: Dataset) -> dict[str, object]:
    """What actually happened, so a diagnosis can be scored.

    A conclusion is only checkable if the truth was written down before the
    investigation ran.
    """
    inside = [
        t
        for t in dataset.transactions
        if INCIDENT.start <= ist_date(t.attempted_at) < INCIDENT.end and t.method == INCIDENT.method
    ]
    affected = [t for t in inside if t.issuer in INCIDENT.issuers]
    unaffected = [t for t in inside if t.issuer not in INCIDENT.issuers]

    expected = SCENARIO._section("expected_diagnosis")
    return {
        "incident_id": str(SCENARIO._section("incident")["id"]),
        "start": INCIDENT.start.isoformat(),
        "end": INCIDENT.end.isoformat(),
        "affected_method": INCIDENT.method,
        "affected_issuers": sorted(INCIDENT.issuers),
        "technical_decline_ratio_affected": _technical_ratio(affected),
        "technical_decline_ratio_unaffected": _technical_ratio(unaffected),
        "expected_diagnosis": {
            key: value for key, value in expected.items() if not key.startswith("_")
        },
    }


def _ground_truth(dataset: Dataset) -> dict[str, object]:
    prior = _window_truth(dataset, "prior", PRIOR_FROM, PRIOR_TO)
    current = _window_truth(dataset, "current", CURRENT_FROM, CURRENT_TO)
    return {
        "scenario_id": SCENARIO_ID,
        "seed": SEED,
        "merchant_id": MERCHANT_ID,
        "span_from": SPAN_FROM.isoformat(),
        "span_to": SPAN_TO.isoformat(),
        "transaction_count": len(dataset.transactions),
        "settlement_count": len(dataset.settlements),
        "provenance": {
            "transaction_records": "synthetic, seeded",
            "aggregate_calibration": "NPCI UPI statistics; RBI payment system indicators",
            "sources": "data/calibration/sources.md",
            "parameter_counts": provenance_summary(),
            "disclaimer": (
                "Transaction-level records are synthetic. Aggregate distributions and "
                "operational characteristics are calibrated against public NPCI/RBI "
                "statistics. No real customer or merchant transaction data is represented."
            ),
        },
        "prior": prior,
        "current": current,
        "attribution": _attribution(prior, current),
        "reconciliation": _reconciliation_truth(dataset),
        "incident": _incident_truth(dataset),
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
    "instrument",
    "issuer",
    "status",
    "decline_type",
    "decline_reason",
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

MOVEMENT_COLUMNS = (
    "id",
    "merchant_id",
    "transaction_id",
    "amount_paise",
    "reason",
    "created_at",
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
        record = row if isinstance(row, dict) else asdict(row)  # type: ignore[call-overload]
        values.append("  (" + ", ".join(_sql_literal(record[c]) for c in columns) + ")")
    lines.append(",\n".join(values) + ";")
    lines.append("")
    return lines


def _write_sql(path: Path, dataset: Dataset) -> None:
    lines = [
        "-- Generated by data/seed/generate_seed_data.py. Do not edit by hand.",
        f"-- scenario={SCENARIO_ID}  seed={SEED}  merchant={MERCHANT_ID}",
        f"-- span=[{SPAN_FROM}, {SPAN_TO})",
        "-- Transaction records are synthetic. See data/calibration/sources.md.",
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
    lines += _insert("users", ("id", "email"), [{"id": u, "email": e} for u, e, _, _ in USERS])
    lines += _insert(
        "merchant_members",
        ("user_id", "merchant_id", "role"),
        [{"user_id": u, "merchant_id": m, "role": r} for u, _, m, r in USERS],
    )
    lines += _insert("transactions", LEDGER_COLUMNS, dataset.transactions)
    lines += _insert("settlements", BANK_COLUMNS, dataset.settlements)
    lines += _insert("refunds", MOVEMENT_COLUMNS, dataset.refunds)
    lines += _insert("chargebacks", MOVEMENT_COLUMNS, dataset.chargebacks)
    lines += ["COMMIT;", ""]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


ARTIFACTS = (
    "ledger_side.csv",
    "bank_settlement.csv",
    "seed.sql",
    "golden/ground_truth.json",
)


def write(dataset: Dataset) -> dict[str, str]:
    """Write every artifact and return the checksum manifest."""
    GOLDEN.mkdir(parents=True, exist_ok=True)
    _write_csv(HERE / "ledger_side.csv", LEDGER_COLUMNS, dataset.transactions)
    _write_csv(HERE / "bank_settlement.csv", BANK_COLUMNS, dataset.settlements)
    _write_sql(HERE / "seed.sql", dataset)
    (GOLDEN / "ground_truth.json").write_text(
        json.dumps(dataset.ground_truth, indent=2, sort_keys=True) + "\n",
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
    truth = dataset.ground_truth
    current = truth["current"]
    prior = truth["prior"]
    recon = truth["reconciliation"]
    attribution = truth["attribution"]
    incident = truth["incident"]
    assert isinstance(current, dict)
    assert isinstance(prior, dict)
    assert isinstance(recon, dict)
    assert isinstance(attribution, dict)
    assert isinstance(incident, dict)

    print(f"scenario           {SCENARIO_ID}  seed={SEED}")
    print(f"transactions       {len(dataset.transactions)}")
    print(f"settlements        {len(dataset.settlements)}")
    print()
    print(f"{'':<22}{'prior':>16}{'current':>16}")
    for label, key in (
        ("attempts", "attempt_count"),
        ("captures", "capture_count"),
        ("attempted value", "attempted_value_paise"),
        ("gross", "gross_payments_paise"),
        ("fees", "fees_paise"),
        ("refunds", "refunds_paise"),
        ("chargebacks", "chargebacks_paise"),
        ("net revenue", "net_revenue_paise"),
        ("success rate", "success_rate_ratio"),
        ("technical declines", "technical_decline_ratio"),
        ("business declines", "business_decline_ratio"),
        ("effective fee rate", "effective_fee_rate_ratio"),
    ):
        print(f"{label:<22}{prior[key]!s:>16}{current[key]!s:>16}")
    print()
    print(f"net change         {attribution['net_change_paise']} paise")
    print(f"net change ratio   {attribution['net_change_ratio']}")
    print(f"residual           {attribution['rounding_residual_paise']}")
    print()
    print(f"incident TD (affected)    {incident['technical_decline_ratio_affected']}")
    print(f"incident TD (unaffected)  {incident['technical_decline_ratio_unaffected']}")
    print()
    print(
        f"reconciliation     {recon['ledger_count']} / {recon['bank_count']} / "
        f"{recon['matched_pairs']} / {recon['matched_clean']} / "
        f"{recon['exception_count']} / {recon['clean_match_rate_ratio']}"
    )
    print()
    for name, digest in manifest.items():
        print(f"{digest}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
