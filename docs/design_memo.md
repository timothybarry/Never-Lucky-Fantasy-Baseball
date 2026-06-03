# Design Memo: A Statcast-Scored Fantasy League

## The thesis

Traditional rotisserie categories — HR, R, RBI, SB, AVG on the hitting side; W,
K, SV, ERA, WHIP on the pitching side — almost all measure **outcomes**.
Outcomes are contaminated by luck, ballpark, defense, bullpen support, and
lineup context. A hitter's batting average swings with where his line drives
happen to land; a pitcher's win total depends on whether his offense scored.

The premise of this project: if the league instead scored **process and skill**
metrics — the things a player actually controls and that stabilize quickly and
predict the future — you would reward the players who are genuinely good rather
than the ones who got fortunate. In effect, **the scoring engine becomes the
analytical judgment layer**: it bakes "trust the underlying skill, not the
noisy result" directly into how you win.

## The category slate

The slate deliberately **blends counting and rate stats**, because each solves
a different problem:

- **Counting stats** (Barrels, R+RBI, SB, K, QS) reward volume and the
  season-long grind. They keep playing time and durability valuable and prevent
  a part-time masher from coasting on rate alone.
- **Rate / expected stats** (xwOBA, 90th-pct EV, Chase%, xFIP, Whiff%, Barrel%
  allowed) reward per-opportunity quality — the skill underneath the box score.

And every category measures a **different** skill (no redundancy):

| Hitting | Skill measured | Counting/Rate | Replaces |
|---|---|---|---|
| Barrels | Power / contact quality | Counting | HR |
| R + RBI | Lineup-context production | Counting | R, RBI |
| xwOBA | Overall offensive value | Rate | AVG/OBP |
| 90th-pct EV | Raw power ceiling | Rate | — (new) |
| Chase% | Plate discipline | Rate | — (new) |
| SB | Speed | Counting | SB |

| Pitching | Skill measured | Counting/Rate | Replaces |
|---|---|---|---|
| K | Volume strikeouts | Counting | K |
| xFIP | Run-prevention skill | Rate | ERA |
| Whiff% | Stuff / swing-and-miss | Rate | — (new) |
| Barrel% allowed | Contact management | Rate | WHIP-ish |
| QS | Durability / role | Counting | W |

### Why the minimum-opportunity thresholds matter

Rate categories carry a per-player PA/IP/batted-ball **minimum** (see
`categories.py`). This is the single most important design lever and the one a
casual implementation gets wrong. Without it, a hitter with 20 plate
appearances and a fluky 1.100 xwOBA would top the xwOBA category and distort
the whole league. The threshold is exactly the "small-sample is noise, not
signal" discipline, encoded as a rule. Setting it is a judgment call: too low
and you reward mirages, too high and you exclude legitimate breakouts. The
values here (100 PA for xwOBA, 25 IP for xFIP, etc.) are tuned for a full
season; a different league length would re-tune them.

## Honest accounting: what raw pitch data can and cannot give you

This project aggregates **raw pitch-by-pitch Statcast data** (one row per pitch)
into season-level player stats. That is the freely available form of the data.
Crucially, **not every fantasy stat is cleanly recoverable from pitch rows**,
and the integrity of the project depends on being honest about which is which
rather than fabricating the gaps.

**Computed cleanly and trustworthy (real):**

- **Barrels** — count of `launch_speed_angle == 6` (the official barrel
  classification; verified on real data: ~104 mph / ~26° / ~56% HR rate).
- **90th-pct EV** — 90th percentile of `launch_speed` on batted balls.
- **Chase rate** — swings (`description`) at out-of-zone pitches (`zone > 9`)
  divided by out-of-zone pitches seen.
- **Strikeouts, Whiff%, Barrel% allowed** — direct from `events` / `description`
  / barrel flags.
- **HR** — count of `events == 'home_run'`.
- **IP** — derived from outs recorded (`events` mapped to outs), which is more
  accurate than the common `PA / 4.25` shortcut.

**Approximated and explicitly labeled (do not present as official):**

- **xwOBA** — computed here as the mean of
  `estimated_woba_using_speedangle`. True xwOBA also incorporates the run values
  of walks and strikeouts via the wOBA scale; the per-pitch contact mean is a
  close, defensible proxy but not the official figure.
- **xFIP** — a transparent FIP-style proxy:
  `((13·lgHR/FB·FB) + 3·(BB+HBP) − 2·K) / IP + 3.10`. The fly-ball denominator
  comes from `bb_type` and the constant is fixed rather than season-derived.
- **QS** — approximated per game from outs recorded (≥18) and runs charged
  (≤3); true earned-run accounting requires official scoring.

**Not recoverable from pitch data alone (handled honestly, never faked):**

- **R (runs scored)** — requires tracking who was on base when a run scored
  across plays. We do **not** fabricate it; it is reported as 0 unless a real
  season export is merged in. (An earlier auto-generated version of this project
  invented R as `HR + SB·0.35` — exactly the kind of fabricated "signal" this
  project exists to reject.)
- **SB** — stolen bases attach to the runner and are only partially present as
  `stolen_base_*` events; the count undercounts and is labeled approximate.
- **W, SV, ERA, WHIP** — require game-level context (decisions, earned-run
  accounting) not present in pitch rows.

The honest path for a published, audited league is to **merge a real
season-stat export** (FanGraphs / Savant leaderboards) for the context stats
(R, RBI, SB, QS, W, SV, ERA, WHIP, official xFIP) while computing the
Statcast-native categories from the pitch data. The architecture supports this:
sources are decoupled from scoring, so adding an authoritative context-stat
merge changes only the data layer.

## A note on player-name resolution

In pitch-level Statcast data, the `player_name` column is **always the
pitcher**. Naively using it to label hitters mislabels every batter (a real bug
in an earlier auto-generated version). This project resolves batter and pitcher
MLBAM IDs to real names via the **Chadwick Bureau register**, a public CSV on
GitHub, with a graceful fallback to `MLBAM <id>` when offline.

## What the analysis shows

Running the engine on real 2020 data and comparing player values under the
Statcast slate versus the traditional slate surfaces the thesis cleanly:

- **Biggest risers under Statcast scoring** are elite-stuff arms the old stats
  undervalue — e.g. Devin Williams (historic 2020 changeup season), deGrom,
  Bieber, Karinchak — high-whiff, low-barrel pitchers whose skill outran their
  W/SV totals.
- **Players who look better under traditional scoring** are soft-contact
  veterans whose ERA/W flattered them while their underlying stuff lagged.

That contrast is the entire point: **process scoring rewards skill; outcome
scoring rewards results, which are partly luck.**
