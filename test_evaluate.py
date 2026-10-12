import csv
import pathlib

import pytest

from evaluate import (
    auc,
    load_reference_set,
    metrics,
    precision_at_k,
    prr_for_counts,
)

REFERENCE_SET = pathlib.Path(__file__).with_name("fixtures") / "euadr_reference_set.csv"


def test_reference_set_is_the_published_size():
    records = load_reference_set()
    positives = [r for r in records if r["groundTruth"] == 1]
    negatives = [r for r in records if r["groundTruth"] == 0]
    assert len(records) == 93
    assert len(positives) == 43
    assert len(negatives) == 50


def test_reference_set_covers_ten_outcomes():
    records = load_reference_set()
    assert len({r["outcomeName"] for r in records}) == 10


def test_nimesulide_is_not_in_the_reference_set():
    # dropped because it is not in rxnorm, which is why there are 43 not 44
    records = load_reference_set()
    assert not any("nimesulide" in r["exposureName"].lower() for r in records)


def test_reference_set_columns():
    with open(REFERENCE_SET, encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    assert header == ["exposureName", "outcomeName", "groundTruth", "indicationName", "comparatorName"]


def test_prr_from_cells_matches_a_hand_calculation():
    # drug_total=100 -> b=90. reaction_total=50 -> c=40. 1000 reports -> d=860
    # (10/100) / (40/900) = 2.25
    assert prr_for_counts(10, 100, 50, 1000) == pytest.approx(2.25)


def test_prr_is_none_when_the_drug_covers_every_report():
    # every report has the drug, so the ratio has no finite value
    assert prr_for_counts(10, 1000, 50, 1000) is None


def test_auc_of_perfect_separation():
    assert auc([3.0, 4.0], [1.0, 2.0]) == pytest.approx(1.0)


def test_auc_of_reversed_separation():
    assert auc([1.0, 2.0], [3.0, 4.0]) == pytest.approx(0.0)


def test_auc_counts_ties_as_a_half():
    # one pair at equal scores: (0 + 0.5) / 1
    assert auc([2.0], [2.0]) == pytest.approx(0.5)


def test_auc_counts_some_ties():
    # positives {2, 4} against negatives {2, 3}
    # 0.5 + 0 + 1 + 1 = 2.5, over 4 pairs
    assert auc([2.0, 4.0], [2.0, 3.0]) == pytest.approx(0.625)


def test_auc_is_none_without_both_groups():
    assert auc([], [1.0]) is None
    assert auc([1.0], []) is None


def scored(prr, ground_truth):
    return {
        "drug": "D",
        "outcome": "O",
        "ground_truth": ground_truth,
        "reports": 5,
        "prr": prr,
        "term": "T",
    }


# 5 positives at 10.0 and 2 negatives at 3.0
FIVE_AND_TWO = [scored(10.0, 1) for _ in range(5)] + [scored(3.0, 0) for _ in range(2)]


def test_recall_and_specificity_at_a_threshold():
    row = metrics(FIVE_AND_TWO, 10.0)
    assert row["positives_scored"] == 5
    assert row["negatives_scored"] == 2
    assert row["hits"] == 5
    assert row["recall"] == pytest.approx(1.0)
    assert row["false_alarms"] == 0
    assert row["specificity"] == pytest.approx(1.0)
    assert row["precision"] == pytest.approx(1.0)


def test_a_threshold_below_the_negatives_catches_them():
    row = metrics(FIVE_AND_TWO, 2.0)
    assert row["hits"] == 5
    assert row["false_alarms"] == 2
    assert row["specificity"] == pytest.approx(0.0)
    assert row["precision"] == pytest.approx(5 / 7)


def test_missing_pairs_are_counted_separately_not_as_negatives():
    rows = FIVE_AND_TWO + [scored(None, 0), scored(None, 1)]
    row = metrics(rows, 10.0)
    assert row["missing"] == 2
    assert row["positives_scored"] == 5
    assert row["negatives_scored"] == 2
    assert row["specificity"] == pytest.approx(1.0)


def test_metrics_without_negatives_gives_no_specificity():
    row = metrics([scored(10.0, 1)], 10.0)
    assert row["specificity"] is None
    assert row["recall"] == pytest.approx(1.0)


def test_precision_at_k_takes_the_highest_first():
    # ranked by prr the top 3 are all positives
    rows = [
        scored(10.0, 1), scored(9.0, 1), scored(8.0, 1),
        scored(7.0, 0), scored(6.0, 0), scored(5.0, 0), scored(4.0, 0),
    ]
    value, counted = precision_at_k(rows, 3)
    assert counted == 3
    assert value == pytest.approx(1.0)

    value, counted = precision_at_k(rows, 7)
    assert counted == 7
    assert value == pytest.approx(3 / 7)


def test_precision_at_k_ignores_pairs_without_a_prr():
    rows = [scored(10.0, 1), scored(None, 1)]
    value, counted = precision_at_k(rows, 5)
    assert counted == 1
    assert value == pytest.approx(1.0)


def test_precision_at_k_with_nothing_to_rank():
    value, counted = precision_at_k([scored(None, 1)], 5)
    assert value is None
    assert counted == 0
