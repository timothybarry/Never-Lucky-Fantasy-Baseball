"""Swing Lab data: Savant's leaderboards joined, qualified and turned into the page's payload (offline fixtures).

The fixtures are raw text in Savant's own CSV format: a UTF-8 BOM, quoted ids and quoted numbers such as
"80.994236701", names as "Last, First" and no newline after the last row."""

import json
import sys
import urllib.parse
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import statcast_roto.bat_tracking as bt  # noqa: E402
from statcast_roto.bat_tracking import bat_payload, outcome_fit, qualify, season_table, strict_cv  # noqa: E402

SP = ('"id","name","side","avg_bat_speed","swing_tilt","attack_angle","attack_direction","ideal_attack_angle_rate",'
      '"avg_intercept_y_vs_plate","avg_intercept_y_vs_batter","avg_batter_y_position","avg_batter_x_position","competitive_swings"')
BS = ('"id","name","swings_competitive","percent_swings_competitive","contact","avg_bat_speed","hard_swing_rate",'
      '"squared_up_per_bat_contact","squared_up_per_swing","blast_per_bat_contact","blast_per_swing","swing_length","swords",'
      '"batter_run_value","whiffs","whiff_per_swing","batted_ball_events","batted_ball_event_per_swing"')
EX = ('"last_name, first_name","player_id","year","pa","bip","ba","est_ba","est_ba_minus_ba_diff","slg","est_slg",'
      '"est_slg_minus_slg_diff","woba","est_woba","est_woba_minus_woba_diff"')
SC = ('"last_name, first_name","player_id","attempts","avg_hit_angle","anglesweetspotpercent","max_hit_speed","avg_hit_speed",'
      '"ev50","fbld","gb","max_distance","avg_distance","avg_hr_distance","ev95plus","ev95percent","barrels","brl_percent","brl_pa"')
LEAGUE_ROW = '9999,"League","R","71.794129595",32.220627653617505,10.028216657778847,-1.75976423169991,0.5100442674345077,2.87,30.73,27.85,27.72,{}'


def _write(path: Path, head: str, rows) -> None:
    path.write_bytes(("﻿" + "\n".join([head, *rows])).encode("utf-8"))


def _season(src: Path, year: str, hitters, league_swings=297_284, kinds=tuple(bt.ENDPOINTS)) -> Path:
    """One season's leaderboards as Savant serves them. A hitter without "brl" has too few batted balls for the
    Statcast table and is left out of it."""
    rows = {
        "swing_path": (SP, [f'{h["id"]},"{h["name"]}","{h["side"]}","{h["bat"]:.9f}",{h["tilt"]},{h["aa"]},{h["dir"]},'
                            f'{h["ideal"]},2.86,30.66,27.80,27.93,{h["swings"]}' for h in hitters]),
        "league": (SP, [LEAGUE_ROW.format(league_swings)]),
        "bat_speed": (BS, [f'{h["id"]},"{h["name"]}",{h["swings"]},0.91,{h["swings"] * 2 // 3},"{h["bat"]:.9f}",0.6,0.3,'
                           f'{h["sq"]},0.2,{h["blast"]},"{h["length"]:.9f}",4,-1.5,{round(h["swings"] * h["whiff"])},'
                           f'{h["whiff"]},{h["swings"] // 3},0.33' for h in hitters]),
        "expected": (EX, [f'"{h["name"]}","{h["id"]}","{year}","{h["swings"] // 2}","{h["swings"] // 3}",0.25,0.26,-0.01,'
                          f'0.42,0.45,-0.03,{h["xwoba"] - 0.01:.3f},{h["xwoba"]},0.01' for h in hitters]),
        "statcast": (SC, [f'"{h["name"]}","{h["id"]}","{h["swings"] // 3}","12.5",33.1,"110.2","89","95.1","92","85.3","420",'
                          f'"170","395","{h["swings"] // 6}",{h["ev95"]},"{h["swings"] // 30}",{h["brl"]},{h["brl"] * 0.7:.1f}'
                          for h in hitters if h["brl"] is not None]),
    }
    for kind in kinds:
        _write(src / f"{kind}_{year}.csv", *rows[kind])
    return src


def _hitter(i, name, side, swings, **kw):
    return {"id": i, "name": name, "side": side, "swings": swings, "bat": 72.0, "tilt": 32.0, "aa": 10.0, "dir": -1.7,
            "ideal": 0.5, "length": 7.3, "sq": 0.25, "blast": 0.11, "whiff": 0.23, "brl": 8.1, "ev95": 40.2, "xwoba": 0.32, **kw}


