import sys
from pathlib import Path

# `streamlit run` only puts app/ on the import path, so add the project root for `app` and `src`.
PROJECT_ROOT = next(path for path in Path(__file__).resolve().parents if (path / "src").is_dir())
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from app.components import data
from app.components.charts import ACCENT, DIVERGING, INK, INK_MUTED, MARKER_RING, MUTED_MARK, SERIES, show, style
from app.components.sidebar import PAGE_ICON, footer, page_header, season_picker
from app.components.tables import show_table
from src.analysis.tactical import (
    PROFILE_FEATURES,
    club_profiles,
    cluster_profiles,
    describe_cluster,
    similar_clubs,
)

st.set_page_config(page_title="Tactical Analysis | UCL Analytics", page_icon=PAGE_ICON, layout="wide")
page_header("Tactical Analysis", "Style profiles from team stats, clubs grouped by how their numbers look.")


@st.cache_data(ttl=3600, show_spinner="Clustering club profiles...")
def build_clusters(min_matches: int, k: int | None):
    profiles = club_profiles(data.club_matches(), min_matches=min_matches)
    return profiles, cluster_profiles(profiles, k=k)



st.caption(
    "Each club-season is described by per-match averages: possession, passing volume and accuracy, long-ball "
    "share, crosses, shots taken and faced, tackles, interceptions, clearances and fouls. Only seasons from "
    "2018-19 are used because older seasons are missing some of these stats. Progressive passing, pressing "
    "and final-third data aren't available."
)

profiles, auto = build_clusters(min_matches=4, k=None)
silhouettes = auto["silhouettes"]

# Only offer seasons where at least some clubs have played enough games to be clustered.
def with_club_names(frame):
    """Add club names. Profiles only carry ids, and a club's name can be looked up per season."""
    names = data.club_seasons().set_index(["season_year", "club_id"])["club_name"]
    keys = list(zip(frame["season_year"], frame["club_id"]))
    return frame.assign(club_name=[names.get(key, "") for key in keys])


season_year = season_picker(allowed=set(profiles["season_year"]))
footer()

with st.sidebar:
    k = st.slider("Number of clusters", 2, 8, auto["k"],
                  help=f"Defaults to the best silhouette score (k = {auto['k']}).")
_, result = build_clusters(min_matches=4, k=k)
clustered = result["profiles"]
centres = result["centres"]

st.caption("Clubs need at least four matches in a season to be included, so the current season appears "
           "once enough games have been played.")

# --- Choosing k ----------------------------------------------------------------------------
left, right = st.columns([2, 3], gap="large")
with left:
    fig = go.Figure(go.Scatter(
        x=silhouettes["k"], y=silhouettes["silhouette"], mode="lines+markers",
        line=dict(color=ACCENT, width=2), marker=dict(size=8),
        hovertemplate="k = %{x}<br>Silhouette: %{y:.3f}<extra></extra>",
    ))
    fig.add_vline(x=k, line_color=MUTED_MARK, line_width=1)
    style(fig, "How well separated are the clusters?", "Number of clusters (k)", "Silhouette score", height=320)
    show(st, fig)
    best = silhouettes["silhouette"].max()
    st.caption(
        f"{len(clustered)} club-seasons. Silhouette runs from -1 to 1; the best here is {best:.2f}, which means the "
        "groups overlap a lot. Club styles sit on a spectrum more than in neat boxes, so treat the clusters as a "
        "rough summary."
    )

with right:
    labels = [PROFILE_FEATURES[name] for name in PROFILE_FEATURES]
    z = centres[list(PROFILE_FEATURES)].to_numpy()
    fig = go.Figure(go.Heatmap(
        z=z, x=labels, y=[f"Cluster {i} ({n} club-seasons)" for i, n in zip(centres.index, centres["clubs"])],
        colorscale=DIVERGING, zmid=0, zmin=-2, zmax=2,
        colorbar=dict(title="z-score", thickness=10), xgap=2, ygap=2,
        hovertemplate="%{y}<br>%{x}: %{z:+.2f} SD from average<extra></extra>",
    ))
    style(fig, "What each cluster looks like (average z-scores)", None, None, height=320)
    fig.update_xaxes(tickangle=-35, showline=False)
    fig.update_yaxes(autorange="reversed")
    show(st, fig)

