"""The single implementation of every project command.

Everything runs **inside Docker**. Nothing is installed on the host -- no venv,
no global pip. When this script is invoked on the host it re-invokes itself
inside the ``tools`` container; when it is already inside a container
(``RAZORMIND_IN_CONTAINER=1``, set in the Dockerfile) it runs the step directly.

So these three are the same thing:

    make check
    python scripts/task.py check
    docker compose run --rm tools scripts/task.py check

Usage:  python scripts/task.py <target> [<target> ...]
        python scripts/task.py --list
"""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "apps" / "api" / "src"

IN_CONTAINER = os.environ.get("RAZORMIND_IN_CONTAINER") == "1"

#: Targets that manage containers and therefore must run on the host.
HOST_ONLY = {"build", "up", "down", "dev", "web", "psql", "shell"}


def _run(*args: str) -> int:
    """Run a Python subcommand in this interpreter, with the API importable."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(SRC), env.get("PYTHONPATH", "")]))
    print(f"\n$ python {' '.join(args)}", flush=True)
    return subprocess.call([sys.executable, *args], cwd=str(ROOT), env=env)


def _console(*args: str) -> int:
    """Run an installed console script, with the API importable."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(SRC), env.get("PYTHONPATH", "")]))
    print(f"\n$ {' '.join(args)}", flush=True)
    return subprocess.call(list(args), cwd=str(ROOT), env=env)


def _compose(*args: str) -> int:
    """Run a docker compose command on the host."""
    print(f"\n$ docker compose {' '.join(args)}", flush=True)
    return subprocess.call(["docker", "compose", *args], cwd=str(ROOT))


#: Targets that need Postgres, and so run in the api service (which is on the
#: compose network and waits for the database to be healthy) rather than in
#: the standalone tools container.
NEEDS_DATABASE = {
    "migrate",
    "loadseed",
    "reconcile",
    "revenue",
    "diagnose",
    "verify",
    "ask",
    "dbtest",
}


#: Targets that take free-form arguments rather than being a bare verb. Every
#: other target is a name and nothing else, which is what lets `task.py check
#: test` mean "run both".
TAKES_ARGUMENTS = {"ask"}


def _in_tools(target: str, *args: str) -> int:
    """Run one target inside a container."""
    if target in NEEDS_DATABASE:
        return _compose(
            "run",
            "--rm",
            "--build",
            "--entrypoint",
            "python",
            "api",
            "scripts/task.py",
            target,
            *args,
        )
    return _compose("run", "--rm", "--build", "tools", "scripts/task.py", target, *args)


# --------------------------------------------------------------------------
# container targets (host only)
# --------------------------------------------------------------------------


def build() -> int:
    """Build the API image. This is where every download happens."""
    return _compose("build", "api")


def up() -> int:
    """Start Postgres, the API and the web app."""
    return _compose("up", "-d", "db", "api", "web")


def down() -> int:
    """Stop everything. Add --volumes by hand to also drop the database."""
    return _compose("down")


def dev() -> int:
    """Run the API in the foreground with reload. Single worker -- see D-12."""
    return _compose("up", "--build", "db", "api")


def web() -> int:
    """Run the Next.js dev server in the foreground."""
    return _compose("up", "--build", "web")


def psql() -> int:
    """Open psql against the local database container."""
    return _compose("exec", "db", "psql", "-U", "razormind", "-d", "razormind")


def shell() -> int:
    """Interactive shell inside the toolchain container."""
    return _compose("run", "--rm", "--build", "--entrypoint", "bash", "tools")


# --------------------------------------------------------------------------
# checks (run inside the container)
# --------------------------------------------------------------------------


def lint() -> int:
    """ruff: lint and format check."""
    return _run("-m", "ruff", "check", ".") or _run("-m", "ruff", "format", "--check", ".")


def fmt() -> int:
    """ruff: apply formatting and safe fixes."""
    return _run("-m", "ruff", "check", "--fix", ".") or _run("-m", "ruff", "format", ".")


def types() -> int:
    """mypy --strict."""
    return _run("-m", "mypy")


def boundaries() -> int:
    """import-linter: the trust boundary contracts in .importlinter."""
    # The console script, not `python -m importlinter.cli`: that module has no
    # __main__ guard, so it exits 0 without evaluating a single contract.
    # tests/test_boundaries.py is what caught it.
    return _console("lint-imports")


