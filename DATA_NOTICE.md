# Data notice

Never Lucky is a non-commercial portfolio project. It is not affiliated with,
endorsed by, or sponsored by Major League Baseball or MLB Advanced Media.

## What is in this repository

- **Code** (MIT, see `LICENSE`).
- **`data/precomputed/`**: per-player season tables derived by this project.
  The Statcast columns (barrels, xwOBA, EV90, chase rate, whiff rate, barrel%
  allowed, the xFIP and QS proxies) are this project's own aggregations of
  pitch-level data. The box-score columns (R, RBI, SB, AVG, OBP, SLG, W, SV,
  ERA, WHIP, IP and similar) are official season totals.
- **`site/league.json`**: league-wide season totals aggregated by this project.

Baseball statistics and the underlying pitch-level and season data are
© MLB Advanced Media, L.P. They are included only as small derived tables so
the code can run and be tested; they are not offered for any other use. If you
are a rights holder and want any of it removed, open an issue and it will be
taken down.

## What is not in this repository

- **Raw pitch-level Statcast files** (about 1.6 GB, from Baseball Savant).
- **Raw MLB Stats API season pulls** (`data/fantasy_outcomes/mlb_*.csv`).
  `scripts/enrich_precomputed.py --fetch` downloads them again, about ten
  requests in total, for personal use under MLB's terms.
- **Savant bat-tracking leaderboards** (`data/bat_tracking/`, for the Swing
  Lab): the swing path / attack angle, bat tracking, expected statistics and
  Statcast leaderboards for each season from 2023, plus each hitter's batting
  side from the MLB Stats API. `scripts/fetch_bat_tracking.py` downloads them
  in about 27 requests: 20 to Baseball Savant, three seconds apart, and 7 to
  the MLB Stats API for batting sides. MLB's Terms of Use (section 1(xi))
  prohibit automated scripts that collect information from its sites, so you
  can instead save each CSV with the leaderboard's Download CSV button; the
  script fetches only files that are missing. `site/build_payload.py` stops
  with a message naming the file and the setting when a swing path table was
  saved at Min. Total Swings "Qualified", when the bat tracking table lists
  other hitters than swing path, or when a league table isn't one row. The
  pages default to Savant's own qualified hitters, so set these first, press
  Update, then download:
  - `swing_path_<year>.csv`: Bat Tracking › Swing Path / Attack Angle, with
    Type Batters, Game Type Regular, Min. Total Swings 1, Min. Results 1 and
    Start and End Year both `<year>` (in the URL: `gameType=Regular`,
    `minSwings=1`, `minGroupSwings=1`).
  - `league_<year>.csv`: the same page and settings, but Type League (one
    row).
  - `bat_speed_<year>.csv`: Bat Tracking, with the same settings as swing
    path.
  - `expected_<year>.csv`: Expected Statistics, with Batters, `<year>`,
    Minimum PA and minimum 1.
  - `statcast_<year>.csv`: Exit Velocity & Barrels, with Batters, `<year>`
    and Minimum BBE 1.
- **The built page** (`site/never_lucky_five_seasons.html`), which embeds the
  same data. `site/build_site.py` rebuilds it.

## Credits

- Bat-tracking metrics and definitions, and the 80% squared-up and 164 blast
  rules, are MLB Statcast's, via Baseball Savant and the MLB glossary.
- The exit-velocity ceiling, 1.23 × bat speed + 0.23 × pitch speed at the
  plate, is this project's reconstruction: Statcast doesn't publish the
  equation, and this one reproduces its three glossary examples within
  0.1 mph.
- Collision physics: A. M. Nathan, "Characterizing the performance of baseball
  bats", *Am. J. Phys.* 71, 134 (2003).
- Flush launch angle: Kensrud, Nathan and Smith, *Am. J. Phys.* 85, 503
  (2017).
- Timing and plane match: A. M. Nathan, "Optimizing the Swing, Part Deux"
  (2015).
- The swing drawings are this project's own; no Savant video or image is used.
- Player names: the Chadwick Bureau register, Open Data Commons Attribution
  License (ODC-By 1.0).
- Charts in the older dashboard: Chart.js v4.4.1 (MIT), vendored in
  `src/statcast_roto/vendor/`.
- Fonts on the page: Google Fonts (Big Shoulders Display, Chakra Petch,
  JetBrains Mono), under the SIL Open Font License.
