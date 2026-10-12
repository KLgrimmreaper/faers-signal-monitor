"""Tests for the publish step.

The cloud write itself needs a hosted database, so what is testable here is the
selection and the refusal to publish a population that is too small to mean anything.
"""

import pytest

from publish import MIN_POPULATION, rows_for, select_top

SUMMARY = {"reports": 406184}


def signal(drug, reaction, prr, reports_both=10):
    return {
        "drug": drug,
        "reaction": reaction,
        "reports_both": reports_both,
        "drug_total": 100,
        "reaction_total": 200,
        "prr": prr,
        "ror": 1.5,
    }


def test_select_top_takes_the_highest_prr_first():
    signals = [signal("A", "X", 2.0), signal("B", "Y", 9.0), signal("C", "Z", 5.0)]
    assert [s["drug"] for s in select_top(signals, 2)] == ["B", "C"]


def test_select_top_drops_pairs_with_no_prr():
    # an undefined ratio cannot be ranked, so it is not published
    signals = [signal("A", "X", 2.0), signal("B", "Y", None)]
    assert [s["drug"] for s in select_top(signals, 10)] == ["A"]


def test_select_top_with_zero_means_everything_rankable():
    signals = [signal("A", "X", 2.0), signal("B", "Y", 3.0)]
    assert len(select_top(signals, 0)) == 2


def test_rows_for_carries_the_run_date_and_the_population():
    rows = rows_for([signal("A", "X", 2.0, reports_both=7)], SUMMARY, "2024-05-01")
    assert rows == [("2024-05-01", "A", "X", 7, 2.0, 1.5, 100, 200, 406184)]


def test_the_population_column_comes_from_the_summary_not_the_pair():
    # total_reports is the whole table, so it must not be taken from the pair's counts
    row = rows_for([signal("A", "X", 2.0)], {"reports": 999}, "2024-05-01")[0]
    assert row[-1] == 999


def test_the_population_floor_is_above_a_day_of_reports():
    # a fresh runner holds a day or two, which is what this is meant to catch
    assert MIN_POPULATION > 10000


def test_nothing_is_selected_when_every_pair_is_undefined():
    assert select_top([signal("A", "X", None)], 10) == []
