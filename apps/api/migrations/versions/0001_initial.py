"""Initial schema and row-level security.

Revision ID: 0001
Revises:
Create Date: Phase 1

This first revision builds the tables from ``runtime/schema.py`` directly, so
that the schema has exactly one definition rather than a definition and a
transcription of it that can drift. Every *later* revision is written as
explicit ``op`` calls -- from here on the metadata describes where we are
going and the migrations describe how we got there.
"""

from collections.abc import Sequence

from alembic import op

from runtime.schema import MERCHANT_SCOPED_TABLES, METADATA

revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


# The identity a policy is evaluated against.
#
# On Supabase this function is redefined as `SELECT auth.uid()`. Locally it
# reads a session GUC that the connection sets after authenticating. Keeping
# the indirection in one function means the policies below are byte-identical
# in both environments -- the thing that would otherwise be tested locally and
# different in production is exactly the thing you cannot afford to guess at.
CURRENT_USER_FN = """
CREATE OR REPLACE FUNCTION razormind_current_user_id() RETURNS uuid AS $fn$
    SELECT NULLIF(current_setting('razormind.user_id', true), '')::uuid;
$fn$ LANGUAGE sql STABLE;
"""

# The application connects as this role. It is deliberately *not* the owner of
# the tables: a table owner is exempt from row-level security by default, so
# running the API as the owner would leave the policies below decorative.
APP_ROLE = "razormind_app"

CREATE_APP_ROLE = f"""
DO $do$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        CREATE ROLE {APP_ROLE} NOLOGIN;
    END IF;
END
$do$;
"""


def upgrade() -> None:
    bind = op.get_bind()
    METADATA.create_all(bind=bind)

    op.execute(CURRENT_USER_FN)
    op.execute(CREATE_APP_ROLE)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE};")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};")

    # merchant_members is readable by the app role but not merchant-scoped
    # itself: every policy below joins through it, so a policy on it would be
    # circular. A user can therefore see which merchants exist in their own
    # membership rows and nothing else, because that is all the table holds.
    for table in MERCHANT_SCOPED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_merchant_isolation ON {table}
            USING (
                merchant_id IN (
                    SELECT merchant_id FROM merchant_members
                    WHERE user_id = razormind_current_user_id()
                )
            );
            """
        )

    op.execute("ALTER TABLE merchant_members ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY merchant_members_self ON merchant_members
        USING (user_id = razormind_current_user_id());
        """
    )


def downgrade() -> None:
    for table in (*MERCHANT_SCOPED_TABLES, "merchant_members"):
        suffix = "self" if table == "merchant_members" else "merchant_isolation"
        op.execute(f"DROP POLICY IF EXISTS {table}_{suffix} ON {table};")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP FUNCTION IF EXISTS razormind_current_user_id();")
    METADATA.drop_all(bind=op.get_bind())
