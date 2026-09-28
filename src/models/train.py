"""
Train and evaluate the match outcome models, then write Elo ratings,
predictions and evaluation scores to the database.

Validation is walk-forward by season: to test on 2019-20, train on every season
before it. Matches are never shuffled across time.

The target is the result after 90 minutes (home win / draw / away win), so
extra time and penalties don't count.
"""

import logging

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.features.elo import calculate_elo
from src.features.match_features import FEATURE_COLUMNS, OUTCOMES, build_match_features

log = logging.getLogger(__name__)

# 2012-13 is only used to warm up Elo and form, since every club starts cold.
FIRST_TRAINING_SEASON = 2013
# Test on each season from here on, training only on what came before.
FIRST_TEST_SEASON = 2016


def make_models() -> dict:
    """The models we compare. Kept deliberately small; there are only ~2,000 matches."""
    return {
        "Base rates": DummyClassifier(strategy="prior"),
        "Elo only": make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)),
        "Logistic regression": make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.5, max_iter=1000)
        ),
        "Random forest": make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(n_estimators=300, min_samples_leaf=25, max_features=0.5, random_state=7),
        ),
        "Gradient boosting": HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=30, random_state=7
        ),
    }


def model_features(model_name: str) -> list[str]:
    return ["elo_diff", "is_neutral_venue"] if model_name == "Elo only" else FEATURE_COLUMNS


def predict_ordered(model, frame: pd.DataFrame) -> np.ndarray:
    """Predicted probabilities with columns always in H, D, A order."""
    probabilities = model.predict_proba(frame)
    order = [list(model.classes_).index(outcome) for outcome in OUTCOMES]
    return probabilities[:, order]


def multiclass_brier(outcomes: pd.Series, probabilities: np.ndarray) -> float:
    """Mean squared error across all three outcomes (0 is perfect, 2 is the worst possible)."""
    actual = np.column_stack([(outcomes == outcome).to_numpy() for outcome in OUTCOMES]).astype(float)
    return float(np.mean(np.sum((probabilities - actual) ** 2, axis=1)))


def multiclass_log_loss(outcomes: pd.Series, probabilities: np.ndarray) -> float:
    """
    Average of -log(probability given to what actually happened).

    Written out by hand because sklearn's log_loss assumes the columns are in
    alphabetical order (A, D, H), and ours are H, D, A.
    """
    actual_column = outcomes.map({outcome: i for i, outcome in enumerate(OUTCOMES)}).to_numpy()
    chosen = probabilities[np.arange(len(actual_column)), actual_column]
    return float(-np.mean(np.log(np.clip(chosen, 1e-15, 1))))


def score_predictions(outcomes: pd.Series, probabilities: np.ndarray) -> dict:
    predicted = np.array(OUTCOMES)[probabilities.argmax(axis=1)]
    return {
        "n_matches": len(outcomes),
        "log_loss": multiclass_log_loss(outcomes, probabilities),
        "brier_score": multiclass_brier(outcomes, probabilities),
        "accuracy": accuracy_score(outcomes, predicted),
        "macro_f1": f1_score(outcomes, predicted, labels=OUTCOMES, average="macro", zero_division=0),
    }


