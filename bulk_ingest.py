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

DOWNLOAD = "https://fis.fda.gov/content/Exports/faers_ascii_{quarter}.zip"

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


def read_columns(handle, columns):
    header = handle.readline().decode("latin-1").rstrip("\r\n").split("$")
    positions = [header.index(column) for column in columns]
    print(f"  columns {columns} at {positions}")
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


def main():
    parser = argparse.ArgumentParser(description="load a quarterly faers extract")
    parser.add_argument("--quarter", default="2024q1")
    parser.add_argument("--limit", type=int, default=0, help="reports to load, 0 for all")
    parser.add_argument("--data", default="data", help="folder holding the zip")
    parser.add_argument("--replace", action="store_true", help="clear events first")
    args = parser.parse_args()

    folder = pathlib.Path(args.data)
    folder.mkdir(exist_ok=True)
    archive_path = download(args.quarter.lower(), folder)
    members = quarter_files(args.quarter.lower())

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
    with zipfile.ZipFile(archive_path) as archive:
        print("building staging tables")
        with conn.cursor() as cur:
            cur.execute(STAGING)
        conn.commit()

        print("demo")
        with archive.open(members["demo"]) as handle:
            header, positions = read_columns(handle, ["primaryid", "caseversion", "fda_dt"])
            demo_rows = list(stream_rows(handle, header, positions, args.limit))
        copy_stream(conn, "COPY stage_demo (primaryid, caseversion, fda_dt) FROM STDIN", demo_rows)
        conn.commit()
        # DEMO has to be held in memory because the detail files are filtered against it.
        # At a quarter of reports that is a few hundred thousand ids, which is fine.
        keep = {row[0] for row in demo_rows}
        del demo_rows
        print(f"  {len(keep):,} reports staged in {time.time() - started:.1f}s")

        print("drug")
        step = time.time()
        with archive.open(members["drug"]) as handle:
            header, positions = read_columns(handle, ["primaryid", "drugname", "role_cod"])
            copy_stream(
                conn,
                "COPY stage_drug (primaryid, drugname, role_cod) FROM STDIN",
                stream_rows(handle, header, positions, keep=keep),
            )
        conn.commit()
        print(f"  drug rows copied in {time.time() - step:.1f}s")

        print("reaction")
        step = time.time()
        with archive.open(members["reac"]) as handle:
            header, positions = read_columns(handle, ["primaryid", "pt"])
            copy_stream(
                conn,
                "COPY stage_reac (primaryid, pt) FROM STDIN",
                stream_rows(handle, header, positions, keep=keep),
            )
        conn.commit()
        print(f"  reaction rows copied in {time.time() - step:.1f}s")

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

        with conn.cursor() as cur:
            cur.execute("SELECT count(*), count(DISTINCT report_id) FROM events")
            after, reports = cur.fetchone()

    print("refreshing the marginals")
    db.refresh_marginals(conn)

    conn.close()
    print()
    print(f"rows added: {added:,}")
    print(f"events now: {after:,} rows for {reports:,} reports")
    print(f"total time: {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
