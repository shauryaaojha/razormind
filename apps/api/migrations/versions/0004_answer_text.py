"""The answer gets a column, and prose gets tied to its origin.

Revision ID: 0004
Revises: 0003

``agent_executions`` carried ``response_source`` and ``grounding_attempts``
from 0001 -- a label saying where the answer came from, and a counter saying
how hard it was to get -- and no column for the answer. Both were written
before anything generated text, and the gap only becomes visible when something
does: ``response_source = 'LLM'`` on a row with no text is a statement about a
sentence the database never saw.

So ``answer_text`` and ``claims_json`` arrive together, with a constraint that
keeps them honest in both directions:

* text with no declared source cannot be labelled by the UI, and "who wrote
  this" is the first question a reader of a generated financial summary asks;
* a source with no text claims something was written when nothing was, which is
  exactly the shape a blocked execution must never be able to take.

``claims_json`` is stored beside the prose rather than derived from it later.
The claims are what grounding checked -- each one pinning a span of the answer
to an evidence id -- and re-extracting them afterwards would be a second,
unverified parse of the same text.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_executions", sa.Column("answer_text", sa.Text(), nullable=True))
    op.add_column("agent_executions", sa.Column("claims_json", JSONB, nullable=True))
    op.create_check_constraint(
        "ck_executions_answer_has_a_source",
        "agent_executions",
        "(answer_text IS NULL) = (response_source IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_executions_answer_has_a_source", "agent_executions")
    op.drop_column("agent_executions", "claims_json")
    op.drop_column("agent_executions", "answer_text")
