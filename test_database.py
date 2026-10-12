"""Tests that need a database: idempotency, resumability, and the statistics query.

These run against a separate database, never the one holding the loaded quarter. If no
server is reachable they skip, so the rest of the suite still runs with nothing running.
"""

import itertools

import db
from ingest import INSERT_ROW
from signals import cell_counts, compute_signals, data_summary

# unique report ids per row. reusing one would collapse every row into a single event,
# because (report_id, drug, reaction) is the primary key
counter = itertools.count()


def rows(count, drug="IBUPROFEN", reaction="NAUSEA", report=None):
    out = []
    for _ in range(count):
        report_id = report or f"r{next(counter)}"
        out.append((report_id, drug, drug, reaction, False, None))
    return out


def report_rows(count, report, drug="IBUPROFEN", reaction="NAUSEA"):
    """Several rows for the one report, which needs a different reaction or drug each."""
    return [
        (report, drug, drug, f"{reaction} {index}", False, None)
        for index in range(count)
    ]


def insert(conn, values):
    with conn.cursor() as cur:
        cur.executemany(INSERT_ROW, values)
    conn.commit()


def count(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM events")
        return cur.fetchone()[0]


def test_inserting_the_same_batch_twice_adds_nothing(clean_events):
    conn = clean_events
    batch = [("1", "IBUPROFEN", "IBUPROFEN", "NAUSEA", False, None)]
    insert(conn, batch)
    insert(conn, batch)
    assert count(conn) == 1


def test_a_partial_overlap_only_adds_the_new_rows(clean_events):
    conn = clean_events
    insert(conn, [("1", "IBUPROFEN", "IBUPROFEN", "NAUSEA", False, None)])
    insert(
        conn,
        [
            ("1", "IBUPROFEN", "IBUPROFEN", "NAUSEA", False, None),
            ("2", "ASPIRIN", "ASPIRIN", "NAUSEA", False, None),
        ],
    )
    assert count(conn) == 2


def test_a_resumed_load_does_not_duplicate_the_first_half(clean_events):
    # the shape of a resumable ingest: the first attempt dies partway, the second
    # replays from the start, and every row must end up in the table exactly once
    conn = clean_events
    whole = [
        ("1", "A", "A", "NAUSEA", False, None),
        ("2", "A", "A", "NAUSEA", False, None),
        ("3", "B", "B", "NAUSEA", False, None),
        ("4", "B", "B", "NAUSEA", False, None),
    ]
    insert(conn, whole[:3])
    assert count(conn) == 3

    insert(conn, whole)
    assert count(conn) == 4


def test_a_different_reaction_on_the_same_report_is_a_new_row(clean_events):
    conn = clean_events
    insert(conn, [("1", "IBUPROFEN", "IBUPROFEN", "NAUSEA", False, None)])
    insert(conn, [("1", "IBUPROFEN", "IBUPROFEN", "HEADACHE", False, None)])
    assert count(conn) == 2


def test_no_events_gives_no_signals(clean_events):
    assert compute_signals(clean_events) == []
    summary = data_summary(clean_events)
    assert summary["reports"] == 0
    assert summary["rows"] == 0


def test_signals_come_back_with_the_expected_cells(clean_events):
    conn = clean_events
    # 10 reports. ibuprofen in 6, nausea in 6, both in 4, so b is 2, c is 2 and d is 2
    values = []
    for index in range(4):
        values.append((f"both{index}", "IBUPROFEN", "IBUPROFEN", "NAUSEA", False, None))
    for index in range(2):
        values.append((f"drug{index}", "IBUPROFEN", "IBUPROFEN", "HEADACHE", False, None))
    for index in range(2):
        values.append((f"reac{index}", "ASPIRIN", "ASPIRIN", "NAUSEA", False, None))
    for index in range(2):
        values.append((f"neither{index}", "ASPIRIN", "ASPIRIN", "HEADACHE", False, None))
    insert(conn, values)
    db.refresh_marginals(conn)

    signals = {(s["drug"], s["reaction"]): s for s in compute_signals(conn, min_reports=1)}
    both = signals[("IBUPROFEN", "NAUSEA")]

    cells = cell_counts(4, both["drug_total"], both["reaction_total"], 10)
    assert cells == (4, 2, 2, 2)
    assert both["prr"] is not None


def test_the_min_reports_floor_is_applied(clean_events):
    conn = clean_events
    insert(conn, rows(2, reaction="RARE"))
    insert(conn, rows(5, reaction="COMMON"))
    db.refresh_marginals(conn)

    with_floor = {s["reaction"] for s in compute_signals(conn, min_reports=3)}
    assert with_floor == {"COMMON"}

    without = {s["reaction"] for s in compute_signals(conn, min_reports=1)}
    assert without == {"RARE", "COMMON"}


def test_a_pair_whose_marginals_leave_no_d_returns_no_prr(clean_events):
    conn = clean_events
    # every report is ibuprofen, so c and d cannot both be positive and prr is undefined
    insert(conn, report_rows(4, "only", reaction="NAUSEA"))
    db.refresh_marginals(conn)

    signals = {s["reaction"]: s for s in compute_signals(conn, min_reports=1)}
    assert signals["NAUSEA 0"]["prr"] is None


def test_data_summary_counts_the_reports(clean_events):
    conn = clean_events
    insert(conn, report_rows(3, "A"))
    insert(conn, report_rows(2, "B"))
    insert(conn, rows(2, drug="ASPIRIN", reaction="HEADACHE"))
    db.refresh_marginals(conn)

    summary = data_summary(conn)
    assert summary["reports"] == 4
    assert summary["rows"] == 7
