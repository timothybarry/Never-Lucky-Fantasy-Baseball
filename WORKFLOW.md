# WORKFLOW — Converting Your Raw CSVs into Scored Standings

A plain-English, step-by-step guide to the data pipeline. Written for Windows +
Anaconda (your setup). Read top to bottom the first time; after that you'll only
need the two commands in Step 4 and 5.

---

## The 30-second mental model

You have **raw pitch-by-pitch CSVs** (one row per pitch, ~90 columns — the big
files from Baseball Savant / pybaseball). The engine scores **aggregated
season tables** (one row per player). The pipeline bridges the two:

```
   your raw pitch CSV                 build_precomputed.py              the engine
  (data/raw_sample/)      ───────►   (aggregates + drafts)   ───────►   (scores it)
                                     writes 3 files to
                                     data/precomputed/
```

**One run = one season.** Each season gets its own three files
(`hitters_<tag>.csv`, `pitchers_<tag>.csv`, `rosters_<tag>.csv`).

---

## Step 0 — Open the right terminal, in the right place

Everything is run from the **repo root folder** using the **full path to your
3.11 python.exe** (this is the bulletproof method we landed on — no conda
activation guesswork).

Open **Anaconda Prompt** (or a VS Code terminal set to Command Prompt), then:

```
cd path\to\never-lucky
set PYTHONPATH=src
```

> `set PYTHONPATH=src` tells Python where the code lives. You re-run this once
> per terminal session (it resets when you close the window).

For brevity below, PY means your interpreter. You can either type the full path
each time, or set a shortcut for the session:

```
set PY=path\to\your\env\python.exe
```

Then use `%PY%` wherever you see PY below.

---

## Step 1 — Put your raw CSV where the pipeline looks for it

