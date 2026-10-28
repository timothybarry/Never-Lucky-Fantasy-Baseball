"""
bat_tracking.py
===============

Bat-tracking season tables from Baseball Savant, for the Swing Lab.

Statcast began tracking the bat itself on 2023-07-14 (the start of the 2023
second half), so this is a separate era from the 2017-2021 roto league:
different seasons, different players, its own page section.

Per season, all regular season, all keyed by MLBAM id:

    swing_path   bat speed, swing path tilt, attack angle, attack direction,
                 ideal attack angle rate, contact point, stance position
    bat_speed    swing length, squared-up and blast rates, whiff rate
    expected     xBA, xSLG, xwOBA (est_*) and their actual counterparts
    statcast     barrel% and hard-hit%
    league       the league-average swing-path row

Verified against the leaderboard pages' own form code (2026-10-28):

* gameType must be sent explicitly as "Regular". Unknown values such as "R"
  silently return regular season PLUS postseason.
* Savant's default "q" qualifier is undocumented, shifts by season and counts
  postseason swings, so every batter is fetched (minSwings=1) and the site
  applies its own documented qualifier (see qualify()).
* Switch hitters appear as side "R" in the CSV; bat_sides() reads the real
  R/L/S from the MLB Stats API.

The raw CSVs land in data/bat_tracking/ and are never committed (DATA_NOTICE.md).
scripts/fetch_bat_tracking.py makes about 27 requests: 20 to Baseball Savant
(five leaderboards for each season, 2023-2026), three seconds apart, and 7 to
the MLB Stats API for batting sides (977 hitters, 150 a request). A file already
in the folder is used as is, so each CSV can instead be saved by hand with its
page's Download CSV button, named <kind>_<year>.csv. The pages' defaults differ
from these settings, so set them and press Update before downloading:

    swing_path   Bat Tracking > Swing Path / Attack Angle: Type Batters, Game
                 Type Regular, Min. Total Swings 1 and Min. Results 1 (the URL's
                 minSwings and minGroupSwings), Start and End Year both <year>
    league       the same page and settings with Type League (one row)
    bat_speed    Bat Tracking: the same settings as swing_path
    expected     Expected Statistics: Batters, <year>, Minimum PA, minimum 1
    statcast     Exit Velocity & Barrels: Batters, <year>, Minimum BBE 1

bat_payload() stops with a ValueError naming the file and the setting when a
swing path table was saved at Min. Total Swings "Qualified", when the bat
tracking table lists other hitters than swing path, or when the league table
isn't one row.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd

SAVANT = "https://baseballsavant.mlb.com"
STATSAPI = "https://statsapi.mlb.com/api/v1"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) statcast-roto/1.0"
FIRST_DAY = {"2023": "2023-07-14"}  # bat tracking starts mid-2023
PAUSE_S = 3.0  # between requests: a handful per season, never a crawl


def _swing_path_params(year: str, scope: str = "batter") -> dict[str, str]:
    return {"gameType": "Regular", "minSwings": "1", "minGroupSwings": "1",
            "seasonStart": year, "seasonEnd": year, "type": scope, "csv": "true"}


ENDPOINTS = {
    "swing_path": ("/leaderboard/bat-tracking/swing-path-attack-angle", lambda y: _swing_path_params(y)),
    "league": ("/leaderboard/bat-tracking/swing-path-attack-angle", lambda y: _swing_path_params(y, "league")),
    "bat_speed": ("/leaderboard/bat-tracking", lambda y: _swing_path_params(y)),
    "expected": ("/leaderboard/expected_statistics",
                 lambda y: {"type": "batter", "year": y, "position": "", "team": "", "filterType": "pa", "min": "1", "csv": "true"}),
    "statcast": ("/leaderboard/statcast",
                 lambda y: {"type": "batter", "year": y, "position": "", "team": "", "min": "1",
                            "sort": "barrels_per_pa", "sortDir": "desc", "csv": "true"}),
}

# A season the tracking covers only in part: left out of the full-season swing count, and flagged on the page.
PARTIAL = {"2023": "Bat tracking began July 14, 2023, so 2023 swing traits, squared-up and blast rates cover the second "
                   "half only; its xwOBA, barrel and hard-hit rates cover the full season."}
# One payload row: page column -> table column, in the page's order.
ROW = {"id": "id", "name": "name", "side": "side", "bat_speed": "avg_bat_speed", "tilt": "swing_tilt", "aa": "attack_angle",
       "dir": "attack_direction", "ideal": "ideal_attack_angle_rate", "int_plate": "avg_intercept_y_vs_plate",
       "int_batter": "avg_intercept_y_vs_batter", "bx": "avg_batter_x_position", "by": "avg_batter_y_position",
       "swings": "competitive_swings", "length": "swing_length", "squared": "squared_up_per_swing", "blast": "blast_per_swing",
       "hard": "hard_swing_rate", "whiff": "whiff_per_swing", "xwoba": "est_woba", "woba": "woba", "xslg": "est_slg",
       "brl": "brl_percent", "hardhit": "ev95percent", "pa": "pa"}
PERCENT = ("brl_percent", "ev95percent")  # the Statcast leaderboard's percents; every other rate is already a fraction
FEATURES = {"bat_speed": "avg_bat_speed", "aa": "attack_angle", "tilt": "swing_tilt", "dir": "attack_direction",
            "length": "swing_length", "ideal": "ideal_attack_angle_rate"}
OUTCOMES = {"brl": ("brl_percent", "Barrel rate"), "hardhit": ("ev95percent", "Hard-hit rate"),
            "blast": ("blast_per_swing", "Blasts per swing"), "squared": ("squared_up_per_swing", "Squared-up per swing"),
            "whiff": ("whiff_per_swing", "Whiffs per swing")}
LEAGUE = ("bat_speed", "aa", "tilt", "dir", "ideal")  # the league row has no swing length


def _get(url: str, *, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8-sig")


def fetch_tables(years: list[str], out_dir: Path, *, force: bool = False, log=print) -> list[Path]:
    """Download every (kind, year) CSV that isn't already in out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for year in years:
        for kind, (path, params) in ENDPOINTS.items():
            dest = out_dir / f"{kind}_{year}.csv"
            if dest.exists() and not force:
                log(f"  {dest.name}: already here, using it")
                continue
            text = _get(f"{SAVANT}{path}?{urllib.parse.urlencode(params(year))}")
            if not text.strip() or text.lstrip().startswith("<"):
                raise RuntimeError(f"{kind} {year}: Savant returned no CSV (got {len(text)} bytes)")
            dest.write_text(text, encoding="utf-8")
            written.append(dest)
            log(f"  {dest.name}: {text.count(chr(10))} rows")
            time.sleep(PAUSE_S)
    return written


