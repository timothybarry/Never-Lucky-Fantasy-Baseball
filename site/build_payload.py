"""Score all five seasons with the repo pipeline and emit a compact site payload."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # the engine root (site/ lives inside it)
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402
from statcast_roto.sources import PrecomputedCSVSource  # noqa: E402
from statcast_roto.scoring import RotoScorer  # noqa: E402
from statcast_roto.value import PlayerValueModel  # noqa: E402
from statcast_roto.categories import DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES  # noqa: E402
from statcast_roto.dashboard import (extract_season, _enrich_player_percentiles_and_ghosts,  # noqa: E402
                                     _action_from_row, _archetype_from_row, LEADERBOARD_SPECS)
from dataclasses import replace  # noqa: E402

TAGS = ["2017", "2018", "2019", "2020", "2021"]

# Official MLB season lines are merged into data/precomputed (scripts/enrich_precomputed.py),
# so SB, R, AVG, W, SV, ERA and WHIP are real and every category scores. Before that merge,
# SB was ~all zeros and one stray steal made a replacement-level hitter the #1 signal.
SC_CATS = tuple(DEFAULT_CATEGORIES)
TR_CATS = tuple(TRADITIONAL_CATEGORIES)
PRE = ROOT / "data" / "precomputed"

# The 60-game 2020 season gets every opportunity threshold scaled by 60/162, so its players are
# judged on the same footing as a full season (rate-category minimums and small-sample flags).
SEASON_GAMES = {"2020": 60}
scale_of = lambda tag: SEASON_GAMES.get(tag, 162) / 162


def scaled(cats, tag):
    s = scale_of(tag)
    return tuple(replace(c, minimum=c.minimum * s) if s != 1 and c.minimum else c for c in cats)


def small_flag(p, side, s):
    """dashboard._sample_tag's rule (100 PA / 50 BBE, 25 IP / 400 pitches), scaled by season length."""
    if side == "hitting":
        return float(p.get("pa") or 0) < 100 * s or float(p.get("batted_balls") or 0) < 50 * s
    return float(p.get("ip") or 0) < 25 * s or float(p.get("pitches") or 0) < 400 * s

seasons, results = [], {}
for tag in TAGS:
    bundle = PrecomputedCSVSource.from_paths(
        hitters=PRE / f"hitters_{tag}.csv", pitchers=PRE / f"pitchers_{tag}.csv",
        rosters=PRE / f"rosters_{tag}.csv", source_name=f"precomputed-{tag}").load()
    result = RotoScorer(scaled(SC_CATS, tag)).score(bundle)
    comp = PlayerValueModel(scaled(SC_CATS, tag), scaled(TR_CATS, tag)).compare(bundle)
    windows = json.loads((PRE / f"leaderboards_{tag}_windows.json").read_text(encoding="utf-8"))
    season = extract_season(tag, result, comp, bundle.hitters, bundle.pitchers, windows)
    for side in ("hitting", "pitching"):
        for p in season.players[side]:
            p["small_sample"] = small_flag(p, side, scale_of(tag))
    seasons.append(season)
    results[tag] = result
    print(tag, len(bundle.hitters), len(bundle.pitchers), flush=True)

_enrich_player_percentiles_and_ghosts(seasons)


def r(v, n=4):
    if v is None:
        return None
    if isinstance(v, float):
        if v != v:
            return None
        return round(v, n)
    return v


HIT_KEYS = ["pa", "pa_statcast", "batted_balls", "pitches_seen", "barrels", "xwoba", "ev90", "chase_rate", "hr",
            "r", "rbi", "r_plus_rbi", "sb", "cs", "avg", "obp", "slg", "ops", "bb", "so", "babip"]
PIT_KEYS = ["ip", "pitches", "batted_balls_allowed", "k", "xfip", "whiff_rate", "barrel_rate_allowed", "qs",
            "w", "l", "sv", "hld", "g", "gs", "era", "whip", "bb", "er", "tbf"]
