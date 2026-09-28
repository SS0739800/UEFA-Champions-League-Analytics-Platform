"""Turn raw ESPN JSON into flat tables that match sql/schema.sql."""

import logging
import re
import unicodedata
from pathlib import Path

import pandas as pd

from src.config import FIRST_SEASON

log = logging.getLogger(__name__)

# ESPN isn't consistent with its stage slugs across seasons
# ("quarter-finals" vs "quarterfinals", "play-off-round" vs "playoff-round"),
# so map them all to one name. Qualifying rounds are left out on purpose:
# ESPN only has them for some seasons.
STAGE_BY_SLUG = {
    "group-stage": "group_stage",
    "league-phase": "league_phase",
    "knockout-round-playoffs": "knockout_playoff",
    "round-of-16": "round_of_16",
    "quarter-finals": "quarter_final",
    "quarterfinals": "quarter_final",
    "semi-finals": "semi_final",
    "semifinals": "semi_final",
    "final": "final",
}

QUALIFYING_SLUGS = {
    "preliminary-round",
    "qualifying-first-round",
    "qualifying-second-round",
    "qualifying-third-round",
    "play-off-round",
    "playoff-round",
    "playoffs",
}

# Order matters for "how far did this club get".
STAGE_ORDER = [
    "group_stage",
    "league_phase",
    "knockout_playoff",
    "round_of_16",
    "quarter_final",
    "semi_final",
    "final",
]

POSITION_GROUPS = {
    "G": "GK",
    "CD": "DEF", "CD-L": "DEF", "CD-R": "DEF", "LB": "DEF", "RB": "DEF",
    "LWB": "DEF", "RWB": "DEF", "SW": "DEF", "D": "DEF",
    "DM": "MID", "CM": "MID", "CM-L": "MID", "CM-R": "MID", "RCM": "MID",
    "LM": "MID", "RM": "MID", "AM": "MID", "AM-L": "MID", "AM-R": "MID", "M": "MID",
    "F": "FWD", "CF": "FWD", "CF-L": "FWD", "CF-R": "FWD", "RCF": "FWD",
    "LF": "FWD", "RF": "FWD", "ST": "FWD",
}

# ESPN stat name -> our column name.
CLUB_STAT_COLUMNS = {
    "possessionPct": "possession_pct",
    "totalShots": "shots",
    "shotsOnTarget": "shots_on_target",
    "blockedShots": "blocked_shots",
    "totalPasses": "passes",
    "accuratePasses": "passes_completed",
    "totalCrosses": "crosses",
    "accurateCrosses": "crosses_completed",
    "totalLongBalls": "long_balls",
    "accurateLongBalls": "long_balls_completed",
    "totalTackles": "tackles",
    "effectiveTackles": "tackles_won",
    "interceptions": "interceptions",
    "totalClearance": "clearances",
    "wonCorners": "corners",
    "foulsCommitted": "fouls",
    "offsides": "offsides",
    "yellowCards": "yellow_cards",
    "redCards": "red_cards",
    "saves": "saves",
}
# penaltyKickGoals/penaltyKickShots are left out on purpose. In some seasons
# penaltyKickGoals holds the team's total goals instead, so penalties are
# counted from the key events.

PLAYER_STAT_COLUMNS = {
    "totalGoals": "goals",
    "goalAssists": "assists",
    "totalShots": "shots",
    "shotsOnTarget": "shots_on_target",
    "foulsCommitted": "fouls_committed",
    "foulsSuffered": "fouls_suffered",
    "offsides": "offsides",
    "yellowCards": "yellow_cards",
    "redCards": "red_cards",
    "ownGoals": "own_goals",
    "saves": "saves",
    "goalsConceded": "goals_conceded",
    "shotsFaced": "shots_faced",
}