def bat_sides(ids: list[int], cache: Path, *, log=print) -> dict[int, str]:
    """MLBAM id -> 'R' / 'L' / 'S' from the MLB Stats API (cached), since the CSV calls switch hitters 'R'."""
    known = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    need = sorted({int(i) for i in ids} - {int(k) for k in known})
    for i in range(0, len(need), 150):
        batch = ",".join(str(x) for x in need[i:i + 150])
        data = json.loads(_get(f"{STATSAPI}/people?personIds={batch}"))
        for p in data.get("people", []):
            known[str(p["id"])] = (p.get("batSide") or {}).get("code", "")
        time.sleep(PAUSE_S)
    if need:
        cache.write_text(json.dumps(known, indent=0, sort_keys=True), encoding="utf-8")
        log(f"  bat sides: {len(need)} looked up, {len(known)} cached")
    return {int(k): v for k, v in known.items()}


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")


def complete_years(src: Path, *, log=print) -> list[str]:
    """Seasons with all five leaderboards in src. A season missing any of them is named and skipped."""
    have: dict[str, set[str]] = {}
    for p in src.glob("*_*.csv"):
        kind, _, year = p.stem.rpartition("_")
        if kind in ENDPOINTS and year.isdigit():
            have.setdefault(year, set()).add(kind)
    years = []
    for y in sorted(have):
        missing = [f"{k}_{y}.csv" for k in ENDPOINTS if k not in have[y]]
        if missing:
            log(f"bat tracking: skipping {y}, missing {', '.join(missing)}")
        else:
            years.append(y)
    return years


def league_row(year: str, src: Path) -> pd.Series:
    """The season's league-average swing-path row (the swing path page with Type League)."""
    lg = _read(src / f"league_{year}.csv")
    if len(lg) != 1:
        raise ValueError(f"league_{year}.csv has {len(lg)} rows, not the one league row: save the Swing Path / Attack Angle "
                         f"leaderboard again with Type League (Game Type Regular, Min. Total Swings 1, Min. Results 1, {year})")
    return lg.iloc[0]


