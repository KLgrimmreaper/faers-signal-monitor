"""Tests for the openfda report to event row conversion, and the empty fetch check."""

import datetime

import pytest

from ingest import build_events, check_fetch


def report(primaryid="1", drugs=("IBUPROFEN",), reactions=("NAUSEA",), **extra):
    body = {
        "safetyreportid": primaryid,
        "receivedate": extra.pop("receivedate", "20240101"),
        "serious": extra.pop("serious", "1"),
        "patient": {
            "drug": [{"medicinalproduct": name} for name in drugs],
            "reaction": [{"reactionmeddrapt": name} for name in reactions],
        },
    }
    body.update(extra)
    return body


def test_one_drug_and_one_reaction_gives_one_row():
    rows = build_events(report())
    assert len(rows) == 1
    assert rows[0][:4] == ("1", "IBUPROFEN", "IBUPROFEN", "NAUSEA")


def test_names_are_uppercased_and_the_raw_name_is_kept():
    rows = build_events(report(drugs=("Ibuprofen",), reactions=("Nausea",)))
    assert rows[0][1] == "IBUPROFEN"
    assert rows[0][2] == "Ibuprofen"
    assert rows[0][3] == "NAUSEA"


def test_every_drug_and_reaction_combo_becomes_a_row():
    # openfda does not say which drug caused which reaction, so all of them count
    rows = build_events(report(drugs=("A", "B"), reactions=("X", "Y")))
    assert len(rows) == 4
    assert {row[1] for row in rows} == {"A", "B"}
    assert {row[3] for row in rows} == {"X", "Y"}


def test_a_repeated_drug_collapses_to_one_row_per_reaction():
    # a drug listed twice, once per indication, is still one drug on the report
    rows = build_events(report(drugs=("REPATHA", "REPATHA"), reactions=("X",)))
    assert len(rows) == 1


def test_the_received_date_is_parsed():
    rows = build_events(report(receivedate="20240229"))
    assert rows[0][5] == datetime.date(2024, 2, 29)


def test_a_missing_received_date_is_allowed():
    rows = build_events(report(receivedate=""))
    assert rows[0][5] is None


def test_serious_is_a_boolean():
    assert build_events(report(serious="1"))[0][4] is True
    assert build_events(report(serious="2"))[0][4] is False


def test_a_report_without_an_id_is_skipped():
    body = report()
    del body["safetyreportid"]
    assert build_events(body) == []


def test_a_report_without_a_patient_is_skipped():
    assert build_events({"safetyreportid": "1"}) == []


def test_blank_drug_or_reaction_names_are_dropped():
    body = report(drugs=("", "A"), reactions=("X",))
    rows = build_events(body)
    assert len(rows) == 1
    assert rows[0][1] == "A"


def test_check_fetch_stops_when_reports_exist_but_none_came_back():
    # the failure this is for: the api says the range has data and then hands over none
    with pytest.raises(ValueError) as error:
        check_fetch(5000, [])
    assert "returned no records" in str(error.value)


def test_check_fetch_allows_a_genuinely_empty_range():
    # nothing available and nothing returned is a real answer, not a failure
    check_fetch(0, [])


def test_check_fetch_allows_a_partial_fetch():
    # short of the range is a warning elsewhere, not a halt
    check_fetch(5000, [{"safetyreportid": "1"}])