# Pooled 2017-21 percentiles, ranked against qualified (non-small) player-seasons only; small
# samples are placed on that same distribution. Value = key in the row ("sig" for the signal score).
LOW_GOOD = {"chase_rate", "xfip", "barrel_rate_allowed", "era", "whip"}
PCT_KEYS = {"hitting": ["sig", "xwoba", "barrels", "ev90", "chase_rate", "r_plus_rbi", "sb", "hr", "r", "rbi", "avg", "obp", "slg", "ops"],
            "pitching": ["sig", "k", "xfip", "whiff_rate", "barrel_rate_allowed", "qs", "w", "sv", "era", "whip"]}

# Compact player table: one list of columns per side, rows as arrays.
H_COLS = ["id", "name", "pos", "small", "sig", "trad", "gap", "scr", "trr"] + HIT_KEYS + ["pct", "action", "arch"]
P_COLS = ["id", "name", "pos", "small", "sig", "trad", "gap", "scr", "trr"] + PIT_KEYS + ["pct", "action", "arch"]

def with_ids(teams, rps):
    """Attach MLBAM ids to roster entries; short names like 'J. Ramírez' collide across the pool."""
    key = {(r.team, r.side, f"{r.player_name.split()[0][0]}. {r.player_name.split()[-1]}"): str(r.player_id)
           for r in rps.itertuples() if len(str(r.player_name).split()) >= 2}
    for team, t in teams.items():
        for side, entries in (("hitting", t["hitters"]), ("pitching", t["pitchers"])):
            for e in entries:
                e["id"] = key.get((team, side, e["name"]))
    return teams


out = {"categories": [{"key": c.key, "label": c.label, "side": c.side, "higher": c.higher_is_better, "kind": c.kind, "desc": c.description} for c in SC_CATS], "tags": TAGS, "cols": {"hitting": H_COLS, "pitching": P_COLS}, "specs": LEADERBOARD_SPECS, "seasons": {}}
for s in seasons:
    res = results[s.tag]
    cat_points = res.category_points
    cat_values = res.category_values
    players = {}
    for side, keys in (("hitting", HIT_KEYS), ("pitching", PIT_KEYS)):
        rows = []
        for p in s.players[side]:
            rows.append([p["player_id"], p["player_name"], p["position"], 1 if p["small_sample"] else 0,
                         r(p["signal_score"], 3), r(p["traditional_value"], 3), r(p["noise_gap"], 3),
                         p["statcast_rank"], p["traditional_rank"]]
                        + [r(p.get(k)) for k in keys] + [{}, p["action"], p["archetype"]])
        players[side] = rows
    windows = {}
    for k, w in s.leaderboard_windows.items():
        windows[k] = {"label": w.get("label"), "start": w.get("start"), "end": w.get("end"),
                      "n": w.get("n_pitches"), "lb": w["leaderboards"]}
    out["seasons"][s.tag] = {
        "n_hitters": s.n_hitters, "n_pitchers": s.n_pitchers,
        "standings": s.standings, "teams": with_ids(s.teams, res.roster_player_stats), "windows": windows, "players": players,
        "category_points": json.loads(cat_points.to_json(orient="records")),
        "category_values": json.loads(cat_values.to_json(orient="records", double_precision=4)),
    }

import numpy as np  # noqa: E402

# ---- pooled percentiles (qualified rows define the distribution) ----
for side, cols in (("hitting", H_COLS), ("pitching", P_COLS)):
    ix = {c: i for i, c in enumerate(cols)}
    allrows = [row for t in TAGS for row in out["seasons"][t]["players"][side]]
    for key in PCT_KEYS[side]:
        ref = np.sort(np.array([row[ix[key]] for row in allrows if not row[ix["small"]] and row[ix[key]] is not None], float))
        if not len(ref):
            continue
        for row in allrows:
            v = row[ix[key]]
            if v is None:
                continue
            lo, hi = np.searchsorted(ref, v, "left"), np.searchsorted(ref, v, "right")
            p = (lo + hi) / 2 / len(ref) * 100  # mid-rank, so ties share a percentile
            row[ix["pct"]]["signal_score" if key == "sig" else key] = round(float(100 - p if key in LOW_GOOD else p), 0)
    # Signal read and archetype follow the percentiles the page shows (dashboard.py's rules, our ranks).
    for row in allrows:
        d = {"side": side, "small_sample": bool(row[ix["small"]]), "noise_gap": row[ix["gap"]],
             "signal_score": row[ix["sig"]], "percentiles": row[ix["pct"]]}
        row[ix["action"]], row[ix["arch"]] = _action_from_row(d), _archetype_from_row(d)

