"""Evidence rows are addressed by metric, window and slice -- not by a surrogate id.

Revision ID: 0003
Revises: 0002

0001 gave the table a UUID primary key and a unique constraint on
``(execution_id, metric_id)``. Both were written before anything published
evidence, and both are wrong in the same way: they assume one row per metric per
execution.

A revenue analysis publishes ``net_revenue_paise`` for **two** windows in one
execution, and the failure analysis publishes ``by_method.success_rate_ratio``
for four rails in each of them. Under the old constraint the second row of each
pair was a unique-violation, and under the old key a formula operand -- which
cites ``finance.revenue_analysis/1.0/net_revenue_paise/2026-08-01_2026-08-24``
verbatim -- had nothing to resolve against, because the stored id was a UUID
nobody had written down.

So the id becomes the address it already was in memory, the primary key becomes
``(execution_id, id)``, and the window and slice become columns rather than
something a reader has to parse back out of a string.

Two constraints arrive with them:

* exactly one of ``formula_json`` and ``aggregation_json``, which is D-29
  enforced by the database rather than only by pydantic;
* ``aggregation_json``, which 0001 had no column for at all -- a leaf metric's
  fold had nowhere to be stored, so its support would have been lost on the way
  to the table.

The table has never held a row, so this drops and recreates rather than
migrating in place. That is stated rather than assumed: the ``DROP TABLE`` is
safe only because nothing has written here yet, and it would not be next month.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("evidence")
    op.create_table(
        "evidence",
        sa.Column(
            "execution_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("tool_version", sa.Text(), nullable=False),
        sa.Column("metric_id", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("value_json", JSONB, nullable=False),
        sa.Column("period_from", sa.Date(), nullable=False),
        sa.Column("period_to", sa.Date(), nullable=False),
        sa.Column("dimension_value", sa.Text(), nullable=True),
        sa.Column("formula_json", JSONB, nullable=True),
        sa.Column("aggregation_json", JSONB, nullable=True),
        sa.Column("inputs_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "source_record_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("rules_applied", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "verification_checks", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("execution_id", "id", name="pk_evidence"),
        sa.CheckConstraint(
            "unit IN ('paise', 'ratio', 'pp', 'count')", name="ck_evidence_unit_valid"
        ),
        sa.CheckConstraint(
            "(formula_json IS NULL) <> (aggregation_json IS NULL)",
            name="ck_evidence_exactly_one_support",
        ),
        sa.CheckConstraint("period_from < period_to", name="ck_evidence_period_half_open"),
    )
    op.create_index("ix_evidence_execution_metric", "evidence", ["execution_id", "metric_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_execution_metric", table_name="evidence")
    op.drop_table("evidence")
    op.create_table(
        "evidence",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "execution_id",
            UUID(as_uuid=True),
            sa.ForeignKey("agent_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("tool_version", sa.Text(), nullable=False),
        sa.Column("metric_id", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("value_json", JSONB, nullable=False),
        sa.Column("formula_json", JSONB, nullable=True),
        sa.Column("inputs_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "source_record_ids", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("rules_applied", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "verification_checks", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "unit IN ('paise', 'ratio', 'pp', 'count')", name="ck_evidence_unit_valid"
        ),
        sa.UniqueConstraint("execution_id", "metric_id", name="uq_evidence_execution_metric"),
    )
