import sys
from pathlib import Path

# `streamlit run` only puts app/ on the import path, so add the project root for `app` and `src`.
PROJECT_ROOT = next(path for path in Path(__file__).resolve().parents if (path / "src").is_dir())
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support

from app.components import data
from app.components.charts import ACCENT, MARKER_RING, MUTED_MARK, SEQUENTIAL, SERIES, show, style
from app.components.glossary import HELP
from app.components.sidebar import footer, page_header
from app.components.tables import show_table
from src.database.connection import get_engine
from src.features.elo import calculate_elo
from src.features.match_features import FEATURE_COLUMNS, OUTCOMES, build_match_features
from src.models.train import FIRST_TRAINING_SEASON, load_model_inputs, make_models

st.set_page_config(page_title="Prediction Lab | UCL Analytics", layout="wide")
page_header(
    "Prediction Lab",
    "Home win, draw or away win after 90 minutes, predicted only from what was known before kickoff.",
)
footer()

OUTCOME_NAMES = {"H": "Home win", "D": "Draw", "A": "Away win"}
FEATURE_NAMES = {
    "elo_diff": "Elo difference (home minus away)",
    "form_points_diff": "Points per game, last 5",
    "goals_for_diff": "Goals scored per game, last 5",
    "goals_against_diff": "Goals conceded per game, last 5",
    "shots_on_target_for_diff": "Shots on target per game, last 5",
    "shots_on_target_against_diff": "Shots on target faced per game, last 5",
    "experience_diff": "UCL experience (log of games played)",
    "is_neutral_venue": "Neutral venue",
    "is_knockout": "Knockout match",
    "first_leg_goal_diff": "First-leg goal difference",
}

evaluation = data.load("model scores", data.query, "SELECT * FROM model_evaluation")
if evaluation.empty:
    st.error("There are no model results yet. Run `python -m src.etl.run` without --skip-model.")
    st.stop()

summary = (
    evaluation.groupby("model_name")
    .apply(lambda df: pd.Series({
        "matches": df["n_matches"].sum(),
        # Weight each season by its number of matches.
        "log_loss": np.average(df["log_loss"], weights=df["n_matches"]),
        "brier_score": np.average(df["brier_score"], weights=df["n_matches"]),
        "accuracy": np.average(df["accuracy"], weights=df["n_matches"]),
        "macro_f1": np.average(df["macro_f1"], weights=df["n_matches"]),
    }), include_groups=False)
    .sort_values("log_loss")
    .reset_index()
)
model_order = summary["model_name"].tolist()
# Fixed colours per model so they don't change between runs. The baseline is grey.
model_color = {
    "Logistic regression": SERIES[0], "Elo only": SERIES[1], "Random forest": SERIES[2],
    "Gradient boosting": SERIES[3], "Base rates": MUTED_MARK,
}
best_model = model_order[0]

model = st.sidebar.selectbox("Model", model_order, index=0,
                             help=f"Defaults to the lowest backtest log loss ({best_model}).")

st.warning(
    "These are model outputs, not forecasts to bet on. Even the best model here is wrong about the "
    "result a bit over 40% of the time, and football has a lot of randomness a model can't see: "
    "injuries, rotation, domestic form and the draw itself."
)

upcoming_tab, backtest_tab, calibration_tab, drivers_tab = st.tabs(
    ["Upcoming matches", "Backtest", "Calibration", "What the model uses"]
)

