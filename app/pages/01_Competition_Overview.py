import sys
from pathlib import Path

# `streamlit run` only puts app/ on the import path, so add the project root for `app` and `src`.
PROJECT_ROOT = next(path for path in Path(__file__).resolve().parents if (path / "src").is_dir())
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import plotly.graph_objects as go
import streamlit as st

from app.components import data
from app.components.charts import ACCENT, MUTED_MARK, SERIES, show, style
from app.components.glossary import HELP
from app.components.sidebar import footer, page_header, season_picker
from app.components.tables import show_table
from src.analysis.tournament_index import COMPONENT_LABELS, DEFAULT_WEIGHTS, index_components, tournament_index

st.set_page_config(page_title="Competition Overview | UCL Analytics", layout="wide")
page_header("Competition Overview", "Standings, results and trends for one season, with history for context.")

season_year = season_picker()
footer()

seasons = data.seasons().set_index("season_year")
season_label = seasons.loc[season_year, "season"]
season_finished = seasons.loc[season_year, "scheduled"] == 0

matches = data.club_matches(season_year)
home_rows = matches[matches["is_home"]]

# A short summary line instead of a row of big number cards.
goals = int(home_rows["goals_for"].sum() + home_rows["goals_against"].sum())
played = len(home_rows)
non_neutral = home_rows[~home_rows["is_neutral_venue"]]
home_win_rate = (non_neutral["goals_for"] > non_neutral["goals_against"]).mean()
cols = st.columns(4)
cols[0].metric("Matches played", f"{played}")
cols[1].metric("Goals", f"{goals}")
cols[2].metric("Goals per match", f"{goals / played:.2f}")
cols[3].metric("Home win rate", f"{home_win_rate:.0%}", help="Neutral venues (finals) are left out.")

if played < 40:
    st.info(f"Only {played} matches of {season_label} have been played. Season averages will move a lot.")

# --- Standings and recent results -------------------------------------------------
is_groups = seasons.loc[season_year, "format"] == "group_stage"
table_tab, results_tab = st.tabs(["Group tables" if is_groups else "League phase table", "Latest results"])

with table_tab:
    standings = data.load("standings", data.query, """
        SELECT gs.*, c.name AS club_name FROM v_group_standings gs
        JOIN clubs c ON c.club_id = gs.club_id
        WHERE gs.season_year = :season_year
        ORDER BY gs.group_name, gs.position
    """, season_year=season_year)

    if is_groups:
        group = st.segmented_control("Group", sorted(standings["group_name"].unique()), default="A",
                                     label_visibility="collapsed")
        table = standings[standings["group_name"] == (group or "A")]
    else:
        table = standings

    show_table(table, {
        "position": ("#", "int"), "club_name": ("Club", "text"), "played": ("P", "int"), "wins": ("W", "int"),
        "draws": ("D", "int"), "losses": ("L", "int"), "goals_for": ("GF", "int"), "goals_against": ("GA", "int"),
        "goal_difference": ("GD", "int"), "points": ("Pts", "int"),
    }, height=min(38 * len(table) + 40, 460))
    st.caption("Worked out from results. Ties are split on goal difference then goals scored, "
               "not UEFA's full tiebreakers, so a tied position can differ from the official table.")

with results_tab:
    recent = home_rows.sort_values("kickoff_utc", ascending=False).head(12).copy()
    recent["score"] = (
        recent["goals_for"].astype(int).astype(str) + "-" + recent["goals_against"].astype(int).astype(str)
    )
    recent["stage_label"] = recent["stage"].str.replace("_", " ").str.capitalize()
    recent["date"] = recent["kickoff_utc"].dt.date
    show_table(recent, {
        "date": ("Date", "shortdate"), "stage_label": ("Stage", "text"), "club_name": ("Home", "text"),
        "score": ("Score", "text"), "opponent_name": ("Away", "text"),
    }, height=460)

# --- Tournament Performance Index -------------------------------------------------
st.divider()
st.subheader("Club performance: Tournament Performance Index", anchor=False)
st.caption(HELP["tpi"])

with st.expander("How the index works, and change the weights"):
    st.markdown(
        "Each component is turned into a z-score within the season (0 = average club, +1 = one standard "
        "deviation better), then combined with the weights below. Stage reached is only used once a season "
        "is over; until then its weight is shared among the rest. With 6 to 17 games per club, one or two "
        "results can move a club a long way, so treat small gaps as noise."
    )
    weight_cols = st.columns(3)
    weights = {}
    for i, (name, default) in enumerate(DEFAULT_WEIGHTS.items()):
        weights[name] = weight_cols[i % 3].slider(COMPONENT_LABELS[name], 0.0, 0.5, default, 0.05, key=f"w_{name}")
    if sum(weights.values()) == 0:
        st.warning("All weights are zero, so the default weights are used.")
        weights = DEFAULT_WEIGHTS

