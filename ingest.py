import argparse
import datetime
import os
import sys

import db
import runs
from fetch import OpenFdaError, count_reports_in_range, fetch_reports

INSERT_ROW = """
    INSERT INTO events (report_id, drug, drug_raw, reaction, serious, received_date)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (report_id, drug, reaction) DO NOTHING
"""


def build_events(report):
    report_id = report.get("safetyreportid")
    if not report_id:
        return []

    patient = report.get("patient") or {}
    drugs = [d.get("medicinalproduct") for d in patient.get("drug") or []]
    reactions = [r.get("reactionmeddrapt") for r in patient.get("reaction") or []]

    received = report.get("receivedate")
    received_date = None
    if received:
        received_date = datetime.date(int(received[:4]), int(received[4:6]), int(received[6:8]))
    serious = report.get("serious") == "1"

    # openfda doesn't say which drug goes with which reaction, so every combo in a
    # report counts. the set also collapses a drug listed twice for two indications,
    # which is right because prr counts reports, not mentions.
    rows = {
        # upper case because the same term comes back in mixed case. drug_raw keeps
        # the original. nothing else is cleaned: openfda writes an apostrophe as a
        # caret, so "STILL^S DISEASE" is what the source says
        (report_id, drug.upper(), drug, reaction.upper(), serious, received_date)
        for drug in drugs
        if drug
        for reaction in reactions
        if reaction
    }
    return list(rows)


def main():
    day = datetime.date.today()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=(day - datetime.timedelta(days=1)).strftime("%Y%m%d"))
    parser.add_argument("--until", default=day.strftime("%Y%m%d"))
    parser.add_argument("--limit", type=int, default=5000, help="stop after this many reports")
    parser.add_argument("--dry-run", action="store_true", help="fetch and build rows, write nothing")
    args = parser.parse_args()

    api_key = os.environ.get("OPENFDA_API_KEY")
    try:
        available = count_reports_in_range(args.since, args.until, api_key=api_key)
        reports = fetch_reports(args.since, args.until, args.limit, api_key=api_key)
    except OpenFdaError as exc:
        print(f"fetch failed: {exc}")
        return 1
    print(f"{len(reports):,} reports for {args.since} to {args.until}")

    # openfda pages by offset, so a capped run is the first N records it holds and
    # not a sample. don't let a partial load pass for the whole range.
    if available > len(reports):
        print(
            f"warning: {available:,} reports exist in this range but only "
            f"{len(reports):,} were ingested. openFDA returns records in a fixed "
            f"order, so this is the start of the range, not a sample of it. "
            f"Narrow the dates or raise --limit."
        )

    rows = [row for report in reports for row in build_events(report)]
    print(f"{len(rows):,} event rows")

    if args.dry_run:
        print("dry run, nothing written")
        return 0

    conn = db.connect()
    db.apply_schema(conn)
    with runs.record(conn, "api", f"{args.since}..{args.until}") as run:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM events")
            before = cur.fetchone()[0]
            cur.executemany(INSERT_ROW, rows)
            cur.execute("SELECT count(*) FROM events")
            after = cur.fetchone()[0]
        conn.commit()
        run.rows_read = len(reports)
        run.rows_new = after - before
        db.refresh_marginals(conn)
    conn.close()

    print(f"{before:,} rows in events before, {after:,} after, {after - before:,} new")
    return 0


if __name__ == "__main__":
    sys.exit(main())