def season_table(year: str, src: Path, sides: dict[int, str] | None = None) -> pd.DataFrame:
    """Join the four leaderboards for one season into one row per batter (every batter, unqualified).
    A table saved at the wrong Savant settings stops with a ValueError that names the file and the setting."""
    sp = _read(src / f"swing_path_{year}.csv")
    if sp["competitive_swings"].min() > 50:  # an all-batter table always reaches down to a handful of swings
        raise ValueError(f"swing_path_{year}.csv starts at {sp['competitive_swings'].min()} competitive swings, so it was saved "
                         "at Savant's default Min. Total Swings 'Qualified': save it again with Min. Total Swings 1")
    sp["avg_bat_speed"] = pd.to_numeric(sp["avg_bat_speed"], errors="coerce")
    bs = _read(src / f"bat_speed_{year}.csv")
    if set(bs["id"]) != set(sp["id"]):
        raise ValueError(f"bat_speed_{year}.csv lists {len(bs)} hitters and swing_path_{year}.csv {len(sp)}, not the same ones: "
                         "save the Bat Tracking leaderboard again with Type Batters, Game Type Regular, Min. Total Swings 1 "
                         f"and Min. Results 1 for {year}, like swing path")
    ex = _read(src / f"expected_{year}.csv").rename(columns={"player_id": "id"})
    sc = _read(src / f"statcast_{year}.csv").rename(columns={"player_id": "id"})
    t = sp.merge(bs[["id", "swing_length", "squared_up_per_swing", "blast_per_swing", "hard_swing_rate", "whiff_per_swing"]], on="id", how="left")
    t = t.merge(ex[["id", "pa", "est_ba", "est_slg", "est_woba", "woba"]], on="id", how="left")
    keep = [c for c in ("brl_percent", "ev95percent", "avg_hit_angle") if c in sc.columns]
    t = t.merge(sc[["id"] + keep], on="id", how="left")
    if sides:  # only upgrade R: an "L" season of a switch hitter means he batted only left-handed that year
        t["side"] = ["S" if s == "R" and sides.get(int(i)) == "S" else s for i, s in zip(t["id"], t["side"])]
    t["year"] = str(year)
    return t


def qualify(t: pd.DataFrame, league_swings: float, full_season_swings: float, *, per_full_season: int = 600) -> pd.DataFrame:
    """Keep batters with at least 600 regular-season competitive swings per full season, scaled by how much of the
    season was tracked (2023 starts in July). The cut is rounded once, so the filter and the page's label agree."""
    cut = round(per_full_season * float(league_swings) / float(full_season_swings))
    out = t[t["competitive_swings"] >= cut].copy()
    out.attrs["min_swings"] = cut
    return out


def strict_cv(X: np.ndarray, y: np.ndarray, seasons: np.ndarray, ids: np.ndarray) -> np.ndarray:
    """Held-out least-squares predictions: each row comes from a fit without its season and without any other season
    of the same hitter, so a hitter never predicts himself. Rows with a NaN outcome are skipped (NaN)."""
    ok = ~np.isnan(y)
    pred = np.full(len(y), np.nan)
    for i in np.flatnonzero(ok):
        tr = ok & (seasons != seasons[i]) & (ids != ids[i])
        b, *_ = np.linalg.lstsq(X[tr], y[tr], rcond=None)
        pred[i] = X[i] @ b
    return pred


def outcome_fit(X: np.ndarray, y: np.ndarray, seasons: np.ndarray, ids: np.ndarray) -> dict:
    """One outcome: the full-pool fit, its strict held-out R², the 80% band of held-out misses and the observed range."""
    ok = ~np.isnan(y)
    res = (y - strict_cv(X, y, seasons, ids))[ok]
    r2 = 1 - float((res ** 2).sum()) / float(((y[ok] - y[ok].mean()) ** 2).sum())
    b, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
    lo, hi = np.quantile(res, [0.1, 0.9])  # 8 in 10 held-out misses fall inside this band
    return {"intercept": round(float(b[0]), 5), "coef": [round(float(c), 5) for c in b[1:]], "r2_oos": round(r2, 3),
            "band": [round(float(lo), 4), round(float(hi), 4)], "clip": [round(float(y[ok].min()), 4), round(float(y[ok].max()), 4)]}


def flip_name(n) -> str:
    """Savant writes "Last, First"."""
    last, _, first = str(n).partition(", ")
    return f"{first} {last}".strip() if first else str(n)


