import sys
from pathlib import Path

# `streamlit run` only puts app/ on the import path, so add the project root for `app` and `src`.
PROJECT_ROOT = next(path for path in Path(__file__).resolve().parents if (path / "src").is_dir())
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import plotly.graph_objects as go
import streamlit as st

from app.components import data
from app.components.charts import ACCENT, INK_MUTED, MARKER_RING, SERIES, show, style
from app.components.glossary import HELP
from app.components.sidebar import PAGE_ICON, footer, page_header, season_picker
from app.components.tables import show_table
from src.analysis.player_metrics import default_min_minutes, filter_by_minutes, poisson_rate_interval

st.set_page_config(page_title="Player Intelligence | UCL Analytics", page_icon=PAGE_ICON, layout="wide")
page_header("Player Intelligence", "Per-90 scoring, creation, shooting and goalkeeping, with a minutes filter.")

POSITION_NAMES = {"GK": "Goalkeepers", "DEF": "Defenders", "MID": "Midfielders", "FWD": "Forwards",
                  "UNK": "Unknown (only used as a sub)"}

season_year = season_picker()
players = data.player_seasons(season_year)

clubs = sorted(players["club_name"].unique())
chosen_clubs = st.sidebar.multiselect("Clubs", clubs, placeholder="All clubs")
positions = st.sidebar.multiselect(
    "Positions", list(POSITION_NAMES), default=["DEF", "MID", "FWD"], format_func=POSITION_NAMES.get
)
suggested = default_min_minutes(players)
max_minutes = int(players["minutes"].max())
min_minutes = st.sidebar.slider(
    "Minimum minutes", 0, max_minutes, min(suggested, max_minutes), step=15,
    help="Players below this are hidden. The default is three full games, or less early in a season.",
)
footer()

filtered = filter_by_minutes(players, min_minutes)
if chosen_clubs:
    filtered = filtered[filtered["club_name"].isin(chosen_clubs)]
if positions:
    filtered = filtered[filtered["position_group"].isin(positions)]

st.caption(
    f"{len(filtered)} players shown with at least {min_minutes} minutes. " + HELP["per90"]
    + " A player with one goal in 45 minutes shows 2.0 goals per 90."
)
if filtered.empty:
    st.warning("No players match these filters. Try lowering the minimum minutes.")
    st.stop()

filtered = filtered.assign(player_label=filtered["player_name"] + " (" + filtered["club_name"] + ")")
base_columns = {
    "player_name": ("Player", "text"), "club_name": ("Club", "text"), "position_group": ("Pos", "text"),
    "appearances": ("Apps", "int"), "minutes": ("Minutes", "int"),
}

scoring, creation, shooting, discipline, keepers = st.tabs(
    ["Scoring", "Creation", "Shooting", "Discipline", "Goalkeeping"]
)

with scoring:
    left, right = st.columns([3, 2], gap="large")
    with left:
        show_table(filtered.sort_values("non_penalty_goals_per90", ascending=False), {
            **base_columns, "goals": ("Goals", "int"), "penalty_goals": ("Pens", "int"),
            "goals_per90": ("Goals / 90", "dec2"), "non_penalty_goals_per90": ("NP goals / 90", "dec2"),
        }, height=460, help_text={"non_penalty_goals_per90": HELP["non_penalty"]})

    with right:
        top = filtered[filtered["non_penalty_goals"] > 0].nlargest(15, "non_penalty_goals_per90")
        lower, upper = poisson_rate_interval(top["non_penalty_goals"], top["minutes"])
        top = top.assign(lower=lower, upper=upper).iloc[::-1]
        fig = go.Figure(go.Scatter(
            x=top["non_penalty_goals_per90"], y=top["player_label"], mode="markers",
            marker=dict(color=ACCENT, size=9, line=MARKER_RING),
            error_x=dict(type="data", symmetric=False, array=top["upper"] - top["non_penalty_goals_per90"],
                         arrayminus=top["non_penalty_goals_per90"] - top["lower"], color=INK_MUTED, thickness=1.2),
            customdata=top[["non_penalty_goals", "minutes", "lower", "upper"]],
            hovertemplate="%{y}<br>%{x:.2f} NP goals / 90<br>%{customdata[0]} goals in %{customdata[1]} min"
                          "<br>90% range: %{customdata[2]:.2f} to %{customdata[3]:.2f}<extra></extra>",
        ))
        style(fig, "Non-penalty goals per 90, with a 90% range", "Non-penalty goals / 90", None, height=460)
        fig.update_xaxes(rangemode="tozero")
        show(st, fig)
        st.caption("The line shows the range of scoring rates that fit the player's goals and minutes "
                   "(Poisson). Wide lines mean few minutes, so don't read much into the order.")

