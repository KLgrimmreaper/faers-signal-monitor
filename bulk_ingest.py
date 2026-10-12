"""Load the quarterly FAERS ASCII files into the events table.

    python bulk_ingest.py --quarter 2024q1

DEMO holds one row per report, DRUG one row per drug on a report and REAC one per
reaction, all linked by primaryid. The three files are streamed out of the zip and into
the events table through COPY, with postgres doing the join at the end because the join
is tens of millions of rows and holding that in python would not work.

A report's drugs and reactions are cross joined, which is the same assumption the rest of
the project makes: FAERS does not record which drug caused which reaction.
"""

import argparse
import pathlib
import sys
import time
import urllib.request
import zipfile

import db
import runs

DOWNLOAD = "https://fis.fda.gov/content/Exports/faers_ascii_{quarter}.zip"

# A quarter of 2024q1 gives about 4.7 drug rows and 3.6 reaction rows per report. These
# floors sit well under that: they are there to catch a file that loaded but contributed
# almost nothing, not to police normal variation between quarters.
DRUG_PER_REPORT = 3.0
REACTION_PER_REPORT = 2.0

STAGING = """
    DROP TABLE IF EXISTS stage_demo;
    DROP TABLE IF EXISTS stage_drug;
    DROP TABLE IF EXISTS stage_reac;

    CREATE UNLOGGED TABLE stage_demo (
        primaryid TEXT,
        caseversion TEXT,
        fda_dt TEXT
    );
    CREATE UNLOGGED TABLE stage_drug (
        primaryid TEXT,
        drugname TEXT,
        role_cod TEXT
    );
    CREATE UNLOGGED TABLE stage_reac (
        primaryid TEXT,
        pt TEXT
    );
"""

INDEXES = """
    CREATE INDEX stage_demo_id ON stage_demo (primaryid);
    CREATE INDEX stage_drug_id ON stage_drug (primaryid);
    CREATE INDEX stage_reac_id ON stage_reac (primaryid);
    ANALYZE stage_demo;
    ANALYZE stage_drug;
    ANALYZE stage_reac;
"""

MERGE = """
    INSERT INTO events (report_id, drug, drug_raw, reaction, serious, received_date)
    SELECT DISTINCT
        d.primaryid,
        upper(btrim(g.drugname)),
        btrim(g.drugname),
        upper(btrim(r.pt)),
        NULL::boolean,
        to_date(nullif(d.fda_dt, ''), 'YYYYMMDD')
    FROM stage_demo d
    JOIN stage_drug g ON g.primaryid = d.primaryid
    JOIN stage_reac r ON r.primaryid = d.primaryid
    WHERE btrim(g.drugname) <> '' AND btrim(r.pt) <> ''
    ON CONFLICT (report_id, drug, reaction) DO NOTHING
"""


def quarter_files(quarter):
    year, q = quarter[:4], quarter[4:]
    prefix = f"{year[2:]}{q.upper()}"
    return {
        "demo": f"ASCII/DEMO{prefix}.txt",
        "drug": f"ASCII/DRUG{prefix}.txt",
        "reac": f"ASCII/REAC{prefix}.txt",
    }


def download(quarter, folder):
    target = folder / f"faers_ascii_{quarter}.zip"
    if target.exists():
        print(f"{target.name} already here, {target.stat().st_size:,} bytes")
        return target
    print(f"downloading {DOWNLOAD.format(quarter=quarter)}")
    request = urllib.request.Request(DOWNLOAD.format(quarter=quarter),
                                     headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=1800) as response:
        target.write_bytes(response.read())
    print(f"  {target.stat().st_size:,} bytes")
    return target


class SchemaDrift(Exception):
    """A file no longer has the columns this loader expects."""


# the load halts on these rather than guessing. the fda has changed the extract before,
# and a rename would silently drop a field instead of failing
EXPECTED = {
    "demo": ["primaryid", "caseversion", "fda_dt"],
    "drug": ["primaryid", "drugname", "role_cod"],
    "reac": ["primaryid", "pt"],
}


def check_header(header, label):
    missing = [column for column in EXPECTED[label] if column not in header]
    if missing:
        raise SchemaDrift(
            f"{label} is missing {missing}. the file has {header}. "
            f"stopping rather than loading a partial record"
        )
    return [header.index(column) for column in EXPECTED[label]]


def check_not_empty(label, rows):
    if rows == 0:
        raise ValueError(
            f"{label} produced 0 rows. that is the shape of a silent failure, "
            f"so the load stops instead of writing a partial one"
        )


def check_median(label, rows, read, ceiling):
    """Halt when a file yields far fewer rows per report than it should.

    The failure this catches: a file loads, reports are written, but the detail file
    contributed almost nothing, so the statistics are quietly computed on a fraction of
    the reactions. A silent shrink is worse than a crash.
    """
    if read == 0:
        return
    rate = rows / read
    if rate < ceiling:
        raise ValueError(
            f"{label} gave {rate:.1f} rows per report, under the {ceiling} expected. "
            f"{rows:,} rows for {read:,} reports. stopping rather than loading a partial"
        )
    print(f"  {label}: {rate:.1f} rows per report")


