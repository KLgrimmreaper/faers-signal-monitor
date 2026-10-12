"""Capture the query plan comparison and the generated report, for the images.

The pair query is run twice, once with the marginal recomputed per row and once against
the materialized view, so the before and after come from real plans rather than from a
figure copied out of an earlier session.

    python capture_plans.py
"""

import pathlib
import re
import subprocess
import sys
import time

import db

OUT = pathlib.Path(__file__).parent / "docs" / "captures"

SLOW = """
EXPLAIN (ANALYZE, BUFFERS)
WITH totals AS (
    SELECT count(DISTINCT report_id) AS reports FROM events
)
SELECT
    e.drug,
    e.reaction,
    count(DISTINCT e.report_id) AS reports_both,
    (SELECT count(DISTINCT report_id) FROM events WHERE drug = e.drug) AS drug_total,
    (SELECT count(DISTINCT report_id) FROM events WHERE reaction = e.reaction) AS reaction_total,
    (SELECT reports FROM totals) AS total_reports
FROM events e
WHERE e.drug = 'ROFECOXIB'
GROUP BY e.drug, e.reaction
"""

FAST = """
EXPLAIN (ANALYZE, BUFFERS)
SELECT
    e.drug,
    e.reaction,
    count(DISTINCT e.report_id) AS reports_both,
    dt.total AS drug_total,
    rt.total AS reaction_total,
    et.reports AS total_reports
FROM events e
JOIN drug_totals dt ON dt.drug = e.drug
JOIN reaction_totals rt ON rt.reaction = e.reaction
CROSS JOIN event_totals et
WHERE e.drug = 'ROFECOXIB'
GROUP BY e.drug, e.reaction, dt.total, rt.total, et.reports
"""

WANTED = ("Execution Time", "Index", "Seq Scan", "Bitmap", "Hash", "Nested Loop")


def run_plan(conn, sql):
    started = time.time()
    with conn.cursor() as cur:
        cur.execute(sql)
        rows = [row[0] for row in cur.fetchall()]
    return rows, time.time() - started


def block(label, rows, wall):
    kept = [line for line in rows if any(token in line for token in WANTED)]
    return [f"=== {label} ==="] + kept + [f"wall clock: {wall:.2f}s"]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    conn = db.connect()
    slow_rows, slow_wall = run_plan(conn, SLOW)
    fast_rows, fast_wall = run_plan(conn, FAST)
    conn.close()

    lines = block("before: marginal recomputed per row", slow_rows, slow_wall)
    lines.append("")
    lines += block("after: marginal from a materialized view", fast_rows, fast_wall)
    (OUT / "explain.txt").write_text("\n".join(lines), encoding="utf-8", newline="\n")

    slow = re.search(r"Execution Time: ([\d.]+) ms", "\n".join(slow_rows))
    fast = re.search(r"Execution Time: ([\d.]+) ms", "\n".join(fast_rows))
    print(f"explain: {slow.group(1)} ms -> {fast.group(1)} ms")

    result = subprocess.run([sys.executable, "report.py"], capture_output=True, text=True)
    print((result.stdout or result.stderr).strip().splitlines()[-1])
    report = pathlib.Path("report.md").read_text(encoding="utf-8")
    (OUT / "report.txt").write_text(report, encoding="utf-8", newline="\n")
    print(f"report: {len(report.splitlines())} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
