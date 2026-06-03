# Statcast Roto

**A fantasy baseball rotisserie engine scored on Statcast / expected-stat
categories instead of luck-polluted traditional stats.**

Traditional roto categories (HR, R, RBI, SB, AVG / W, K, SV, ERA, WHIP) mostly
measure *outcomes* — which are contaminated by luck, park, defense, and lineup
context. This engine scores teams on *skill and process* metrics — **barrels,
xwOBA, 90th-percentile exit velocity, chase rate, xFIP, whiff rate, and barrel%
allowed** — blending counting stats (which reward volume) with rate/expected
stats (which reward per-opportunity quality). In effect, the scoring engine
*is* the analytical judgment layer: "trust the underlying skill, not the noisy
result" is baked into how you win.

It runs on **real 2020 Statcast data** out of the box, aggregated from
pitch-by-pitch rows, with player names resolved via the Chadwick register.

---

## Quick start

```bash
# 1. (optional) create a venv, then install
pip install -e ".[dev]"

# 2. run the full demo on the bundled real-2020 data
make demo            # or: python examples/run_demo.py

# 3. run the test suite
make test            # 18 tests
```

No network or paid data feed is required for the default path — a real-2020
player pool is precomputed and bundled in `data/precomputed/`.

### As a library

```python
from statcast_roto import PrecomputedCSVSource, score_roto

bundle = PrecomputedCSVSource().load()      # real 2020 pool + 10-team league
result = score_roto(bundle)
print(result.standings)
```

### From the command line

```bash
# Score the bundled league on the Statcast slate
python -m statcast_roto.cli --source precomputed --outputs outputs

# Aggregate a RAW pitch-level Statcast CSV from scratch, then score
python -m statcast_roto.cli --source pitch \
    --pitches data/raw_sample/statcast_2020_sample.csv \
    --rosters data/precomputed/rosters_2020.csv \
    --outputs outputs_pitch
```

---

## What you get

Running the demo produces standings plus the **headline analysis** — how player
*values* shift when you move from outcome scoring to process scoring:

- **Biggest risers under Statcast scoring**: elite-stuff arms the old stats
  undervalue (e.g. Devin Williams's historic 2020 changeup season, deGrom,
  Bieber, Karinchak — high-whiff, low-barrel pitchers).
- **Players who look better under traditional scoring**: soft-contact veterans
  whose ERA/W flattered them while their underlying stuff lagged.

That contrast is the whole point: **process scoring rewards skill; outcome
scoring rewards results, which are partly luck.**

Outputs (CSV + PNG) land in `outputs/`:

| File | Contents |
|---|---|
| `standings.csv` | Final roto standings + per-category points |
| `team_category_values.csv` | Raw aggregated category values per team |
| `team_category_points.csv` | Roto points per category per team |
| `player_value_comparison.csv` | Each player's value under both slates |
| `biggest_statcast_bumps.csv` | Players who gain most under Statcast scoring |
| `biggest_traditional_bumps.csv` | Players who gain most under traditional scoring |
| `standings.png`, `value_delta.png` | Charts |

---

## How it works

```
data source ──► normalized DataBundle ──► RotoScorer ──► standings
   │                                          ▲
   ├── PrecomputedCSVSource (bundled CSVs)     │
   └── PitchLevelCSVSource  (raw pitch CSV) ───┘
                                          └──► PlayerValueModel ──► value comparison
```

The **data layer is decoupled from the scoring engine** (sources all satisfy
one `DataSource` protocol and return the same normalized schema). That means:

- the engine runs identically whether rows come from precomputed CSVs, raw
  pitch aggregation, or (later) a live/keyed feed;
- the whole thing is testable and runnable without a network pull;
- swapping in a real season-stat export for the context categories changes only
  the data layer, never the scoring.

### Modules

| Module | Responsibility |
|---|---|
| `categories.py` | The category slate as declarative data — *the objective function* |
| `schemas.py` | Normalized data contract + validation |
| `sources.py` | `PrecomputedCSVSource` (bundled aggregated data) |
| `pitch_level.py` | `PitchLevelCSVSource` — aggregate raw pitch data from scratch |
| `scoring.py` | `RotoScorer` — counting sums, opportunity-weighted rates, roto ranks |
| `value.py` | `PlayerValueModel` — how player value shifts between slates |
| `drafting.py` | Snake-draft helper to build example leagues |
| `charts.py` | Standings + value-delta charts |
| `cli.py` | Command-line entry point |

---

## Data sources & honest accounting

This project aggregates **raw pitch-by-pitch Statcast data** (the freely
available form) into season-level stats. Not every fantasy stat is cleanly
recoverable from pitch rows, and the integrity of the project depends on being
honest about which is which rather than fabricating the gaps. In brief:

- **Real / clean:** barrels, 90th-pct EV, chase rate, K, whiff%, barrel%
  allowed, HR, IP (from outs).
- **Approximated & labeled:** xwOBA (per-pitch contact mean), xFIP (FIP-style
  proxy), QS (from outs + runs per game).
- **Not recoverable from pitch data alone (never faked):** R, SB, W, SV, ERA,
  WHIP — reported as 0/approximate, to be merged from an audited season export
  for a published league.

The full accounting — including the barrel/zone definitions, the name-resolution
fix (in pitch data `player_name` is always the *pitcher*), and the
minimum-opportunity design lever — is in **[`docs/design_memo.md`](docs/design_memo.md)**.

### Using your own data

- **Raw pitch CSV** (Savant / `pybaseball.statcast` schema, one row per pitch):
  point `PitchLevelCSVSource` at it.
- **Already-aggregated CSVs**: drop them in `data/precomputed/` matching the
  schema in `schemas.py` and use `PrecomputedCSVSource`.
- **Your own league**: supply a rosters CSV with columns `team, side,
  player_id` (MLBAM IDs). `snake_draft_rosters()` can generate one from a pool.

---

## Project layout

```
statcast-fantasy-roto/
├── src/statcast_roto/        # the package
├── data/
│   ├── precomputed/          # real-2020 aggregated hitters/pitchers/rosters
│   └── raw_sample/           # a small real pitch-level sample (aggregation demo)
├── examples/run_demo.py      # end-to-end demonstration
├── tests/                    # 18 tests (scoring math, aggregation, value model)
├── docs/design_memo.md       # thesis + category design + honest data accounting
├── outputs/                  # generated CSVs + charts
├── pyproject.toml
└── Makefile
```

The bundled real-2020 pool is **415 hitters, 323 pitchers**, drafted into a
**10-team, 16-player league**.

---

## License

MIT.
