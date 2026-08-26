"""Load data/seed/seed.sql into DATABASE_URL.

Kept separate from the generator: generating the fixture is deterministic and
offline, loading it needs a database. Conflating the two would make the
generator untestable without Postgres.
"""

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

SEED_SQL = ROOT / "data" / "seed" / "seed.sql"


async def load() -> int:
    if not SEED_SQL.exists():
        print("seed.sql is missing -- run `task.py seed` first", file=sys.stderr)
        return 1
    url = os.environ.get("DATABASE_URL")
    if not url:
        from config.settings import get_settings

        url = get_settings().database_url

    statements = SEED_SQL.read_text(encoding="utf-8")
    engine = create_async_engine(url, echo=False)
    async with engine.begin() as connection:
        await connection.execute(text("SET session_replication_role = 'replica'"))
        for statement in _split(statements):
            await connection.execute(text(statement))
    await engine.dispose()
    print(f"loaded {SEED_SQL.relative_to(ROOT).as_posix()}")
    return 0


def _split(script: str) -> list[str]:
    """Split on semicolons at end of line, skipping comments and BEGIN/COMMIT.

    The engine already runs the whole load in one transaction, so the script's
    own BEGIN/COMMIT would nest and be rejected.
    """
    statements: list[str] = []
    buffer: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if stripped in {"BEGIN;", "COMMIT;"}:
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statements.append("\n".join(buffer).rstrip().rstrip(";"))
            buffer = []
    return statements


if __name__ == "__main__":
    raise SystemExit(asyncio.run(load()))
