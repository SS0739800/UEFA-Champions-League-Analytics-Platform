import numpy as np
import plotly.graph_objects as go
import streamlit as st

from app.components import data
from app.components.charts import ACCENT, INK_SECONDARY, MUTED_MARK, show, style
from app.components.glossary import HELP, NO_XG
from app.components.sidebar import footer, page_header, season_picker
from app.components.tables import show_table
from src.analysis.finishing import goals_above_average, season_conversion_rates, team_finishing
from src.analysis.player_metrics import default_min_minutes, filter_by_minutes

st.set_page_config(page_title="Finishing & Efficiency | UCL Analytics", layout="wide")
page_header("Finishing & Efficiency", "Goals compared with shots and shots on target, for players and clubs.")

season_year = season_picker()
players = data.player_seasons(season_year)

positions = st.sidebar.multiselect("Positions", ["DEF", "MID", "FWD"], default=["MID", "FWD"])
clubs = st.sidebar.multiselect("Clubs", sorted(players["club_name"].unique()), placeholder="All clubs")
suggested = default_min_minutes(players)
min_minutes = st.sidebar.slider("Minimum minutes", 0, int(players["minutes"].max()), suggested, step=15)
min_shots = st.sidebar.slider("Minimum non-penalty shots", 0, 30, 5,
                              help="Conversion rates from two or three shots are mostly luck.")
footer()

st.info(NO_XG)
with st.expander("How to read these numbers"):
    st.markdown(f"""
- **Conversion**: {HELP['conversion']}
- **Goals per shot on target**: {HELP['goals_per_sot']}
- **Average-conversion goals**: non-penalty shots on target multiplied by the whole competition's
  goals per shot on target this season. It's what a player would have scored finishing like the average player.
- **Goals above average**: {HELP['goals_above_average']}
- Penalties are taken out of all of these. {HELP['non_penalty']}
""")

# Rates are worked out from every player in the season, before any filters.
rates = season_conversion_rates(players).set_index("season_year").loc[season_year]
finishing = goals_above_average(players)
shown = filter_by_minutes(finishing, min_minutes)
shown = shown[shown["non_penalty_shots"] >= min_shots]
if positions:
    shown = shown[shown["position_group"].isin(positions)]
if clubs:
    shown = shown[shown["club_name"].isin(clubs)]

st.caption(
    f"This season, {rates['goals_per_shot']:.1%} of non-penalty shots and {rates['goals_per_shot_on_target']:.1%} "
    f"of non-penalty shots on target were scored. {len(shown)} players match the filters."
)
if shown.empty:
    st.warning("No players match these filters. Lower the minimum minutes or shots.")
    st.stop()

# --- Player scatter ---------------------------------------------------------------------------
shown = shown.assign(player_label=shown["player_name"] + " (" + shown["club_name"] + ")")
max_sot = max(float(shown["non_penalty_shots_on_target"].max()), 1.0)
line_x = np.array([0, max_sot * 1.05])

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=line_x, y=line_x * rates["goals_per_shot_on_target"], mode="lines", name="Average finishing",
    line=dict(color=MUTED_MARK, width=2), hoverinfo="skip",
))
# Shots and goals are whole numbers, so lots of players land on the same spot.
# Spread them sideways a little so each one can be seen and hovered.
rng = np.random.default_rng(0)
jitter = rng.uniform(-0.18, 0.18, len(shown))
fig.add_trace(go.Scatter(
    x=shown["non_penalty_shots_on_target"] + jitter, y=shown["non_penalty_goals"], mode="markers", name="Players",
    marker=dict(color=ACCENT, size=9, opacity=0.8, line=dict(color="white", width=2)),
    customdata=shown[["player_label", "non_penalty_shots", "goals_above_average", "minutes",
                      "non_penalty_shots_on_target"]],
    hovertemplate="%{customdata[0]}<br>%{y} NP goals from %{customdata[4]} shots on target (%{customdata[1]} shots)"
                  "<br>Goals above average: %{customdata[2]:+.1f}<br>%{customdata[3]} minutes<extra></extra>",
))
# Name only the few players furthest from the line, and only where they don't share a spot with someone else.
spot_counts = shown.groupby(["non_penalty_shots_on_target", "non_penalty_goals"])["player_name"].transform("size")
alone = shown[spot_counts == 1]
for _, row in alone.reindex(alone["goals_above_average"].abs().sort_values(ascending=False).index).head(4).iterrows():
    fig.add_annotation(x=row["non_penalty_shots_on_target"], y=row["non_penalty_goals"], text=row["player_name"],
                       showarrow=False, yshift=12, font=dict(size=11, color=INK_SECONDARY))
