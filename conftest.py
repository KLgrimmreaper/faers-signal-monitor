"""Shared test setup.

Tests that need postgres run against a separate database, never the one holding the
loaded quarter. db.py reads the standard PG* variables, so pointing it elsewhere is a
matter of setting them before db is imported.

Everything else runs with no database at all, which is what CI mostly does.
"""

import os
import subprocess
import sys

import pytest

TEST_DB = "faers_test"

# Overridden rather than defaulted. db.py reads these, and a setdefault does nothing when
# the variable is already set, which once ran this whole suite against the real database
# and truncated it.
os.environ["PGDATABASE"] = TEST_DB
os.environ["PGUSER"] = "faers"
os.environ["PGPASSWORD"] = "faers"
os.environ["PGHOST"] = "localhost"
os.environ["PGPORT"] = "5432"


def _server_reachable():
    try:
        import psycopg

        psycopg.connect("host=localhost port=5432 user=faers password=faers dbname=postgres",
                        connect_timeout=5).close()
        return True
    except Exception:
        return False


def _test_database_exists():
    import psycopg

    conn = psycopg.connect("host=localhost port=5432 user=faers password=faers dbname=postgres")
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
        found = cur.fetchone() is not None
    conn.close()
    return found


@pytest.fixture(scope="session")
def postgres():
    """The test database, or a skip when there is no server or no test database.

    The database is not created here on purpose. Creating it needs a connection to
    another database, and a fixture that can do that is a fixture that can also wipe the
    wrong one.
    """
    if not _server_reachable():
        pytest.skip("no postgres reachable, skipping the database tests")
    if not _test_database_exists():
        pytest.skip(f"{TEST_DB} does not exist, create it with: createdb {TEST_DB}")

    import db

    conn = db.connect()
    db.apply_schema(conn)
    conn.close()
    return TEST_DB


@pytest.fixture
def clean_events(postgres):
    """An empty events table and refreshed marginals, tidied up afterwards."""
    import db

    conn = db.connect()
    connected = conn.info.dbname
    if connected != TEST_DB:
        conn.close()
        pytest.fail(f"refusing to truncate: expected {TEST_DB}, connected to {connected}")

    with conn.cursor() as cur:
        cur.execute("TRUNCATE events")
    conn.commit()
    db.refresh_marginals(conn)
    yield conn
    with conn.cursor() as cur:
        cur.execute("TRUNCATE events")
    conn.commit()
    conn.close()
