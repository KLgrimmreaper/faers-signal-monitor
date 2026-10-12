"""Publish the computed signals to the hosted database.

    python publish.py --dry-run
    python publish.py --top 1000

Only the signals go to the cloud. The events table stays local, because a year of reports
does not fit in a free tier and the signal table does.

The row is keyed on the run date and the pair, so publishing twice on the same day
replaces that day's rows rather than duplicating them.
"""

import argparse
import datetime
import pathlib
import sys

import db
from signals import MIN_REPORTS, compute_signals, data_summary

BATCH = 1000

# a quarter of reports. the point is to catch a table holding a day or two, which is what
# a fresh runner has, not to be a precise figure
MIN_POPULATION = 100000

INSERT = """
    INSERT INTO signals (run_date, drug, reaction, reports_both, prr, ror,
                         drug_total, reaction_total, total_reports)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (run_date, drug, reaction) DO UPDATE SET
        reports_both = EXCLUDED.reports_both,
        prr = EXCLUDED.prr,
        ror = EXCLUDED.ror,
        drug_total = EXCLUDED.drug_total,
        reaction_total = EXCLUDED.reaction_total,
        total_reports = EXCLUDED.total_reports
"""


def select_top(signals, top):
    """The highest PRR pairs, since a free tier holds a few thousand rows not half a million."""
    usable = [s for s in signals if s["prr"] is not None]
    usable.sort(key=lambda s: s["prr"], reverse=True)
    return usable[:top] if top else usable


def rows_for(signals, summary, run_date):
    return [
        (
            run_date,
            s["drug"],
            s["reaction"],
            s["reports_both"],
            s["prr"],
            s["ror"],
            s["drug_total"],
            s["reaction_total"],
            summary["reports"],
        )
        for s in signals
    ]


def apply_schema(conn):
    sql = pathlib.Path(__file__).with_name("signals_schema.sql").read_text()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()


def publish(conn, rows, run_date):
    """Write the rows in batches. Returns how many went through."""
    written = 0
    with conn.cursor() as cur:
        for start in range(0, len(rows), BATCH):
            cur.executemany(INSERT, rows[start:start + BATCH])
            written += len(rows[start:start + BATCH])
    conn.commit()
    return written


def main():
    parser = argparse.ArgumentParser(description="publish the signals to the cloud database")
    parser.add_argument("--top", type=int, default=1000, help="rows to publish, 0 for all")
    parser.add_argument("--min-reports", type=int, default=MIN_REPORTS)
    parser.add_argument("--dry-run", action="store_true", help="compute but write nothing")
    parser.add_argument(
        "--require-full",
        action="store_true",
        help="refuse to publish unless the local table holds a real population",
    )
    args = parser.parse_args()

    local = db.connect()
    signals = compute_signals(local, args.min_reports)
    summary = data_summary(local)
    local.close()

    # a disproportionality statistic computed from a day of reports is not a
    # disproportionality statistic. a runner starts with an empty database, so without
    # this a scheduled job would happily publish nonsense for a whole quarter
    if args.require_full and summary["reports"] < MIN_POPULATION:
        print(f"refusing to publish: {summary['reports']:,} reports loaded, "
              f"under the {MIN_POPULATION:,} a real population needs")
        print("load the quarterly files first, see bulk_ingest.py")
        return 1

    selected = select_top(signals, args.top)
    run_date = datetime.date.today()
    print(f"{len(signals):,} pairs with at least {args.min_reports} reports")
    print(f"{len(selected):,} selected to publish for {run_date}")

    rows = rows_for(selected, summary, run_date)

    if args.dry_run:
        print("dry run, nothing published")
        for row in rows[:5]:
            print("   ", row)
        return 0

    cloud = db.connect_cloud()
    apply_schema(cloud)
    written = publish(cloud, rows, run_date)

    with cloud.cursor() as cur:
        cur.execute("SELECT count(*) FROM signals")
        total = cur.fetchone()[0]
    cloud.close()

    print(f"published {written:,} rows")
    print(f"signals table now holds {total:,} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
