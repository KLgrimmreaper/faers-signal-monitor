import pytest

from signals import cell_counts, prr, ror


def test_prr_matches_a_hand_calculation():
    # (10/100) / (40/1000) = 0.1 / 0.04 = 2.5
    assert prr(10, 90, 40, 960) == pytest.approx(2.5)


def test_ror_matches_a_hand_calculation():
    # (10 * 960) / (90 * 40) = 9600 / 3600
    assert ror(10, 90, 40, 960) == pytest.approx(2.6666666, rel=1e-6)


def test_prr_of_one_when_the_rates_match():
    assert prr(10, 90, 50, 450) == pytest.approx(1.0)


def test_ror_of_one_when_the_odds_match():
    assert ror(10, 90, 50, 450) == pytest.approx(1.0)


@pytest.mark.parametrize("empty", ["b", "c", "d"])
def test_a_zero_cell_gives_none_rather_than_infinity(empty):
    cells = {"a": 10, "b": 90, "c": 40, "d": 960}
    cells[empty] = 0
    assert prr(cells["a"], cells["b"], cells["c"], cells["d"]) is None
    assert ror(cells["a"], cells["b"], cells["c"], cells["d"]) is None


def test_zero_a_is_a_real_zero_not_an_error():
    # no reports mention both, so the rate is 0 and the ratio is 0
    assert prr(0, 100, 40, 960) == pytest.approx(0.0)
    assert ror(0, 100, 40, 960) == pytest.approx(0.0)


def test_cell_counts_from_a_worked_example():
    # 1000 reports, drug in 120, reaction in 50, both in 10
    assert cell_counts(10, 120, 50, 1000) == (10, 110, 40, 840)


def test_cell_counts_add_up_to_the_total():
    # if this fails the four cells are not a partition of the reports and every
    # statistic built on them is wrong
    for args in [(10, 120, 50, 1000), (3, 5, 900, 1000), (50, 91, 60, 1508)]:
        a, b, c, d = cell_counts(*args)
        assert a + b + c + d == args[3]
        assert b == args[1] - a
        assert c == args[2] - a


def test_d_is_the_bulk_of_the_reports_in_practice():
    # a real pair covers a small part of the data, so d should be large
    a, b, c, d = cell_counts(50, 91, 60, 1508)
    assert (a, b, c, d) == (50, 41, 10, 1407)
    assert d > a + b + c