def nofloat() -> int:
    """The C-01 money guard: no float, no rounding outside runtime/money.py."""
    return _run("scripts/check_no_float.py")


def seed() -> int:
    """Regenerate the fixture: both CSVs, seed.sql, expectations and checksums."""
    return _run("data/seed/generate_seed_data.py")


def verify_seed() -> int:
    """The ten fixture assertions. Runs before anything trusts the data."""
    return _run("scripts/verify_seed.py")


def migrate() -> int:
    """Apply migrations to DATABASE_URL."""
    return _console("alembic", "upgrade", "head")


def loadseed() -> int:
    """Apply migrations, then load seed.sql into the database."""
    code = migrate()
    if code != 0:
        return code
    return _run("scripts/load_seed.py")


def reconcile() -> int:
    """Reconcile the golden window against the database and persist the run."""
    return _run("scripts/reconcile.py")


def revenue() -> int:
    """The golden revenue bridge, through finance.reconciliation then finance.revenue_analysis."""
    return _run("scripts/revenue.py")


def diagnose() -> int:
    """Every v1 tool over the golden window, plus the cross-tool equivalences."""
    return _run("scripts/diagnose.py")


def verify() -> int:
    """Every v1 tool, then the five verification layers, then the provenance walk."""
    return _run("scripts/verify.py")


def ask(*args: str) -> int:
    """One question through the whole agent runtime: intent, plan, DAG, verification."""
    return _run("scripts/ask.py", *args)


def test() -> int:
    """pytest with branch coverage on runtime/, which must stay at 100%."""
    return _run("-m", "pytest", "--cov", "--cov-report=term-missing")


def dbtest() -> int:
    """The integration tests that need a live Postgres (row-level security)."""
    return _run("-m", "pytest", "-m", "db", "--no-cov", "-q")


def check() -> int:
    """Everything CI runs, in CI's order. The Phase 0 exit criterion."""
    for step in (lint, types, boundaries, nofloat, verify_seed, test):
        code = step()
        if code != 0:
            print(f"\n>>> {step.__name__} FAILED (exit {code})", file=sys.stderr)
            return code
    print("\n>>> check OK")
    return 0


TARGETS: dict[str, Callable[[], int]] = {
    "build": build,
    "up": up,
    "down": down,
    "dev": dev,
    "web": web,
    "psql": psql,
    "shell": shell,
    "lint": lint,
    "fmt": fmt,
    "types": types,
    "boundaries": boundaries,
    "nofloat": nofloat,
    "seed": seed,
    "verify-seed": verify_seed,
    "migrate": migrate,
    "loadseed": loadseed,
    "reconcile": reconcile,
    "revenue": revenue,
    "diagnose": diagnose,
    "verify": verify,
    "ask": ask,
    "dbtest": dbtest,
    "test": test,
    "check": check,
}


def _usage() -> int:
    print(__doc__)
    print("Targets:")
    width = max(len(name) for name in TARGETS)
    for name, fn in TARGETS.items():
        summary = (fn.__doc__ or "").strip().splitlines()[0]
        where = "host " if name in HOST_ONLY else "docker"
        print(f"  {name.ljust(width)}  [{where}]  {summary}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "--list"}:
        return _usage()

    # A target that takes arguments consumes the rest of the line. Checking
    # this before the unknown-target scan is what stops a question being read
    # as a list of targets nobody registered.
    if argv[0] in TAKES_ARGUMENTS:
        target, arguments = argv[0], argv[1:]
        if IN_CONTAINER:
            return TARGETS[target](*arguments)
        return _in_tools(target, *arguments)

    unknown = [name for name in argv if name not in TARGETS]
    if unknown:
        print(f"unknown target(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    if IN_CONTAINER:
        host_only = [name for name in argv if name in HOST_ONLY]
        if host_only:
            print(
                f"target(s) {', '.join(host_only)} manage containers and cannot run inside one",
                file=sys.stderr,
            )
            return 2
        for name in argv:
            code = TARGETS[name]()
            if code != 0:
                return code
        return 0

    # On the host: container targets run here, everything else is delegated
    # into the toolchain container so that no dependency touches the host.
    for name in argv:
        code = TARGETS[name]() if name in HOST_ONLY else _in_tools(name)
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
