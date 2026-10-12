"""Tests for the checks that stop a bad load.

These matter more than most: the failure they guard against is a load that succeeds and
writes less than it should, which leaves no error anywhere.
"""

import pytest

from bulk_ingest import (
    DRUG_PER_REPORT,
    REACTION_PER_REPORT,
    SchemaDrift,
    check_header,
    check_median,
    check_not_empty,
)

GOOD_DEMO = ["primaryid", "caseid", "caseversion", "i_f_code", "fda_dt"]
GOOD_DRUG = ["primaryid", "caseid", "drug_seq", "role_cod", "drugname"]
GOOD_REAC = ["primaryid", "caseid", "pt"]


def test_a_good_header_is_accepted():
    assert check_header(GOOD_DEMO, "demo") == [0, 2, 4]
    assert check_header(GOOD_DRUG, "drug") == [0, 4, 3]
    assert check_header(GOOD_REAC, "reac") == [0, 2]


def test_a_renamed_column_halts_the_load():
    # this is schema drift: the field was renamed, so reading on would drop the column
    renamed = ["primaryid", "caseid", "caseversion", "i_f_code", "fda_date"]
    with pytest.raises(SchemaDrift):
        check_header(renamed, "demo")


def test_the_drift_message_names_the_missing_column():
    with pytest.raises(SchemaDrift) as error:
        check_header(["primaryid"], "drug")
    assert "drugname" in str(error.value)


def test_a_completely_different_file_halts():
    with pytest.raises(SchemaDrift):
        check_header(["col1", "col2"], "reac")


def test_zero_rows_halts():
    with pytest.raises(ValueError):
        check_not_empty("demo", 0)


def test_one_row_does_not_halt():
    # not the check's job to judge small numbers, only empty
    check_not_empty("demo", 1)


def test_a_shrunken_detail_file_halts():
    # 100 reports with only one drug row each is the shape of a partial load
    with pytest.raises(ValueError) as error:
        check_median("drug", 100, 100, DRUG_PER_REPORT)
    assert "rows per report" in str(error.value)


def test_a_normal_detail_file_passes():
    # 2024q1 really does give about 4.7 drug rows and 3.6 reaction rows per report
    check_median("drug", 470000, 100000, DRUG_PER_REPORT)
    check_median("reac", 360000, 100000, REACTION_PER_REPORT)


def test_the_floor_sits_below_the_real_rate():
    # the real quarter rates are about 4.7 and 3.6, so the floors must not be above them
    assert DRUG_PER_REPORT < 4.7
    assert REACTION_PER_REPORT < 3.6


def test_no_reports_read_is_not_a_median_failure():
    # dividing by zero reports would be a different bug; this check must not mask it
    check_median("drug", 0, 0, DRUG_PER_REPORT)
