import os
import pathlib

import psycopg

DEFAULTS = {
    "host": "localhost",
    "port": "5432",
    "user": "faers",
    "password": "faers",
    "dbname": "faers",
}


def connect():
    # defaults match docker-compose.yml. PG* env vars win if they are set
    settings = {
        key: os.environ.get("PG" + key.upper(), value)
        for key, value in DEFAULTS.items()
    }
    return psycopg.connect(**settings)


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