style(fig, "Non-penalty goals against shots on target", "Non-penalty shots on target", "Non-penalty goals",
      height=480)
fig.update_xaxes(rangemode="tozero")
fig.update_yaxes(rangemode="tozero")
show(st, fig)
st.caption(
    "Players above the grey line scored more non-penalty goals than an average finisher would from the same "
    "number of shots on target; players below it scored fewer. Over one season most of that gap is noise, "
    "and none of it accounts for how good the chances were. Points are nudged sideways slightly so players "
    "with the same numbers don't hide each other."
)

show_table(shown.sort_values("goals_above_average", ascending=False), {
    "player_name": ("Player", "text"), "club_name": ("Club", "text"), "position_group": ("Pos", "text"),
    "minutes": ("Mins", "int"), "non_penalty_shots": ("NP shots", "int"),
    "non_penalty_shots_on_target": ("NP SoT", "int"), "non_penalty_goals": ("NP goals", "int"),
    "np_conversion": ("Conv.", "pct"), "np_goals_per_shot_on_target": ("Goals / SoT", "pct"),
    "average_conversion_goals": ("Avg. goals", "dec1"), "goals_above_average": ("+/- avg", "signed1"),
}, height=420, help_text={"goals_above_average": HELP["goals_above_average"], "np_conversion": HELP["conversion"]})

# --- Team finishing -------------------------------------------------------------------------------
st.divider()
st.subheader("Club finishing", anchor=False)
teams = team_finishing(data.club_seasons(season_year))
teams = teams.assign(
    sot_per_match=teams["shots_on_target"] / teams["matches"],
    goals_per_match_float=teams["goals_for"] / teams["matches"],
)
competition_rate = teams["goals_for"].sum() / teams["shots_on_target"].sum()
line_x = np.array([0, float(teams["sot_per_match"].max()) * 1.05])

fig = go.Figure()
fig.add_trace(go.Scatter(x=line_x, y=line_x * competition_rate, mode="lines", name="Competition average",
                         line=dict(color=MUTED_MARK, width=2), hoverinfo="skip"))
fig.add_trace(go.Scatter(
    x=teams["sot_per_match"], y=teams["goals_per_match_float"], mode="markers", name="Clubs",
    marker=dict(color=ACCENT, size=10, line=dict(color="white", width=2)),
    customdata=teams[["club_name", "matches", "goals_per_shot_on_target"]],
    hovertemplate="%{customdata[0]} (%{customdata[1]} games)<br>%{x:.1f} shots on target / match"
                  "<br>%{y:.2f} goals / match<br>%{customdata[2]:.0%} of shots on target scored<extra></extra>",
))
style(fig, "Goals against shots on target, per match", "Shots on target per match", "Goals per match", height=420)
fig.update_xaxes(rangemode="tozero")
fig.update_yaxes(rangemode="tozero")
show(st, fig)
st.caption("Club goals include penalties and own goals in their favour, so this line sits a little higher "
           "than the player one.")

show_table(teams.sort_values("goals_per_shot_on_target", ascending=False), {
    "club_name": ("Club", "text"), "matches": ("Games", "int"), "shots": ("Shots", "int"),
    "shots_on_target": ("On target", "int"), "goals_for": ("Goals", "int"),
    "shot_accuracy": ("Accuracy", "pct"), "conversion": ("Goals / shot", "pct"),
    "goals_per_shot_on_target": ("Goals / on target", "pct"),
    "conceded_per_shot_on_target_faced": ("Conceded / on target faced", "pct"),
}, height=420, help_text={"conceded_per_shot_on_target_faced":
                          "Share of opponents' shots on target that went in. Lower usually means good goalkeeping, "
                          "or opponents shooting from worse positions."})
