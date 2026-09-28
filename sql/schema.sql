-- UCL Analytics schema (PostgreSQL).
--
-- The ETL rebuilds everything from raw files, so this script drops and recreates
-- tables. Season-level numbers (standings, season totals, per-90 stats) are views
-- in views.sql, not tables, so they can't drift out of sync with the match data.

DROP VIEW IF EXISTS v_player_season_stats, v_club_season_stats, v_group_standings, v_club_matches CASCADE;
DROP TABLE IF EXISTS
    model_evaluation,
    match_predictions,
    club_elo,
    match_events,
    player_match_stats,
    club_match_stats,
    matches,
    players,
    clubs,
    seasons,
    competitions
CASCADE;


CREATE TABLE competitions (
    competition_id  SMALLSERIAL PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    espn_slug       TEXT NOT NULL UNIQUE
);

CREATE TABLE seasons (
    season_id       SMALLSERIAL PRIMARY KEY,
    competition_id  SMALLINT NOT NULL REFERENCES competitions (competition_id),
    start_year      SMALLINT NOT NULL,
    label           TEXT NOT NULL,                       -- e.g. '2026-27'
    format          TEXT NOT NULL CHECK (format IN ('group_stage', 'league_phase')),
    UNIQUE (competition_id, start_year)
);

CREATE TABLE clubs (
    club_id         SERIAL PRIMARY KEY,
    espn_team_id    INTEGER NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    short_name      TEXT NOT NULL,
    abbreviation    TEXT
);

CREATE TABLE players (
    player_id       SERIAL PRIMARY KEY,
    espn_athlete_id INTEGER NOT NULL UNIQUE,
    full_name       TEXT NOT NULL
);

CREATE TABLE matches (
    match_id            SERIAL PRIMARY KEY,
    espn_event_id       BIGINT NOT NULL UNIQUE,
    season_id           SMALLINT NOT NULL REFERENCES seasons (season_id),
    stage               TEXT NOT NULL CHECK (stage IN (
                            'group_stage', 'league_phase', 'knockout_playoff',
                            'round_of_16', 'quarter_final', 'semi_final', 'final')),
    group_name          TEXT,                            -- 'A' to 'H', group stage only
    leg                 SMALLINT CHECK (leg IN (1, 2)),  -- NULL for single matches
    kickoff_utc         TIMESTAMPTZ NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('scheduled', 'finished')),
    home_club_id        INTEGER NOT NULL REFERENCES clubs (club_id),
    away_club_id        INTEGER NOT NULL REFERENCES clubs (club_id),
    -- Final score including extra time, but not penalties.
    home_goals          SMALLINT CHECK (home_goals >= 0),
    away_goals          SMALLINT CHECK (away_goals >= 0),
    -- Score after 90 minutes, rebuilt from goal events. The prediction target uses this.
    home_goals_90       SMALLINT CHECK (home_goals_90 >= 0),
    away_goals_90       SMALLINT CHECK (away_goals_90 >= 0),
    went_to_extra_time  BOOLEAN NOT NULL DEFAULT FALSE,
    home_shootout_goals SMALLINT,
    away_shootout_goals SMALLINT,
    -- ESPN's winner flag. For a first leg this is just who won the game, not the tie.
    winner_club_id      INTEGER REFERENCES clubs (club_id),
    is_neutral_venue    BOOLEAN NOT NULL DEFAULT FALSE,
    venue               TEXT,
    attendance          INTEGER CHECK (attendance >= 0),
    CHECK (home_club_id <> away_club_id),
    CHECK (status = 'scheduled' OR (home_goals IS NOT NULL AND away_goals IS NOT NULL)),
    CHECK (group_name IS NULL OR stage = 'group_stage')
);

CREATE INDEX idx_matches_season ON matches (season_id, stage);
CREATE INDEX idx_matches_home_club ON matches (home_club_id);
CREATE INDEX idx_matches_away_club ON matches (away_club_id);
CREATE INDEX idx_matches_kickoff ON matches (kickoff_utc);