EVENT_TYPES = {
    "goal": "goal",
    "goal---header": "goal",
    "goal---free-kick": "goal",
    "goal---volley": "goal",
    "penalty---scored": "penalty_goal",
    "own-goal": "own_goal",
    # Saved penalties count as shots on target, misses don't, so keep them apart.
    "penalty---saved": "penalty_saved",
    "penalty---missed": "penalty_missed",
    "penalty---hit-woodwork": "penalty_missed",
    "yellow-card": "yellow_card",
    "red-card": "red_card",
    "substitution": "substitution",
}

# Key events we don't store: period markers, stoppages and VAR reviews. A VAR
# review that changes something shows up again as its own goal or card event.
IGNORED_EVENT_TYPES = {
    "kickoff", "halftime", "start-2nd-half", "end-regular-time", "start-extra-time",
    "end-extra-time", "start-shootout", "end-match", "end-first-half-extra-time",
    "start-2nd-half-extra-time", "second-half-extra-time", "halftime-extra-time",
    "start-delay", "end-delay",
}

# A few ESPN names are awkward or differ from how the clubs are usually written.
CLUB_NAME_FIXES = {
    "Internazionale": "Inter",
    "Bodo/Glimt": "Bodø/Glimt",
    "F.C. København": "FC Copenhagen",
}


def normalize_stage(slug: str) -> str | None:
    """Return our stage name, or None for qualifying rounds. Unknown slugs raise."""
    if slug in QUALIFYING_SLUGS:
        return None
    if slug not in STAGE_BY_SLUG:
        raise ValueError(f"Unknown ESPN stage slug '{slug}'. Add it to STAGE_BY_SLUG or QUALIFYING_SLUGS.")
    return STAGE_BY_SLUG[slug]


def is_main_tournament_event(event: dict) -> bool:
    season = event["season"]
    return season["year"] >= FIRST_SEASON and normalize_stage(season["slug"]) is not None


def normalize_club_name(name: str) -> str:
    # ESPN mixes composed and decomposed accents, which breaks exact matching.
    name = unicodedata.normalize("NFC", name).strip()
    name = re.sub(r"\s+", " ", name)
    return CLUB_NAME_FIXES.get(name, name)


def parse_clock(display_value: str) -> tuple[int, int]:
    """
    Turn ESPN's clock text into (minute, added time).

    "45'+2'" -> (45, 2), "73'" -> (73, 0). Empty text raises, because a
    goal or sub without a minute is something we'd want to know about.
    """
    match = re.fullmatch(r"(\d+)'(?:\+(\d+)')?", display_value.strip())
    if not match:
        raise ValueError(f"Can't read the match clock '{display_value}'")
    return int(match.group(1)), int(match.group(2) or 0)


def position_group(code: str) -> str | None:
    """Map an ESPN position code to GK/DEF/MID/FWD. Returns None for substitutes."""
    if code == "SUB":
        return None
    if code not in POSITION_GROUPS:
        log.warning("Unknown ESPN position code '%s', using UNK", code)
        return "UNK"
    return POSITION_GROUPS[code]


def is_neutral_venue(season_year: int, stage: str, espn_flag: bool | None) -> bool:
    # ESPN rarely sets neutralSite, so add the cases we know about:
    # every final, and the 2019-20 Lisbon mini-tournament from the quarter-finals on.
    if espn_flag:
        return True
    if stage == "final":
        return True
    return season_year == 2019 and stage in {"quarter_final", "semi_final"}


def parse_group_name(competition: dict) -> str | None:
    """
    Find the group letter for a group stage match.

    ESPN puts it in different places depending on the season: 'A' on its own,
    'Group A', or 'UEFA CHAMPIONS LEAGUE - GROUP A', either in the group field
    or only in the game note.
    """
    group = competition.get("group") or {}
    candidates = [group.get("abbreviation"), group.get("name"), competition.get("altGameNote")]
    for text in candidates:
        if not text:
            continue
        if re.fullmatch(r"[A-H]", text.strip()):
            return text.strip()
        found = re.search(r"\bgroup ([a-h])\b", text, flags=re.IGNORECASE)
        if found:
            return found.group(1).upper()
    return None


