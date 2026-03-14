"""Diagnose Superset database connectivity and data pipeline issues.

Checks every link in the chain: environment → connection → schema → data → Superset.
Run from the project root:

    uv run python scripts/diagnose_superset_db.py

Or with an explicit DATABASE_URL:

    DATABASE_URL=postgresql://rfc:changeme@localhost:5433/rfc \
        uv run python scripts/diagnose_superset_db.py
"""

import os
import sys
from pathlib import Path

# Add src to path so we can import rfc modules.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------
_GREEN = "\033[92m"
_RED = "\033[91m"
_YELLOW = "\033[93m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"  {_GREEN}OK{_RESET}  {msg}")


def fail(msg: str) -> None:
    print(f"  {_RED}FAIL{_RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"  {_YELLOW}WARN{_RESET}  {msg}")


def heading(msg: str) -> None:
    print(f"\n{_BOLD}── {msg} ──{_RESET}")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_env() -> str | None:
    """Check environment variables and .env file."""
    heading("Environment")

    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        ok(f".env file exists at {env_file}")
    else:
        fail(
            f".env file missing at {env_file}\n"
            "        → Copy .env.example to .env and configure DATABASE_URL.\n"
            "        → Without .env, make targets won't have DATABASE_URL set."
        )

    url = os.getenv("DATABASE_URL")
    if url:
        # Mask password for display.
        masked = url
        if "@" in url:
            pre, rest = url.split("@", 1)
            if ":" in pre:
                scheme_user = pre.rsplit(":", 1)[0]
                masked = f"{scheme_user}:****@{rest}"
        ok(f"DATABASE_URL is set: {masked}")
    else:
        fail(
            "DATABASE_URL is not set.\n"
            "        → The DbListener and import scripts need this to write to PostgreSQL.\n"
            "        → Set it in .env or export it in your shell.\n"
            "        → Example: DATABASE_URL=postgresql://rfc:changeme@localhost:5433/rfc"
        )

    # Check docker-compose default vs superset default password mismatch.
    pg_pass = os.getenv("POSTGRES_PASSWORD")
    if pg_pass:
        ok(f"POSTGRES_PASSWORD is set (length={len(pg_pass)})")
    else:
        warn(
            "POSTGRES_PASSWORD is not set.\n"
            "        → docker-compose and superset_config.py both default to 'changeme'.\n"
            "        → Set POSTGRES_PASSWORD in .env to be explicit."
        )

    return url


def check_connection(url: str) -> bool:
    """Try connecting to the database."""
    heading("Database Connection")

    try:
        from sqlalchemy import create_engine, text
    except ImportError:
        fail("sqlalchemy not installed.\n        → Run: uv sync --extra superset")
        return False

    try:
        engine = create_engine(url, connect_args={"connect_timeout": 5})
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            ok(f"Connected to PostgreSQL: {version}")
            engine.dispose()
            return True
    except Exception as e:
        fail(
            f"Cannot connect to database: {e}\n"
            "        → Is PostgreSQL running? Try: docker compose ps\n"
            "        → Is the port correct? Host uses 5433, Docker internal uses 5432.\n"
            "        → Check: docker compose logs postgres"
        )
        return False


def check_schema(url: str) -> bool:
    """Check that RFC tables exist and have the expected schema."""
    heading("Schema")

    from sqlalchemy import create_engine, inspect

    engine = create_engine(url, connect_args={"connect_timeout": 5})
    inspector = inspect(engine)

    expected_tables = [
        "test_runs",
        "test_results",
        "models",
        "pipeline_results",
        "robot_dry_run_results",
        "keyword_results",
        "ollama_metrics",
        "host_info",
    ]

    all_tables = inspector.get_table_names()
    all_ok = True

    for table in expected_tables:
        if table in all_tables:
            ok(f"Table '{table}' exists")
        else:
            fail(f"Table '{table}' is MISSING")
            all_ok = False

    # Check for Superset metadata tables (indicates bootstrap ran).
    superset_tables = [
        t for t in all_tables if t.startswith("ab_") or t == "dashboards"
    ]
    if superset_tables:
        ok(f"Superset metadata tables found ({len(superset_tables)} tables)")
    else:
        warn(
            "No Superset metadata tables found.\n"
            "        → Has 'make bootstrap' been run?\n"
            "        → Run: docker compose run --rm superset-init"
        )

    engine.dispose()
    return all_ok


def check_data(url: str) -> None:
    """Check row counts in all RFC tables."""
    heading("Data")

    from sqlalchemy import create_engine, text

    engine = create_engine(url, connect_args={"connect_timeout": 5})

    tables = [
        "test_runs",
        "test_results",
        "models",
        "pipeline_results",
        "robot_dry_run_results",
        "keyword_results",
        "ollama_metrics",
        "host_info",
    ]

    with engine.connect() as conn:
        for table in tables:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
                count = result.scalar()
                if count and count > 0:
                    ok(f"{table}: {count} rows")
                else:
                    warn(f"{table}: 0 rows (empty)")
            except Exception as e:
                fail(f"{table}: query failed — {e}")

    engine.dispose()


def check_superset_database_connection(url: str) -> None:
    """Check if the Superset 'Database' object exists and its URI is correct."""
    heading("Superset Database Connection")

    from sqlalchemy import create_engine, text

    engine = create_engine(url, connect_args={"connect_timeout": 5})

    with engine.connect() as conn:
        # Check if Superset's dbs table exists (it stores database connections).
        try:
            result = conn.execute(
                text(
                    "SELECT id, database_name, sqlalchemy_uri "
                    "FROM dbs WHERE database_name = 'Robot Framework Results'"
                )
            )
            row = result.fetchone()
            if row:
                db_id, db_name, uri = row
                ok(f"Superset database connection exists (id={db_id})")

                # Check if the URI points to the right place.
                if "postgres:" in uri and ":5432" in uri:
                    ok(f"URI uses Docker-internal hostname: {uri}")
                elif "localhost" in uri:
                    warn(
                        f"URI uses localhost: {uri}\n"
                        "        → This works from the host but NOT from inside Docker.\n"
                        "        → Superset runs inside Docker and needs 'postgres:5432'."
                    )
                else:
                    warn(
                        f"URI: {uri} — verify this resolves correctly from Superset's container"
                    )
            else:
                fail(
                    "No 'Robot Framework Results' database connection in Superset.\n"
                    "        → Run: make bootstrap"
                )
        except Exception:
            warn(
                "Cannot query Superset's 'dbs' table.\n"
                "        → Superset metadata tables may not exist yet.\n"
                "        → Run: make bootstrap"
            )

    engine.dispose()


def check_docker() -> None:
    """Check Docker Compose status."""
    heading("Docker")

    import subprocess

    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            import json

            lines = result.stdout.strip().split("\n")
            for line in lines:
                try:
                    svc = json.loads(line)
                    name = svc.get("Service", svc.get("Name", "?"))
                    state = svc.get("State", svc.get("Status", "?"))
                    if "running" in str(state).lower():
                        ok(f"Service '{name}': {state}")
                    else:
                        warn(f"Service '{name}': {state}")
                except json.JSONDecodeError:
                    pass
        else:
            warn(
                "No Docker Compose services running.\n"
                "        → Start with: make docker-up"
            )
    except FileNotFoundError:
        warn("Docker not found on PATH")
    except subprocess.TimeoutExpired:
        warn("Docker command timed out")
    except Exception as e:
        warn(f"Docker check failed: {e}")


def _parse_db_host_port() -> tuple[str, int]:
    """Extract host and port from DATABASE_URL, DATABASE_HOST, or defaults."""
    database_url = os.getenv("DATABASE_URL", "")
    if database_url and "@" in database_url:
        # Parse host:port from postgresql://user:pass@host:port/db
        after_at = database_url.split("@", 1)[1]
        host_port_part = after_at.split("/", 1)[0]
        if ":" in host_port_part:
            host, port_str = host_port_part.rsplit(":", 1)
            return host, int(port_str)
        return host_port_part, int(os.getenv("POSTGRES_PORT", "5433"))

    host = os.getenv("DATABASE_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5433"))
    return host, port


