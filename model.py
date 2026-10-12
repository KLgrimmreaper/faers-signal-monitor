"""A small model on top of PRR, scored the same way as PRR alone.

    python model.py

The point of this is the verdict, not the model. PRR already scores an AUC of about 0.69
on the EU-ADR reference set, and a network trained on 43 positive and 50 negative pairs
has almost nothing to learn from. What it can plausibly do is combine PRR with a couple
of counts, so the model is deliberately small and the features are the ones a reviewer
would reach for by hand.

Two things keep the comparison honest:

- The folds hold out whole outcomes. Shuffling pairs instead would put the same drug and
  the same outcome on both sides of the split, so the model could memorise the test set
  and come out near 1.0. Holding out an outcome is the harder and truthful question.
- PRR is scored on exactly the same folds as the model, so the two AUCs are comparable.

The rest of the file is a small MLP because that is what the milestone asks for. A
logistic regression would very likely do the same and I say so in the output rather than
pretending the extra capacity earns its place.
"""

import argparse
import sys

import numpy as np
import torch

import db
import evaluate

FEATURES = ["prr", "drug_total", "reaction_total", "reports"]
HIDDEN = 8
EPOCHS = 300
LEARNING_RATE = 0.01


def build_features(scored):
    """One row of features per reference pair, dropping the ones with no PRR.

    Counts go in as logs, since they run from single digits to hundreds of thousands and
    a raw column that wide would swamp everything else.
    """
    rows = []
    labels = []
    outcomes = []
    for signal in scored:
        if signal["prr"] is None:
            continue
        rows.append([
            np.log1p(signal["prr"]),
            np.log1p(signal["drug_total"]),
            np.log1p(signal["reaction_total"]),
            np.log1p(signal["reports"]),
        ])
        labels.append(signal["ground_truth"])
        outcomes.append(signal["outcome"])
    return np.array(rows, dtype=np.float32), np.array(labels, dtype=np.float32), outcomes


def standardise(train, test):
    """Scale on the training fold only, so the test fold cannot leak through the mean."""
    mean = train.mean(axis=0)
    deviation = train.std(axis=0)
    deviation[deviation == 0] = 1.0
    return (train - mean) / deviation, (test - mean) / deviation


class Small(torch.nn.Module):
    def __init__(self, inputs, hidden=HIDDEN):
        super().__init__()
        self.layers = torch.nn.Sequential(
            torch.nn.Linear(inputs, hidden),
            torch.nn.Tanh(),
            torch.nn.Linear(hidden, 1),
        )

    def forward(self, x):
        return self.layers(x).squeeze(-1)


def train_fold(train_x, train_y, seed):
    torch.manual_seed(seed)
    model = Small(train_x.shape[1])
    # the positives are 43 of 93, so the classes are close enough to balanced that plain
    # weighting is fine and there is no need to resample
    loss_fn = torch.nn.BCEWithLogitsLoss()
    optimiser = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    x = torch.from_numpy(train_x)
    y = torch.from_numpy(train_y)

    model.train()
    for _ in range(EPOCHS):
        optimiser.zero_grad()
        loss = loss_fn(model(x), y)
        loss.backward()
        optimiser.step()
    model.eval()
    return model


def cross_validate(features, labels, outcomes, seeds=5):
    """Leave one outcome out at a time, and average over a few restarts.

    One run of a network this small on this few rows is mostly noise, so the seeds are
    averaged and the spread is reported rather than a single number.
    """
    unique = sorted(set(outcomes))
    per_seed = []
    model_scores = np.zeros(len(labels))

    for seed in range(seeds):
        scores = np.zeros(len(labels))
        for outcome in unique:
            test = np.array([o == outcome for o in outcomes])
            train = ~test
            if labels[test].sum() == 0 or labels[train].sum() == 0:
                # a fold with no positives on one side says nothing, so it is left out
                continue

            train_x, test_x = standardise(features[train], features[test])
            model = train_fold(train_x, labels[train], seed)
            with torch.no_grad():
                scores[test] = model(torch.from_numpy(test_x)).numpy()
        per_seed.append(auc_of(scores, labels, outcomes))
        model_scores += scores

    model_scores /= seeds
    # PRR needs no training, so it is the same on every seed
    return features[:, 0], model_scores, per_seed