def walk_forward(features: pd.DataFrame, last_test_season: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Train on all seasons before each test season and predict that season.

    Returns (predictions, evaluation) with one row per match per model and one
    row per model per test season.
    """
    finished = features[(features["status"] == "finished") & (features["season_year"] >= FIRST_TRAINING_SEASON)]
    prediction_rows, evaluation_rows = [], []

    for test_season in range(FIRST_TEST_SEASON, last_test_season + 1):
        train = finished[finished["season_year"] < test_season]
        test = finished[finished["season_year"] == test_season]
        if test.empty:
            continue

        for model_name, model in make_models().items():
            columns = model_features(model_name)
            model.fit(train[columns], train["outcome"])
            probabilities = predict_ordered(model, test[columns])

            scores = score_predictions(test["outcome"], probabilities)
            evaluation_rows.append({"model_name": model_name, "test_season": test_season, **scores})

            prediction_rows.append(pd.DataFrame({
                "match_id": test["match_id"].to_numpy(),
                "model_name": model_name,
                "prediction_type": "backtest",
                "trained_through": train["kickoff_utc"].max().date(),
                "p_home_win": probabilities[:, 0],
                "p_draw": probabilities[:, 1],
                "p_away_win": probabilities[:, 2],
            }))

        log.info("Walk-forward: tested on %s (%s matches, trained on %s)", test_season, len(test), len(train))

    return pd.concat(prediction_rows, ignore_index=True), pd.DataFrame(evaluation_rows)


def predict_upcoming(features: pd.DataFrame) -> pd.DataFrame:
    """Fit every model on all finished matches and predict the scheduled ones."""
    finished = features[(features["status"] == "finished") & (features["season_year"] >= FIRST_TRAINING_SEASON)]
    upcoming = features[features["status"] == "scheduled"]
    if upcoming.empty:
        return pd.DataFrame()

    frames = []
    for model_name, model in make_models().items():
        columns = model_features(model_name)
        model.fit(finished[columns], finished["outcome"])
        probabilities = predict_ordered(model, upcoming[columns])
        frames.append(pd.DataFrame({
            "match_id": upcoming["match_id"].to_numpy(),
            "model_name": model_name,
            "prediction_type": "upcoming",
            "trained_through": finished["kickoff_utc"].max().date(),
            "p_home_win": probabilities[:, 0],
            "p_draw": probabilities[:, 1],
            "p_away_win": probabilities[:, 2],
        }))
    return pd.concat(frames, ignore_index=True)


def round_probabilities(predictions: pd.DataFrame) -> pd.DataFrame:
    """Round to 4 places for storage and push any rounding error into the draw so rows still sum to 1."""
    predictions = predictions.copy()
    predictions["p_home_win"] = predictions["p_home_win"].round(4)
    predictions["p_away_win"] = predictions["p_away_win"].round(4)
    predictions["p_draw"] = (1 - predictions["p_home_win"] - predictions["p_away_win"]).round(4)
    return predictions


def load_model_inputs(engine: Engine) -> tuple[pd.DataFrame, pd.DataFrame]:
    with engine.connect() as connection:
        matches = pd.read_sql(text("""
            SELECT m.match_id, s.start_year AS season_year, m.stage, m.leg, m.kickoff_utc, m.status,
                   m.home_club_id, m.away_club_id, m.home_goals, m.away_goals,
                   m.home_goals_90, m.away_goals_90, m.is_neutral_venue
            FROM matches m
            JOIN seasons s ON s.season_id = m.season_id
        """), connection)
        club_stats = pd.read_sql(text("SELECT match_id, club_id, shots_on_target FROM club_match_stats"), connection)
    return matches, club_stats


def build_derived_tables(engine: Engine) -> None:
    """Calculate Elo, run the backtest, predict upcoming matches and save it all."""
    matches, club_stats = load_model_inputs(engine)

    elo = calculate_elo(matches)
    features = build_match_features(matches, club_stats, elo)

    finished_seasons = features.loc[features["status"] == "finished", "season_year"]
    # Only backtest on seasons that are complete; the current one is too short to score fairly.
    complete_seasons = sorted(
        season for season in finished_seasons.unique()
        if not ((features["season_year"] == season) & (features["status"] == "scheduled")).any()
    )
    predictions, evaluation = walk_forward(features, last_test_season=max(complete_seasons))
    upcoming = predict_upcoming(features)

    summary = evaluation.groupby("model_name")[["log_loss", "brier_score", "accuracy"]].mean().sort_values("log_loss")
    log.info("Average backtest scores by model:\n%s", summary.round(4).to_string())

    all_predictions = round_probabilities(pd.concat([predictions, upcoming], ignore_index=True))
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE club_elo, match_predictions, model_evaluation"))
        elo.round(1).to_sql("club_elo", connection, if_exists="append", index=False, method="multi", chunksize=2000)
        all_predictions.to_sql(
            "match_predictions", connection, if_exists="append", index=False, method="multi", chunksize=2000
        )
        evaluation.round(4).to_sql("model_evaluation", connection, if_exists="append", index=False, method="multi")

    log.info(
        "Saved %s Elo rows, %s backtest and %s upcoming predictions",
        len(elo), len(predictions), len(upcoming),
    )