def _to_number(value) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


# ---------------------------------------------------------------------------
# Scoreboard events -> matches and clubs
# ---------------------------------------------------------------------------

def parse_event(event: dict) -> dict:
    """Build one matches row from a scoreboard event (ESPN ids, not our ids)."""
    competition = event["competitions"][0]
    status = event["status"]
    season_year = event["season"]["year"]
    stage = normalize_stage(event["season"]["slug"])

    teams = {team["homeAway"]: team for team in competition["competitors"]}
    home, away = teams["home"], teams["away"]
    finished = bool(status["type"]["completed"])

    group_name = parse_group_name(competition) if stage == "group_stage" else None

    leg = (competition.get("leg") or {}).get("value")
    went_to_extra_time = finished and (status.get("period") or 0) >= 3
    went_to_penalties = finished and status["type"]["name"] == "STATUS_FINAL_PEN"

    winner = None
    for team in (home, away):
        if finished and team.get("winner"):
            winner = int(team["id"])

    attendance = competition.get("attendance")

    return {
        "espn_event_id": int(event["id"]),
        "season_year": season_year,
        "stage": stage,
        "group_name": group_name,
        "leg": int(leg) if leg else None,
        "kickoff_utc": pd.Timestamp(event["date"]),
        "status": "finished" if finished else "scheduled",
        "home_espn_id": int(home["id"]),
        "away_espn_id": int(away["id"]),
        "home_goals": int(home["score"]) if finished else None,
        "away_goals": int(away["score"]) if finished else None,
        "went_to_extra_time": went_to_extra_time,
        "home_shootout_goals": home.get("shootoutScore") if went_to_penalties else None,
        "away_shootout_goals": away.get("shootoutScore") if went_to_penalties else None,
        "winner_espn_id": winner,
        "is_neutral_venue": is_neutral_venue(season_year, stage, competition.get("neutralSite")),
        "venue": (competition.get("venue") or {}).get("fullName"),
        # ESPN uses 0 both for "unknown" and for closed-door games, so we can't trust it.
        "attendance": attendance if attendance else None,
    }


def build_matches(events: list[dict]) -> pd.DataFrame:
    rows = [parse_event(event) for event in events if is_main_tournament_event(event)]
    matches = pd.DataFrame(rows).sort_values("kickoff_utc").reset_index(drop=True)
    return matches


def build_clubs(events: list[dict]) -> pd.DataFrame:
    """One row per ESPN team id, using the most recent name ESPN gives it."""
    rows = []
    for event in events:
        if not is_main_tournament_event(event):
            continue
        for competitor in event["competitions"][0]["competitors"]:
            team = competitor["team"]
            rows.append({
                "espn_team_id": int(team["id"]),
                "name": normalize_club_name(team["displayName"]),
                "short_name": normalize_club_name(team.get("shortDisplayName") or team["displayName"]),
                "abbreviation": team.get("abbreviation"),
                "seen_at": event["date"],
            })

    clubs = pd.DataFrame(rows).sort_values("seen_at")
    clubs = clubs.drop_duplicates("espn_team_id", keep="last").drop(columns="seen_at")
    return clubs.sort_values("name").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Match summaries -> stats, players and events
# ---------------------------------------------------------------------------

def parse_club_stats(summary: dict, espn_event_id: int) -> list[dict]:
    rows = []
    for team in summary.get("boxscore", {}).get("teams", []):
        stats = {stat["name"]: stat.get("displayValue") for stat in team.get("statistics", [])}
        row = {"espn_event_id": espn_event_id, "espn_team_id": int(team["team"]["id"])}
        for espn_name, column in CLUB_STAT_COLUMNS.items():
            row[column] = _to_number(stats.get(espn_name))
        rows.append(row)
    return rows


