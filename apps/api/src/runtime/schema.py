"""The database schema, as SQLAlchemy **Core** tables.

Core rather than the ORM on purpose (docs/12-tech-stack.md): reconciliation is
only reproducible if every query carries an explicit ``ORDER BY`` with a unique
tiebreaker, and an ORM's identity map hides exactly the thing that has to stay
visible.

Column conventions, all enforced elsewhere as well:

* money is ``BigInteger`` paise, and the column name ends in ``_paise``
* ratios are ``Numeric(9, 6)`` and the column name ends in ``_ratio``
* instants are ``TIMESTAMPTZ``; a *date* is an IST calendar date and is stored
  as ``DATE``, derived by ``runtime/calendar.py`` and never as ``UTC::date``
* enumerations are ``TEXT`` plus a ``CHECK``, not Postgres ``ENUM`` types --
  adding a value to a Postgres enum inside a transaction is a migration
  hazard, and the check constraint reads identically in a diff
"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

__all__ = [
    "DECLINE_TYPES",
    "EXCEPTION_CATEGORIES",
    "EXECUTION_STATUSES",
    "INSTRUMENTS",
    "MATCH_RULES",
    "MERCHANT_ROLES",
    "MERCHANT_SCOPED_TABLES",
    "METADATA",
    "PAYMENT_METHODS",
    "TRANSACTION_STATUSES",
    "agent_executions",
    "chargebacks",
    "evidence",
    "execution_events",
    "merchant_members",
    "merchants",
    "reconciliation_exceptions",
    "reconciliation_matches",
    "reconciliation_runs",
    "settlements",
    "tool_executions",
    "transactions",
    "users",
]

METADATA = MetaData()

# --------------------------------------------------------------------------
# vocabularies -- single definition, referenced by the CHECK constraints and
# by the seed generator, so the two cannot drift
# --------------------------------------------------------------------------

TRANSACTION_STATUSES = ("ATTEMPTED", "FAILED", "CAPTURED", "SETTLED", "REFUNDED")

#: The *rail*.
PAYMENT_METHODS = ("UPI", "CARD", "NETBANKING", "WALLET")

#: The *funding source*, which is what decides the fee. A UPI payment funded
#: from a bank account carries no MDR; the same rail funded from a prepaid
#: wallet carries an interchange. Collapsing the two is what makes a flat fee
#: model unable to represent a real fee discrepancy.
INSTRUMENTS = (
    "UPI_BANK_ACCOUNT",
    "UPI_PPI_WALLET",
    "UPI_RUPAY_CREDIT",
    "RUPAY_DEBIT",
    "OTHER_DEBIT",
    "CREDIT_CARD",
    "NETBANKING",
    "WALLET",
)

#: NPCI distinguishes these and publishes both per bank, monthly. A technical
#: decline is the platform's problem and spikes during an incident; a business
#: decline is the customer's and stays flat. An investigation that cannot
#: separate them can only report that a success rate moved.
DECLINE_TYPES = ("TECHNICAL_DECLINE", "BUSINESS_DECLINE")
MERCHANT_ROLES = ("OWNER", "ANALYST", "VIEWER")
MATCH_RULES = (
    "EXACT_UTR",
    "REF_AMOUNT",
    "REF_DATE_WINDOW",
    "AMOUNT_DATE_WINDOW",
    "AMOUNT_DATE_CANDIDATE",
)
EXCEPTION_CATEGORIES = (
    "TIMING_LAG",
    "AMOUNT_MISMATCH",
    "FEE_DISCREPANCY",
    "NO_COUNTERPART",
    "POSSIBLE_DUPLICATE",
)
EXCEPTION_SIDES = ("LEDGER", "BANK")
EXECUTION_STATUSES = (
    "PENDING",
    "PLANNING",
    "NEEDS_CLARIFICATION",
    "VALIDATING",
    "REJECTED",
    "EXECUTING",
    "PARTIAL",
    "VERIFYING",
    "BLOCKED",
    "EXPLAINING",
    "COMPLETED",
    "FAILED",
)


def _one_of(column: str, values: tuple[str, ...]) -> CheckConstraint:
    listed = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({listed})", name=f"ck_{column}_valid")


_NOW = text("now()")

# --------------------------------------------------------------------------
# identity and tenancy
# --------------------------------------------------------------------------

users = Table(
    "users",
    METADATA,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("email", Text, nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_NOW),
)

merchants = Table(
    "merchants",
    METADATA,
    Column("id", String(32), primary_key=True),
    Column("name", Text, nullable=False),
    Column("currency", String(3), nullable=False, server_default=text("'INR'")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_NOW),
    CheckConstraint("currency = 'INR'", name="ck_merchants_currency_supported"),
)

merchant_members = Table(
    "merchant_members",
    METADATA,
    Column(
        "user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "merchant_id",
        String(32),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("role", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_NOW),
    _one_of("role", MERCHANT_ROLES),
)

# --------------------------------------------------------------------------
# domain
# --------------------------------------------------------------------------

transactions = Table(
    "transactions",
    METADATA,
    Column("id", String(32), primary_key=True),
    Column("merchant_id", String(32), ForeignKey("merchants.id"), nullable=False),
    Column("external_ref", Text, nullable=False),
    # Nullable on purpose: a missing UTR is precisely what forces the weaker
    # matching rules (docs/03-reconciliation.md).
    Column("utr", Text, nullable=True),
    Column("method", Text, nullable=False),
    Column("instrument", Text, nullable=False),
    Column("issuer", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("decline_type", Text, nullable=True),
    Column("decline_reason", Text, nullable=True),
    Column("amount_paise", BigInteger, nullable=False),
    Column("fee_paise", BigInteger, nullable=False),
    Column("currency", String(3), nullable=False, server_default=text("'INR'")),
    Column("attempted_at", DateTime(timezone=True), nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=True),
    Column("settlement_due_date", Date, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_NOW),
    _one_of("method", PAYMENT_METHODS),
    _one_of("instrument", INSTRUMENTS),
    _one_of("status", TRANSACTION_STATUSES),
    CheckConstraint(
        "decline_type IS NULL OR decline_type IN ('TECHNICAL_DECLINE', 'BUSINESS_DECLINE')",
        name="ck_transactions_decline_type_valid",
    ),
    # A failure must say which kind it was, and a success must not claim one.
    # Without this the TD/BD split degrades silently into "some rows have it".
    CheckConstraint(
        "(status = 'FAILED') = (decline_type IS NOT NULL)",
        name="ck_transactions_decline_type_agrees_with_status",
    ),
    CheckConstraint("amount_paise >= 0", name="ck_transactions_amount_non_negative"),
    CheckConstraint("fee_paise >= 0", name="ck_transactions_fee_non_negative"),
    CheckConstraint("currency = 'INR'", name="ck_transactions_currency_supported"),
    # A captured payment must carry the two fields the settlement SLA is
    # computed from; an uncaptured one must carry neither.
    CheckConstraint(
        "(captured_at IS NULL) = (settlement_due_date IS NULL)",
        name="ck_transactions_capture_fields_agree",
    ),
    Index("ix_transactions_merchant_captured", "merchant_id", "captured_at"),
    Index("ix_transactions_merchant_method_attempted", "merchant_id", "method", "attempted_at"),
    Index(
        "ix_transactions_declines",
        "merchant_id",
        "issuer",
        "attempted_at",
        postgresql_where=text("decline_type IS NOT NULL"),
    ),
    Index(
        "ix_transactions_merchant_utr",
        "merchant_id",
        "utr",
        postgresql_where=text("utr IS NOT NULL"),
    ),
)

settlements = Table(
    "settlements",
    METADATA,
    Column("id", String(32), primary_key=True),
    Column("merchant_id", String(32), ForeignKey("merchants.id"), nullable=False),
    Column("bank_ref", Text, nullable=True),
    Column("utr", Text, nullable=True),
    Column("amount_paise", BigInteger, nullable=False),
    Column("fee_paise", BigInteger, nullable=False),
    Column("currency", String(3), nullable=False, server_default=text("'INR'")),
    Column("value_date", Date, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_NOW),
    CheckConstraint("amount_paise >= 0", name="ck_settlements_amount_non_negative"),
    CheckConstraint("fee_paise >= 0", name="ck_settlements_fee_non_negative"),
    CheckConstraint("currency = 'INR'", name="ck_settlements_currency_supported"),
    Index("ix_settlements_merchant_value_date", "merchant_id", "value_date"),
    Index(
        "ix_settlements_merchant_utr",
        "merchant_id",
        "utr",
        postgresql_where=text("utr IS NOT NULL"),
    ),
)

refunds = Table(
    "refunds",
    METADATA,
    Column("id", String(32), primary_key=True),
    Column("merchant_id", String(32), ForeignKey("merchants.id"), nullable=False),
    Column("transaction_id", String(32), ForeignKey("transactions.id"), nullable=False),
    Column("amount_paise", BigInteger, nullable=False),
    Column("reason", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("amount_paise > 0", name="ck_refunds_amount_positive"),
    Index("ix_refunds_merchant_created", "merchant_id", "created_at"),
)

chargebacks = Table(
    "chargebacks",
    METADATA,
    Column("id", String(32), primary_key=True),
    Column("merchant_id", String(32), ForeignKey("merchants.id"), nullable=False),
    Column("transaction_id", String(32), ForeignKey("transactions.id"), nullable=False),
    Column("amount_paise", BigInteger, nullable=False),
    Column("reason", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("amount_paise > 0", name="ck_chargebacks_amount_positive"),
    Index("ix_chargebacks_merchant_created", "merchant_id", "created_at"),
)

# --------------------------------------------------------------------------
# reconciliation
# --------------------------------------------------------------------------

reconciliation_runs = Table(
    "reconciliation_runs",
    METADATA,
    Column("id", String(64), primary_key=True),
    Column("merchant_id", String(32), ForeignKey("merchants.id"), nullable=False),
    Column("period_from", Date, nullable=False),
    Column("period_to", Date, nullable=False),
    Column("ledger_count", Integer, nullable=False),
    Column("bank_count", Integer, nullable=False),
    Column("matched_pairs", Integer, nullable=False),
    Column("matched_clean", Integer, nullable=False),
    Column("matched_with_exception", Integer, nullable=False),
    Column("unmatched_ledger", Integer, nullable=False),
    Column("unmatched_bank", Integer, nullable=False),
    Column("clean_match_rate_ratio", Numeric(9, 6), nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_NOW),
    # Half-open [from, to), so adjacent periods tile with neither gap nor
    # overlap (docs/02-data-model.md#time).
    CheckConstraint("period_from < period_to", name="ck_runs_period_half_open"),
    CheckConstraint(
        "clean_match_rate_ratio >= 0 AND clean_match_rate_ratio <= 1",
        name="ck_runs_clean_match_rate_is_a_ratio",
    ),
    CheckConstraint("status IN ('COMPLETED', 'FAILED')", name="ck_runs_status_valid"),
    # I3, as a constraint rather than an assertion.
    CheckConstraint(
        "matched_pairs = matched_clean + matched_with_exception",
        name="ck_runs_i3_pairs_split",
    ),
    # I1.
    CheckConstraint(
        "matched_clean + matched_with_exception + unmatched_ledger = ledger_count",
        name="ck_runs_i1_ledger_accounted",
    ),
    # I2.
    CheckConstraint(
        "2 * matched_pairs + unmatched_ledger + unmatched_bank = ledger_count + bank_count",
        name="ck_runs_i2_two_sided_total",
    ),
    Index("ix_runs_merchant_period", "merchant_id", "period_from", "period_to"),
)

reconciliation_matches = Table(
    "reconciliation_matches",
    METADATA,
    Column("id", String(64), primary_key=True),
    Column(
        "run_id",
        String(64),
        ForeignKey("reconciliation_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("transaction_id", String(32), ForeignKey("transactions.id"), nullable=False),
    Column("settlement_id", String(32), ForeignKey("settlements.id"), nullable=False),
    Column("rule", Text, nullable=False),
    Column("confidence_ratio", Numeric(9, 6), nullable=False),
    Column("reason", Text, nullable=False),
    Column("amount_delta_paise", BigInteger, nullable=False),
    Column("lag_days", Integer, nullable=False),
    _one_of("rule", MATCH_RULES),
    # I5 and I6: the one-to-one guarantee, enforced by the database rather
    # than trusted to the matcher (C-07).
    UniqueConstraint("run_id", "transaction_id", name="uq_matches_run_transaction"),
    UniqueConstraint("run_id", "settlement_id", name="uq_matches_run_settlement"),
    # Rule 5 produces a rejected candidate, never a match. The auto-match
    # threshold is 0.85 and the database is where that stops being a promise.
    CheckConstraint(
        "confidence_ratio >= 0.85 AND confidence_ratio <= 1",
        name="ck_matches_above_auto_match_threshold",
    ),
)

reconciliation_exceptions = Table(
    "reconciliation_exceptions",
    METADATA,
    Column("id", String(64), primary_key=True),
    Column(
        "run_id",
        String(64),
        ForeignKey("reconciliation_runs.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("category", Text, nullable=False),
    Column("side", Text, nullable=False),
    Column("transaction_id", String(32), ForeignKey("transactions.id"), nullable=True),
    Column("settlement_id", String(32), ForeignKey("settlements.id"), nullable=True),
    Column("amount_paise", BigInteger, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'OPEN'")),
    Column("detail_json", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_NOW),
    _one_of("category", EXCEPTION_CATEGORIES),
    _one_of("side", EXCEPTION_SIDES),
    CheckConstraint(
        "status IN ('OPEN', 'RESOLVED', 'ACKNOWLEDGED')",
        name="ck_exceptions_status_valid",
    ),
    # Every exception references at least one real record id
    # (docs/03-reconciliation.md, verification of the run).
    CheckConstraint(
        "transaction_id IS NOT NULL OR settlement_id IS NOT NULL",
        name="ck_exceptions_reference_a_record",
    ),
    Index("ix_exceptions_run_category", "run_id", "category"),
)

# --------------------------------------------------------------------------
# agent
# --------------------------------------------------------------------------

agent_executions = Table(
    "agent_executions",
    METADATA,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id"), nullable=False),
    Column("merchant_id", String(32), ForeignKey("merchants.id"), nullable=False),
    Column("client_request_id", Text, nullable=True),
    Column("input", Text, nullable=False),
    Column("intent_json", JSONB, nullable=True),
    Column("plan_json", JSONB, nullable=True),
    Column("period_from", Date, nullable=True),
    Column("period_to", Date, nullable=True),
    Column("status", Text, nullable=False),
    Column("error_json", JSONB, nullable=True),
    Column("response_source", Text, nullable=True),
    Column("grounding_attempts", Integer, nullable=False, server_default=text("0")),
    Column("seed", BigInteger, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_NOW),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=_NOW),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    _one_of("status", EXECUTION_STATUSES),
    CheckConstraint(
        "response_source IS NULL OR response_source IN ('LLM', 'TEMPLATE_FALLBACK')",
        name="ck_executions_response_source_valid",
    ),
    CheckConstraint(
        "period_from IS NULL OR period_to IS NULL OR period_from < period_to",
        name="ck_executions_period_half_open",
    ),
    # Idempotency: replaying a client_request_id returns the original run.
    UniqueConstraint("merchant_id", "client_request_id", name="uq_executions_client_request"),
    Index("ix_executions_merchant_created", "merchant_id", "created_at"),
)

tool_executions = Table(
    "tool_executions",
    METADATA,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "execution_id",
        UUID(as_uuid=True),
        ForeignKey("agent_executions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("tool_name", Text, nullable=False),
    Column("tool_version", Text, nullable=False),
    Column("input_json", JSONB, nullable=False),
    Column("output_json", JSONB, nullable=True),
    Column("status", Text, nullable=False),
    Column("error_json", JSONB, nullable=True),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("duration_ms", Integer, nullable=True),
    CheckConstraint(
        "status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'SKIPPED')",
        name="ck_tool_executions_status_valid",
    ),
    Index("ix_tool_executions_execution", "execution_id"),
)

evidence = Table(
    "evidence",
    METADATA,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "execution_id",
        UUID(as_uuid=True),
        ForeignKey("agent_executions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("tool_name", Text, nullable=False),
    Column("tool_version", Text, nullable=False),
    Column("metric_id", Text, nullable=False),
    Column("unit", Text, nullable=False),
    Column("value_json", JSONB, nullable=False),
    Column("formula_json", JSONB, nullable=True),
    Column("inputs_json", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("source_record_ids", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("rules_applied", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("verification_checks", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_NOW),
    # Metric ids carry mandatory unit suffixes (D-14).
    CheckConstraint("unit IN ('paise', 'ratio', 'pp', 'count')", name="ck_evidence_unit_valid"),
    UniqueConstraint("execution_id", "metric_id", name="uq_evidence_execution_metric"),
)

execution_events = Table(
    "execution_events",
    METADATA,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column(
        "execution_id",
        UUID(as_uuid=True),
        ForeignKey("agent_executions.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("seq", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("payload_json", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=_NOW),
    # Append-only and monotonically sequenced per execution. This table *is*
    # the audit trail and it backs both the SSE stream and the history UI.
    UniqueConstraint("execution_id", "seq", name="uq_events_execution_seq"),
    CheckConstraint("seq >= 0", name="ck_events_seq_non_negative"),
    Index("ix_events_execution_seq", "execution_id", "seq"),
)

#: Tables carrying a ``merchant_id`` and therefore subject to row-level
#: security. Named here so the migration and the RLS test read from one list.
MERCHANT_SCOPED_TABLES = (
    "transactions",
    "settlements",
    "refunds",
    "chargebacks",
    "reconciliation_runs",
    "agent_executions",
)