Drop your raw pitch file into the **`data\raw_sample\`** folder inside the repo.

Example: copy `Statcast_2021.csv` into
`...\statcast-fantasy-roto-final\data\raw_sample\Statcast_2021.csv`

> It does NOT have to be small. The "sample" folder name is just where raw pitch
> files live. A full-season file is fine.

---

## Step 2 — Sanity-check it's the right kind of file

The pipeline expects the standard Savant / pybaseball **pitch-level** schema —
one row per pitch, with columns like `batter`, `pitcher`, `events`,
`description`, `zone`, `launch_speed`, `launch_angle`, `launch_speed_angle`,
`estimated_woba_using_speedangle`. Your `Statcast_2020.csv` is exactly this
shape, so any season you exported the same way will work.

If a file is missing those columns, the script will stop and tell you which ones
— that means it's an already-aggregated file, not raw pitch data (use it via
`--source precomputed` instead).

---

## Step 3 — Run the conversion (raw → precomputed)

```
%PY% scripts\build_precomputed.py --pitches data\raw_sample\Statcast_2021.csv --tag 2021
```

What happens:
- aggregates every hitter and pitcher from the pitch rows
- resolves real player names via the Chadwick register (downloads once;
  falls back to `MLBAM <id>` if you're offline)
- writes three files into `data\precomputed\`:
  - `hitters_2021.csv`
  - `pitchers_2021.csv`
  - `rosters_2021.csv`  (an auto-drafted, balanced 10-team league)
- prints the exact Step 4 command for you to copy

> `--tag 2021` is just the filename suffix. Use whatever label you want
> (`--tag 2021`, `--tag aprilonly`, etc.). It keeps seasons from overwriting
> each other.

**Handy options** (optional):
- `--no-names` — skip the name lookup (faster / works fully offline; uses IDs)
- `--teams 12 --hitters-per 9 --pitchers-per 7` — change the auto-draft league size
- `--no-roster` — don't auto-draft (use when you'll supply your own roster)
- `--min-pa 50 --min-ip 20` — pool thresholds (drop tiny-sample players)

---

## Step 4 — Score the season you just built

```
%PY% -m statcast_roto.cli --source precomputed --hitters data\precomputed\hitters_2021.csv --pitchers data\precomputed\pitchers_2021.csv --rosters data\precomputed\rosters_2021.csv --outputs outputs_2021
```

This prints the standings + the "who rises under Statcast scoring" analysis, and
writes all the CSVs and charts into a new **`outputs_2021\`** folder.

---

## Step 5 — Look at your results

Open the `outputs_2021\` folder. You'll find:
- `standings.csv` — final roto standings
- `biggest_statcast_bumps.csv` — players the Statcast slate values most
- `biggest_traditional_bumps.csv` — players the old stats overrated
- `standings.png`, `value_delta.png` — charts
- a few more detail CSVs

---

## Doing more than one season

Just repeat Steps 1, 3, 4 with a different file and tag:

```
%PY% scripts\build_precomputed.py --pitches data\raw_sample\Statcast_2022.csv --tag 2022
%PY% -m statcast_roto.cli --source precomputed --hitters data\precomputed\hitters_2022.csv --pitchers data\precomputed\pitchers_2022.csv --rosters data\precomputed\rosters_2022.csv --outputs outputs_2022
```

Over time you build a library: `hitters_2020.csv`, `hitters_2021.csv`,
`hitters_2022.csv`, ... each scorable instantly.

---

## Using YOUR real league instead of the auto-draft

The auto-drafted roster is just so you have something to score immediately. If
you have actual league rosters, make a CSV with three columns:

```
team,side,player_id
Regression to the Mean,hitting,665487
Regression to the Mean,pitching,594798
...
```

- `team` — the fantasy team name
- `side` — either `hitting` or `pitching`
- `player_id` — the player's **MLBAM id** (the same id used in the raw data's
  `batter`/`pitcher` columns; also the `player_id` column in your generated
  `hitters_<tag>.csv` / `pitchers_<tag>.csv`)

Then pass it with `--rosters path\to\your_rosters.csv` in Step 4, and add
`--no-roster` in Step 3 so the script doesn't bother auto-drafting one.

> The player_ids must exist in the season you aggregated. The easiest way to
> get the right ids: open your generated `hitters_<tag>.csv` — the `player_id`
> and `player_name` columns are right there to copy from.

---

## Quick troubleshooting

| Symptom | Fix |
|---|---|
| `No module named statcast_roto` | You forgot `set PYTHONPATH=src`, or you're not in the repo root. |
| `future feature annotations is not defined` | Wrong Python (old 3.6). Use the full path to a Python 3.10+ interpreter. |
| `missing expected Statcast columns` | That file is already aggregated, not raw pitches — score it directly with `--source precomputed`. |
| `roster contains player IDs missing from player tables` | Your roster is for a different season than the player files. Use the matching `rosters_<tag>.csv`, or rebuild the roster. |
| Names show as `MLBAM 12345` | The Chadwick lookup couldn't reach GitHub (offline). Numbers are still correct; rerun with internet for names, or ignore. |

---

## The honesty note (keep this in mind when you show it off)

Stats computed cleanly from pitch data are real: **barrels, 90th-pct EV, chase
rate, K (strikeout double plays included), whiff%, barrel% allowed, HR**.
Regular-season pitches only (the 2020 export also carries the four AL Wild Card
games, which `_prepare` drops). A few are **labeled approximations**: **xwOBA**
(per-pitch mean), **xFIP** (FIP-style proxy), **QS** (from outs + runs).

**R, RBI, SB, AVG, OBP, SLG, W, SV, ERA, WHIP and IP** can't be recovered from
pitch rows, so they come from official season lines. `scripts/enrich_precomputed.py
--fetch` pulls them from the public MLB Stats API (statsapi.mlb.com) by MLBAM id
and merges them onto the precomputed seasons; `build_precomputed.py` merges them
automatically when `data/fantasy_outcomes/mlb_*_<tag>.csv` exist. Full detail in
`docs/design_memo.md`. Owning this distinction is exactly the judgment that
makes the project credible.
