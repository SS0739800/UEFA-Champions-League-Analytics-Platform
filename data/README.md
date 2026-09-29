# data/

Nothing in here is committed except this file and the `.gitkeep` placeholders.
Everything is rebuilt by the pipeline.

| Folder | What goes in it | Written by |
|---|---|---|
| `raw/espn/scoreboard/` | One JSON file per calendar year, exactly as ESPN returned it | `src/etl/extract.py` |
| `raw/espn/summary/` | One JSON file per finished match (box score, lineups, key events) | `src/etl/extract.py` |
| `processed/` | CSV copies of the cleaned tables, plus the validation reports | `src/etl/run.py` |

The raw files are ESPN's responses and aren't ours to redistribute, which is
why they're git-ignored. The first run downloads about 2,000 match summaries,
which takes around an hour at the polite request rate used. After that, finished
matches are never downloaded again.

To rebuild the database from files you already have, without calling ESPN:

```bash
python -m src.etl.run --offline
```

The two validation files in `processed/` are worth a look:

- `validation_stat_coverage.csv`: for each season and stat, the share of
  team-matches with a non-zero value. Low shares mean ESPN didn't record it.
- `validation_inconsistent_scores.csv`: matches where the goal events or player
  goals don't add up to the final score.
