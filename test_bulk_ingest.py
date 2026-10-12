"""Tests for the bulk ingest helpers.

The layout and filtering are done by hand rather than by a library, so they get tests.
The failure mode without them is silent: a dropped row is a missing report, not an error.
"""

import io

from bulk_ingest import quarter_files, read_columns, stream_rows

HEADER = "primaryid$caseid$caseversion$i_f_code$fda_dt"


def opener(*rows):
    """A handle with a header line followed by the given data rows."""
    body = "".join(row + "\n" for row in rows)
    return io.BytesIO((HEADER + "\n" + body).encode("latin-1"))


def test_quarter_files_uses_the_two_digit_year_and_upper_quarter():
    members = quarter_files("2024q1")
    assert members["demo"] == "ASCII/DEMO24Q1.txt"
    assert members["drug"] == "ASCII/DRUG24Q1.txt"
    assert members["reac"] == "ASCII/REAC24Q1.txt"


def test_quarter_files_handles_an_upper_case_quarter():
    assert quarter_files("2024Q3")["demo"] == "ASCII/DEMO24Q3.txt"


def test_read_columns_finds_positions_from_the_header():
    # positions come from the header, not from assuming the column order
    handle = io.BytesIO((HEADER + "\n").encode("latin-1"))
    header, positions = read_columns(handle, "demo")
    assert positions == [0, 2, 4]
    assert header[0] == "primaryid"


def test_stream_rows_takes_the_wanted_fields_in_order():
    handle = opener("1$a$1$F$20240101", "2$b$1$F$20240202")
    header, positions = read_columns(handle, "demo")
    wanted = ["primaryid", "fda_dt"]
    picked = [header.index(c) for c in wanted]
    assert list(stream_rows(handle, header, picked)) == [
        ["1", "20240101"],
        ["2", "20240202"],
    ]


def test_stream_rows_skips_short_lines():
    # a truncated line must not shift the columns of everything after it
    handle = opener("1$a$1$F$20240101", "2$b", "3$c$1$F$20240303")
    header, positions = read_columns(handle, "demo")
    rows = list(stream_rows(handle, header, positions))
    assert [row[0] for row in rows] == ["1", "3"]


def test_stream_rows_keeps_only_the_requested_reports():
    handle = opener("1$a$1$F$20240101", "2$b$1$F$20240202", "3$c$1$F$20240303")
    header, positions = read_columns(handle, "demo")
    rows = list(stream_rows(handle, header, positions, keep={"1", "3"}))
    assert [row[0] for row in rows] == ["1", "3"]


def test_stream_rows_stops_at_the_limit():
    handle = opener("1$a$1$F$20240101", "2$b$1$F$20240202", "3$c$1$F$20240303")
    header, positions = read_columns(handle, "demo")
    rows = list(stream_rows(handle, header, positions, limit=2))
    assert [row[0] for row in rows] == ["1", "2"]


def test_an_empty_keep_set_yields_nothing():
    # this is what a filter against zero reports does, and it must not fall back to all
    handle = opener("1$a$1$F$20240101", "2$b$1$F$20240202")
    header, positions = read_columns(handle, "demo")
    assert list(stream_rows(handle, header, positions, keep=set())) == []
