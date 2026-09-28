"""
Shared helpers for tests.

The fixtures here are small, made-up matches between clubs like "Home FC" and
"Away FC". They copy the shape of ESPN's JSON so the parsing code can be tested
without the network. None of these numbers are real.
"""

import pandas as pd
import pytest


def make_event(
    event_id="1",
    season_year=2023,
    slug="group-stage",
    date="2023-09-19T19:00Z",
    home=("100", "Home FC"),
    away=("200", "Away FC"),
    home_score="2",
    away_score="1",
    completed=True,
    status_name="STATUS_FULL_TIME",
    period=2,
    extra_competition=None,
    home_extra=None,
    away_extra=None,
):
    home_team = {"id": home[0], "homeAway": "home", "score": home_score, "winner": int(home_score) > int(away_score),
                 "team": {"id": home[0], "displayName": home[1], "shortDisplayName": home[1], "abbreviation": "HOM"}}
    away_team = {"id": away[0], "homeAway": "away", "score": away_score, "winner": int(away_score) > int(home_score),
                 "team": {"id": away[0], "displayName": away[1], "shortDisplayName": away[1], "abbreviation": "AWY"}}
    home_team.update(home_extra or {})
    away_team.update(away_extra or {})
    competition = {
        # ESPN lists the away side first sometimes, so do that here too.
        "competitors": [away_team, home_team],
        "venue": {"fullName": "Test Stadium"},
        "attendance": 40000,
        "altGameNote": "UEFA Champions League, Group A",
    }
    competition.update(extra_competition or {})
    return {
        "id": event_id,
        "date": date,
        "season": {"year": season_year, "slug": slug},
        "status": {"period": period, "type": {"name": status_name, "completed": completed}},
        "competitions": [competition],
    }


def roster_player(athlete_id, name, position="CM", starter=True, subbed_in=False, subbed_out=False,
                  plays=None, stats=None):
    return {
        "athlete": {"id": str(athlete_id), "displayName": name},
        "position": {"abbreviation": position},
        "starter": starter,
        "subbedIn": subbed_in,
        "subbedOut": subbed_out,
        "plays": plays or [],
        "stats": [{"name": key, "value": value} for key, value in (stats or {}).items()],
    }


def play(minute_text, substitution=False, red_card=False):
    return {"clock": {"displayValue": minute_text}, "substitution": substitution, "redCard": red_card}


def key_event(play_id, event_type, team_id, minute_text, period, athletes=(), shootout=False):
    return {
        "id": str(play_id),
        "type": {"type": event_type},
        "team": {"id": str(team_id)} if team_id else None,
        "clock": {"displayValue": minute_text},
        "period": {"number": period},
        "participants": [{"athlete": {"id": str(a), "displayName": f"Player {a}"}} for a in athletes],
        "shootout": shootout,
    }


@pytest.fixture
def simple_matches():
    """Four made-up matches between three clubs, in kickoff order."""
    return pd.DataFrame({
        "match_id": [1, 2, 3, 4],
        "season_year": [2020, 2020, 2020, 2020],
        "stage": ["group_stage"] * 4,
        "leg": [None] * 4,
        "kickoff_utc": pd.to_datetime(
            ["2020-10-01", "2020-10-08", "2020-10-15", "2020-10-22"], utc=True
        ),
        "status": ["finished", "finished", "finished", "scheduled"],
        "home_club_id": [10, 20, 10, 30],
        "away_club_id": [20, 30, 30, 10],
        "home_goals": [2, 1, 0, None],
        "away_goals": [0, 1, 3, None],
        "home_goals_90": [2, 1, 0, None],
        "away_goals_90": [0, 1, 3, None],
        "is_neutral_venue": [False] * 4,
    })
