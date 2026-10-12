"""Tests for the model's data handling and training loop.

The AUC on the reference set is in the README, not here: it depends on the loaded
quarter and would make CI meaningless either way. What is worth testing is that the
features are built correctly, that scaling does not leak, and that the training loop can
actually fit something.
"""

import numpy as np
import pytest

from model import build_features, standardise, train_fold, xor_check


def signal(prr, ground_truth, drug_total=100, reaction_total=200, reports=10):
    return {
        "drug": "D",
        "outcome": "O" + str(ground_truth),
        "ground_truth": ground_truth,
        "reports": reports,
        "drug_total": drug_total,
        "reaction_total": reaction_total,
        "prr": prr,
        "term": "T",
    }


def test_pairs_without_a_prr_are_dropped():
    features, labels, outcomes = build_features([signal(2.0, 1), signal(None, 0)])
    assert len(labels) == 1
    assert labels[0] == 1


def test_the_features_are_logs_of_the_four_values():
    # float32, because torch wants that, so compare with a tolerance
    features, _, _ = build_features([signal(2.0, 1, drug_total=100, reaction_total=200, reports=10)])
    assert features[0][0] == pytest.approx(np.log1p(2.0), rel=1e-6)
    assert features[0][1] == pytest.approx(np.log1p(100), rel=1e-6)
    assert features[0][2] == pytest.approx(np.log1p(200), rel=1e-6)
    assert features[0][3] == pytest.approx(np.log1p(10), rel=1e-6)


def test_labels_and_outcomes_line_up_with_the_features():
    features, labels, outcomes = build_features([signal(2.0, 1), signal(3.0, 0)])
    assert len(features) == len(labels) == len(outcomes) == 2
    assert list(labels) == [1, 0]


def test_standardise_uses_the_training_fold_only():
    # if the test row influenced the mean the two would differ, which is the leak this
    # is here to prevent
    train = np.array([[0.0], [2.0]], dtype=np.float32)
    test = np.array([[100.0]], dtype=np.float32)
    scaled_train, scaled_test = standardise(train, test)
    assert scaled_train.mean() == 0
    assert scaled_test[0][0] > 10


def test_standardise_survives_a_constant_column():
    # a column with no spread would divide by zero and hand the model NaNs
    train = np.array([[1.0, 5.0], [1.0, 7.0]], dtype=np.float32)
    test = np.array([[1.0, 6.0]], dtype=np.float32)
    scaled_train, scaled_test = standardise(train, test)
    assert np.isfinite(scaled_train).all()
    assert np.isfinite(scaled_test).all()


def test_the_training_loop_can_fit_xor():
    # the smallest thing a linear model cannot fit. if this fails, a low score on the
    # reference set would be the code rather than the data
    correct, _ = xor_check()
    assert correct == 4


def test_training_is_deterministic_for_a_seed():
    x = np.array([[0, 0], [0, 1], [1, 0], [1, 1]], dtype=np.float32)
    y = np.array([0, 1, 1, 0], dtype=np.float32)
    import torch

    first = train_fold(x, y, seed=1)
    second = train_fold(x, y, seed=1)
    with torch.no_grad():
        a = first(torch.from_numpy(x)).numpy()
        b = second(torch.from_numpy(x)).numpy()
    assert np.allclose(a, b)


def test_the_model_outputs_one_score_per_row():
    import torch

    x = np.array([[0, 0], [0, 1], [1, 0]], dtype=np.float32)
    y = np.array([0, 1, 1], dtype=np.float32)
    model = train_fold(x, y, seed=0)
    with torch.no_grad():
        out = model(torch.from_numpy(x)).numpy()
    assert out.shape == (3,)
