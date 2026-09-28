"""
Club style profiles from team match stats, and clustering on top of them.

A "profile" here is just per-match averages of things like possession, passing
volume and defensive actions. The clusters group clubs whose numbers look
alike. They are statistical groups, not tactical labels: two clubs can land in
the same cluster for very different reasons (a pressing side and a deep block
can both make lots of tackles, for example).

ESPN has no progressive passing, pressing or final-third data, so those
dimensions aren't here.
"""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

PROFILE_FEATURES = {
    "possession_pct": "Possession %",
    "passes": "Passes / match",
    "pass_completion": "Pass completion",
    "long_ball_share": "Long balls / passes",
    "crosses": "Crosses / match",
    "shots": "Shots / match",
    "shots_against": "Shots faced / match",
    "tackles": "Tackles / match",
    "interceptions": "Interceptions / match",
    "clearances": "Clearances / match",
    "fouls": "Fouls / match",
}

# Interceptions are missing up to 2017-18, and several other stats are missing
# in 2017-18 (see DATA_SOURCES.md), so clustering starts in 2018-19.
FIRST_PROFILE_SEASON = 2018


def club_profiles(club_matches: pd.DataFrame, min_matches: int = 4) -> pd.DataFrame:
    """Per-match averages for each club-season, from v_club_matches rows."""
    frame = club_matches[club_matches["season_year"] >= FIRST_PROFILE_SEASON]
    grouped = frame.groupby(["season_year", "season", "club_id"])
    profiles = grouped.agg(
        matches=("match_id", "size"),
        possession_pct=("possession_pct", "mean"),
        passes=("passes", "mean"),
        passes_completed=("passes_completed", "sum"),
        total_passes=("passes", "sum"),
        long_balls=("long_balls", "sum"),
        crosses=("crosses", "mean"),
        shots=("shots", "mean"),
        shots_against=("shots_against", "mean"),
        tackles=("tackles", "mean"),
        interceptions=("interceptions", "mean"),
        clearances=("clearances", "mean"),
        fouls=("fouls", "mean"),
    ).reset_index()

    profiles["pass_completion"] = profiles["passes_completed"] / profiles["total_passes"]
    profiles["long_ball_share"] = profiles["long_balls"] / profiles["total_passes"]
    profiles = profiles.drop(columns=["passes_completed", "total_passes", "long_balls"])

    # A club with two or three games doesn't have a stable profile yet.
    return profiles[profiles["matches"] >= min_matches].reset_index(drop=True)


def standardize(profiles: pd.DataFrame) -> tuple[np.ndarray, StandardScaler]:
    scaler = StandardScaler()
    scaled = scaler.fit_transform(profiles[list(PROFILE_FEATURES)])
    return scaled, scaler


def silhouette_by_k(scaled: np.ndarray, k_values=range(2, 9), random_state: int = 7) -> pd.DataFrame:
    """Silhouette score for each number of clusters. Higher means better separated groups."""
    rows = []
    for k in k_values:
        labels = KMeans(n_clusters=k, n_init=20, random_state=random_state).fit_predict(scaled)
        rows.append({"k": k, "silhouette": silhouette_score(scaled, labels)})
    return pd.DataFrame(rows)


def cluster_profiles(profiles: pd.DataFrame, k: int | None = None, random_state: int = 7) -> dict:
    """
    Cluster club-seasons with k-means on standardized profile features.

    If k isn't given, pick the one with the best silhouette score. Returns the
    profiles with a cluster column, 2D PCA coordinates for plotting, the
    silhouette table and each cluster's average z-scores.
    """
    scaled, _ = standardize(profiles)
    silhouettes = silhouette_by_k(scaled, random_state=random_state)
    if k is None:
        k = int(silhouettes.loc[silhouettes["silhouette"].idxmax(), "k"])

    model = KMeans(n_clusters=k, n_init=20, random_state=random_state)
    labels = model.fit_predict(scaled)

    pca = PCA(n_components=2, random_state=random_state)
    coordinates = pca.fit_transform(scaled)

    result = profiles.copy()
    # Number clusters from 1 for display.
    result["cluster"] = labels + 1
    result["pc1"] = coordinates[:, 0]
    result["pc2"] = coordinates[:, 1]

    centres = pd.DataFrame(model.cluster_centers_, columns=list(PROFILE_FEATURES))
    centres.index = centres.index + 1
    centres["clubs"] = pd.Series(labels + 1).value_counts().sort_index()

    loadings = pd.DataFrame(pca.components_.T, index=list(PROFILE_FEATURES), columns=["pc1", "pc2"])

    return {
        "profiles": result,
        "k": k,
        "silhouettes": silhouettes,
        "centres": centres,
        "pca_loadings": loadings,
        "explained_variance": pca.explained_variance_ratio_,
    }


def describe_cluster(centre: pd.Series, top_n: int = 2) -> str:
    """
    Plain description of a cluster from its average z-scores, e.g.
    "More possession % and passes / match; fewer clearances / match than average."
    """
    values = centre[list(PROFILE_FEATURES)]
    highest = values.sort_values(ascending=False).head(top_n)
    lowest = values.sort_values().head(top_n)

    def names(series):
        return " and ".join(PROFILE_FEATURES[name].lower() for name in series.index)

    parts = []
    if (highest > 0.3).any():
        parts.append(f"Higher {names(highest[highest > 0.3])}")
    if (lowest < -0.3).any():
        parts.append(f"lower {names(lowest[lowest < -0.3])}")
    if not parts:
        return "Close to average on every measure"
    return "; ".join(parts) + " than average"


def similar_clubs(profiles: pd.DataFrame, season_year: int, club_id: int, n: int = 5) -> pd.DataFrame:
    """
    Club-seasons with the closest profiles to one club-season, by distance in
    standardized feature space. Looks across every season, not just the same one.
    """
    scaled, _ = standardize(profiles)
    target = profiles.index[(profiles["season_year"] == season_year) & (profiles["club_id"] == club_id)]
    if target.empty:
        raise KeyError(f"No profile for club {club_id} in {season_year}. It may have too few matches.")

    distances = np.linalg.norm(scaled - scaled[target[0]], axis=1)
    result = profiles.assign(distance=distances).drop(index=target[0])
    return result.nsmallest(n, "distance")