cluster_lines = [
    f"- **Cluster {i}** ({centres.loc[i, 'clubs']} club-seasons): {describe_cluster(centres.loc[i])}."
    for i in centres.index
]
st.markdown("\n".join(cluster_lines))
st.caption("Descriptions list the features more than 0.3 standard deviations from average. They describe the "
           "numbers, not a playing philosophy: lots of tackles can mean pressing high or defending deep.")

# --- Map of clubs --------------------------------------------------------------------------
st.divider()
loadings = result["pca_loadings"]
explained = result["explained_variance"]


def axis_label(component: str, share: float) -> str:
    top = loadings[component].abs().nlargest(2).index
    names = " & ".join(PROFILE_FEATURES[name].lower() for name in top)
    return f"{component.upper()} ({share:.0%} of variance, mostly {names})"


in_season = clustered[clustered["season_year"] == season_year]
others = clustered[clustered["season_year"] != season_year]
hover = "%{customdata[0]} %{customdata[1]}<br>Cluster %{customdata[2]}<extra></extra>"

if k <= 3:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=others["pc1"], y=others["pc2"], mode="markers", name="Other seasons",
        marker=dict(color=MUTED_MARK, size=6, opacity=0.5),
        customdata=others[["season", "club_id", "cluster"]], hoverinfo="skip",
    ))
    for cluster in range(1, k + 1):
        subset = in_season[in_season["cluster"] == cluster]
        subset = with_club_names(subset)
        fig.add_trace(go.Scatter(
            x=subset["pc1"], y=subset["pc2"], mode="markers", name=f"Cluster {cluster}",
            marker=dict(color=SERIES[cluster - 1], size=10, line=MARKER_RING),
            customdata=subset[["season", "club_name", "cluster"]],
            hovertemplate="%{customdata[1]} (%{customdata[0]})<br>Cluster %{customdata[2]}<extra></extra>",
        ))
    style(fig, "Club-season map (clubs from the selected season in colour)",
          axis_label("pc1", explained[0]), axis_label("pc2", explained[1]), height=480)
    show(st, fig)
else:
    # More than three groups is too many colours for one scatter, so draw one small panel per cluster.
    titles = [f"Cluster {i}" for i in range(1, k + 1)]
    fig = make_subplots(rows=1, cols=k, shared_yaxes=True, subplot_titles=titles)
    for cluster in range(1, k + 1):
        rest = clustered[clustered["cluster"] != cluster]
        fig.add_trace(go.Scatter(x=rest["pc1"], y=rest["pc2"], mode="markers", showlegend=False,
                                 marker=dict(color=MUTED_MARK, size=4, opacity=0.4), hoverinfo="skip"),
                      row=1, col=cluster)
        subset = in_season[in_season["cluster"] == cluster]
        subset = with_club_names(subset)
        fig.add_trace(go.Scatter(
            x=subset["pc1"], y=subset["pc2"], mode="markers", showlegend=False,
            marker=dict(color=ACCENT, size=8, line=MARKER_RING),
            customdata=subset[["season", "club_name"]],
            hovertemplate="%{customdata[1]} (%{customdata[0]})<extra></extra>",
        ), row=1, col=cluster)
    style(fig, "Club-season map, one panel per cluster (selected season in blue)", None, None, height=380)
    show(st, fig)
    st.caption(f"Horizontal: {axis_label('pc1', explained[0])}. Vertical: {axis_label('pc2', explained[1])}.")

st.caption("The map squeezes eleven stats into two directions with PCA, so some differences between clubs are "
           "lost. Clusters were found using all eleven stats, not these two axes.")

# --- One club ------------------------------------------------------------------------------
st.divider()
season_clubs = data.club_seasons(season_year)
available = season_clubs[season_clubs["club_id"].isin(in_season["club_id"])].sort_values("club_name")
if available.empty:
    st.stop()