# --- Upcoming -------------------------------------------------------------------------------
with upcoming_tab:
    upcoming = data.load("predictions", data.query, """
        SELECT m.kickoff_utc, s.label AS season, m.stage, h.name AS home, a.name AS away,
               p.p_home_win, p.p_draw, p.p_away_win, p.trained_through
        FROM match_predictions p
        JOIN matches m ON m.match_id = p.match_id
        JOIN seasons s ON s.season_id = m.season_id
        JOIN clubs h ON h.club_id = m.home_club_id
        JOIN clubs a ON a.club_id = m.away_club_id
        WHERE p.prediction_type = 'upcoming' AND p.model_name = :model
        ORDER BY m.kickoff_utc
    """, model=model)

    if upcoming.empty:
        st.info("No scheduled matches in the data right now.")
    else:
        trained_through = pd.to_datetime(upcoming["trained_through"].iloc[0])
        next_date = upcoming["kickoff_utc"].dt.date.min()
        next_round = upcoming[upcoming["kickoff_utc"].dt.date <= next_date + pd.Timedelta(days=3)]
        show_all = st.toggle(f"Show all {len(upcoming)} scheduled matches", value=False)
        table = upcoming if show_all else next_round
        table = table.assign(date=table["kickoff_utc"].dt.date)
        show_table(table, {
            "date": ("Date", "date"), "home": ("Home", "text"), "away": ("Away", "text"),
            "p_home_win": ("Home win", "prob"), "p_draw": ("Draw", "prob"), "p_away_win": ("Away win", "prob"),
        }, height=min(38 * len(table) + 40, 560))
        st.caption(
            f"Model: {model}, trained on every finished match up to {trained_through:%d %b %Y}. Every fixture uses "
            "Elo and form as they stand today, so predictions for later rounds will change once the next games "
            "are played."
        )

# --- Backtest ---------------------------------------------------------------------------------
with backtest_tab:
    st.markdown(
        "Each season from 2016-17 was predicted by models trained only on earlier seasons "
        "(walk-forward validation), so every number here is out-of-sample."
    )
    show_table(summary, {
        "model_name": ("Model", "text"), "matches": ("Matches predicted", "int"),
        "log_loss": ("Log loss", "dec3"), "brier_score": ("Brier score", "dec3"),
        "accuracy": ("Accuracy", "pct"), "macro_f1": ("Macro F1", "dec3"),
    }, help_text={"log_loss": HELP["log_loss"], "brier_score": HELP["brier"]})
    base = summary.set_index("model_name").loc["Base rates", "log_loss"]
    elo_only = summary.set_index("model_name").loc["Elo only", "log_loss"]
    st.caption(
        f"'Base rates' always predicts the historical split of home wins, draws and away wins ({base:.3f}). "
        f"'Elo only' uses nothing but the rating gap ({elo_only:.3f}). The full models barely beat Elo alone: "
        "most of what can be predicted before kickoff is how strong the two clubs are."
    )

    evaluation = evaluation.assign(season=evaluation["test_season"].map(lambda y: f"{y}-{str(y + 1)[-2:]}"))
    fig = go.Figure()
    for name in model_order:
        subset = evaluation[evaluation["model_name"] == name].sort_values("test_season")
        fig.add_trace(go.Scatter(
            x=subset["season"], y=subset["log_loss"], name=name, mode="lines+markers",
            line=dict(color=model_color[name], width=2), marker=dict(size=7),
            hovertemplate="%{x}<br>" + name + ": %{y:.3f}<extra></extra>",
        ))
    style(fig, "Log loss by test season (lower is better)", None, "Log loss", height=360)
    show(st, fig)

    backtest = data.load("backtest predictions", data.query, """
        SELECT m.match_id, s.start_year AS season_year, s.label AS season, m.kickoff_utc, m.stage,
               h.name AS home, a.name AS away, m.home_goals_90, m.away_goals_90,
               p.p_home_win, p.p_draw, p.p_away_win
        FROM match_predictions p
        JOIN matches m ON m.match_id = p.match_id
        JOIN seasons s ON s.season_id = m.season_id
        JOIN clubs h ON h.club_id = m.home_club_id
        JOIN clubs a ON a.club_id = m.away_club_id
        WHERE p.prediction_type = 'backtest' AND p.model_name = :model
        ORDER BY m.kickoff_utc
    """, model=model)
    backtest["actual"] = np.select(
        [backtest["home_goals_90"] > backtest["away_goals_90"], backtest["home_goals_90"] == backtest["away_goals_90"]],
        ["H", "D"], "A",
    )
    probabilities = backtest[["p_home_win", "p_draw", "p_away_win"]].to_numpy(dtype=float)
    backtest["predicted"] = np.array(OUTCOMES)[probabilities.argmax(axis=1)]

    left, right = st.columns(2, gap="large")
    with left:
        matrix = confusion_matrix(backtest["actual"], backtest["predicted"], labels=OUTCOMES)
        fig = go.Figure(go.Heatmap(
            z=matrix, x=[OUTCOME_NAMES[o] for o in OUTCOMES], y=[OUTCOME_NAMES[o] for o in OUTCOMES],
            colorscale=SEQUENTIAL, showscale=False, xgap=2, ygap=2,
            text=matrix, texttemplate="%{text}", textfont=dict(size=14),
            hovertemplate="Actual: %{y}<br>Predicted: %{x}<br>%{z} matches<extra></extra>",
        ))
        style(fig, f"{model}: predicted against actual", "Most likely outcome (predicted)", "Actual result",
              height=340)
        fig.update_yaxes(autorange="reversed")
        show(st, fig)

    with right:
        precision, recall, f1, support = precision_recall_fscore_support(
            backtest["actual"], backtest["predicted"], labels=OUTCOMES, zero_division=0
        )
        per_class = pd.DataFrame({
            "outcome": [OUTCOME_NAMES[o] for o in OUTCOMES], "support": support,
            "precision": precision, "recall": recall, "f1": f1,
            "predicted_share": [(backtest["predicted"] == o).mean() for o in OUTCOMES],
        })
        st.markdown("**By outcome**")
        show_table(per_class, {
            "outcome": ("Outcome", "text"), "support": ("Matches", "int"), "precision": ("Precision", "pct"),
            "recall": ("Recall", "pct"), "f1": ("F1", "dec2"), "predicted_share": ("Picked", "pct"),
        }, help_text={"predicted_share": "Share of matches where this was the model's most likely outcome."})
        st.caption(
            "Draws are almost never the single most likely outcome, so recall for draws is close to zero even "
            "though the model does give them sensible probabilities. That's normal for football models, and it's "
            "why accuracy is a poor way to judge them."
        )

    st.markdown("**Past predictions**")
    season_options = backtest["season"].unique().tolist()[::-1]
    chosen_season = st.selectbox("Season", season_options, key="backtest_season")
    past = backtest[backtest["season"] == chosen_season].sort_values("kickoff_utc", ascending=False)
    past = past.assign(
        date=past["kickoff_utc"].dt.date,
        score_90=past["home_goals_90"].astype(int).astype(str) + "-" + past["away_goals_90"].astype(int).astype(str),
        actual_label=past["actual"].map(OUTCOME_NAMES),
        hit=np.where(past["actual"] == past["predicted"], "Yes", "No"),
    )
    show_table(past, {
        "date": ("Date", "date"), "home": ("Home", "text"), "away": ("Away", "text"),
        "p_home_win": ("Home win", "prob"), "p_draw": ("Draw", "prob"), "p_away_win": ("Away win", "prob"),
        "score_90": ("Score at 90'", "text"), "actual_label": ("Result", "text"),
        "hit": ("Most likely was right", "text"),
    }, height=420)

