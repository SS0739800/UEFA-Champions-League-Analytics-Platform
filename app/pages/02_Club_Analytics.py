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

from app.components import data
from app.components.charts import ACCENT, MUTED_MARK, SERIES, show, style
from app.components.glossary import HELP, NO_XG
from app.components.sidebar import PAGE_ICON, footer, page_header, season_picker
from app.components.tables import show_table
from src.analysis.tournament_index import STAGE_ORDER

st.set_page_config(page_title="Club Analytics | UCL Analytics", page_icon=PAGE_ICON, layout="wide")
page_header("Club Analytics", "One club's season: results, shots, home and away, and how it compares.")

season_year = season_picker()
matches = data.club_matches(season_year)
clubs = sorted(matches["club_name"].unique())
remembered = st.session_state.get("shared_club")
club_name = st.sidebar.selectbox("Club", clubs, index=clubs.index(remembered) if remembered in clubs else 0)
st.session_state["shared_club"] = club_name
footer()

club = matches[matches["club_name"] == club_name].sort_values("kickoff_utc").copy()
club_id = int(club["club_id"].iloc[0])
season_label = club["season"].iloc[0]

STAGE_NAMES = {1: "the first phase", 2: "the knockout play-offs", 3: "the round of 16", 4: "the quarter-finals",
               5: "the semi-finals", 6: "the final"}
wins, draws, losses = (club["result"] == "W").sum(), (club["result"] == "D").sum(), (club["result"] == "L").sum()
furthest = int(club["stage"].map(STAGE_ORDER).max())
won_title = bool(((club["stage"] == "final") & club["won_match"]).any())
season_over = data.seasons().set_index("season_year").loc[season_year, "scheduled"] == 0
if won_title:
    reached = "won the title"
elif season_over and furthest == 6:
    reached = "lost the final"
elif season_over:
    reached = f"went out in {STAGE_NAMES[furthest]}"
else:
    reached = f"has played in {STAGE_NAMES[furthest]} so far"

st.subheader(club_name, anchor=False)
st.markdown(
    f"**{season_label}:** played {len(club)}, won {wins}, drew {draws}, lost {losses}; "
    f"scored {int(club['goals_for'].sum())}, conceded {int(club['goals_against'].sum())}; {reached}."
)
if len(club) < 4:
    st.info("Fewer than four matches so far. Percentiles and averages below are very rough.")

# --- Percentiles against the rest of the season -------------------------------------
per_club = matches.groupby("club_name").agg(
    points=("points", "mean"),
    goals_for=("goals_for", "mean"),
    goals_against=("goals_against", "mean"),
    sot=("shots_on_target", "mean"),
    sot_against=("shots_on_target_against", "mean"),
    possession=("possession_pct", "mean"),
    passes=("passes", "mean"),
).astype(float)
# Lower is better for things conceded, so flip those before ranking.
better_when_lower = {"goals_against", "sot_against"}
percentiles = pd.DataFrame({
    column: (-per_club[column] if column in better_when_lower else per_club[column]).rank(pct=True) * 100
    for column in per_club.columns
})
labels = {
    "points": "Points / match", "goals_for": "Goals scored / match", "goals_against": "Goals conceded / match",
    "sot": "Shots on target / match", "sot_against": "Shots on target faced / match",
    "possession": "Possession", "passes": "Passes / match",
}
club_pct = percentiles.loc[club_name].dropna()
club_values = per_club.loc[club_name]

left, right = st.columns([3, 2], gap="large")
with left:
    fig = go.Figure(go.Bar(
        y=[labels[c] for c in club_pct.index][::-1], x=club_pct.values[::-1], orientation="h",
        marker_color=ACCENT,
        customdata=np.round(club_values[club_pct.index].values[::-1], 2),
        hovertemplate="%{y}<br>Value: %{customdata}<br>Percentile: %{x:.0f}<extra></extra>",
    ))
    fig.add_vline(x=50, line_color=MUTED_MARK, line_width=1)
    style(fig, f"Compared with the other {len(per_club) - 1} clubs this season", "Percentile (higher is better)",
          None, height=340)
    fig.update_xaxes(range=[0, 100])
    show(st, fig)
    st.caption("For goals and shots conceded, a high percentile means conceding fewer. "
               "Possession and passes describe style more than quality.")

with right:
    st.markdown("**Opposition**")
    avg_opponent = club["opponent_elo_before"].astype(float).mean()
    season_avg = matches["opponent_elo_before"].astype(float).mean()
    st.markdown(
        f"Average opponent Elo **{avg_opponent:.0f}**, against a season average of {season_avg:.0f}. "
        f"{'A harder' if avg_opponent > season_avg else 'An easier'} schedule than the typical club."
    )
    st.caption(HELP["elo"])

