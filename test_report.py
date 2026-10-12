from report import build_markdown, ranked, readable

SUMMARY = {
    "reports": 1508,
    "rows": 26032,
    "first_date": "2024-01-01",
    "last_date": "2024-01-01",
}


def signal(drug, reaction, reports_both, prr, ror=None):
    return {
        "drug": drug,
        "reaction": reaction,
        "reports_both": reports_both,
        "drug_total": reports_both + 5,
        "reaction_total": reports_both + 8,
        "prr": prr,
        "ror": ror,
    }


def test_ranked_puts_the_highest_prr_first():
    signals = [signal("A", "X", 3, 2.0), signal("B", "Y", 4, 9.0), signal("C", "Z", 5, 5.0)]
    assert [s["drug"] for s in ranked(signals)] == ["B", "C", "A"]


def test_ranked_drops_pairs_with_no_defined_prr():
    signals = [signal("A", "X", 3, 2.0), signal("B", "Y", 4, None)]
    assert [s["drug"] for s in ranked(signals)] == ["A"]


def test_readable_turns_a_caret_into_an_apostrophe():
    # openFDA stores "STILL^S DISEASE" for Still's disease.
    assert readable("STILL^S DISEASE") == "STILL'S DISEASE"


def test_readable_leaves_ordinary_terms_alone():
    assert readable("NAUSEA") == "NAUSEA"


def test_the_table_has_one_row_per_pair_up_to_top():
    signals = [signal(f"DRUG{i}", f"REACTION{i}", 3, 100.0 - i) for i in range(10)]
    markdown = build_markdown(signals, SUMMARY, 3, 4, "2026-01-01")
    table_rows = [line for line in markdown.splitlines() if line.startswith("| ") and line[2].isdigit()]
    assert len(table_rows) == 4
    assert "| 1 | DRUG0 |" in table_rows[0]


def test_the_report_states_what_it_is_not():
    markdown = build_markdown([signal("A", "X", 3, 2.0)], SUMMARY, 3, 50, "2026-01-01")
    assert "not evidence that a drug causes a" in markdown
    assert "worth a human looking at" in markdown


def test_a_single_day_gets_an_extra_warning():
    markdown = build_markdown([signal("A", "X", 3, 2.0)], SUMMARY, 3, 50, "2026-01-01")
    assert "holds a single day" in markdown


def test_a_wider_range_does_not_get_the_single_day_warning():
    wider = dict(SUMMARY, last_date="2024-06-30")
    markdown = build_markdown([signal("A", "X", 3, 2.0)], wider, 3, 50, "2026-01-01")
    assert "holds a single day" not in markdown


def test_the_header_reports_what_was_used():
    signals = [signal("A", "X", 3, 2.0), signal("B", "Y", 4, None)]
    markdown = build_markdown(signals, SUMMARY, 3, 50, "2026-01-01")
    assert "reports in the table: 1,508" in markdown
    assert "pairs with at least 3 reports: 2" in markdown
    assert "pairs where prr is defined: 1" in markdown


def test_a_missing_ror_is_shown_as_not_available():
    markdown = build_markdown([signal("A", "X", 3, 2.0, ror=None)], SUMMARY, 3, 50, "2026-01-01")
    assert "| n/a |" in markdown