def check_port_mapping() -> None:
    """Verify the port mapping is working."""
    heading("Port Mapping")

    import socket

    db_host, db_port = _parse_db_host_port()
    try:
        sock = socket.create_connection((db_host, db_port), timeout=3)
        sock.close()
        ok(f"{db_host}:{db_port} is accepting connections")
    except (ConnectionRefusedError, TimeoutError, OSError):
        fail(
            f"{db_host}:{db_port} is NOT reachable.\n"
            f"        → Is PostgreSQL running on {db_host}?\n"
            f"        → Check: docker compose ps postgres\n"
            f"        → Check: docker compose logs postgres"
        )

    # Check Superset port.
    superset_port = int(os.getenv("SUPERSET_PORT", "8088"))
    try:
        sock = socket.create_connection(("localhost", superset_port), timeout=3)
        sock.close()
        ok(f"localhost:{superset_port} (Superset) is accepting connections")
    except (ConnectionRefusedError, TimeoutError, OSError):
        warn(f"localhost:{superset_port} (Superset) is NOT reachable")


def main() -> None:
    print(f"{_BOLD}Superset Database Diagnostic{_RESET}")
    print("=" * 50)

    # 1. Environment
    url = check_env()

    # 2. Docker
    check_docker()

    # 3. Port mapping
    check_port_mapping()

    if not url:
        print(f"\n{_RED}Cannot continue without DATABASE_URL.{_RESET}")
        print("Set it and re-run this script.")
        sys.exit(1)

    # 4. Connection
    if not check_connection(url):
        print(f"\n{_RED}Cannot continue without database connection.{_RESET}")
        sys.exit(1)

    # 5. Schema
    check_schema(url)

    # 6. Data
    check_data(url)

    # 7. Superset Database connection object
    check_superset_database_connection(url)

    heading("Summary")
    print(
        "If tables exist but are empty, data isn't being written.\n"
        "Common causes:\n"
        "  1. DATABASE_URL not set when running 'make robot-*'\n"
        "  2. DbListener exception silently caught (check Robot output for\n"
        "     'DbListener: FAILED to archive results')\n"
        "  3. Tests using SQLite (no DATABASE_URL) instead of PostgreSQL\n"
        "\n"
        "If data exists but Superset shows nothing:\n"
        "  1. Flush Redis cache: make cache-flush\n"
        "  2. Check Superset database connection URI in SQL Lab\n"
        "  3. Re-run bootstrap: make bootstrap\n"
    )


if __name__ == "__main__":
    main()