st.markdown("**Home and away**")
venue = club[~club["is_neutral_venue"]].assign(where=lambda df: np.where(df["is_home"], "Home", "Away"))
split = venue.groupby("where").agg(
    played=("match_id", "size"), wins=("result", lambda r: (r == "W").sum()),
    draws=("result", lambda r: (r == "D").sum()), losses=("result", lambda r: (r == "L").sum()),
    goals_for=("goals_for", "sum"), goals_against=("goals_against", "sum"), ppm=("points", "mean"),
    sot=("shots_on_target", "mean"), sot_against=("shots_on_target_against", "mean"),
).reindex(["Home", "Away"]).dropna(how="all").reset_index()
show_table(split, {
    "where": ("", "text"), "played": ("P", "int"), "wins": ("W", "int"), "draws": ("D", "int"),
    "losses": ("L", "int"), "goals_for": ("GF", "int"), "goals_against": ("GA", "int"),
    "ppm": ("Pts / match", "dec2"), "sot": ("SoT / match", "dec1"), "sot_against": ("SoT faced / match", "dec1"),
})
neutral = int(club["is_neutral_venue"].sum())
if neutral:
    st.caption(f"{neutral} match(es) at a neutral venue are left out of this split.")

# --- Match by match --------------------------------------------------------------------
st.divider()
club["label"] = club["kickoff_utc"].dt.strftime("%d %b")
chart_left, chart_right = st.columns(2, gap="large")
with chart_left:
    fig = go.Figure()
    sides = [("shots_on_target", "For", SERIES[0]), ("shots_on_target_against", "Against", SERIES[1])]
    for column, name, color in sides:
        fig.add_trace(go.Bar(
            x=club["label"], y=club[column], name=name, marker_color=color, customdata=club["opponent_name"],
            hovertemplate="%{x} v %{customdata}<br>" + name + ": %{y}<extra></extra>",
        ))
    style(fig, "Shots on target, match by match", None, "Shots on target", height=340)
    fig.update_layout(barmode="group", bargroupgap=0.08)
    show(st, fig)
    st.caption(NO_XG)

with chart_right:
    history = data.load("Elo history", data.query, """
        SELECT m.kickoff_utc, s.start_year AS season_year, s.label AS season, e.elo_after
        FROM club_elo e
        JOIN matches m ON m.match_id = e.match_id
        JOIN seasons s ON s.season_id = m.season_id
        WHERE e.club_id = :club_id AND e.elo_after IS NOT NULL
        ORDER BY m.kickoff_utc
    """, club_id=club_id)
    # Break the line where the club missed a season, so it doesn't draw a fake trend across the gap.
    missed = history["season_year"].diff() > 1
    gaps = history[missed].assign(
        elo_after=np.nan, kickoff_utc=history.loc[missed, "kickoff_utc"] - pd.Timedelta(days=1)
    )
    history = pd.concat([history, gaps]).sort_values("kickoff_utc")
    fig = go.Figure(go.Scatter(
        x=history["kickoff_utc"], y=history["elo_after"].astype(float), mode="lines", connectgaps=False,
        line=dict(color=ACCENT, width=2), customdata=history["season"],
        hovertemplate="%{x|%d %b %Y} (%{customdata})<br>Elo: %{y:.0f}<extra></extra>",
    ))
    style(fig, "Elo rating across all seasons", None, "Elo after match", height=340)
    show(st, fig)
    st.caption("Gaps are seasons the club wasn't in the competition. Ratings before about 2015 are still "
               "settling, because every club starts from scratch in 2012-13.")

st.markdown("**Every match**")
club["score"] = club["goals_for"].astype(int).astype(str) + "-" + club["goals_against"].astype(int).astype(str)
club.loc[club["went_to_extra_time"], "score"] += " (aet)"
club["venue_label"] = np.where(club["is_neutral_venue"], "N", np.where(club["is_home"], "H", "A"))
club["stage_label"] = club["stage"].str.replace("_", " ").str.capitalize()
club["date"] = club["kickoff_utc"].dt.date
show_table(club.sort_values("kickoff_utc", ascending=False), {
    "date": ("Date", "date"), "stage_label": ("Stage", "text"), "venue_label": ("H/A", "text"),
    "opponent_name": ("Opponent", "text"), "score": ("Score", "text"), "result": ("Result", "text"),
    "possession_pct": ("Possession %", "dec1"), "shots": ("Shots", "int"), "shots_on_target": ("SoT", "int"),
    "shots_on_target_against": ("SoT faced", "int"), "opponent_elo_before": ("Opponent Elo", "int"),
}, help_text={"opponent_elo_before": HELP["elo"]})
st.caption("Score includes extra time but not penalties. H = home, A = away, N = neutral venue.")