def _num(v, n: int = 4):
    v = v.item() if hasattr(v, "item") else v
    return None if v is None or (isinstance(v, float) and v != v) else (round(v, n) if isinstance(v, float) else v)


def bat_payload(btd: Path, *, log=print) -> dict | None:
    """The site's payload["bat"]: each complete season's qualified hitters, the league rows and the swing model.
    None, with a fetch hint, when no season has all five leaderboards."""
    years = complete_years(btd, log=log)
    # The qualifier scales from a full season and strict CV needs another season to train on.
    if len(years) < 2 or all(y in PARTIAL for y in years):
        log(f"bat tracking: the Swing Lab needs two complete seasons, one of them a full season (found {years or 'none'} in {btd}), "
            "so it will say how to get them. Fetch them with python scripts/fetch_bat_tracking.py (or save them by hand, see DATA_NOTICE.md).")
        return None
    cache = btd / "bat_sides.json"
    if cache.exists():
        sides = {int(k): v for k, v in json.loads(cache.read_text(encoding="utf-8")).items()}
    else:
        sides = {}
        log("bat tracking: warning: no bat_sides.json, so switch hitters will show as right-handed until "
            "scripts/fetch_bat_tracking.py has fetched batting sides")
    league = {y: league_row(y, btd) for y in years}
    swings = {y: float(league[y]["competitive_swings"]) for y in years}
    full = [swings[y] for y in years if y not in PARTIAL]
    full_sw = float(np.median(full)) if full else max(swings.values())
    tabs, min_swings = {}, {}
    for y in years:
        t = qualify(season_table(y, btd, sides), swings[y], full_sw)
        min_swings[y] = t.attrs["min_swings"]
        tabs[y] = t.assign(name=t["name"].map(flip_name), **{c: t[c] / 100 for c in PERCENT})  # the one percent -> fraction step
    cols = list(ROW.values())
    seasons = {y: [[int(r["id"]), str(r["name"]), str(r["side"])] + [_num(r[c]) for c in cols[3:]] for _, r in t.iterrows()]
               for y, t in tabs.items()}
    # Empirical layer: season outcomes from six swing traits, scored by strict_cv(). xwOBA isn't modeled: swing traits
    # explain only about a quarter of it, and its typical miss is as wide as the league's whole spread.
    pool = pd.concat(tabs.values(), ignore_index=True).dropna(subset=list(FEATURES.values())).reset_index(drop=True)
    Xr = pool[list(FEATURES.values())].astype(float)
    mu, sd = Xr.mean(), Xr.std(ddof=0)
    Z = ((Xr - mu) / sd).to_numpy()
    X = np.column_stack([np.ones(len(Z)), Z])
    yrs, ids = pool["year"].to_numpy(), pool["id"].to_numpy()
    outcomes = {}
    for key, (col, label) in OUTCOMES.items():
        m = outcomes[key] = {"label": label, **outcome_fit(X, pool[col].astype(float).to_numpy(), yrs, ids)}
        log(f"swing model {key}: strict out-of-sample R2 {m['r2_oos']:.3f}, 80% band {m['band'][0]:+.4f}/{m['band'][1]:+.4f}")
    # "Off the map": past the 95th percentile of real hitters' distance to their 5th-nearest other hitter.
    dist = np.sqrt(((Z[:, None, :] - Z[None, :, :]) ** 2).sum(-1))
    dist[ids[:, None] == ids[None, :]] = np.inf
    offmap = float(np.quantile(np.sort(dist, axis=1)[:, 4], 0.95))
    log(f"swing model off-map distance {offmap:.2f}")
    log("bat tracking: " + str({y: len(v) for y, v in seasons.items()}))
    return {
        "tags": years, "cols": list(ROW), "seasons": seasons,
        "partial": {y: PARTIAL[y] for y in years if y in PARTIAL},
        "min_swings": {y: int(min_swings[y]) for y in years},
        "league": {y: {k: round(float(league[y][FEATURES[k]]), 3) for k in LEAGUE} for y in years},
        "model": {"features": list(FEATURES), "mean": [round(float(mu[c]), 4) for c in FEATURES.values()],
                  "sd": [round(float(sd[c]), 4) for c in FEATURES.values()], "outcomes": outcomes, "n": int(len(pool)),
                  "hitters": int(pool["id"].nunique()), "offmap": round(offmap, 3)},
    }
