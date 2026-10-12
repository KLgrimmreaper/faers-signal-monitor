import argparse
import csv
import pathlib
import sys

import db

REFERENCE_SET = pathlib.Path(__file__).with_name("fixtures") / "euadr_reference_set.csv"

# the reference set names omop cohorts as outcomes, not meddra terms, so each one needs
# the reaction terms that stand for it
OUTCOME_TERMS = {
    "Anaphylaxis #1": [
        "ANAPHYLACTIC SHOCK", "ANAPHYLACTIC REACTION", "ANAPHYLAXIS", "ANAPHYLACTOID REACTION",
    ],
    "Cardiac Valve Fibrosis #1": [
        "CARDIAC VALVE FIBROSIS", "CARDIAC VALVE DISEASE", "CARDIAC VALVE INCOMPETENCE",
        "CARDIAC VALVE STENOSIS", "VALVULAR HEART DISEASE",
    ],
    "HOI Upper GI #3": [
        "GASTROINTESTINAL HAEMORRHAGE", "GASTROINTESTINAL HEMORRHAGE", "MELAENA",
        "HAEMATEMESIS", "GASTRIC ULCER", "GASTRIC ULCER HAEMORRHAGE", "PEPTIC ULCER",
        "DUODENAL ULCER", "GASTRIC HAEMORRHAGE", "UPPER GASTROINTESTINAL HAEMORRHAGE",
    ],
    "Leukopenia Including Neutropenia and Agranulocytosis": [
        "LEUKOPENIA", "NEUTROPENIA", "AGRANULOCYTOSIS", "PANCYTOPENIA",
        "WHITE BLOOD CELL COUNT DECREASED", "GRANULOCYTOPENIA", "FEBRILE NEUTROPENIA",
    ],
    "OMOP Acute Liver Failure 1": [
        "ACUTE HEPATIC FAILURE", "ACUTE LIVER FAILURE", "HEPATIC FAILURE", "LIVER FAILURE",
        "HEPATOTOXICITY", "HEPATIC NECROSIS", "ACUTE HEPATIC FAILURE ",
    ],
    "OMOP Acute Renal Failure 1": [
        "ACUTE KIDNEY INJURY", "ACUTE RENAL FAILURE", "RENAL FAILURE", "RENAL IMPAIRMENT",
        "KIDNEY INJURY", "RENAL INJURY", "OLIGURIA",
    ],
    "OMOP Acute myocardial Infarction  1": [
        "MYOCARDIAL INFARCTION", "ACUTE MYOCARDIAL INFARCTION", "MYOCARDIAL INFARCT",
    ],
    "OMOP Aplastic Anemia 1": [
        "APLASTIC ANAEMIA", "APLASTIC ANEMIA", "BONE MARROW FAILURE", "PANCYTOPENIA",
        "BONE MARROW DEPRESSION", "APLASIA",
    ],
    "Rhabdomyolysis #1": [
        "RHABDOMYOLYSIS", "MYOGLOBINURIA", "BLOOD CREATINE PHOSPHOKINASE INCREASED",
        "MUSCLE NECROSIS", "MYOPATHY",
    ],
    "Stevens-Johnson Syndrome #1": [
        "STEVENS-JOHNSON SYNDROME", "STEVENS JOHNSON SYNDROME", "TOXIC EPIDERMAL NECROLYSIS",
        "ERYTHEMA MULTIFORME",
    ],
}


def load_reference_set(path=REFERENCE_SET):
    with open(path, encoding="utf-8") as handle:
        records = list(csv.DictReader(handle))
    for record in records:
        record["groundTruth"] = int(record["groundTruth"])
    return records


def pair_counts(conn, min_reports=1):
    with conn.cursor() as cur:
        cur.execute(
            """SELECT drug, reaction, count(DISTINCT report_id)
               FROM events
               GROUP BY drug, reaction
               HAVING count(DISTINCT report_id) >= %s""",
            (min_reports,),
        )
        return {(drug, reaction): count for drug, reaction, count in cur.fetchall()}


def prr_for_counts(a, drug_total, reaction_total, total_reports):
    b = drug_total - a
    c = reaction_total - a
    d = total_reports - a - b - c
    if b <= 0 or c <= 0 or d <= 0:
        return None
    return (a / (a + b)) / (c / (c + d))