# ---- thesis test: does this year's Statcast value predict next year's box score? ----
def ols(y, X):
    X = np.column_stack([np.ones(len(y))] + list(X))
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = len(y) - X.shape[1]
    cov = (resid @ resid / dof) * np.linalg.inv(X.T @ X)
    return beta, np.sqrt(np.diag(cov)), 1 - (resid @ resid) / ((y - y.mean()) @ (y - y.mean()))


def cluster_se(y, X, groups):
    """OLS coefficients with player-clustered (CR1) standard errors: one player can sit in up to four pairs."""
    X = np.column_stack([np.ones(len(y))] + list(X))
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    u = y - X @ beta
    meat = np.zeros((X.shape[1], X.shape[1]))
    uniq = np.unique(groups)
    for g in uniq:
        s = X[groups == g].T @ u[groups == g]
        meat += np.outer(s, s)
    n, k, G = len(y), X.shape[1], len(uniq)
    cov = (G / (G - 1)) * ((n - 1) / (n - k)) * xtx_inv @ meat @ xtx_inv
    return beta, np.sqrt(np.diag(cov))


def pair_test(pairs, ix, seed):
    """Every thesis number for one set of (season, row_N, row_N+1) pairs."""
    rng = np.random.default_rng(seed)
    sig0 = np.array([x[ix["sig"]] for _, x, _ in pairs]); trad0 = np.array([x[ix["trad"]] for _, x, _ in pairs])
    sig1 = np.array([y[ix["sig"]] for _, _, y in pairs]); trad1 = np.array([y[ix["trad"]] for _, _, y in pairs])
    gap0 = np.array([x[ix["gap"]] for _, x, _ in pairs])  # the stored per-player gap the page shows
    dtrad = trad1 - trad0
    pid = np.array([x[ix["id"]] for _, x, _ in pairs])
    r_box = float(np.corrcoef(trad0, trad1)[0, 1]); r_sc = float(np.corrcoef(sig0, trad1)[0, 1])
    # Bootstrap over players, not pairs, so a player's repeated seasons travel together.
    players = np.unique(pid); rows_of = {p: np.flatnonzero(pid == p) for p in players}
    boots, sticks = [], []
    for _ in range(2000):
        k = np.concatenate([rows_of[p] for p in rng.choice(players, len(players))])
        r_tt = np.corrcoef(trad0[k], trad1[k])[0, 1]
        boots.append(np.corrcoef(sig0[k], trad1[k])[0, 1] - r_tt)
        sticks.append(np.corrcoef(sig0[k], sig1[k])[0, 1] - r_tt)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    s_lo, s_hi = np.percentile(sticks, [2.5, 97.5])
    # Out of sample: fit on the other season pairs, score the held-out pair, pool the errors.
    grp = np.array([a for a, _, _ in pairs])
    sse_box = sse_both = 0.0
    for g in np.unique(grp):
        tr, te = grp != g, grp == g
        for cols_, acc in (([trad0], "box"), ([trad0, sig0], "both")):
            Xtr = np.column_stack([np.ones(tr.sum())] + [c[tr] for c in cols_])
            b_, *_ = np.linalg.lstsq(Xtr, trad1[tr], rcond=None)
            pred = np.column_stack([np.ones(te.sum())] + [c[te] for c in cols_]) @ b_
            err = float(((trad1[te] - pred) ** 2).sum())
            if acc == "box":
                sse_box += err
            else:
                sse_both += err
    sst = float(((trad1 - trad1.mean()) ** 2).sum())
    oos = {"box": round(1 - sse_box / sst, 3), "both": round(1 - sse_both / sst, 3)}
    # Pure skill slate (no volume categories): does contact quality alone predict next year's box score?
    pure0 = np.array([PURE[(a, x[ix["id"]])] for a, x, _ in pairs])
    r_pure = float(np.corrcoef(pure0, trad1)[0, 1])
    _, _, r2_both = ols(trad1, [trad0, gap0])
    _, _, r2_box = ols(trad1, [trad0])
    beta, se = cluster_se(trad1, [trad0, gap0], pid)
    # Regression-to-the-mean baseline: the change last year's box score alone predicts.
    b_rtm, _, _ = ols(dtrad, [trad0])
    expect = b_rtm[0] + b_rtm[1] * trad0
    order = np.argsort(gap0, kind="stable"); bins = []
    for chunk in np.array_split(order, 5):  # equal-count fifths, ties split by order
        d, g = dtrad[chunk], gap0[chunk]
        bins.append({"lo": round(float(g.min()), 3), "hi": round(float(g.max()), 3), "n": int(len(chunk)),
                     "gap": round(float(g.mean()), 3), "dtrad": round(float(d.mean()), 3),
                     "se": round(float(d.std(ddof=1) / np.sqrt(len(d))), 3), "rtm": round(float(expect[chunk].mean()), 3)})
    return {"n": len(pairs), "players": int(len(players)), "r_box": round(r_box, 3), "r_sc": round(r_sc, 3),
            "r_sc_sc": round(float(np.corrcoef(sig0, sig1)[0, 1]), 3), "diff_ci": [round(float(lo), 3), round(float(hi), 3)],
            "stick_ci": [round(float(s_lo), 3), round(float(s_hi), 3)], "r2_oos_box": oos["box"], "r2_oos_both": oos["both"],
            "r_pure": round(r_pure, 3),
            "gap_coef": round(float(beta[2]), 3), "gap_se": round(float(se[2]), 3),
            "r2_box": round(float(r2_box), 3), "r2_both": round(float(r2_both), 3), "bins": bins}