# --- Calibration ----------------------------------------------------------------------------------
with calibration_tab:
    st.markdown(
        "If the model says 60% for a home win, home sides should win about 60% of those matches. Each point "
        "groups backtest predictions into bins and compares the average predicted probability with how often "
        "the outcome happened."
    )
    bins = np.linspace(0, 1, 11)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", name="Perfect calibration",
                             line=dict(color=MUTED_MARK, width=1.5), hoverinfo="skip"))
    rows = []
    for i, (outcome, column) in enumerate(zip(OUTCOMES, ["p_home_win", "p_draw", "p_away_win"])):
        frame = pd.DataFrame({"p": backtest[column].astype(float), "hit": (backtest["actual"] == outcome).astype(int)})
        frame["bin"] = pd.cut(frame["p"], bins, include_lowest=True)
        grouped = frame.groupby("bin", observed=True).agg(predicted=("p", "mean"), observed=("hit", "mean"),
                                                          matches=("hit", "size"))
        # Bins with a handful of matches just add noise to the picture.
        grouped = grouped[grouped["matches"] >= 15]
        fig.add_trace(go.Scatter(
            x=grouped["predicted"], y=grouped["observed"], mode="lines+markers", name=OUTCOME_NAMES[outcome],
            line=dict(color=SERIES[i], width=2), marker=dict(size=8, line=MARKER_RING),
            customdata=grouped["matches"],
            hovertemplate=OUTCOME_NAMES[outcome] + "<br>Predicted %{x:.0%}, happened %{y:.0%}"
                          "<br>%{customdata} matches<extra></extra>",
        ))
        rows.append(grouped.reset_index().assign(outcome=OUTCOME_NAMES[outcome]))
    style(fig, f"{model}: calibration on backtest matches", "Predicted probability", "Observed frequency",
          height=460)
    fig.update_xaxes(range=[0, 1], tickformat=".0%")
    fig.update_yaxes(range=[0, 1], tickformat=".0%")
    show(st, fig)
    st.caption("Bins with fewer than 15 matches are hidden. Draw probabilities mostly stay between about 10% "
               "and 30%, which is why that line is short.")

    with st.expander("Calibration as a table"):
        calibration = pd.concat(rows)
        calibration["bin"] = calibration["bin"].astype(str)
        show_table(calibration, {
            "outcome": ("Outcome", "text"), "bin": ("Probability bin", "text"), "matches": ("Matches", "int"),
            "predicted": ("Average predicted", "pct"), "observed": ("Happened", "pct"),
        })

