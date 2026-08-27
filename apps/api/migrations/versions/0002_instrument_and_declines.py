"""Instrument, issuer, and the technical/business decline taxonomy.

Revision ID: 0002
Revises: 0001

Three things the flat model could not express.

**Instrument.** ``method`` is the rail; ``instrument`` is the funding source, and
the funding source is what decides the fee. Bank-account UPI carries no MDR;
the same rail funded from a prepaid wallet carries an interchange. Under a flat
percentage a fee discrepancy is arithmetic noise. Under an instrument-dependent
schedule it means a specific commercial rule was applied wrongly, which is a
finding an analyst can act on.

**Issuer.** Without it an incident cannot be localised, and "UPI is failing" is
as far as any investigation can get.

**Decline type.** NPCI distinguishes technical declines (a bank or NPCI back end
failing) from business declines (wrong PIN, insufficient funds, limit exceeded)
and publishes both per bank, monthly. The distinction is the whole reason this
platform can say *why* a success rate moved rather than only that it did.

This revision is written as explicit ``op`` calls, as promised in 0001: from
here on the metadata says where we are going and the migrations say how we got
there.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

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


def upgrade() -> None:
    # Added with a server_default so the migration is safe against a populated
    # table, then dropped so the application must always be explicit.
    op.add_column(
        "transactions",
        sa.Column("instrument", sa.Text(), nullable=False, server_default="UPI_BANK_ACCOUNT"),
    )
    op.add_column(
        "transactions",
        sa.Column("issuer", sa.Text(), nullable=False, server_default="UNKNOWN"),
    )
    op.add_column("transactions", sa.Column("decline_type", sa.Text(), nullable=True))
    op.add_column("transactions", sa.Column("decline_reason", sa.Text(), nullable=True))
    op.alter_column("transactions", "instrument", server_default=None)
    op.alter_column("transactions", "issuer", server_default=None)

    listed = ", ".join(f"'{value}'" for value in INSTRUMENTS)
    op.create_check_constraint("ck_instrument_valid", "transactions", f"instrument IN ({listed})")
    op.create_check_constraint(
        "ck_transactions_decline_type_valid",
        "transactions",
        "decline_type IS NULL OR decline_type IN ('TECHNICAL_DECLINE', 'BUSINESS_DECLINE')",
    )
    # A failure must say which kind it was, and a success must not claim one.
    # Without this the TD/BD split degrades silently into "some rows have it",
    # and every decline rate computed from it is quietly wrong.
    #
    # Added NOT VALID deliberately. Rows written before this revision have no
    # decline type because nothing recorded one, and there is no honest
    # backfill -- picking a default would mean inventing the very field the
    # investigation depends on. NOT VALID still enforces the rule on every
    # insert and update; it only declines to retroactively assert something
    # about history that nobody knows. Run VALIDATE CONSTRAINT once the table
    # holds no pre-taxonomy rows.
    op.execute(
        "ALTER TABLE transactions ADD CONSTRAINT "
        "ck_transactions_decline_type_agrees_with_status "
        "CHECK ((status = 'FAILED') = (decline_type IS NOT NULL)) NOT VALID"
    )

    op.create_index(
        "ix_transactions_merchant_method_attempted",
        "transactions",
        ["merchant_id", "method", "attempted_at"],
    )
    op.create_index(
        "ix_transactions_declines",
        "transactions",
        ["merchant_id", "issuer", "attempted_at"],
        postgresql_where=sa.text("decline_type IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_declines", table_name="transactions")
    op.drop_index("ix_transactions_merchant_method_attempted", table_name="transactions")
    op.drop_constraint(
        "ck_transactions_decline_type_agrees_with_status", "transactions", type_="check"
    )
    op.drop_constraint("ck_transactions_decline_type_valid", "transactions", type_="check")
    op.drop_constraint("ck_instrument_valid", "transactions", type_="check")
    op.drop_column("transactions", "decline_reason")
    op.drop_column("transactions", "decline_type")
    op.drop_column("transactions", "issuer")
    op.drop_column("transactions", "instrument")