club_names = available["club_name"].tolist()
remembered = st.session_state.get("shared_club")
club_name = st.selectbox("Club", club_names, index=club_names.index(remembered) if remembered in club_names else 0)
st.session_state["shared_club"] = club_name
club_id = int(available.loc[available["club_name"] == club_name, "club_id"].iloc[0])

row = clustered[(clustered["season_year"] == season_year) & (clustered["club_id"] == club_id)].iloc[0]
season_rows = clustered[clustered["season_year"] == season_year]

left, right = st.columns(2, gap="large")
with left:
    percentiles = {PROFILE_FEATURES[f]: (season_rows[f] <= row[f]).mean() * 100 for f in PROFILE_FEATURES}
    fig = go.Figure(go.Bar(
        y=list(percentiles)[::-1], x=list(percentiles.values())[::-1], orientation="h", marker_color=ACCENT,
        customdata=[round(row[f], 3) for f in PROFILE_FEATURES][::-1],
        hovertemplate="%{y}<br>Value: %{customdata}<br>Percentile: %{x:.0f}<extra></extra>",
    ))
    fig.add_vline(x=50, line_color=MUTED_MARK, line_width=1)
    style(fig, f"{club_name}: style percentiles this season", "Percentile among clubs this season", None, height=420)
    fig.update_xaxes(range=[0, 100])
    show(st, fig)
    st.caption(f"Cluster {int(row['cluster'])}. High isn't good or bad here: a high clearances percentile "
               "means the club made more clearances than most.")

with right:
    similar = similar_clubs(clustered, season_year, club_id, n=8)
    similar = with_club_names(similar)
    st.markdown(f"**Closest profiles to {club_name} {row['season']}**")
    show_table(similar, {
        "club_name": ("Club", "text"), "season": ("Season", "text"), "cluster": ("Cluster", "int"),
        "distance": ("Distance", "dec2"),
    }, height=340)
    st.caption("Distance is measured across all eleven standardized stats and every season since 2018-19. "
               "Smaller means more alike.")

# --- Possession against defending ------------------------------------------------------------
st.divider()
season_named = season_rows.merge(season_clubs[["club_id", "club_name"]], on="club_id")
fig = go.Figure(go.Scatter(
    x=season_named["possession_pct"], y=season_named["shots_against"], mode="markers",
    marker=dict(color=[ACCENT if c == club_id else MUTED_MARK for c in season_named["club_id"]],
                size=[16 if c == club_id else 9 for c in season_named["club_id"]], line=MARKER_RING),
    customdata=season_named[["club_name"]],
    hovertemplate="%{customdata[0]}<br>Possession %{x:.1f}%<br>Shots faced %{y:.1f} / match<extra></extra>",
))
fig.add_vline(x=season_named["possession_pct"].median(), line_color=MUTED_MARK, line_width=1)
fig.add_hline(y=season_named["shots_against"].median(), line_color=MUTED_MARK, line_width=1)
# Name the selected club on the chart, so it doesn't rely on colour alone.
selected = season_named[season_named["club_id"] == club_id].iloc[0]
fig.add_annotation(x=selected["possession_pct"], y=selected["shots_against"], text=club_name, showarrow=False,
                   yshift=18, font=dict(color=INK, size=12))
style(fig, "Possession against shots faced", "Average possession (%)", "Shots faced per match", height=420)
fig.update_yaxes(autorange="reversed")
fig.add_annotation(x=0.01, y=0.99, xref="paper", yref="paper", showarrow=False, xanchor="left", yanchor="top",
                   text="Less of the ball, few shots faced", font=dict(color=INK_MUTED, size=11))
fig.add_annotation(x=0.99, y=0.01, xref="paper", yref="paper", showarrow=False, xanchor="right", yanchor="bottom",
                   text="More of the ball, many shots faced", font=dict(color=INK_MUTED, size=11))
show(st, fig)
st.caption(f"{club_name} is highlighted. The y-axis is flipped so clubs that allow fewer shots sit higher. "
           "Lines mark the season medians. Top-left clubs keep opponents quiet without much possession.")