-- One row per club per finished match. Home/away and the opponent come from matches.
CREATE TABLE club_match_stats (
    match_id                INTEGER NOT NULL REFERENCES matches (match_id) ON DELETE CASCADE,
    club_id                 INTEGER NOT NULL REFERENCES clubs (club_id),
    possession_pct          NUMERIC(4, 1) CHECK (possession_pct BETWEEN 0 AND 100),
    shots                   SMALLINT CHECK (shots >= 0),
    shots_on_target         SMALLINT CHECK (shots_on_target >= 0),
    blocked_shots           SMALLINT CHECK (blocked_shots >= 0),
    passes                  SMALLINT CHECK (passes >= 0),
    passes_completed        SMALLINT CHECK (passes_completed >= 0),
    crosses                 SMALLINT CHECK (crosses >= 0),
    crosses_completed       SMALLINT CHECK (crosses_completed >= 0),
    long_balls              SMALLINT CHECK (long_balls >= 0),
    long_balls_completed    SMALLINT CHECK (long_balls_completed >= 0),
    tackles                 SMALLINT CHECK (tackles >= 0),
    tackles_won             SMALLINT CHECK (tackles_won >= 0),
    interceptions           SMALLINT CHECK (interceptions >= 0),
    clearances              SMALLINT CHECK (clearances >= 0),
    corners                 SMALLINT CHECK (corners >= 0),
    fouls                   SMALLINT CHECK (fouls >= 0),
    offsides                SMALLINT CHECK (offsides >= 0),
    yellow_cards            SMALLINT CHECK (yellow_cards >= 0),
    red_cards               SMALLINT CHECK (red_cards >= 0),
    saves                   SMALLINT CHECK (saves >= 0),
    PRIMARY KEY (match_id, club_id),
    CHECK (shots_on_target <= shots),
    CHECK (passes_completed <= passes),
    CHECK (crosses_completed <= crosses),
    CHECK (long_balls_completed <= long_balls)
);

CREATE INDEX idx_club_match_stats_club ON club_match_stats (club_id);

-- Only players who actually got on the pitch.
CREATE TABLE player_match_stats (
    match_id            INTEGER NOT NULL REFERENCES matches (match_id) ON DELETE CASCADE,
    player_id           INTEGER NOT NULL REFERENCES players (player_id),
    club_id             INTEGER NOT NULL REFERENCES clubs (club_id),
    position            TEXT,                            -- ESPN code, e.g. 'CD-L', 'LM', 'F'
    position_group      TEXT NOT NULL CHECK (position_group IN ('GK', 'DEF', 'MID', 'FWD', 'UNK')),
    is_starter          BOOLEAN NOT NULL,
    minute_on           SMALLINT NOT NULL CHECK (minute_on >= 0),
    minute_off          SMALLINT NOT NULL,
    minutes_played      SMALLINT NOT NULL CHECK (minutes_played BETWEEN 0 AND 120),
    goals               SMALLINT NOT NULL DEFAULT 0 CHECK (goals >= 0),
    assists             SMALLINT NOT NULL DEFAULT 0 CHECK (assists >= 0),
    shots               SMALLINT NOT NULL DEFAULT 0 CHECK (shots >= 0),
    shots_on_target     SMALLINT NOT NULL DEFAULT 0 CHECK (shots_on_target >= 0),
    fouls_committed     SMALLINT NOT NULL DEFAULT 0 CHECK (fouls_committed >= 0),
    fouls_suffered      SMALLINT NOT NULL DEFAULT 0 CHECK (fouls_suffered >= 0),
    offsides            SMALLINT NOT NULL DEFAULT 0 CHECK (offsides >= 0),
    yellow_cards        SMALLINT NOT NULL DEFAULT 0 CHECK (yellow_cards >= 0),
    red_cards           SMALLINT NOT NULL DEFAULT 0 CHECK (red_cards >= 0),
    own_goals           SMALLINT NOT NULL DEFAULT 0 CHECK (own_goals >= 0),
    saves               SMALLINT NOT NULL DEFAULT 0 CHECK (saves >= 0),
    goals_conceded      SMALLINT NOT NULL DEFAULT 0 CHECK (goals_conceded >= 0),
    shots_faced         SMALLINT NOT NULL DEFAULT 0 CHECK (shots_faced >= 0),
    PRIMARY KEY (match_id, player_id),
    CHECK (minute_off >= minute_on)
);