# --- Drivers ------------------------------------------------------------------------------------------
with drivers_tab:
    @st.cache_data(ttl=3600, show_spinner="Fitting the logistic regression...")
    def logistic_coefficients() -> pd.DataFrame:
        matches, club_stats = load_model_inputs(get_engine())
        features = build_match_features(matches, club_stats, calculate_elo(matches))
        finished = features[(features["status"] == "finished") & (features["season_year"] >= FIRST_TRAINING_SEASON)]
        pipeline = make_models()["Logistic regression"]
        pipeline.fit(finished[FEATURE_COLUMNS], finished["outcome"])
        classifier = pipeline[-1]
        coefficients = pd.DataFrame(classifier.coef_, index=classifier.classes_, columns=FEATURE_COLUMNS)
        return coefficients

    coefficients = data.load("model inputs", logistic_coefficients)
    home_vs_away = (coefficients.loc["H"] - coefficients.loc["A"]).sort_values()

    fig = go.Figure(go.Bar(
        x=home_vs_away.values, y=[FEATURE_NAMES[name] for name in home_vs_away.index], orientation="h",
        marker_color=[ACCENT if value > 0 else SERIES[1] for value in home_vs_away.values],
        hovertemplate="%{y}<br>%{x:+.3f}<extra></extra>",
    ))
    fig.add_vline(x=0, line_color=MUTED_MARK, line_width=1)
    style(fig, "Logistic regression: what pushes a prediction towards a home win",
          "Change in log-odds of home win vs away win, per standard deviation", None, height=420)
    show(st, fig)
    st.markdown(
        """
Blue bars push towards the home side winning, orange towards the away side. Features are standardized,
so bar lengths are comparable. Every feature is known before kickoff: Elo ratings come from earlier
matches only, and form covers each club's previous five Champions League games (tested in
`tests/test_features.py`).

- The Elo gap does most of the work, which matches the backtest: Elo on its own is nearly as good as the full model.
- Recent points per game ends up with a *negative* sign. It's strongly correlated with Elo (about 0.7), so once
  Elo is in the model, form only nudges it. It doesn't mean good form hurts.
- A club that won the first leg is a little less likely to win the second. Sitting on a lead is a plausible
  reason, but the model can't tell us why.
- Features overlap (goals and shots on target move together), so individual coefficients shouldn't be
  read as clean causal effects.

**What the model can't see:** domestic league form, injuries and suspensions, squad rotation, travel, the
weather, or anything about the players on the pitch. It also treats the first game of a club new to the
competition as if it were an average newcomer.
"""
    )
    with st.expander("How the models were built"):
        st.markdown(
            f"""
- **Target:** result after 90 minutes. Extra time and penalties are ignored, so knockout ties that went the
  distance count as draws.
- **Training data:** every finished match from {FIRST_TRAINING_SEASON}-{str(FIRST_TRAINING_SEASON + 1)[-2:]}
  onwards. 2012-13 is only used to warm up Elo and form.
- **Validation:** walk-forward by season, never a random split, so no model ever sees a match from the
  season it's predicting.
- **Models:** base rates, Elo-only logistic regression, logistic regression on all features, random forest
  and gradient boosting. The more complex models don't beat logistic regression, so it's the default.
"""
        )