finished_seasons = set(seasons.index[seasons["scheduled"] == 0])
components = index_components(matches, finished_seasons)
index = tournament_index(components, weights).merge(
    matches[["club_id", "club_name"]].drop_duplicates(), on="club_id"
)
if not season_finished:
    st.caption("Stage reached isn't used yet because the season is still going.")

show_table(index, {
    "tpi_rank": ("Rank", "int"), "club_name": ("Club", "text"), "tpi": ("Index", "signed2"),
    "matches": ("Games", "int"), "points_per_match": ("Pts / match", "dec2"),
    "goal_diff_per_match": ("GD / match", "signed2"), "sot_diff_per_match": ("SoT diff / match", "signed1"),
    "opponent_strength": ("Opponent Elo", "int"), "recent_form": ("Last 5 pts / match", "dec2"),
}, height=420, help_text={"tpi": HELP["tpi"], "sot_diff_per_match": HELP["sot_diff"],
                          "opponent_strength": HELP["opponent_elo"]})

# --- History ------------------------------------------------------------------------
st.divider()
st.subheader("How the competition has changed", anchor=False)
trends = data.load("season trends", data.named, "season_trends")
home_adv = data.load("home advantage", data.named, "home_advantage_by_season")


def trend_chart(column: str, title: str, y_title: str, fmt: str):
    colors = [ACCENT if year == season_year else MUTED_MARK for year in trends["season_year"]]
    fig = go.Figure(go.Bar(
        x=trends["season"], y=trends[column], marker_color=colors,
        hovertemplate="%{x}<br>" + y_title + ": %{y:" + fmt + "}<extra></extra>",
    ))
    style(fig, title, None, y_title, height=300)
    fig.update_yaxes(rangemode="tozero")
    return fig


chart_left, chart_right = st.columns(2, gap="large")
with chart_left:
    show(st, trend_chart("goals_per_match", "Goals per match", "Goals", ".2f"))
with chart_right:
    show(st, trend_chart(
        "shots_on_target_per_match", "Shots on target per match (both teams)", "Shots on target", ".1f"
    ))
st.caption(f"{season_label} is highlighted. 2026-27 only covers the matches played so far.")

chart_left, chart_right = st.columns(2, gap="large")
with chart_left:
    fig = go.Figure()
    for column, label, color in [("home_win_rate", "Home win", SERIES[0]), ("draw_rate", "Draw", SERIES[1]),
                                 ("away_win_rate", "Away win", SERIES[2])]:
        fig.add_trace(go.Scatter(
            x=home_adv["season"], y=home_adv[column].astype(float), name=label, mode="lines+markers",
            line=dict(color=color, width=2), marker=dict(size=7),
            hovertemplate="%{x}<br>" + label + ": %{y:.0%}<extra></extra>",
        ))
    style(fig, "Result split by season", None, "Share of matches", height=320)
    fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    show(st, fig)
    st.caption("2020-21 was played mostly behind closed doors, and home and away win rates almost met.")

with chart_right:
    first, last = int(trends["season_year"].min()), int(trends["season_year"].max())
    periods = data.load("goal timing", data.named, "goals_by_match_period", from_season=first, to_season=last)
    fig = go.Figure(go.Bar(
        x=periods["match_period"], y=periods["share_pct"].astype(float), marker_color=ACCENT,
        customdata=periods["goals"], hovertemplate="%{x}<br>%{y:.1f}% of goals (%{customdata})<extra></extra>",
    ))
    style(fig, "When goals are scored, all seasons", "Minute", "Share of goals (%)", height=320)
    show(st, fig)
    st.caption("Added time stays with its half, so 45+2 counts as first half. Most knockout ties never "
               "reach extra time, which is why that bar is small.")

with st.expander("Season trends as a table"):
    show_table(trends, {
        "season": ("Season", "text"), "matches": ("Matches", "int"), "goals_per_match": ("Goals / match", "dec2"),
        "shots_per_match": ("Shots / match", "dec1"), "shots_on_target_per_match": ("SoT / match", "dec1"),
        "goals_per_shot": ("Goals / shot", "dec3"), "passes_per_match": ("Passes / match", "int"),
        "pass_completion": ("Pass completion", "pct"),
    })
    st.caption("Passing numbers are blank for 2017-18 because ESPN didn't record them.")