def rate_test(pairs, ix, box_key, pure, sign, seed):
    """Rate against rate, no playing time: does this year's pure-skill value predict next year's
    box-score rate (OPS for hitters, ERA for pitchers) better than this year's rate does?"""
    keep = [(a, x, y) for a, x, y in pairs if x[ix[box_key]] is not None and y[ix[box_key]] is not None]
    rng = np.random.default_rng(seed)
    b0 = sign * np.array([x[ix[box_key]] for _, x, _ in keep], float)
    b1 = sign * np.array([y[ix[box_key]] for _, _, y in keep], float)
    p0 = np.array([pure[(a, x[ix["id"]])] for a, x, _ in keep]); p1 = np.array([pure[(TAGS[TAGS.index(a) + 1], y[ix["id"]])] for a, _, y in keep])
    pid = np.array([x[ix["id"]] for _, x, _ in keep]); players = np.unique(pid); rows_of = {p: np.flatnonzero(pid == p) for p in players}
    boots = []
    for _ in range(2000):
        k = np.concatenate([rows_of[p] for p in rng.choice(players, len(players))])
        boots.append(np.corrcoef(p0[k], b1[k])[0, 1] - np.corrcoef(b0[k], b1[k])[0, 1])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    grp = np.array([a for a, _, _ in keep]); sse = {"box": 0.0, "both": 0.0}
    for g in np.unique(grp):
        tr, te = grp != g, grp == g
        for name, cols_ in (("box", [b0]), ("both", [b0, p0])):
            b_, *_ = np.linalg.lstsq(np.column_stack([np.ones(tr.sum())] + [c[tr] for c in cols_]), b1[tr], rcond=None)
            sse[name] += float(((b1[te] - np.column_stack([np.ones(te.sum())] + [c[te] for c in cols_]) @ b_) ** 2).sum())
    sst = float(((b1 - b1.mean()) ** 2).sum())
    return {"n": len(keep), "r_box": round(float(np.corrcoef(b0, b1)[0, 1]), 3), "r_sc": round(float(np.corrcoef(p0, b1)[0, 1]), 3),
            "r_sc_sc": round(float(np.corrcoef(p0, p1)[0, 1]), 3), "diff_ci": [round(float(lo), 3), round(float(hi), 3)],
            "r2_oos_box": round(1 - sse["box"] / sst, 3), "r2_oos_both": round(1 - sse["both"] / sst, 3)}


# Pure skill slate: rate stats only, no volume (barrels enter as barrels per ball in play).
PURE_CATS = {"hitting": {"brl_rate": 1, "xwoba": 1, "ev90": 1, "chase_rate": -1},
             "pitching": {"xfip": -1, "whiff_rate": 1, "barrel_rate_allowed": -1}}