def player_minutes(player: dict, match_length: int) -> tuple[int, int]:
    """
    Work out when a player came on and went off.

    Starters begin at 0. Subs come on at the minute of their substitution.
    Players leave at their substitution off or a red card, otherwise they play
    to the end. Added time is ignored, so these are slightly low.
    """
    subs = []
    red_card_minute = None
    for play in player.get("plays", []):
        minute, _ = parse_clock(play["clock"]["displayValue"])
        if play.get("substitution"):
            subs.append(minute)
        if play.get("redCard"):
            red_card_minute = minute

    subs.sort()
    if player["starter"]:
        minute_on = 0
        minute_off = subs[0] if player.get("subbedOut") and subs else match_length
    else:
        minute_on = subs[0] if subs else match_length
        minute_off = subs[1] if player.get("subbedOut") and len(subs) > 1 else match_length

    if red_card_minute is not None:
        minute_off = min(minute_off, red_card_minute)

    minute_on = min(minute_on, match_length)
    minute_off = max(min(minute_off, match_length), minute_on)
    return minute_on, minute_off


def parse_player_stats(summary: dict, espn_event_id: int, match_length: int) -> list[dict]:
    rows = []
    for roster in summary.get("rosters", []):
        espn_team_id = int(roster["team"]["id"])
        for player in roster.get("roster", []):
            # Unused substitutes are listed too. Leave them out.
            if not (player.get("starter") or player.get("subbedIn")):
                continue

            minute_on, minute_off = player_minutes(player, match_length)
            stats = {stat["name"]: stat.get("value") for stat in player.get("stats", [])}
            code = player.get("position", {}).get("abbreviation")
            row = {
                "espn_event_id": espn_event_id,
                "espn_athlete_id": int(player["athlete"]["id"]),
                "player_name": player["athlete"]["displayName"],
                "espn_team_id": espn_team_id,
                "position": None if code == "SUB" else code,
                "position_group": position_group(code) if code else "UNK",
                "is_starter": bool(player["starter"]),
                "minute_on": minute_on,
                "minute_off": minute_off,
                "minutes_played": minute_off - minute_on,
            }
            for espn_name, column in PLAYER_STAT_COLUMNS.items():
                row[column] = int(stats.get(espn_name) or 0)
            rows.append(row)
    return rows


def parse_key_events(summary: dict, espn_event_id: int) -> list[dict]:
    rows = []
    for key_event in summary.get("keyEvents", []):
        espn_type = key_event["type"].get("type", "")
        # Period 5 is the shootout. Cards can be shown there too, but they're
        # not part of the match we analyse.
        if key_event.get("shootout") or key_event["period"]["number"] > 4:
            continue
        if espn_type in IGNORED_EVENT_TYPES or espn_type.startswith("var---"):
            continue
        if espn_type not in EVENT_TYPES:
            log.warning("Skipping unknown key event type '%s' in event %s", espn_type, espn_event_id)
            continue

        minute, added = parse_clock(key_event["clock"]["displayValue"])
        participants = key_event.get("participants") or []
        athlete_ids = [int(p["athlete"]["id"]) for p in participants]
        athlete_names = [p["athlete"].get("displayName") for p in participants]
        team = key_event.get("team") or {}

        rows.append({
            "espn_event_id": espn_event_id,
            "espn_play_id": int(key_event["id"]),
            "event_type": EVENT_TYPES[espn_type],
            # For own goals ESPN credits the team that benefits, which is what we want.
            "espn_team_id": int(team["id"]) if team.get("id") else None,
            "espn_athlete_id": athlete_ids[0] if athlete_ids else None,
            "player_name": athlete_names[0] if athlete_names else None,
            "secondary_espn_athlete_id": athlete_ids[1] if len(athlete_ids) > 1 else None,
            "secondary_player_name": athlete_names[1] if len(athlete_names) > 1 else None,
            "period": key_event["period"]["number"],
            "minute": minute,
            "added_time": added,
        })
    return rows


