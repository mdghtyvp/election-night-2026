# Vermont election results → Datawrapper (6 races, one repo)

`fetch_races.py` downloads the Vermont SOS feed once, pulls out each race
listed in `races.json`, and writes one CSV per race into `data/`. A GitHub
Action runs it and commits any changes. Each Datawrapper chart links to the
raw URL of its own CSV.

```
races.json                      <- which races to pull (edit this to add/change)
fetch_races.py                  <- the script (no dependencies beyond Python 3)
data/<slug>.csv                 <- output, one per race
.github/workflows/update-results.yml
```

CSV columns: `Candidate, Party, Votes, Percent, Winner`
(leader first; `Winner` is "Yes" once the state flags the race, otherwise blank).

## One-time setup

1. Create a **public** GitHub repo and push all of these files to `main`.
2. **Actions tab → enable workflows**, then run "Update election results CSVs"
   once with **Run workflow**. Check that `data/` has six CSVs.
3. Each chart's data URL is:
   `https://raw.githubusercontent.com/<user>/<repo>/main/data/<slug>.csv`

| Race | slug |
|---|---|
| State's Attorney, Chittenden | `states-attorney-chittenden` |
| State's Attorney, Franklin | `states-attorney-franklin` |
| State's Attorney, Grand Isle | `states-attorney-grand-isle` |
| Sheriff, Franklin | `sheriff-franklin` |
| Sheriff, Orange | `sheriff-orange` |
| Sheriff, Windsor | `sheriff-windsor` |

## Make it run on time (important)

GitHub's built-in `schedule:` trigger can run 30–60 minutes late. Instead, have
a free external cron service call GitHub's API every 2–3 minutes. The built-in
schedule stays on as a fallback.

1. **Create a token**: GitHub → Settings → Developer settings → Fine-grained
   tokens → new token, limited to *this repo only*, permission
   **Actions: Read and write**. Set it to expire shortly after election night.
2. **At cron-job.org** (or similar), create a job:
   - URL: `https://api.github.com/repos/<user>/<repo>/actions/workflows/update-results.yml/dispatches`
   - Method: `POST`
   - Headers:
     - `Authorization: Bearer <your token>`
     - `Accept: application/vnd.github+json`
     - `X-GitHub-Api-Version: 2022-11-28`
   - Body: `{"ref":"main"}`
   - Schedule: every 2 or 3 minutes. A success response is HTTP **204**.
3. Watch the Actions tab for a few minutes to confirm runs appear on cadence.

Treat the token like a password: it can start workflows in your repo.

## Datawrapper, per chart

1. Upload Data → **Link external dataset** → paste that race's raw URL.
2. Candidate → labels, Votes (or Percent) → values. Party is available if you
   want to color or annotate by party.
3. Publish. Datawrapper re-reads the URL on its own schedule; check the
   refresh options available on your plan.

Expect a few minutes of total lag between the state posting numbers and the
chart changing: feed → our run (≤3 min) → GitHub's raw-file cache (~5 min) →
Datawrapper's refresh. Do a dry run before election night: edit a CSV by hand
in GitHub, and time how long the published chart takes to follow.

## If something looks wrong

- **A race fails** (name or district changed in the feed): that race's CSV is
  left untouched, the other five still update, and the Actions run shows red
  with the reason in the "Fetch feed" log. Matching is exact on office name and
  district, so it can never silently chart the wrong race.
- **The feed is down**: no CSV is touched; charts keep the last good numbers.
- **Feed URL changes** (it is specific to each election): update `feed_url` in
  `races.json`. A race can also carry its own `"feed_url"` to override it.
- GitHub **disables scheduled workflows in repos with 60 days of no activity**;
  the external trigger isn't affected, but re-enable the fallback if needed.
- Test locally: `python fetch_races.py --feed-file election-summary.xml`

## Adding a race

Add an entry to `races.json` with a `slug` (becomes the filename), `office`,
and `district`, copied exactly from the feed's `<OfficeName>` and
`<OfficeDistrict>`. Note some districts have odd spellings in the feed
(e.g. `GRAND ISLE County`, `CHITTENDEN-CENTRAL_ SENATE`).