RATE_BOX = {"hitting": ("ops", 1, "OPS"), "pitching": ("era", -1, "ERA")}
thesis = {}
for side, cols in (("hitting", H_COLS), ("pitching", P_COLS)):
    ix = {c: i for i, c in enumerate(cols)}
    val = lambda r, c: (r[ix["barrels"]] / r[ix["batted_balls"]] if r[ix["batted_balls"]] else None) if c == "brl_rate" else r[ix[c]]
    # Pure skill value: mean within-season z over the rate-only skill stats, qualified rows only.
    PURE = {}
    for t in TAGS:
        rows = [r for r in out["seasons"][t]["players"][side] if not r[ix["small"]]]
        zs = []
        for c, sign in PURE_CATS[side].items():
            v = np.array([val(r, c) if val(r, c) is not None else np.nan for r in rows], float)
            zs.append(sign * (v - np.nanmean(v)) / np.nanstd(v))
        for r, z in zip(rows, np.nanmean(np.vstack(zs), axis=0)):
            PURE[(t, r[ix["id"]])] = float(z)
    by = {t: {row[ix["id"]]: row for row in out["seasons"][t]["players"][side]
              if not row[ix["small"]] and row[ix["sig"]] is not None and row[ix["trad"]] is not None} for t in TAGS}
    pairs, per = [], []
    for a, b in zip(TAGS, TAGS[1:]):
        ab = [(by[a][i], by[b][i]) for i in by[a] if i in by[b]]
        pairs += [(a, x, y) for x, y in ab]
        if ab:
            s0 = np.array([x[ix["sig"]] for x, _ in ab]); t0 = np.array([x[ix["trad"]] for x, _ in ab]); t1 = np.array([y[ix["trad"]] for _, y in ab])
            per.append({"from": a, "to": b, "n": len(ab), "r_box": round(float(np.corrcoef(t0, t1)[0, 1]), 3),
                        "r_sc": round(float(np.corrcoef(s0, t1)[0, 1]), 3)})
    # The 60-game 2020 season is where luck has the most room, so every number is reported twice:
    # all pairs, and full seasons only.
    full = [p for p in pairs if "2020" not in (p[0], TAGS[TAGS.index(p[0]) + 1])]
    box_key, sign, label = RATE_BOX[side]
    thesis[side] = {**pair_test(pairs, ix, 20170402), "per": per, "full": pair_test(full, ix, 20180329),
                    "rate": {"stat": label, "all": rate_test(pairs, ix, box_key, PURE, sign, 20190328),
                             "full": rate_test(full, ix, box_key, PURE, sign, 20210401)}}
    print(side, {k: v for k, v in thesis[side].items() if k not in ("bins", "per", "full", "rate")})
    print("   full seasons:", {k: v for k, v in thesis[side]["full"].items() if k != "bins"})
    print("   rate test:", thesis[side]["rate"])
out["thesis"] = thesis

# ---- official league totals (every MLB player, from the MLB Stats API pulls) ----
OUTC = ROOT / "data" / "fantasy_outcomes"
out["league_official"] = {}
for t in TAGS:
    need = [OUTC / f"mlb_batting_{t}.csv", OUTC / f"mlb_pitching_{t}.csv"]
    if not all(p.exists() for p in need):
        raise SystemExit(f"Missing {need[0].name} or {need[1].name}. Run: python scripts/enrich_precomputed.py "
                         "--tags 2017 2018 2019 2020 2021 --fetch")
    b = pd.read_csv(need[0]); pt = pd.read_csv(need[1])
    out["league_official"][t] = {"r": int(b["R"].sum()), "rbi": int(b["RBI"].sum()), "sb": int(b["SB"].sum()),
                                 "cs": int(b["CS"].sum()), "h": int(b["H"].sum()), "pa": int(b["PA"].sum()),
                                 "sv": int(pt["SV"].sum()), "w": int(pt["W"].sum())}
print("league_official", out["league_official"])
# ---- Swing Lab: Savant bat tracking, mid-2023 on (a separate era from the roto league) ----
from statcast_roto.bat_tracking import bat_payload  # noqa: E402

bat = bat_payload(ROOT / "data" / "bat_tracking")  # None (with a fetch hint) until a season has all five CSVs
if bat is not None:
    out["bat"] = bat

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("payload.json")
OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
print("wrote", OUT, OUT.stat().st_size)
