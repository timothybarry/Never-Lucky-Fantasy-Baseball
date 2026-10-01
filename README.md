# Never Lucky

**A fantasy baseball rotisserie league scored on Statcast skill instead of
luck-polluted box scores, built over five MLB seasons (2017–2021) of
pitch-level data.**

Traditional roto categories (HR, R, RBI, SB, AVG / W, K, SV, ERA, WHIP) mostly
measure outcomes, and outcomes carry luck, park, defense and lineup context.
Never Lucky scores the process instead: barrels, xwOBA, 90th-percentile exit
velocity, chase rate, whiff rate, xFIP and barrel% allowed, alongside a few
volume lanes (R+RBI, SB, K, QS) so playing time still matters. The gap between
a player's Statcast value and his box-score value is where the edge lives.

The project ships two things:

- **`statcast_roto`**, a Python package: swappable data sources, a roto scoring
  engine, and a value model comparing the Statcast and traditional slates.
- **A five-season site** (`site/`): a single self-contained HTML page with an
  infographic splash (the signal field, season ribbon, league trends, a
  five-year "signal hall"), a test of the thesis, and standings, leaderboards
  and a scouting table with per-player percentile profiles.

## What the five seasons say

Same player, back-to-back qualified seasons, within-season z-scores. The 60-game
2020 season is reported separately.

| Full-season pairs (2017→18, 2018→19) | Hitters | Pitchers |
|---|---|---|
| 1. Repeats next season (r): Statcast value vs box-score value | .735 vs .616 | .566 vs .454 |
| 2. Next season's box score, out-of-sample R²: box score alone → + Statcast | .378 → .375 | .199 → .222 |
| 3. Rate vs rate, next season's OPS / ERA, out-of-sample R²: rate alone → + skill rates | .091 → .133 | −.021 → .042 |

The thesis is that Statcast measures skill better than the box score, and the
site tests it in the open. Statcast wins two of three for hitters and three of
three for pitchers. The one loss is hitters' box-score composite, which is
mostly playing time and lineup role, and those carry over on their own. Rate
for rate, skill stats sharpen the forecast on both sides, and a pitcher's ERA
barely predicts his next ERA at all. The site shows every test with its
interval, with and without the 60-game 2020 season.

## Quick start

```bash
pip install -e ".[dev]"
python -m pytest            # pitch-level tests skip unless the raw sample is present
python examples/run_demo.py # score a precomputed season
```

## Rebuild the site

`data/precomputed/` is committed, so the site builds without the raw files.
The official season lines it was enriched with are not committed; fetch them
first (about ten requests to the public MLB Stats API):

```bash
python scripts/enrich_precomputed.py --tags 2017 2018 2019 2020 2021 --fetch
python site/build_payload.py     # scores all five seasons -> site/payload.json
python site/build_site.py        # -> site/never_lucky_five_seasons.html
```

Or `make enrich` then `make site`.

### Re-deriving the Statcast aggregates (optional, about 1.6 GB)

The raw pitch files are too big for the repo, so they download after you clone,
the same way a model's weights would. `scripts/fetch_raw_statcast.py` pulls each
regular season from Baseball Savant through pybaseball (slow: roughly 10–20
minutes a season) into `data/raw_sample/`:

```bash
pip install -e ".[live]"
python scripts/fetch_raw_statcast.py --seasons 2017 2018 2019 2020 2021   # or: make raw
python scripts/build_precomputed.py --pitches data/raw_sample/statcast_2021.csv --tag 2021 --min-pa 50 --min-ip 20
python scripts/build_precomputed.py --pitches data/raw_sample/statcast_2020.csv --tag 2020 --min-pa 19 --min-ip 7.4  # 60-game season
python site/league_agg.py        # league totals for the splash; needs all five raw seasons
```

The fetch script hasn't been run end to end here (pybaseball isn't in this
project's environment); the five seasons in `data/precomputed` were built from
Baseball Savant exports.

`build_precomputed.py` keeps regular-season games only and merges the official
season lines automatically when `data/fantasy_outcomes/mlb_*_<tag>.csv` exist.
`WORKFLOW.md` walks through the pipeline step by step.

## Category slate

| Hitting | Better | | Pitching | Better |
|---|---|---|---|---|
| Barrels | higher | | K | higher |
| R+RBI | higher | | xFIP | lower |
| xwOBA | higher | | Whiff% | higher |
| 90th-pct EV | higher | | Barrel% allowed | lower |
| Chase% | lower | | QS | higher |
| SB | higher | | | |

Rate categories carry minimum-opportunity thresholds (`categories.py`), so a
tiny-sample waiver legend can't top them.

## How it works

```text
src/statcast_roto/
  categories.py        the objective function: both slates as declarative data
  sources.py           precomputed CSV source (data-origin agnostic)
  pitch_level.py       raw pitch rows -> season tables (regular season only)
  mlb_stats_api.py     official season lines from statsapi.mlb.com, keyed by MLBAM id
  fantasy_outcomes.py  merges official R/RBI/SB/AVG/OBP/SLG and W/SV/ERA/WHIP/IP
  scoring.py           roto aggregation and standings
  value.py             Statcast vs traditional value per player
  dashboard.py         the older Chart.js dashboard (scripts/build_dashboard.py)
scripts/               build_precomputed, enrich_precomputed, build_dashboard
site/                  the five-season page: build_payload, build_site, league_agg, template
tests/                 pytest suite
```

The scoring engine never learns where its numbers came from: a new data source
is one new loader, with scoring, value and the site unchanged.

## Honest data accounting

- **From the pitch files** (regular season only): barrels, EV90 and barrel%
  allowed (balls in play only), chase%, whiff%, K (strikeout double plays
  included), HR.
- **Official season lines** (MLB Stats API, matched by MLBAM id): PA, R, RBI,
  SB, AVG, OBP, SLG, OPS, W, SV, ERA, WHIP, IP. Checked against
  Baseball-Reference for every player-season, 2017–2021.
- **Labeled approximations:** xwOBA on contact (mean of the speed/angle
  estimate over balls in play), xFIP (FIP-style proxy), QS (rebuilt from outs
  and runs in each start).
- **2020** had 60 games, so every opportunity threshold that season is scaled
  by 60/162 (player-pool floors, small-sample flags, category minimums).
- **Rosters** are auto-drafted per season for a 10-team league; team names
  carry over, rosters don't.

See `DATA_NOTICE.md` for what data is and isn't in this repository.

## License

Code: MIT (see `LICENSE`). Data: see `DATA_NOTICE.md`. Not affiliated with
Major League Baseball.