def fill_sub_positions(player_stats: pd.DataFrame) -> pd.DataFrame:
    """
    Substitutes come through as 'SUB', so borrow the position group the player
    most often starts in. Players who never started stay UNK.
    """
    starts = player_stats[player_stats["position_group"].notna() & player_stats["is_starter"]]
    usual_group = starts.groupby("espn_athlete_id")["position_group"].agg(lambda groups: groups.mode().iloc[0])

    player_stats = player_stats.copy()
    missing = player_stats["position_group"].isna()
    player_stats.loc[missing, "position_group"] = (
        player_stats.loc[missing, "espn_athlete_id"].map(usual_group).fillna("UNK")
    )
    return player_stats


def drop_repeated_roster_rows(player_stats: pd.DataFrame) -> pd.DataFrame:
    """
    A few 2018-19 matches list the goalkeeper twice with identical stats.
    Drop exact copies only. If a player shows up twice with different numbers,
    leave both so validation fails and someone looks at it.
    """
    deduplicated = player_stats.drop_duplicates()
    dropped = len(player_stats) - len(deduplicated)
    if dropped:
        log.warning("Dropped %s exact duplicate player rows from ESPN rosters", dropped)
    return deduplicated.reset_index(drop=True)


def goals_after_90(events: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """Count goals in the first two periods for each finished match."""
    goal_types = {"goal", "penalty_goal", "own_goal"}
    regular_goals = events[events["event_type"].isin(goal_types) & (events["period"] <= 2)]
    counts = regular_goals.groupby(["espn_event_id", "espn_team_id"]).size()

    def count_for(row, side):
        if row["status"] != "finished":
            return None
        return int(counts.get((row["espn_event_id"], row[f"{side}_espn_id"]), 0))

    matches = matches.copy()
    matches["home_goals_90"] = matches.apply(count_for, axis=1, side="home")
    matches["away_goals_90"] = matches.apply(count_for, axis=1, side="away")
    return matches


def transform(events: list[dict], summary_dir: Path) -> dict[str, pd.DataFrame]:
    """Build every table from the raw scoreboard events and summary files."""
    from src.etl.extract import load_json

    matches = build_matches(events)
    clubs = build_clubs(events)

    club_stats, player_stats, key_events = [], [], []
    finished = matches[matches["status"] == "finished"]
    for match in finished.itertuples():
        path = summary_dir / f"{match.espn_event_id}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"Missing summary for finished match {match.espn_event_id}. Run the pipeline without --offline."
            )
        summary = load_json(path)
        match_length = 120 if match.went_to_extra_time else 90
        club_stats += parse_club_stats(summary, match.espn_event_id)
        player_stats += parse_player_stats(summary, match.espn_event_id, match_length)
        key_events += parse_key_events(summary, match.espn_event_id)

    club_stats = pd.DataFrame(club_stats)
    player_stats = drop_repeated_roster_rows(pd.DataFrame(player_stats))
    player_stats = fill_sub_positions(player_stats)
    key_events = pd.DataFrame(key_events)
    matches = goals_after_90(key_events, matches)

    # Players can appear in key events without a roster entry, so collect names from both.
    names = pd.concat([
        player_stats[["espn_athlete_id", "player_name"]],
        key_events[["espn_athlete_id", "player_name"]],
        key_events[["secondary_espn_athlete_id", "secondary_player_name"]].set_axis(
            ["espn_athlete_id", "player_name"], axis=1
        ),
    ]).dropna()
    players = (
        names.assign(espn_athlete_id=names["espn_athlete_id"].astype(int))
        .drop_duplicates("espn_athlete_id", keep="last")
        .rename(columns={"player_name": "full_name"})
        .sort_values("espn_athlete_id")
        .reset_index(drop=True)
    )

    log.info(
        "Transformed %s matches (%s finished), %s clubs, %s players, %s key events",
        len(matches), len(finished), len(clubs), len(players), len(key_events),
    )
    return {
        "matches": matches,
        "clubs": clubs,
        "players": players,
        "club_match_stats": club_stats,
        "player_match_stats": player_stats.drop(columns="player_name"),
        "match_events": key_events.drop(columns=["player_name", "secondary_player_name"]),
    }
