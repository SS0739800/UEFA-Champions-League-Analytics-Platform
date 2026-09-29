# Deploying

The live setup has three parts:

| Part | Where | What it does |
|---|---|---|
| Database | Supabase (free) | Holds everything the dashboard reads |
| Dashboard | Streamlit Community Cloud (free) | Serves `app/Home.py`, redeploys on every push to `main` |
| Updates | GitHub Actions (free) | Runs `python -m src.etl.run --update` every day at 06:00 UTC |

The first full load is done from your own machine, because it needs the raw ESPN files in `data/raw/`
(about 2,000 match summaries). After that, the daily update only needs a handful of requests.

You'll end up with two database logins:

- **postgres** (the Supabase owner): used by your laptop and the GitHub Action to write data.
- **app_reader** (read-only): used by the dashboard. If its password ever leaked, nobody could change anything.

## 1. Create the Supabase project

1. Create a project at [supabase.com](https://supabase.com). Save the database password somewhere safe.
2. **Turn off the Data API** (Project Settings, then Data API). Supabase otherwise exposes every table in
   the `public` schema through a web API, and these tables don't use row-level security. The dashboard
   talks to PostgreSQL directly and doesn't need that API.
3. Click **Connect** and copy the **Session pooler** connection string. It looks like:

   ```
   postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
   ```

   Add `?sslmode=require` to the end. Use the session pooler, not the direct connection (IPv6 only on the
   free plan, which Streamlit Cloud and GitHub can't reach) and not the transaction pooler on port 6543
   (it breaks psycopg's prepared statements).

## 2. Load the data from your laptop

With the raw files already in `data/raw/`:

```bash
# bash
DATABASE_URL="postgresql://postgres.<ref>:<password>@<host>:5432/postgres?sslmode=require" \
    python -m src.etl.run --offline
```

```powershell
# PowerShell
$env:DATABASE_URL = "postgresql://postgres.<ref>:<password>@<host>:5432/postgres?sslmode=require"
python -m src.etl.run --offline
Remove-Item Env:DATABASE_URL
```

This builds the schema, loads every season and trains the models: about a minute locally, a bit longer
over the internet.

## 3. Create the read-only user

In Supabase's SQL editor, choosing your own password:

```sql
CREATE ROLE app_reader WITH LOGIN PASSWORD 'pick-a-long-random-password';
GRANT USAGE ON SCHEMA public TO app_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO app_reader;

-- A full load drops and recreates the tables, so make future tables readable too.
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT SELECT ON TABLES TO app_reader;
```

Its connection string is the same as before, with the user and password swapped:

```
postgresql://app_reader.<project-ref>:<its-password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
```

## 4. Deploy the dashboard

1. On [share.streamlit.io](https://share.streamlit.io), create a new app from this repository:
   branch `main`, main file `app/Home.py`.
2. Under **Advanced settings**, choose Python 3.13 and add this secret:

   ```toml
   DATABASE_URL = "postgresql://app_reader.<project-ref>:<its-password>@<host>:5432/postgres?sslmode=require"
   ```

   Streamlit makes top-level secrets available as environment variables, which is where
   `src/config.py` looks.
3. Deploy. The first start takes a few minutes while it installs the requirements.

## 5. Turn on the daily update

1. In the GitHub repository: **Settings, then Secrets and variables, then Actions, then New repository secret**.
   Name it `DATABASE_URL` and use the **postgres** connection string from step 1 (the update needs to write).
2. Open the **Actions** tab, pick **Update data** and click **Run workflow** to try it straight away.
3. After that it runs every day at 06:00 UTC. Scheduled workflows only run from the default branch, so
   make sure `main` is the default.

Each run adds new fixtures and results, recalculates Elo and the predictions, and logs itself in the
`pipeline_runs` table. The dashboard sidebar shows the last successful check.

## Checking it's working

```sql
SELECT ran_at, mode, status, finished_matches, note
FROM pipeline_runs
ORDER BY ran_at DESC
LIMIT 10;
```

## Things to know

- **ESPN sometimes refuses requests** after a large download. A run that hits this fails with a clear
  message and is logged as `failed`. The dashboard keeps showing the last good data. If it keeps failing,
  run `python -m src.etl.run --update` from your own machine instead.
- **The failed run still keeps Supabase awake.** Free projects pause after about a week without activity,
  and every run (successful or not) writes to `pipeline_runs`. If the project does get paused, restore
  it from the Supabase dashboard.
- **Cold starts.** Streamlit Cloud puts free apps to sleep when nobody visits for a while. The first
  visitor after that waits a little while it starts up.
- **GitHub disables scheduled workflows after 60 days without any pushes** to a public repository, and
  emails you first. Re-enable it from the Actions tab.
- **Rebuilding from scratch** is always possible from your machine with step 2. The raw files in
  `data/raw/` are the only copy of the ESPN downloads and aren't in git, so keep a backup of that folder.