FOUR = [_hitter(100001, "Hitter, Big", "R", 900, bat=80.994236701, length=7.6, brl=15.2, ev95=52.0, xwoba=0.38),
        _hitter(100002, "Switch, Sam", "R", 265),
        _hitter(100003, "Lefty, Lou", "L", 264),
        _hitter(100004, "Peña Jr., Tomás", "L", 12, brl=None)]
SIDES = {100002: "S", 100003: "S", 100004: "L"}  # the MLB Stats API calls Sam and Lou switch hitters
# League swings tracked per season. A full season is the median of the full ones, (286,333 + 297,284) / 2, so the cuts
# are 600 x swings / 291,808.5: 270 in 2023 (tracked from July), 589 in 2024 and 611 in 2025.
LEAGUE_SWINGS = {"2023": 131_430, "2024": 286_333, "2025": 297_284}


def _league_folder(src: Path, years=("2023", "2024", "2025"), n=12, seed=5):
    """n hitters over several seasons, their swing traits persistent and their outcomes a noisy linear rule of them,
    plus a 9-swing hitter each season, so every table reaches down to a handful of swings like an all-batter one."""
    rng, truth = np.random.default_rng(seed), {}
    base = rng.normal(size=(n, 6))
    for y in years:
        hitters = [_hitter(299999, "Cup, Coffee", "R", 9)]
        for k in range(n):
            z, e = base[k] + rng.normal(0, 0.3, 6), rng.normal(0, 1, 5)
            hitters.append(_hitter(
                200000 + k, "Peña Jr., Tomás" if k == 0 else f"Batter{k}, Test", "LR"[k % 2], (330 if y == "2023" else 660) + 15 * k,
                bat=72 + 3 * z[0], tilt=round(32 + 4 * z[1], 3), aa=round(10 + 3.5 * z[2], 3), dir=round(-1.7 + 4 * z[3], 3),
                length=7.3 + 0.4 * z[4], ideal=round(0.5 + 0.08 * z[5], 4), brl=round(8 + 2 * z[0] + z[2] + 0.5 * e[0], 1),
                ev95=round(40 + 6 * z[0] + 2 * e[1], 1), blast=round(0.11 + 0.024 * z[0] + 0.01 * e[2], 4),
                sq=round(0.25 - 0.02 * z[0] + 0.01 * e[3], 4), whiff=round(0.23 + 0.03 * z[0] + 0.03 * z[2] + 0.01 * e[4], 4)))
        _season(src, y, hitters, LEAGUE_SWINGS[y])
        truth.update({(y, h["id"]): h for h in hitters})
    return src, truth


def test_season_table_joins_savants_csvs_and_upgrades_only_r_to_switch(tmp_path):
    t = season_table("2025", _season(tmp_path, "2025", FOUR), sides=SIDES).set_index("id")
    assert t.loc[100001, "avg_bat_speed"] == 80.994236701  # quoted numbers and quoted ids parse, BOM and all
    assert (t.loc[100001, "swing_length"], t.loc[100001, "est_woba"], t.loc[100001, "brl_percent"]) == (7.6, 0.38, 15.2)
    assert t["side"].to_dict() == {100001: "R", 100002: "S", 100003: "L", 100004: "L"}  # Lou's season was left-only
    assert np.isnan(t.loc[100004, "brl_percent"]) and t.loc[100004, "pa"] == 6  # missing from one table: row kept, NaN there


def test_qualifier_rounds_once_so_the_label_is_the_filter(tmp_path):
    t = season_table("2025", _season(tmp_path, "2025", FOUR))
    q = qualify(t, 131_430, 297_284)  # 2023's share: 600 x 131,430 / 297,284 = 265.26 -> 265
    assert type(q.attrs["min_swings"]) is int and q.attrs["min_swings"] == 265
    assert sorted(q.competitive_swings) == [265, 900]  # exactly 265 is kept, 264 is not
    full, half = qualify(t, 297_284, 297_284), qualify(t, 148_642, 297_284)
    assert (full.attrs["min_swings"], list(full.id)) == (600, [100001])
    assert (half.attrs["min_swings"], list(half.id)) == (300, [100001])