with creation:
    show_table(filtered.sort_values("assists_per90", ascending=False), {
        **base_columns, "assists": ("Assists", "int"), "assists_per90": ("Assists / 90", "dec2"),
        "goals": ("Goals", "int"), "goal_contributions_per90": ("Goals + assists / 90", "dec2"),
    }, height=460)
    st.caption("ESPN only records assists, so key passes, expected assists (xA) and chances created "
               "aren't available.")

with shooting:
    show_table(filtered.sort_values("shots_per90", ascending=False), {
        **base_columns, "shots": ("Shots", "int"), "shots_on_target": ("On target", "int"),
        "shots_per90": ("Shots / 90", "dec2"), "shots_on_target_per90": ("On target / 90", "dec2"),
        "shot_accuracy": ("Accuracy", "pct"), "shot_conversion": ("Conversion", "pct"),
    }, height=460, help_text={"shot_accuracy": HELP["shot_accuracy"], "shot_conversion": HELP["conversion"]})
    st.caption("For goals compared with shots, see the Finishing & Efficiency page.")

with discipline:
    show_table(filtered.sort_values("fouls_committed", ascending=False), {
        **base_columns, "fouls_committed": ("Fouls", "int"), "fouls_suffered": ("Fouled", "int"),
        "yellow_cards": ("Yellow", "int"), "red_cards": ("Red", "int"),
    }, height=460)

with keepers:
    goalkeepers = filter_by_minutes(players, min_minutes)
    goalkeepers = goalkeepers[goalkeepers["position_group"] == "GK"]
    if chosen_clubs:
        goalkeepers = goalkeepers[goalkeepers["club_name"].isin(chosen_clubs)]
    goalkeepers = goalkeepers.assign(conceded_per90=goalkeepers["goals_conceded"] * 90 / goalkeepers["minutes"])
    show_table(goalkeepers.sort_values("save_pct", ascending=False), {
        **base_columns, "shots_faced": ("Shots faced", "int"), "saves": ("Saves", "int"),
        "goals_conceded": ("Conceded", "int"), "save_pct": ("Save %", "pct"),
        "conceded_per90": ("Conceded / 90", "dec2"),
    }, height=420, help_text={"save_pct": HELP["save_pct"]})
    st.caption("Goalkeepers are shown whatever the position filter says. Save % depends heavily on the "
               "shots a keeper faces, which this data can't describe.")

st.info("Player-level defensive numbers (tackles, interceptions, pressures) aren't in ESPN's data. "
        "Team-level defending is on the Tactical Analysis page.")

# --- Compare players -------------------------------------------------------------------
st.divider()
st.subheader("Compare players", anchor=False)
options = filtered.sort_values("minutes", ascending=False)["player_label"].tolist()
selected = st.multiselect("Pick up to three players", options, default=options[:2], max_selections=3)

if selected:
    comparison = filtered.set_index("player_label").loc[selected].reset_index()
    metrics = {
        "non_penalty_goals_per90": "NP goals / 90", "assists_per90": "Assists / 90",
        "shots_per90": "Shots / 90", "shots_on_target_per90": "On target / 90",
    }
    fig = go.Figure()
    for i, row in comparison.iterrows():
        fig.add_trace(go.Bar(
            x=list(metrics.values()), y=[row[m] for m in metrics], name=row["player_label"],
            marker_color=SERIES[i], hovertemplate="%{x}: %{y:.2f}<extra>" + row["player_label"] + "</extra>",
        ))
    style(fig, "Per-90 comparison", None, "Per 90 minutes", height=360)
    fig.update_layout(barmode="group", bargroupgap=0.08)
    show(st, fig)
    show_table(comparison, {
        "player_label": ("Player", "text"), "position_group": ("Pos", "text"), "minutes": ("Minutes", "int"),
        "goals": ("Goals", "int"), "non_penalty_goals_per90": ("NP goals / 90", "dec2"),
        "assists_per90": ("Assists / 90", "dec2"), "shots_per90": ("Shots / 90", "dec2"),
        "shot_accuracy": ("Accuracy", "pct"), "shot_conversion": ("Conversion", "pct"),
    })
    st.caption("Players with very different minutes aren't on an equal footing: the one with fewer "
               "minutes has a much less certain rate.")
