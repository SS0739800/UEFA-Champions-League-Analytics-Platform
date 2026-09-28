import numpy as np
import pandas as pd
import pytest

from src.models.train import (
    multiclass_brier,
    multiclass_log_loss,
    predict_ordered,
    round_probabilities,
    score_predictions,
)


def test_brier_is_zero_for_perfect_predictions():
    outcomes = pd.Series(["H", "D", "A"])
    assert multiclass_brier(outcomes, np.eye(3)) == pytest.approx(0.0)


def test_brier_for_a_uniform_guess():
    outcomes = pd.Series(["H"])
    # (2/3)^2 + (1/3)^2 + (1/3)^2
    assert multiclass_brier(outcomes, np.array([[1 / 3, 1 / 3, 1 / 3]])) == pytest.approx(6 / 9)


def test_log_loss_uses_h_d_a_column_order():
    # sklearn's log_loss would read these columns as A, D, H and get this wrong.
    outcomes = pd.Series(["H"])
    assert multiclass_log_loss(outcomes, np.array([[0.7, 0.2, 0.1]])) == pytest.approx(-np.log(0.7))


def test_scores_include_the_expected_metrics():
    outcomes = pd.Series(["H", "A"])
    probabilities = np.array([[0.6, 0.3, 0.1], [0.2, 0.3, 0.5]])
    scores = score_predictions(outcomes, probabilities)
    assert scores["accuracy"] == 1.0
    assert scores["n_matches"] == 2
    assert scores["log_loss"] == pytest.approx(-(np.log(0.6) + np.log(0.5)) / 2)


def test_probabilities_come_back_in_h_d_a_order():
    class FakeModel:
        # sklearn sorts class labels alphabetically: A, D, H.
        classes_ = np.array(["A", "D", "H"])

        def predict_proba(self, frame):
            return np.array([[0.1, 0.2, 0.7]])

    assert predict_ordered(FakeModel(), None).tolist() == [[0.7, 0.2, 0.1]]


def test_rounded_probabilities_still_sum_to_one():
    predictions = pd.DataFrame({"p_home_win": [0.33333], "p_draw": [0.33333], "p_away_win": [0.33334]})
    rounded = round_probabilities(predictions)
    total = rounded[["p_home_win", "p_draw", "p_away_win"]].sum(axis=1).iloc[0]
    assert total == pytest.approx(1.0, abs=1e-9)
