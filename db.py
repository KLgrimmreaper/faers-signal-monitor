import os
import pathlib
from urllib.parse import quote

import psycopg

DEFAULTS = {
    "host": "localhost",
    "port": "5432",
    "user": "faers",
    "password": "faers",
    "dbname": "faers",
}

# libpq calls the variable PGDATABASE, not PGDBNAME, so the obvious PG + key.upper()
# is wrong for this one and silently leaves the default in place
ENV_VARS = {
    "host": "PGHOST",
    "port": "PGPORT",
    "user": "PGUSER",
    "password": "PGPASSWORD",
    "dbname": "PGDATABASE",
}


def connect():
    # Built as a connection string on purpose. Passing dbname as a keyword does not
    # survive PGDATABASE being set: libpq lets the variable win, so the argument is
    # ignored and the wrong database opens
    settings = {
        key: os.environ.get(ENV_VARS[key], value)
        for key, value in DEFAULTS.items()
    }
    conninfo = " ".join(
        f"{key}={quote(str(value), safe='')}" for key, value in settings.items()
    )
    return psycopg.connect(conninfo)


def apply_schema(conn):
    sql = pathlib.Path(__file__).with_name("schema.sql").read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def refresh_marginals(conn):
    """Rebuild the three materialized views. Needed after any load."""
    with conn.cursor() as cur:
        cur.execute("REFRESH MATERIALIZED VIEW drug_totals")
        cur.execute("REFRESH MATERIALIZED VIEW reaction_totals")
        cur.execute("REFRESH MATERIALIZED VIEW event_totals")
    conn.commit()
