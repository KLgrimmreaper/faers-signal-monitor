"""The EU-ADR evaluation as a regression check.

Runs the whole evaluation against a committed fixture, so a change that breaks the
scoring shows up here rather than in the README numbers. No network and no real data:
the fixture is 3,060 synthetic reports and the expected figures were read off it once and
pinned below.

The numbers are not a claim about the method. They are a claim that the code still does
what it did.
"""

import pathlib

import pytest

import evaluate

FIXTURE = pathlib.Path(__file__).with_name("fixtures") / "euadr_fixture.sql"

# read from the fixture. if a change moves these, either the fixture changed or the
# evaluation did, and both are worth stopping for
EXPECTED_SCORED = 92
EXPECTED_TOTAL = 93
EXPECTED_AUC = 0.827243
EXPECTED_HITS_AT_1 = 36
EXPECTED_FALSE_ALARMS_AT_1 = 9
EXPECTED_RECALL_AT_1 = 0.8372093023255814
EXPECTED_SPECIFICITY_AT_1 = 0.8163265306122449


@pytest.fixture
def scored(postgres, clean_events):
    """Load the fixture, then score the reference set against it."""
    import db

    conn = clean_events
    with conn.cursor() as cur:
        cur.execute(FIXTURE.read_text(encoding="utf-8"))
    conn.commit()

    reference = evaluate.load_reference_set()
    counts = evaluate.pair_counts(conn, 1)
    drugs, reactions, total = evaluate.drug_and_reaction_totals(conn)
    return evaluate.score_reference_pairs(reference, counts, drugs, reactions, total)


def test_the_fixture_loads_the_expected_number_of_reports(clean_events, postgres):
    import db

    conn = clean_events
    with conn.cursor() as cur:
        cur.execute(FIXTURE.read_text(encoding="utf-8"))
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), count(DISTINCT report_id) FROM events")
        rows, reports = cur.fetchone()
    assert (rows, reports) == (3060, 3060)


def test_coverage_is_almost_complete(scored):
    usable = [s for s in scored if s["prr"] is not None]
    assert len(scored) == EXPECTED_TOTAL
    assert len(usable) == EXPECTED_SCORED


def test_every_positive_is_scoreable(scored):
    positives = [s for s in scored if s["ground_truth"] == 1 and s["prr"] is not None]
    assert len(positives) == 43


def test_the_auc_is_unchanged(scored):
    positives = [s["prr"] for s in scored if s["ground_truth"] == 1 and s["prr"] is not None]
    negatives = [s["prr"] for s in scored if s["ground_truth"] == 0 and s["prr"] is not None]
    assert evaluate.auc(positives, negatives) == pytest.approx(EXPECTED_AUC, abs=1e-6)


def test_the_threshold_table_is_unchanged(scored):
    row = evaluate.metrics(scored, 1.0)
    assert row["hits"] == EXPECTED_HITS_AT_1
    assert row["false_alarms"] == EXPECTED_FALSE_ALARMS_AT_1
    assert row["recall"] == pytest.approx(EXPECTED_RECALL_AT_1)
    assert row["specificity"] == pytest.approx(EXPECTED_SPECIFICITY_AT_1)


def test_the_ranking_beats_chance_on_the_fixture(scored):
    # the fixture is built with real enrichment in it, so an evaluation that scored
    # everything the same would come out at 0.5 and fail here
    positives = [s["prr"] for s in scored if s["ground_truth"] == 1 and s["prr"] is not None]
    negatives = [s["prr"] for s in scored if s["ground_truth"] == 0 and s["prr"] is not None]
    assert evaluate.auc(positives, negatives) > 0.7


def test_precision_at_ten_is_unchanged(scored):
    value, counted = evaluate.precision_at_k(scored, 10)
    assert counted == 10
    assert value == pytest.approx(0.7)