def test_every_savant_request_pins_the_regular_season_and_every_batter(tmp_path, monkeypatch):
    urls = []
    monkeypatch.setattr(bt, "_get", lambda url, **kw: urls.append(url) or '"id"\n1')
    monkeypatch.setattr(bt, "PAUSE_S", 0)
    bt.fetch_tables(["2024", "2025"], tmp_path, log=lambda *a: None)
    qs = [(u.partition("?")[0], dict(urllib.parse.parse_qsl(u.partition("?")[2], keep_blank_values=True))) for u in urls]
    tracked = [q for path, q in qs if "/bat-tracking" in path]
    assert len(qs) == 10 and len(tracked) == 6  # five leaderboards a season, three of them bat tracking
    for q in tracked:  # "R" silently means regular season plus postseason; "q" is Savant's own qualifier
        assert (q["gameType"], q["minSwings"], q["minGroupSwings"], q["csv"]) == ("Regular", "1", "1", "true")
    assert all(q["min"] == "1" for path, q in qs if "/bat-tracking" not in path)  # expected stats and Statcast: every batter
    assert sorted(q["type"] for q in tracked) == ["batter"] * 4 + ["league"] * 2


@pytest.mark.parametrize("broken, message", [
    ("qualified", r"swing_path_2025\.csv starts at 264 competitive swings.*Min\. Total Swings 1"),
    ("bat_speed", r"bat_speed_2025\.csv lists 3 hitters and swing_path_2025\.csv 4.*Min\. Total Swings 1"),
    ("league", r"league_2025\.csv has 2 rows.*Type League"),
])
def test_files_saved_at_the_wrong_savant_settings_are_named(tmp_path, broken, message):
    _season(tmp_path, "2024", FOUR)
    _season(tmp_path, "2025", FOUR[:3] if broken == "qualified" else FOUR)  # page default: Savant's qualifiers only
    if broken == "bat_speed":
        _season(tmp_path, "2025", FOUR[:3], kinds=("bat_speed",))
    if broken == "league":  # the batter table saved under the league name
        _write(tmp_path / "league_2025.csv", SP, [LEAGUE_ROW.format(1), LEAGUE_ROW.format(2)])
    with pytest.raises(ValueError, match=message):
        bat_payload(tmp_path, log=lambda m: None)


def test_bat_payload_builds_the_swing_lab_from_complete_seasons(tmp_path):
    src, truth = _league_folder(tmp_path)
    _season(src, "2026", FOUR, kinds=("swing_path", "league"))  # a season saved halfway
    (src / "bat_sides.json").write_text(json.dumps({"200001": "S", "200002": "S"}), encoding="utf-8")
    logs = []
    p = bat_payload(src, log=logs.append)
    assert "skipping 2026, missing bat_speed_2026.csv, expected_2026.csv, statcast_2026.csv" in logs[0]
    assert p["tags"] == ["2023", "2024", "2025"] and list(p["partial"]) == ["2023"]
    assert p["min_swings"] == {"2023": 270, "2024": 589, "2025": 611}  # 2023 stays out of the full-season count
    rows = {(y, r[0]): dict(zip(p["cols"], r)) for y, rs in p["seasons"].items() for r in rs}
    assert len(rows) == 36 and not any(i == 299999 for _, i in rows)  # the 9-swing hitter never qualifies
    for (y, i), r in rows.items():  # percents become fractions once
        assert (r["brl"], r["hardhit"]) == (round(truth[y, i]["brl"] / 100, 4), round(truth[y, i]["ev95"] / 100, 4))
    assert (rows["2024", 200003]["name"], rows["2025", 200000]["name"]) == ("Test Batter3", "Tomás Peña Jr.")
    assert (rows["2024", 200001]["side"], rows["2024", 200002]["side"]) == ("S", "L")
    m, brl = p["model"], [truth[k]["brl"] / 100 for k in rows]
    assert (m["n"], m["hitters"], m["features"]) == (36, 12, ["bat_speed", "aa", "tilt", "dir", "length", "ideal"])
    assert m["outcomes"]["brl"]["clip"] == [round(min(brl), 4), round(max(brl), 4)]
    assert m["outcomes"]["brl"]["intercept"] == pytest.approx(np.mean(brl), abs=1e-5)  # standardized traits: mean outcome
    assert p["league"]["2025"] == {"bat_speed": 71.794, "aa": 10.028, "tilt": 32.221, "dir": -1.76, "ideal": 0.51}
    json.dumps(p, allow_nan=False)  # the page embeds it: no NaN or Infinity


def test_bat_payload_without_2023_has_no_partial_note_and_warns_about_sides(tmp_path):
    src, _ = _league_folder(tmp_path)
    (src / "statcast_2023.csv").unlink()
    logs = []
    p = bat_payload(src, log=logs.append)
    assert p["tags"] == ["2024", "2025"] and p["partial"] == {} and p["min_swings"] == {"2024": 589, "2025": 611}
    assert "skipping 2023, missing statcast_2023.csv" in logs[0]
    assert any("no bat_sides.json" in m and "right-handed" in m for m in logs)