def drug_and_reaction_totals(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT drug, count(DISTINCT report_id) FROM events GROUP BY drug")
        drugs = dict(cur.fetchall())
        cur.execute("SELECT reaction, count(DISTINCT report_id) FROM events GROUP BY reaction")
        reactions = dict(cur.fetchall())
        cur.execute("SELECT count(DISTINCT report_id) FROM events")
        total = cur.fetchone()[0]
    return drugs, reactions, total


def score_reference_pairs(reference, counts, drugs, reactions, total):
    # a pair takes its highest matching term. no prr means the data can't support the
    # pair, which is not the same as a low score
    scored = []
    for record in reference:
        terms = OUTCOME_TERMS.get(record["outcomeName"], [])
        exposure = record["exposureName"].upper()
        drug_total = drugs.get(exposure)

        best = None
        matched_term = None
        best_reports = 0
        best_reaction_total = 0
        if drug_total:
            for term in terms:
                reaction_total = reactions.get(term)
                if not reaction_total:
                    continue
                a = counts.get((exposure, term), 0)
                value = prr_for_counts(a, drug_total, reaction_total, total)
                if value is not None and (best is None or value > best):
                    best = value
                    matched_term = term
                    best_reports = a
                    best_reaction_total = reaction_total

        scored.append(
            {
                "drug": record["exposureName"],
                "outcome": record["outcomeName"],
                "ground_truth": record["groundTruth"],
                "reports": best_reports,
                "drug_total": drug_total or 0,
                "reaction_total": best_reaction_total,
                "prr": best,
                "term": matched_term,
            }
        )
    return scored


def auc(positive_scores, negative_scores):
    # same as the wilcoxon statistic pROC uses, ties count a half, so it stays
    # comparable with the ohdsi package
    if not positive_scores or not negative_scores:
        return None
    wins = 0.0
    for value in positive_scores:
        for other in negative_scores:
            if value > other:
                wins += 1
            elif value == other:
                wins += 0.5
    return wins / (len(positive_scores) * len(negative_scores))


def metrics(scored, threshold):
    # pairs with no prr are counted as missing, not as negatives. calling them
    # negatives would push specificity up for free
    scored_pairs = [s for s in scored if s["prr"] is not None]
    missing = [s for s in scored if s["prr"] is None]
    positives = [s for s in scored_pairs if s["ground_truth"] == 1]
    negatives = [s for s in scored_pairs if s["ground_truth"] == 0]

    hits = [s for s in positives if s["prr"] >= threshold]
    false_alarms = [s for s in negatives if s["prr"] >= threshold]

    recall = len(hits) / len(positives) if positives else None
    specificity = 1 - len(false_alarms) / len(negatives) if negatives else None
    flagged = len(hits) + len(false_alarms)
    precision = len(hits) / flagged if flagged else None

    return {
        "threshold": threshold,
        "positives_scored": len(positives),
        "negatives_scored": len(negatives),
        "missing": len(missing),
        "hits": len(hits),
        "false_alarms": len(false_alarms),
        "recall": recall,
        "specificity": specificity,
        "precision": precision,
    }


def precision_at_k(scored, k):
    ranked = sorted(
        (s for s in scored if s["prr"] is not None),
        key=lambda s: s["prr"],
        reverse=True,
    )[:k]
    if not ranked:
        return None, 0
    return sum(1 for s in ranked if s["ground_truth"] == 1) / len(ranked), len(ranked)


def report(scored, thresholds):
    print(f"reference pairs: {len(scored)}")
    positives = [s for s in scored if s["ground_truth"] == 1]
    negatives = [s for s in scored if s["ground_truth"] == 0]
    print(f"  {len(positives)} positive, {len(negatives)} negative")

    scored_any = [s for s in scored if s["prr"] is not None]
    print()
    print(f"coverage: {len(scored_any)} of {len(scored)} pairs scored, "
          f"{len(scored) - len(scored_any)} missing")
    for label, group in (("positive", positives), ("negative", negatives)):
        present = [s for s in group if s["prr"] is not None]
        print(f"  {label}: {len(present)} of {len(group)}")

    print()
    if not scored_any:
        print("no pair in the reference set could be scored, so there are no metrics.")
        print("This is expected until the bulk files are loaded: the events table holds")
        print("one day of reports, and a drug withdrawn in 2004 is not in it.")
        return

    positive_scores = [s["prr"] for s in positives if s["prr"] is not None]
    negative_scores = [s["prr"] for s in negatives if s["prr"] is not None]
    value = auc(positive_scores, negative_scores)
    print(f"AUC: {'n/a' if value is None else f'{value:.3f}'}"
          f"   (from {len(positive_scores)} positives and {len(negative_scores)} negatives)")
    print()
    print("threshold   recall   specificity   precision   hits   false alarms")
    for threshold in thresholds:
        row = metrics(scored, threshold)
        recall = "n/a" if row["recall"] is None else f"{row['recall']:.2f}"
        specificity = "n/a" if row["specificity"] is None else f"{row['specificity']:.2f}"
        precision = "n/a" if row["precision"] is None else f"{row['precision']:.2f}"
        print(f"{threshold:>9.2f}   {recall:>6}   {specificity:>11}   "
              f"{precision:>9}   {row['hits']:>4}   {row['false_alarms']:>12}")

    print()
    for k in (10, 20):
        value, counted = precision_at_k(scored, k)
        if value is None:
            print(f"precision@{k}: no pairs to rank")
        else:
            print(f"precision@{k}: {value:.2f} from the top {counted}")


def main():
    parser = argparse.ArgumentParser(description="score the ranking against eu-adr")
    parser.add_argument("--min-reports", type=int, default=1)
    args = parser.parse_args()

    reference = load_reference_set()
    conn = db.connect()
    counts = pair_counts(conn, args.min_reports)
    drugs, reactions, total = drug_and_reaction_totals(conn)
    conn.close()

    scored = score_reference_pairs(reference, counts, drugs, reactions, total)
    report(scored, [1.0, 1.5, 2.0, 3.0, 5.0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
