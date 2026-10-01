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
- **The built page** (`site/never_lucky_five_seasons.html`), which embeds the
  same data. `site/build_site.py` rebuilds it.

## Credits

- Player names: the Chadwick Bureau register, Open Data Commons Attribution
  License (ODC-By 1.0).
- Charts in the older dashboard: Chart.js v4.4.1 (MIT), vendored in
  `src/statcast_roto/vendor/`.
- Fonts on the page: Google Fonts (Big Shoulders Display, Chakra Petch,
  JetBrains Mono), under the SIL Open Font License.