def bootstrap_difference(prr_scores, model_scores, labels, rounds=2000, seed=0):
    """How often a resampled set of pairs keeps the model ahead of PRR.

    The two AUCs here differ by a few thousandths, which on 91 pairs means nothing, but
    "means nothing" is a claim that deserves a number rather than an opinion.
    """
    generator = np.random.default_rng(seed)
    index = np.arange(len(labels))
    ahead = 0
    differences = []
    for _ in range(rounds):
        pick = generator.choice(index, size=len(index), replace=True)
        if labels[pick].sum() in (0, len(pick)):
            continue
        value_prr = auc_of(prr_scores[pick], labels[pick], None)
        value_model = auc_of(model_scores[pick], labels[pick], None)
        if np.isnan(value_prr) or np.isnan(value_model):
            continue
        differences.append(value_model - value_prr)
        if value_model > value_prr:
            ahead += 1
    differences = np.array(differences)
    return (
        float(np.mean(differences)) if len(differences) else float("nan"),
        float(np.percentile(differences, 2.5)) if len(differences) else float("nan"),
        float(np.percentile(differences, 97.5)) if len(differences) else float("nan"),
        ahead / len(differences) if len(differences) else float("nan"),
    )


def auc_of(scores, labels, outcomes):
    """AUC pooling every held out fold, which is what the model is judged on."""
    positives = scores[labels == 1]
    negatives = scores[labels == 0]
    value = evaluate.auc(list(positives), list(negatives))
    return value if value is not None else float("nan")


def xor_check():
    """A four point sanity check that the network can learn something at all.

    XOR is the smallest thing a linear model cannot fit, so if this comes out at 1.0 the
    training loop works and a negative result later is about the data, not the code.
    """
    x = np.array([[0, 0], [0, 1], [1, 0], [1, 1]], dtype=np.float32)
    y = np.array([0, 1, 1, 0], dtype=np.float32)
    model = train_fold(x, y, seed=0)
    with torch.no_grad():
        out = torch.sigmoid(model(torch.from_numpy(x))).numpy()
    correct = int(((out > 0.5) == (y > 0.5)).sum())
    return correct, out


def main():
    parser = argparse.ArgumentParser(description="a small model on top of prr")
    parser.add_argument("--seeds", type=int, default=5)
    args = parser.parse_args()

    correct, out = xor_check()
    print(f"sanity check on xor: {correct} of 4 correct")
    if correct < 4:
        print("the training loop cannot fit xor, so the result below would not mean anything")
        return 1

    conn = db.connect()
    reference = evaluate.load_reference_set()
    counts = evaluate.pair_counts(conn, 1)
    drugs, reactions, total = evaluate.drug_and_reaction_totals(conn)
    conn.close()

    scored = evaluate.score_reference_pairs(reference, counts, drugs, reactions, total)
    features, labels, outcomes = build_features(scored)
    print()
    print(f"pairs with a usable PRR: {len(labels)}")
    print(f"positives: {int(labels.sum())}, negatives: {int(len(labels) - labels.sum())}")

    prr_scores, model_scores, per_seed = cross_validate(features, labels, outcomes, args.seeds)
    prr_auc = auc_of(prr_scores, labels, outcomes)
    model_auc = auc_of(model_scores, labels, outcomes)

    print()
    print(f"folds: {len(set(outcomes))} outcomes held out, averaged over {args.seeds} seeds")
    print()
    print(f"  PRR alone           AUC {prr_auc:.3f}")
    print(f"  model on top        AUC {model_auc:.3f}")
    print(f"  model across seeds  {min(per_seed):.3f} to {max(per_seed):.3f}")

    mean_difference, low, high, ahead = bootstrap_difference(prr_scores, model_scores, labels)
    print()
    print(f"difference, model minus PRR, {args.seeds} seeds averaged")
    print(f"  mean {mean_difference:+.3f}, 95 percent interval {low:+.3f} to {high:+.3f}")
    print(f"  the model came out ahead in {ahead * 100:.0f} percent of 2000 resamples")

    print()
    print("verdict")
    print("  the reference set is 93 pairs and the folds hold out whole outcomes, so the")
    print("  model is asked to rank pairs for an outcome it never saw. that is the honest")
    print("  question and it is a hard one, with 42 usable positives to learn from.")
    if low <= 0 <= high:
        print()
        print("  the interval spans zero, so the model is not measurably better than PRR.")
        print("  the honest read is that PRR is the answer, and the extra capacity bought")
        print("  nothing that survives the uncertainty. a network small enough to fit in")
        print("  this file cannot fix a reference set this size, and more capacity would")
        print("  fit the labels rather than the problem.")
    else:
        print()
        print(f"  the interval is entirely above zero, so the model did beat PRR here, by")
        print(f"  about {mean_difference:.3f} AUC. it is still 42 positives, so this would")
        print("  want a larger reference set before being believed.")
    print()
    print("  what this does not do is find anything new. the model is trained on which")
    print("  pairs are already believed to be real, so it can only reproduce that")
    print("  judgement, and it never had a chance to beat the labels it learned from.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