def test_bat_payload_without_a_complete_season_says_how_to_fetch(tmp_path):
    logs = []
    assert bat_payload(tmp_path / "not_there", log=logs.append) is None
    _season(tmp_path, "2025", FOUR, kinds=("swing_path", "bat_speed"))
    assert bat_payload(tmp_path, log=logs.append) is None
    assert "skipping 2025" in logs[-2] and "scripts/fetch_bat_tracking.py" in logs[-1]


@pytest.mark.parametrize("keep", [("2023",), ("2025",)])
def test_bat_payload_needs_two_seasons_one_of_them_full(tmp_path, keep):
    src, _ = _league_folder(tmp_path)
    for y in {"2023", "2024", "2025"} - set(keep):
        (src / f"statcast_{y}.csv").unlink()
    logs = []
    assert bat_payload(src, log=logs.append) is None  # no held-out season to score on, or no full season to scale from
    assert "two complete seasons" in logs[-1]


def test_off_map_distance_skips_the_hitters_own_seasons(tmp_path):
    src, _ = _league_folder(tmp_path)
    p = bat_payload(src, log=lambda *a: None)
    m = p["model"]
    rows = [dict(zip(p["cols"], r)) for rs in p["seasons"].values() for r in rs]
    Z = np.array([[(r[f] - mu) / sd for f, mu, sd in zip(m["features"], m["mean"], m["sd"])] for r in rows])
    ids = np.array([r["id"] for r in rows])
    d = np.sqrt(((Z[:, None] - Z[None]) ** 2).sum(-1))
    d[ids[:, None] == ids[None]] = np.inf
    assert m["offmap"] == pytest.approx(np.quantile(np.sort(d, axis=1)[:, 4], 0.95), abs=2e-3)


def test_strict_cv_never_lets_a_hitter_predict_himself():
    rng = np.random.default_rng(1)
    ids, seasons = np.repeat(np.arange(30), 3), np.tile(["2023", "2024", "2025"], 30)  # row 0: hitter 0 in 2023
    X = np.column_stack([np.ones(90), rng.normal(size=(90, 2))])
    y = X @ [0.1, 0.03, -0.02] + rng.normal(0, 0.01, 90)
    later, same = y.copy(), y.copy()
    later[1] += 1  # hitter 0's own 2024
    same[3] += 1  # hitter 1's 2023, the season held out
    pred = strict_cv(X, y, seasons, ids)[0]
    assert strict_cv(X, later, seasons, ids)[0] == pred and strict_cv(X, same, seasons, ids)[0] == pred
    solo = np.arange(90)  # leave out only the season: his own 2024 now moves his 2023 prediction
    assert abs(strict_cv(X, later, seasons, solo)[0] - strict_cv(X, y, seasons, solo)[0]) > 1e-3


def test_the_80_percent_band_holds_for_hitters_the_fit_never_saw():
    rng = np.random.default_rng(2)
    beta = np.array([0.25, 0.03, -0.02, 0.01, 0.0, 0.005, -0.01])

    def draw(n_hitters, n_seasons):
        ids, seasons = np.repeat(np.arange(n_hitters), n_seasons), np.tile(np.arange(n_seasons), n_hitters)
        X = np.column_stack([np.ones(len(ids)), rng.normal(size=(len(ids), 6))])
        return X, X @ beta + rng.exponential(0.03, len(ids)), seasons, ids  # skewed misses, so the band is lopsided

    seen = draw(300, 3)
    fit = outcome_fit(*seen)
    held_out = seen[1] - strict_cv(*seen)  # the R² shown is the held-out one
    assert fit["r2_oos"] == round(1 - (held_out ** 2).sum() / ((seen[1] - seen[1].mean()) ** 2).sum(), 3)
    assert fit["band"] == [round(float(q), 4) for q in np.quantile(held_out, [0.1, 0.9])]  # held-out misses, not in-sample
    X, y, _, _ = draw(5000, 1)
    miss = y - (fit["intercept"] + X[:, 1:] @ np.array(fit["coef"]))
    (lo, hi), inside = fit["band"], (miss >= fit["band"][0]) & (miss <= fit["band"][1])
    assert abs(inside.mean() - 0.8) < 0.03
    assert abs((miss < lo).mean() - 0.1) < 0.025 and abs((miss > hi).mean() - 0.1) < 0.025