CREATE INDEX idx_player_match_stats_player ON player_match_stats (player_id);
CREATE INDEX idx_player_match_stats_club ON player_match_stats (club_id);

CREATE TABLE match_events (
    event_id            SERIAL PRIMARY KEY,
    match_id            INTEGER NOT NULL REFERENCES matches (match_id) ON DELETE CASCADE,
    espn_play_id        BIGINT NOT NULL,
    -- club_id is the club credited with the event. For own goals that's the
    -- club that benefits, not the player's own club.
    event_type          TEXT NOT NULL CHECK (event_type IN (
                            'goal', 'penalty_goal', 'own_goal', 'penalty_saved', 'penalty_missed',
                            'yellow_card', 'red_card', 'substitution')),
    club_id             INTEGER REFERENCES clubs (club_id),
    player_id           INTEGER REFERENCES players (player_id),
    -- Second person involved: the assister for goals, the player coming off for subs.
    secondary_player_id INTEGER REFERENCES players (player_id),
    period              SMALLINT NOT NULL CHECK (period BETWEEN 1 AND 4),
    minute              SMALLINT NOT NULL CHECK (minute BETWEEN 0 AND 130),
    added_time          SMALLINT NOT NULL DEFAULT 0 CHECK (added_time >= 0),
    UNIQUE (match_id, espn_play_id)
);

CREATE INDEX idx_match_events_match ON match_events (match_id);
CREATE INDEX idx_match_events_type ON match_events (event_type);

-- Elo ratings are calculated by src/features/elo.py from UCL results only.
CREATE TABLE club_elo (
    match_id    INTEGER NOT NULL REFERENCES matches (match_id) ON DELETE CASCADE,
    club_id     INTEGER NOT NULL REFERENCES clubs (club_id),
    elo_before  NUMERIC(6, 1) NOT NULL,
    elo_after   NUMERIC(6, 1),          -- NULL for matches that haven't been played
    PRIMARY KEY (match_id, club_id)
);

CREATE TABLE match_predictions (
    match_id        INTEGER NOT NULL REFERENCES matches (match_id) ON DELETE CASCADE,
    model_name      TEXT NOT NULL,
    prediction_type TEXT NOT NULL CHECK (prediction_type IN ('backtest', 'upcoming')),
    trained_through DATE NOT NULL,      -- last match date the model was allowed to see
    p_home_win      NUMERIC(5, 4) NOT NULL CHECK (p_home_win BETWEEN 0 AND 1),
    p_draw          NUMERIC(5, 4) NOT NULL CHECK (p_draw BETWEEN 0 AND 1),
    p_away_win      NUMERIC(5, 4) NOT NULL CHECK (p_away_win BETWEEN 0 AND 1),
    PRIMARY KEY (match_id, model_name),
    CHECK (ABS(p_home_win + p_draw + p_away_win - 1) < 0.001)
);

CREATE TABLE model_evaluation (
    model_name      TEXT NOT NULL,
    test_season     SMALLINT NOT NULL,
    n_matches       INTEGER NOT NULL,
    log_loss        NUMERIC(6, 4) NOT NULL,
    brier_score     NUMERIC(6, 4) NOT NULL,
    accuracy        NUMERIC(5, 4) NOT NULL,
    macro_f1        NUMERIC(5, 4) NOT NULL,
    PRIMARY KEY (model_name, test_season)
);
