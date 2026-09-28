"""Short explanations for the metrics, used in table tooltips and captions."""

HELP = {
    "per90": "Totals scaled to a full 90 minutes. Unreliable for players with few minutes.",
    "sot_diff": "Shots on target for minus shots on target against. We use it in place of xG difference, "
                "which isn't available for the Champions League. It ignores how good the chances were.",
    "elo": "Rating built from Champions League results only. Beating a stronger team gains more points. "
           "Clubs new to the data start at 1250; in recent seasons the average club sits around 1450 to 1500. "
           "Early seasons read low because every club starts from scratch in 2012-13.",
    "opponent_elo": "Average pre-match Elo rating of the clubs faced. Higher means a harder schedule.",
    "tpi": "Tournament Performance Index: our own weighted mix of results, goal and shot difference, "
           "progression, schedule and form. 0 is the average club that season. Not an official UEFA metric.",
    "conversion": "Goals divided by shots.",
    "goals_per_sot": "Goals divided by shots on target.",
    "shot_accuracy": "Share of shots that hit the target.",
    "goals_above_average": "Non-penalty goals minus what an average finisher would score from the same "
                           "number of shots on target. Not xG: it knows nothing about shot location.",
    "non_penalty": "Penalties removed, because they convert at around 75% and would flatter penalty takers.",
    "possession": "Share of the ball, as reported by ESPN.",
    "save_pct": "Saves divided by saves plus goals conceded.",
    "log_loss": "How surprised the model was by the real results. Lower is better. "
                "Always guessing one third each scores about 1.10.",
    "brier": "Squared error of the three probabilities against what happened. Lower is better; 0 is perfect.",
}

NO_XG = (
    "No expected goals (xG) here. ESPN doesn't publish xG for the Champions League, so these "
    "pages use shots and shots on target instead. See DATA_SOURCES.md."
)
