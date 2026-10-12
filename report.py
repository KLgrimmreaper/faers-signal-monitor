import argparse
import datetime
import sys

import db
from signals import MIN_REPORTS, compute_signals, data_summary

# openfda sends an apostrophe in a meddra term as a caret. swap it back for reading
DISPLAY_FIXES = {"^": "'"}


def readable(term):
    for stored, shown in DISPLAY_FIXES.items():
        term = term.replace(stored, shown)
    return term


def ranked(signals):
    usable = [s for s in signals if s["prr"] is not None]
    usable.sort(key=lambda s: s["prr"], reverse=True)
    return usable


def build_markdown(signals, summary, min_reports, top, generated):
    ranked_signals = ranked(signals)
    shown = ranked_signals[:top]

    lines = [
        "# drug and reaction pairs by prr",
        "",
        f"generated {generated} from the local events table",
        "",
        f"- reports in the table: {summary['reports']:,}",
        f"- event rows: {summary['rows']:,}",
        f"- received dates: {summary['first_date']} to {summary['last_date']}",
        f"- pairs with at least {min_reports} reports: {len(signals):,}",
        f"- of those, pairs where prr is defined: {len(ranked_signals):,}",
        "",
        "reports are voluntary, and a widely prescribed or publicised drug gets more of",
        "them regardless of risk. these numbers compare reporting rates, not incidence.",
        "a high prr is not evidence that a drug causes a reaction, and a pair near the",
        "top is worth a human looking at and nothing more.",
        "",
    ]

    if summary["first_date"] == summary["last_date"]:
        lines += [
            "the table holds a single day, so prr and ror here are inflated by small",
            "counts and are not findings.",
            "",
        ]

    lines += [
        f"## top {len(shown)} pairs",
        "",
        "| # | drug | reaction | reports | drug total | prr | ror |",
        "|---|---|---|---|---|---|---|",
    ]

    for position, signal in enumerate(shown, 1):
        ror = signal["ror"]
        ror_text = "n/a" if ror is None else f"{ror:,.2f}"
        lines.append(
            f"| {position} | {readable(signal['drug'])} | {readable(signal['reaction'])} "
            f"| {signal['reports_both']:,} | {signal['drug_total']:,} "
            f"| {signal['prr']:,.2f} | {ror_text} |"
        )

    # sorting on raw prr puts the smallest numerators on top, so the table needs this
    # next to it rather than in a caption somewhere else
    lines += [
        "",
        "the largest ratios are the ones with the fewest reports behind them. the top row",
        "here is a ratio computed from a numerator in single figures, which is why the",
        "numbers run into the hundreds of thousands. this is a property of ranking on raw",
        "prr and not a finding, and a seriousness filter or a higher report floor would",
        "push these down.",
    ]

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="write the ranked pairs to markdown")
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--min-reports", type=int, default=MIN_REPORTS)
    parser.add_argument("--out", default="report.md")
    args = parser.parse_args()

    conn = db.connect()
    signals = compute_signals(conn, args.min_reports)
    summary = data_summary(conn)
    conn.close()

    generated = datetime.date.today().isoformat()
    markdown = build_markdown(signals, summary, args.min_reports, args.top, generated)

    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(markdown)

    print(f"{len(signals):,} pairs with at least {args.min_reports} reports")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