def read_columns(handle, label):
    header = handle.readline().decode("latin-1").rstrip("\r\n").split("$")
    positions = check_header(header, label)
    print(f"  {label}: columns {EXPECTED[label]} at {positions}")
    return header, positions


def stream_rows(handle, header, positions, limit=0, keep=None):
    """Yield the wanted fields from each line.

    keep is a set of primaryids. Filtering here rather than with a DELETE afterwards
    matters: the detail files are far bigger than the report list, and a SQL NOT IN
    against several hundred thousand ids is a nested scan that never finishes.
    """
    read = 0
    for raw in handle:
        if limit and read >= limit:
            break
        fields = raw.decode("latin-1").rstrip("\r\n").split("$")
        if len(fields) < len(header):
            continue
        if keep is not None and fields[0] not in keep:
            continue
        read += 1
        yield [fields[position] for position in positions]


def copy_stream(conn, statement, rows):
    with conn.cursor() as cur:
        with cur.copy(statement) as copy:
            for row in rows:
                copy.write_row(row)


def count_and_copy(conn, statement, rows):
    """Copy a stream and return how many rows went through."""
    copied = 0
    with conn.cursor() as cur:
        with cur.copy(statement) as copy:
            for row in rows:
                copy.write_row(row)
                copied += 1
    return copied


def load(conn, archive, members, limit):
    """Stage, join and return (reports, rows_added). Raises rather than half loading."""
    print("building staging tables")
    with conn.cursor() as cur:
        cur.execute(STAGING)
    conn.commit()

    print("demo")
    with archive.open(members["demo"]) as handle:
        header, positions = read_columns(handle, "demo")
        demo_rows = list(stream_rows(handle, header, positions, limit))
    check_not_empty("demo", len(demo_rows))
    copy_stream(conn, "COPY stage_demo (primaryid, caseversion, fda_dt) FROM STDIN", demo_rows)
    conn.commit()
    # DEMO has to be held in memory because the detail files are filtered against it.
    # At a quarter of reports that is a few hundred thousand ids, which is fine.
    keep = {row[0] for row in demo_rows}
    del demo_rows
    reports = len(keep)
    print(f"  {reports:,} reports staged")

    print("drug")
    step = time.time()
    with archive.open(members["drug"]) as handle:
        header, positions = read_columns(handle, "drug")
        drug_rows = count_and_copy(
            conn,
            "COPY stage_drug (primaryid, drugname, role_cod) FROM STDIN",
            stream_rows(handle, header, positions, keep=keep),
        )
    check_not_empty("drug", drug_rows)
    check_median("drug", drug_rows, reports, DRUG_PER_REPORT)
    print(f"  copied in {time.time() - step:.1f}s")

    print("reaction")
    step = time.time()
    with archive.open(members["reac"]) as handle:
        header, positions = read_columns(handle, "reac")
        reaction_rows = count_and_copy(
            conn,
            "COPY stage_reac (primaryid, pt) FROM STDIN",
            stream_rows(handle, header, positions, keep=keep),
        )
    check_not_empty("reac", reaction_rows)
    check_median("reac", reaction_rows, reports, REACTION_PER_REPORT)
    print(f"  copied in {time.time() - step:.1f}s")

    print("indexing staging tables")
    step = time.time()
    with conn.cursor() as cur:
        cur.execute(INDEXES)
    conn.commit()
    print(f"  indexed in {time.time() - step:.1f}s")

    print("joining")
    step = time.time()
    with conn.cursor() as cur:
        cur.execute(MERGE)
        added = cur.rowcount
    conn.commit()
    print(f"  joined in {time.time() - step:.1f}s")

    return reports, added


def main():
    parser = argparse.ArgumentParser(description="load a quarterly faers extract")
    parser.add_argument("--quarter", default="2024q1")
    parser.add_argument("--limit", type=int, default=0, help="reports to load, 0 for all")
    parser.add_argument("--data", default="data", help="folder holding the zip")
    parser.add_argument("--replace", action="store_true", help="clear events first")
    args = parser.parse_args()

    quarter = args.quarter.lower()
    folder = pathlib.Path(args.data)
    folder.mkdir(exist_ok=True)
    archive_path = download(quarter, folder)
    members = quarter_files(quarter)

    conn = db.connect()
    db.apply_schema(conn)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM events")
        before = cur.fetchone()[0]
        if args.replace:
            cur.execute("TRUNCATE events")
            conn.commit()
    print(f"events before: {before:,}")

    started = time.time()
    # the run row is written first and closed either way, so a failure is recorded
    with runs.record(conn, "bulk", quarter) as run:
        with zipfile.ZipFile(archive_path) as archive:
            reports, added = load(conn, archive, members, args.limit)
        run.rows_read = reports
        run.rows_new = added

        print("refreshing the marginals")
        db.refresh_marginals(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT count(*), count(DISTINCT report_id) FROM events")
            after, total_reports = cur.fetchone()

    conn.close()
    print()
    print(f"rows added: {added:,}")
    print(f"events now: {after:,} rows for {total_reports:,} reports")
    print(f"total time: {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
