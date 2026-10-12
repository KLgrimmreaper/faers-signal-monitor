import argparse
import sys

import db

# anything seen once or twice is noise
MIN_REPORTS = 3

PAIR_COUNTS = """
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
    GROUP BY e.drug, e.reaction
    HAVING count(DISTINCT e.report_id) >= %s
    ORDER BY e.drug, e.reaction
"""


def cell_counts(reports_both, drug_total, reaction_total, total_reports):
    a = reports_both
    b = drug_total - a
    c = reaction_total - a
    d = total_reports - a - b - c
    return a, b, c, d


def prr(a, b, c, d):
    # a zero cell makes the ratio meaningless rather than infinite
    if b == 0 or c == 0 or d == 0:
        return None
    return (a / (a + b)) / (c / (c + d))


def ror(a, b, c, d):
    if b == 0 or c == 0 or d == 0:
        return None
    return (a * d) / (b * c)


def compute_signals(conn, min_reports=MIN_REPORTS):
    with conn.cursor() as cur:
        cur.execute(PAIR_COUNTS, (min_reports,))
        rows = cur.fetchall()

    signals = []
    for drug, reaction, reports_both, drug_total, reaction_total, total_reports in rows:
        a, b, c, d = cell_counts(reports_both, drug_total, reaction_total, total_reports)
        signals.append(
            {
                "drug": drug,
                "reaction": reaction,
                "reports_both": a,
                "drug_total": drug_total,
                "reaction_total": reaction_total,
                "prr": prr(a, b, c, d),
                "ror": ror(a, b, c, d),
            }
        )
    return signals


def data_summary(conn):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT count(DISTINCT report_id), count(*), min(received_date), max(received_date)
               FROM events"""
        )
        reports, rows, first, last = cur.fetchone()
    return {"reports": reports, "rows": rows, "first_date": first, "last_date": last}


def main():
    parser = argparse.ArgumentParser(description="prr and ror per drug and reaction pair")
    parser.add_argument("--min-reports", type=int, default=MIN_REPORTS)
    args = parser.parse_args()

    conn = db.connect()
    signals = compute_signals(conn, args.min_reports)
    conn.close()

    print(f"{len(signals):,} pairs with at least {args.min_reports} reports")
    ranked = [s for s in signals if s["prr"] is not None]
    ranked.sort(key=lambda s: s["prr"], reverse=True)
    for signal in ranked[:20]:
        print(f"  {signal['prr']:6.2f}  {signal['drug'][:30]:30}  {signal['reaction'][:34]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
