"""
dashboard.py
============

Generate a single self-contained, dark-themed, interactive HTML dashboard from
one or more scored seasons. Never Lucky 2.0 adds a Players tab on top of the
existing standings, leaderboards, and team-roster audit:

  1. Global season switcher
  2. Standings tab with clickable team roster inspection
  3. Leaderboards tab with the original 13-view Chart.js drill-down
  4. Players tab with search, composed filters, sortable wide tables, frozen
     player column, small-sample flagging, and single-player profile cards with
     pooled percentiles plus prior-year ghost context

The output remains fully self-contained: Chart.js is inlined and all data is
baked into the HTML payload.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


LEADERBOARD_SPECS: list[dict[str, Any]] = [
    {"key": "risers", "label": "Value risers (Statcast)", "side": "special", "col": "value_delta", "fmt": "delta", "color": "teal", "low": False},
    {"key": "xwoba", "label": "xwOBA leaders", "side": "hitting", "col": "xwoba", "fmt": "rate3", "color": "teal", "low": False, "min_col": "pa", "min_val": 100},
    {"key": "obp", "label": "OBP leaders", "side": "hitting", "col": "obp", "fmt": "rate3", "color": "teal", "low": False, "min_col": "pa", "min_val": 100, "season_only": True},
    {"key": "barrels", "label": "Barrel leaders", "side": "hitting", "col": "barrels", "fmt": "int", "color": "amber", "low": False},
    {"key": "ev90", "label": "90th-pct EV leaders", "side": "hitting", "col": "ev90", "fmt": "rate1", "color": "amber", "low": False, "min_col": "batted_balls", "min_val": 50},
    {"key": "chase", "label": "Chase% (lowest)", "side": "hitting", "col": "chase_rate", "fmt": "pct", "color": "blue", "low": True, "min_col": "pitches_seen", "min_val": 300},
    {"key": "r_plus_rbi", "label": "R + RBI leaders", "side": "hitting", "col": "r_plus_rbi", "fmt": "int", "color": "amber", "low": False, "season_only": True},
    {"key": "sb", "label": "Stolen base leaders", "side": "hitting", "col": "sb", "fmt": "int", "color": "amber", "low": False, "season_only": True},
    {"key": "hr", "label": "Home run leaders", "side": "hitting", "col": "hr", "fmt": "int", "color": "amber", "low": False},
    {"key": "k", "label": "Strikeout leaders", "side": "pitching", "col": "k", "fmt": "int", "color": "amber", "low": False},
    {"key": "xfip", "label": "xFIP (lowest)", "side": "pitching", "col": "xfip", "fmt": "rate2", "color": "blue", "low": True, "min_col": "ip", "min_val": 25},
    {"key": "whiff", "label": "Whiff% leaders", "side": "pitching", "col": "whiff_rate", "fmt": "pct", "color": "teal", "low": False, "min_col": "pitches", "min_val": 400},
    {"key": "barrel_allowed", "label": "Barrel% allowed (lowest)", "side": "pitching", "col": "barrel_rate_allowed", "fmt": "pct", "color": "blue", "low": True, "min_col": "batted_balls_allowed", "min_val": 60},
    {"key": "qs", "label": "Quality start leaders", "side": "pitching", "col": "qs", "fmt": "int", "color": "amber", "low": False},
]

PLAYER_COLUMNS: dict[str, list[dict[str, Any]]] = {
    "hitting": [
        {"key": "player_name", "label": "Player", "fmt": "text", "sticky": True},
        {"key": "position", "label": "Pos", "fmt": "text"},
        {"key": "sample_tag", "label": "Sample", "fmt": "text"},
        {"key": "signal_score", "label": "Signal", "fmt": "delta2", "color": "teal"},
        {"key": "noise_gap", "label": "Noise Gap", "fmt": "delta2", "color": "amber"},
        {"key": "action", "label": "Action", "fmt": "text"},
        {"key": "archetype", "label": "Archetype", "fmt": "text"},
        {"key": "pa", "label": "PA", "fmt": "int"},
        {"key": "barrels", "label": "Barrels", "fmt": "int", "color": "amber"},
        {"key": "xwoba", "label": "xwOBA", "fmt": "rate3", "color": "teal"},
        {"key": "ev90", "label": "EV90", "fmt": "rate1", "color": "amber"},
        {"key": "chase_rate", "label": "Chase%", "fmt": "pct", "color": "blue", "low_good": True},
        {"key": "hr", "label": "HR", "fmt": "int", "color": "amber"},
        {"key": "r_plus_rbi", "label": "R+RBI", "fmt": "int", "color": "amber"},
        {"key": "sb", "label": "SB", "fmt": "int"},
        {"key": "avg", "label": "AVG", "fmt": "rate3"},
        {"key": "obp", "label": "OBP", "fmt": "rate3", "color": "teal"},
        {"key": "slg", "label": "SLG", "fmt": "rate3", "color": "amber"},
        {"key": "statcast_rank", "label": "SC Rank", "fmt": "int"},
        {"key": "traditional_rank", "label": "Trad Rank", "fmt": "int"},
    ],
    "pitching": [
        {"key": "player_name", "label": "Player", "fmt": "text", "sticky": True},
        {"key": "sample_tag", "label": "Sample", "fmt": "text"},
        {"key": "signal_score", "label": "Signal", "fmt": "delta2", "color": "teal"},
        {"key": "noise_gap", "label": "Noise Gap", "fmt": "delta2", "color": "amber"},
        {"key": "action", "label": "Action", "fmt": "text"},
        {"key": "archetype", "label": "Archetype", "fmt": "text"},
        {"key": "ip", "label": "IP", "fmt": "rate1"},
        {"key": "k", "label": "K", "fmt": "int", "color": "amber"},
        {"key": "xfip", "label": "xFIP", "fmt": "rate2", "color": "blue", "low_good": True},
        {"key": "whiff_rate", "label": "Whiff%", "fmt": "pct", "color": "teal"},
        {"key": "barrel_rate_allowed", "label": "Barrel% Allowed", "fmt": "pct", "color": "blue", "low_good": True},
        {"key": "qs", "label": "QS", "fmt": "int", "color": "amber"},
        {"key": "era", "label": "ERA", "fmt": "rate2", "color": "coral", "low_good": True},
        {"key": "whip", "label": "WHIP", "fmt": "rate2", "color": "coral", "low_good": True},
        {"key": "statcast_rank", "label": "SC Rank", "fmt": "int"},
        {"key": "traditional_rank", "label": "Trad Rank", "fmt": "int"},
    ],
}

PROFILE_STATS: dict[str, list[dict[str, Any]]] = {
    "hitting": [
        {"key": "signal_score", "label": "Signal Score", "fmt": "delta2"},
        {"key": "noise_gap", "label": "Noise Gap", "fmt": "delta2"},
        {"key": "xwoba", "label": "xwOBA", "fmt": "rate3"},
        {"key": "obp", "label": "OBP", "fmt": "rate3"},
        {"key": "slg", "label": "SLG", "fmt": "rate3"},
        {"key": "barrels", "label": "Barrels", "fmt": "int"},
        {"key": "ev90", "label": "90th-pct EV", "fmt": "rate1"},
        {"key": "chase_rate", "label": "Chase Discipline", "fmt": "pct", "low_good": True},
        {"key": "r_plus_rbi", "label": "R + RBI", "fmt": "int"},
        {"key": "sb", "label": "SB", "fmt": "int"},
    ],
    "pitching": [
        {"key": "signal_score", "label": "Signal Score", "fmt": "delta2"},
        {"key": "noise_gap", "label": "Noise Gap", "fmt": "delta2"},
        {"key": "k", "label": "Strikeouts", "fmt": "int"},
        {"key": "xfip", "label": "xFIP", "fmt": "rate2", "low_good": True},
        {"key": "whiff_rate", "label": "Whiff%", "fmt": "pct"},
        {"key": "barrel_rate_allowed", "label": "Barrel% Allowed", "fmt": "pct", "low_good": True},
        {"key": "qs", "label": "Quality Starts", "fmt": "int"},
        {"key": "whip", "label": "WHIP", "fmt": "rate2", "low_good": True},
    ],
}

TOP_N = 10


@dataclass
class SeasonData:
    tag: str
    n_hitters: int
    n_pitchers: int
    standings: list[dict[str, Any]]
    leaderboards: dict[str, list]
    teams: dict[str, dict[str, Any]]
    top_riser: str
    players: dict[str, list[dict[str, Any]]]
    leaderboard_windows: dict[str, dict[str, Any]]


def _num(v):
    if pd.isna(v):
        return None
    f = float(v)
    return int(f) if f.is_integer() else round(f, 4)


def _rank_num(v):
    if pd.isna(v):
        return None
    return int(v)


def _short(name: str) -> str:
    parts = str(name).split()
    if len(parts) >= 2:
        return f"{parts[0][0]}. {parts[-1]}"
    return str(name)


def _safe_position(row: pd.Series) -> str:
    for col in ("position", "pos", "primary_position"):
        if col in row and not pd.isna(row[col]) and str(row[col]).strip():
            return str(row[col]).strip()
    return "—"


def _sample_tag(row: pd.Series, side: str) -> tuple[bool, str]:
    if side == "hitting":
        pa = float(row.get("pa", 0) or 0)
        bbe = float(row.get("batted_balls", 0) or 0)
        small = pa < 100 or bbe < 50
        if pa < 100:
            return True, "small"
        if bbe < 50:
            return True, "bbe"
        return small, "ok"
    ip = float(row.get("ip", 0) or 0)
    pitches = float(row.get("pitches", 0) or 0)
    small = ip < 25 or pitches < 400
    if ip < 25:
        return True, "small"
    if pitches < 400:
        return True, "pitches"
    return small, "ok"


def _player_rows(df: pd.DataFrame, values: pd.DataFrame, side: str) -> list[dict[str, Any]]:
    vcols = ["player_id", "side", "statcast_value", "traditional_value", "value_delta",
             "statcast_rank", "traditional_rank", "rank_delta"]
    merged = df.copy()
    merged["side"] = side
    merged = merged.merge(values[vcols], on=["player_id", "side"], how="left")
    rows: list[dict[str, Any]] = []
    skip = {"side"}
    for _, r in merged.iterrows():
        small, tag = _sample_tag(r, side)
        row: dict[str, Any] = {
            "player_id": str(r["player_id"]),
            "player_name": str(r["player_name"]),
            "short_name": _short(str(r["player_name"])),
            "side": side,
            "position": _safe_position(r) if side == "hitting" else "—",
            "small_sample": bool(small),
            "sample_tag": tag,
            "signal_score": _num(r.get("statcast_value")),
            "traditional_value": _num(r.get("traditional_value")),
            "noise_gap": _num(r.get("value_delta")),
            "statcast_rank": _rank_num(r.get("statcast_rank")),
            "traditional_rank": _rank_num(r.get("traditional_rank")),
            "rank_delta": _rank_num(r.get("rank_delta")),
            "action": "Monitor",
            "archetype": "Unclassified",
            "percentiles": {},
            "ghost": None,
        }
        for col, val in r.items():
            if col in row or col in skip or col in {"statcast_value", "traditional_value", "value_delta"}:
                continue
            if col in {"player_name", "position", "pos", "primary_position"}:
                continue
            if pd.api.types.is_number(val):
                row[col] = _num(val)
        row["search_blob"] = " ".join([row["player_name"], row["short_name"], row["position"], row["action"], row["archetype"]]).lower()
        rows.append(row)
    return rows



def _window_minimum(spec: dict[str, Any], window_key: str) -> float:
    """Scale season-level qualification gates for shorter leaderboard windows."""
    base = float(spec.get("min_val", 0) or 0)
    if base <= 0 or window_key == "season":
        return base
    # Strict enough that a two-inning reliever can't post a negative xFIP or a
    # ten-way 0.0% barrel tie at the top, loose enough that a hot list exists.
    scales = {"last30": 0.30, "last14": 0.15, "last7": 0.08}
    mins = {
        "pa": {"last30": 50, "last14": 25, "last7": 15},
        "batted_balls": {"last30": 30, "last14": 18, "last7": 10},
        "pitches_seen": {"last30": 200, "last14": 100, "last7": 50},
        "ip": {"last30": 15, "last14": 8, "last7": 5},
        "pitches": {"last30": 250, "last14": 130, "last7": 70},
        "batted_balls_allowed": {"last30": 40, "last14": 25, "last7": 12},
    }
    col = str(spec.get("min_col", ""))
    if col in mins and window_key in mins[col]:
        return float(mins[col][window_key])
    return max(1.0, round(base * scales.get(window_key, 1.0)))


def build_leaderboard_payload(
    hitters: pd.DataFrame,
    pitchers: pd.DataFrame,
    comparison: Any | None,
    *,
    window_key: str = "season",
    top_n: int = TOP_N,
) -> dict[str, list]:
    """Build the chart-ready leaderboard payload used by the HTML app.

    The season view uses the locked 1.0 qualification gates. Shorter windows
    scale those gates down so "last 7 days" does not become an empty chart,
    while still avoiding one-swing garbage at the top of rate leaderboards.
    """
    leaderboards: dict[str, list] = {}
    for spec in LEADERBOARD_SPECS:
        if spec.get("season_only") and window_key != "season":
            leaderboards[spec["key"]] = []
            continue
        if spec["key"] == "risers":
            if comparison is None or getattr(comparison, "biggest_statcast_bumps", None) is None:
                leaderboards["risers"] = []
            else:
                riser = comparison.biggest_statcast_bumps.head(top_n)
                leaderboards["risers"] = [[_short(n), _num(v)]
                    for n, v in zip(riser["player_name"], riser["value_delta"])]
            continue
        df = hitters if spec["side"] == "hitting" else pitchers
        col = spec["col"]
        if col not in df.columns:
            leaderboards[spec["key"]] = []
            continue
        sub = df[df[col].notna()].copy()
        if "min_col" in spec and spec["min_col"] in sub.columns:
            sub = sub[pd.to_numeric(sub[spec["min_col"]], errors="coerce").fillna(0) >= _window_minimum(spec, window_key)]
        if col == "xfip":
            sub = sub[pd.to_numeric(sub[col], errors="coerce") >= 0]  # a negative xFIP is a tiny-sample artifact
        # Ties break toward the bigger sample, so a 0.0% leader has actually faced someone.
        by, asc = [col], [spec["low"]]
        if spec.get("min_col") in sub.columns:
            by.append(spec["min_col"]); asc.append(False)
        sub = sub.sort_values(by, ascending=asc).head(top_n)
        leaderboards[spec["key"]] = [[_short(r["player_name"]), _num(r[col])]
                                     for _, r in sub.iterrows()]
    return leaderboards

def extract_season(tag, result, comparison, hitters, pitchers, leaderboard_windows: dict[str, Any] | None = None) -> SeasonData:
    standings = result.standings.copy()
    max_pts = standings["total"].max()
    min_pts = standings["total"].min()
    standings_rows = [
        {"rank": int(r["rank"]), "team": str(r["team"]), "total": _num(r["total"]),
         "leader": bool(r["total"] == max_pts), "last": bool(r["total"] == min_pts)}
        for _, r in standings.iterrows()
    ]

    leaderboards = build_leaderboard_payload(hitters, pitchers, comparison, window_key="season")
    windows: dict[str, dict[str, Any]] = {
        "season": {
            "label": "Season",
            "start": None,
            "end": None,
            "n_pitches": None,
            "leaderboards": leaderboards,
        }
    }
    if leaderboard_windows:
        # Accept either a raw {last7: {...}} mapping or a wrapped {timeframes: {...}} file.
        extra = leaderboard_windows.get("timeframes", leaderboard_windows)
        for key, val in extra.items():
            if key == "season":
                continue
            if isinstance(val, dict) and "leaderboards" in val:
                windows[key] = val

    rps = result.roster_player_stats
    teams: dict[str, dict] = {}
    for _, srow in standings.iterrows():
        team = str(srow["team"])
        tdf = rps[rps["team"] == team]
        h = tdf[tdf["side"] == "hitting"]
        p = tdf[tdf["side"] == "pitching"]
        teams[team] = {
            "rank": int(srow["rank"]), "pts": _num(srow["total"]),
            "hitters": [{"name": _short(r["player_name"]), "xwoba": _num(r["xwoba"]),
                "barrels": _num(r["barrels"]), "ev90": _num(r["ev90"]),
                "chase": _num(r["chase_rate"]), "rrbi": _num(r["r_plus_rbi"]),
                "sb": _num(r["sb"]), "hr": _num(r["hr"])}
                for _, r in h.sort_values("barrels", ascending=False).iterrows()],
            "pitchers": [{"name": _short(r["player_name"]), "xfip": _num(r["xfip"]),
                "k": _num(r["k"]), "whiff": _num(r["whiff_rate"]),
                "brla": _num(r["barrel_rate_allowed"]), "qs": _num(r["qs"])}
                for _, r in p.sort_values("k", ascending=False).iterrows()],
        }

    players = {
        "hitting": _player_rows(hitters, comparison.player_values, "hitting"),
        "pitching": _player_rows(pitchers, comparison.player_values, "pitching"),
    }
    top_riser = leaderboards["risers"][0][0] if leaderboards.get("risers") else "--"
    return SeasonData(tag, int(len(hitters)), int(len(pitchers)),
                      standings_rows, leaderboards, teams, top_riser, players, windows)


def _action_from_row(row: dict[str, Any]) -> str:
    sig = row.get("signal_score")
    gap = row.get("noise_gap")
    sig = float(sig) if sig is not None else 0.0
    gap = float(gap) if gap is not None else 0.0
    if row.get("small_sample") and sig >= 0.45:
        return "Limited Sample"
    if gap >= 0.75 and sig >= 0.15:
        return "Positive Skill Gap"
    if gap <= -0.75:
        return "Negative Skill Gap"
    if sig >= 1.0:
        return "Strong Skill Signal"
    if sig >= 0.35:
        return "Moderate Skill Signal"
    if sig <= -0.65:
        return "Weak Skill Signal"
    return "Monitor"


def _pct(row: dict[str, Any], key: str) -> float:
    return float(row.get("percentiles", {}).get(key) or 0)


def _archetype_from_row(row: dict[str, Any]) -> str:
    side = row["side"]
    if row.get("small_sample"):
        return "Limited Sample"
    if row.get("noise_gap") is not None and float(row["noise_gap"]) <= -0.75:
        return "Production Outpacing Skills"
    if side == "hitting":
        if _pct(row, "xwoba") >= 78 and _pct(row, "chase_rate") >= 72:
            return "On-Base Skill"
        if _pct(row, "barrels") >= 78 and _pct(row, "ev90") >= 72:
            return "Power Contact Profile"
        if _pct(row, "sb") >= 85 and _pct(row, "barrels") < 55:
            return "Speed-Oriented Profile"
        if _pct(row, "xwoba") >= 65 and _pct(row, "barrels") < 60:
            return "Contact-Oriented Profile"
        if _pct(row, "barrels") >= 70 and _pct(row, "xwoba") < 50:
            return "Power with OBP Risk"
        return "Balanced Hitting Profile"
    if _pct(row, "k") >= 75 and _pct(row, "whiff_rate") >= 70:
        return "Strikeout and Whiff Profile"
    if _pct(row, "xfip") >= 75 and _pct(row, "barrel_rate_allowed") >= 60:
        return "Run Prevention Profile"
    if _pct(row, "barrel_rate_allowed") >= 78:
        return "Contact Suppression Profile"
    if _pct(row, "qs") >= 75:
        return "Workload Profile"
    return "Balanced Pitching Profile"


def _enrich_player_percentiles_and_ghosts(seasons: list[SeasonData]) -> None:
    rows_by_side: dict[str, list[dict[str, Any]]] = {"hitting": [], "pitching": []}
    for season in seasons:
        for side in rows_by_side:
            rows_by_side[side].extend(season.players.get(side, []))

    profile_by_side = {side: {s["key"]: s for s in specs} for side, specs in PROFILE_STATS.items()}
    for side, rows in rows_by_side.items():
        for key, spec in profile_by_side[side].items():
            vals = pd.Series([r.get(key) for r in rows], dtype="float64")
            good = vals.notna()
            if not good.any():
                continue
            ranked = vals[good].rank(method="average", pct=True, ascending=not spec.get("low_good", False)) * 100
            for idx, pct in ranked.items():
                rows[int(idx)]["percentiles"][key] = round(float(pct), 1)

    for row in rows_by_side["hitting"] + rows_by_side["pitching"]:
        row["action"] = _action_from_row(row)
        row["archetype"] = _archetype_from_row(row)
        row["search_blob"] = " ".join([row["player_name"], row["short_name"], row.get("position") or "", row["action"], row["archetype"]]).lower()

    ordered_tags = [s.tag for s in seasons]
    season_lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for s in seasons:
        for side in ("hitting", "pitching"):
            for row in s.players.get(side, []):
                season_lookup[(s.tag, side, row["player_id"])] = row

    for i, tag in enumerate(ordered_tags):
        if i == 0:
            continue
        prev_tag = ordered_tags[i - 1]
        season = seasons[i]
        for side in ("hitting", "pitching"):
            for row in season.players.get(side, []):
                ghost = season_lookup.get((prev_tag, side, row["player_id"]))
                if not ghost:
                    continue
                keys = [s["key"] for s in PROFILE_STATS[side]]
                row["ghost"] = {
                    "season": prev_tag,
                    "stats": {k: ghost.get(k) for k in keys},
                    "percentiles": {k: ghost.get("percentiles", {}).get(k) for k in keys},
                }


def _banner_data_uri() -> str:
    """Return the embedded cyberpunk banner art as a data URI if present."""
    asset = Path(__file__).resolve().parents[2] / "assets" / "cyberpunk_signal_room.png"
    if not asset.exists():
        return ""
    encoded = base64.b64encode(asset.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def build_multi_season_dashboard(seasons: list[SeasonData], output_path) -> Path:
    """Bake seasons into one interactive HTML file."""
    output_path = Path(output_path)
    _enrich_player_percentiles_and_ghosts(seasons)
    payload = {
        "specs": LEADERBOARD_SPECS,
        "player_columns": PLAYER_COLUMNS,
        "profile_stats": PROFILE_STATS,
        "seasons": {s.tag: asdict(s) for s in seasons},
        "tags": [s.tag for s in seasons],
    }
    chartjs = (Path(__file__).parent / "vendor" / "chart.umd.js").read_text(encoding="utf-8")
    banner_uri = _banner_data_uri()
    html = (_TEMPLATE
            .replace("/*__CHARTJS__*/", chartjs)
            .replace("/*__PAYLOAD__*/", json.dumps(payload))
            .replace("/*__BANNER_IMAGE__*/", banner_uri))
    output_path.write_text(html, encoding="utf-8")
    return output_path


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Never Lucky 2.0 — Statcast Roto Lab</title>
<script>/*__CHARTJS__*/</script>
<style>
  :root{ --bg:#15171c; --panel:#1a1d23; --panel2:#1d2027; --panel3:#222631; --line:#2a2e37;
         --text:#c8ccd4; --bright:#e8ebf0; --muted:#7a818c; --dim:#5f6671;
         --teal:#3fd6a8; --amber:#e0b15a; --blue:#5aa9f0; --coral:#e0735a;
         --tealbg:#11332c; --tealbg2:#0f241f; --coralbg:#351b1a; --shadow:rgba(0,0,0,.28); }
  *{ box-sizing:border-box; margin:0; padding:0; }
  body{ background:radial-gradient(circle at top left,#1b2229 0,#15171c 42%); color:var(--text);
        font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; padding:24px; line-height:1.5; }
  .wrap{ max-width:1240px; margin:0 auto; background:rgba(21,23,28,.94); border-radius:16px; padding:22px 26px; box-shadow:0 18px 55px var(--shadow); }
  .hdr{ display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;
        border-bottom:0.5px solid var(--line); padding-bottom:16px; margin-bottom:16px; }
  .brand{ display:flex; align-items:center; gap:11px; }
  .logo{ width:36px; height:36px; border-radius:10px; background:linear-gradient(135deg,var(--tealbg),#221e16); display:flex; align-items:center; justify-content:center; font-size:18px; border:0.5px solid #345348; }
  .bname{ font-size:15px; font-weight:600; color:var(--bright); }
  .btag{ font-size:11px; color:#5fd3aa; }
  select,input{ background:var(--panel2); color:var(--bright); border:0.5px solid #3a3f4a; border-radius:8px;
          padding:7px 10px; font-family:inherit; font-size:13px; outline:none; }
  input::placeholder{ color:var(--dim); }
  select:focus,input:focus{ border-color:var(--teal); box-shadow:0 0 0 2px rgba(63,214,168,.08); }
  .ctrls{ display:flex; align-items:center; gap:8px; }
  .lbl{ font-size:11px; color:var(--muted); }
  .tabs{ display:flex; gap:8px; margin-bottom:16px; border-bottom:0.5px solid var(--line); padding-bottom:10px; }
  .tab{ background:transparent; color:var(--muted); border:0.5px solid #313641; border-radius:9px; padding:8px 14px; font-size:12px; cursor:pointer; font-family:inherit; }
  .tab.on{ color:var(--teal); border-color:var(--teal); background:var(--tealbg); }

  /* Cyberpunk Signal Room hero. The art is kept proportional: a blurred cover backplate fills the frame, while the main art uses contain so it never squashes. */
  .cyber-hero{ --mx:50%; --my:50%; position:relative; overflow:hidden; min-height:430px; margin:0 0 18px; border:1px solid rgba(63,214,168,.30); border-radius:20px;
    background:#10151b; box-shadow:inset 0 0 80px rgba(63,214,168,.08), 0 18px 55px rgba(0,0,0,.34); }
  .cyber-art-back,.cyber-art-main{ position:absolute; inset:0; background-image:url(/*__BANNER_IMAGE__*/); background-position:center center; background-repeat:no-repeat; }
  .cyber-art-back{ background-size:cover; filter:blur(16px) saturate(1.15); transform:scale(1.06); opacity:.42; }
  .cyber-art-main{ background-size:contain; opacity:.84; }
  .cyber-hero::before{ content:""; position:absolute; inset:0; z-index:1; pointer-events:none;
    background:radial-gradient(circle at var(--mx) var(--my), rgba(63,214,168,.18), transparent 30%), linear-gradient(90deg,rgba(12,18,22,.84) 0%,rgba(12,18,22,.33) 45%,rgba(12,18,22,.66) 100%); }
  .cyber-hero::after{ content:""; position:absolute; inset:0; z-index:2; pointer-events:none;
    background:repeating-linear-gradient(0deg,rgba(255,255,255,.035) 0 1px,transparent 1px 5px), linear-gradient(90deg,rgba(63,214,168,.06),transparent 42%,rgba(224,115,90,.05)); mix-blend-mode:screen; }
  .hero-orbit{ position:absolute; z-index:3; pointer-events:none; border:1px solid rgba(63,214,168,.38); border-radius:50%; left:47%; top:49%; transform:translate(-50%,-50%) rotate(0deg); opacity:.75; }
  .hero-orbit.o1{ width:380px; height:128px; animation:orbitSpin 12s linear infinite; border-color:rgba(63,214,168,.42); }
  .hero-orbit.o2{ width:470px; height:150px; animation:orbitSpin 17s linear infinite reverse; border-color:rgba(224,177,90,.34); }
  .hero-orbit.o3{ width:260px; height:82px; animation:orbitSpin 8s linear infinite; border-color:rgba(224,115,90,.34); }
  @keyframes orbitSpin{ from{ transform:translate(-50%,-50%) rotate(0deg); } to{ transform:translate(-50%,-50%) rotate(360deg); } }
  .cyber-copy,.cyber-readout{ position:relative; z-index:4; }
  .cyber-copy{ max-width:465px; margin:30px 0 0 32px; padding:22px; border:1px solid rgba(63,214,168,.28); border-radius:16px; background:rgba(14,21,27,.72); backdrop-filter:blur(8px); }
  .cyber-kicker{ color:var(--teal); text-transform:uppercase; font-size:11px; letter-spacing:2px; font-weight:800; margin-bottom:6px; }
  .cyber-title{ color:var(--bright); text-transform:uppercase; font-size:42px; line-height:.95; font-weight:850; letter-spacing:1px; text-shadow:0 0 24px rgba(63,214,168,.23); }
  .cyber-title span{ color:var(--teal); }
  .cyber-sub{ margin-top:13px; max-width:430px; color:#e2e6ee; font-size:14px; line-height:1.55; }
  .cyber-actions{ position:absolute; z-index:5; left:32px; bottom:28px; display:flex; gap:10px; flex-wrap:wrap; }
  .cyber-chip{ border:1px solid var(--teal); color:var(--teal); background:rgba(8,16,18,.64); border-radius:999px; padding:8px 15px; font:inherit; font-size:12px; cursor:pointer; box-shadow:0 0 18px rgba(63,214,168,.08); }
  .cyber-chip:hover{ background:rgba(63,214,168,.12); transform:translateY(-1px); }
  .cyber-chip.amber{ border-color:var(--amber); color:var(--amber); }
  .cyber-readout{ position:absolute; right:28px; top:30px; width:min(365px,32vw); display:grid; gap:14px; }
  .cyber-panel{ border:1px solid rgba(63,214,168,.30); border-radius:16px; background:rgba(14,21,27,.72); backdrop-filter:blur(8px); padding:18px; box-shadow:0 14px 38px rgba(0,0,0,.22); }
  .cyber-panel h3{ margin:0 0 12px; color:var(--bright); font-size:13px; text-transform:uppercase; letter-spacing:1.4px; }
  .cyber-stat{ display:grid; grid-template-columns:1fr 120px 56px; gap:9px; align-items:center; padding:6px 0; color:#e3e7ef; font-size:12px; cursor:help; }
  .cyber-bar{ height:9px; border-radius:999px; background:#34404b; overflow:hidden; border:1px solid rgba(255,255,255,.08); }
  .cyber-bar i{ display:block; height:100%; border-radius:inherit; background:linear-gradient(90deg,var(--coral),var(--teal)); }
  .workflow{ display:grid; gap:10px; }
  .workflow-step{ display:grid; grid-template-columns:38px 1fr; gap:12px; align-items:center; border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:12px; background:rgba(255,255,255,.045); cursor:help; transition:.15s ease; }
  .workflow-step:hover{ border-color:rgba(63,214,168,.38); background:rgba(63,214,168,.08); transform:translateX(-2px); }
  .workflow-step .ico{ display:flex; width:34px; height:34px; border-radius:10px; align-items:center; justify-content:center; color:var(--teal); border:1px solid rgba(63,214,168,.40); background:rgba(63,214,168,.10); }
  .workflow-step small{ display:block; color:var(--muted); text-transform:uppercase; letter-spacing:.8px; }
  .workflow-step b{ display:block; color:var(--bright); font-size:13px; margin-top:2px; }
  .tip-bubble{ position:fixed; z-index:9999; max-width:330px; opacity:0; transform:translate(-50%, calc(-100% - 14px)); pointer-events:none; transition:.12s ease; border:1px solid rgba(63,214,168,.48); border-radius:12px; background:rgba(12,17,22,.96); box-shadow:0 18px 42px rgba(0,0,0,.45), 0 0 30px rgba(63,214,168,.10); padding:13px 14px; }
  .tip-bubble.show{ opacity:1; transform:translate(-50%, calc(-100% - 10px)); }
  .tip-bubble.below{ transform:translate(-50%, 14px); }
  .tip-bubble.below.show{ transform:translate(-50%, 10px); }
  .tip-bubble strong{ display:block; color:var(--teal); text-transform:uppercase; letter-spacing:1px; font-size:11px; margin-bottom:6px; }
  .tip-bubble p{ margin:0; color:#dce2ec; font-size:12.5px; line-height:1.46; }
  @media (max-width:980px){ .cyber-hero{min-height:620px}.cyber-copy{margin:22px 20px 0}.cyber-actions{left:20px;bottom:20px}.cyber-readout{left:20px;right:20px;top:245px;width:auto}.cyber-title{font-size:34px} }

  .cards{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:18px; }
  .card{ background:linear-gradient(180deg,var(--panel),#181b21); border:0.5px solid #242934; border-radius:12px; padding:13px 15px; }
  .card .l{ font-size:11px; color:var(--muted); margin-bottom:5px; }
  .card .v{ font-size:22px; font-weight:500; }
  .cols{ display:grid; grid-template-columns:minmax(0,340px) minmax(0,1fr); gap:22px; }
  .sec{ font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; margin-bottom:11px; }
  .srow{ cursor:pointer; display:grid; grid-template-columns:22px 1fr 48px; gap:8px; align-items:center;
         padding:8px 10px; border-radius:8px; margin-bottom:3px; border:0.5px solid transparent; }
  .srow:hover{ background:var(--panel); }
  table{ width:100%; border-collapse:separate; border-spacing:0; }
  .lbnote{ font-size:10.5px; color:#5a8f7a; margin-top:8px; min-height:14px; }
  .foot{ margin-top:18px; padding-top:14px; border-top:0.5px solid var(--line); font-size:10.5px; color:#5a8f7a; line-height:1.6; }
  .subtoggle{ display:flex; gap:6px; margin-bottom:14px; }
  .tbtn{ background:var(--panel2); color:var(--muted); border:0.5px solid #3a3f4a; border-radius:7px;
         padding:6px 13px; font-size:12px; cursor:pointer; font-family:inherit; }
  .tbtn.on{ background:var(--tealbg); color:var(--teal); border-color:var(--teal); }
  .view{ display:none; }
  .view.on{ display:block; }
  .panel{ background:var(--panel); border:0.5px solid #252a34; border-radius:12px; padding:14px; }
  .chartbox{ background:var(--panel); border-radius:12px; padding:14px; min-height:390px; position:relative; }
  .filters{ display:grid; grid-template-columns:1.4fr repeat(5,minmax(0,1fr)); gap:8px; margin-bottom:12px; }
  .filterline{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:11px; }
  .pill{ display:inline-flex; align-items:center; gap:5px; border-radius:999px; padding:3px 8px; font-size:10.5px; border:0.5px solid #3a3f4a; color:var(--muted); }
  .pill.teal{ color:var(--teal); border-color:rgba(63,214,168,.55); background:rgba(63,214,168,.07); }
  .pill.amber{ color:var(--amber); border-color:rgba(224,177,90,.45); background:rgba(224,177,90,.06); }
  .pill.coral{ color:var(--coral); border-color:rgba(224,115,90,.50); background:rgba(224,115,90,.06); }
  .players-grid{ display:grid; grid-template-columns:minmax(0,1.15fr) minmax(330px,.85fr); gap:14px; align-items:start; }
  .tablewrap{ overflow:auto; max-height:620px; border:0.5px solid #252a34; border-radius:12px; background:rgba(26,29,35,.72); }
  .players-table th{ position:sticky; top:0; z-index:3; background:#1c2028; color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.5px; padding:8px 9px; text-align:right; border-bottom:0.5px solid var(--line); white-space:nowrap; cursor:pointer; }
  .players-table th:first-child{ left:0; z-index:5; text-align:left; min-width:170px; }
  .players-table td{ padding:7px 9px; border-bottom:0.5px solid #222732; font-size:12px; text-align:right; white-space:nowrap; color:#d7dce4; }
  .players-table td:first-child{ position:sticky; left:0; z-index:2; text-align:left; background:#1a1d23; min-width:170px; font-weight:500; }
  .players-table tr:hover td{ background:#20242d; }
  .players-table tr:hover td:first-child{ background:#20242d; }
  .players-table tr.selected td{ background:var(--tealbg); }
  .players-table tr.selected td:first-child{ background:var(--tealbg); color:var(--teal); }
  .players-table tr.small td{ opacity:.58; }
  .players-table tr.small td:first-child{ opacity:1; color:#9aa1ad; }
  .namecell{ display:flex; align-items:center; gap:8px; }
  .dot{ width:7px; height:7px; border-radius:50%; background:var(--teal); flex:0 0 auto; }
  .dot.warn{ background:var(--coral); }
  .profile{ min-height:460px; }
  .profile-head{ display:flex; gap:12px; align-items:center; margin-bottom:12px; }
  .sil{ width:58px; height:58px; border-radius:18px; background:radial-gradient(circle at 34% 25%,#39404c 0,#212630 45%,#171a20 100%); border:0.5px solid #303641; display:flex; align-items:center; justify-content:center; color:var(--teal); font-size:22px; }
  .profile-name{ color:var(--bright); font-weight:650; font-size:19px; line-height:1.15; }
  .profile-meta{ color:var(--muted); font-size:11px; display:flex; gap:6px; flex-wrap:wrap; margin-top:6px; }
  .metric-row{ margin:10px 0 12px; }
  .metric-top{ display:flex; justify-content:space-between; align-items:baseline; gap:8px; margin-bottom:4px; }
  .metric-label{ color:#aeb5c0; font-size:11px; }
  .metric-val{ color:var(--bright); font-size:12px; font-weight:500; }
  .bar{ height:11px; border-radius:999px; position:relative; background:linear-gradient(90deg,var(--coral),#313641 47%,var(--teal)); overflow:hidden; border:0.5px solid #2c323d; }
  .barveil{ position:absolute; top:0; right:0; height:100%; background:rgba(21,23,28,.72); }
  .ghostmark{ position:absolute; top:-3px; width:2px; height:17px; background:rgba(232,235,240,.55); box-shadow:0 0 0 1px rgba(0,0,0,.35); }
  .ghosttext{ color:var(--muted); font-size:10px; margin-top:3px; }
  .kv{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin:13px 0; }
  .kv div{ background:var(--panel2); border:0.5px solid #2a2f3b; border-radius:9px; padding:9px; }
  .kv span{ display:block; color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:.6px; }
  .kv b{ display:block; color:var(--bright); font-size:14px; margin-top:3px; font-weight:600; }
  .empty{ color:var(--muted); font-size:12px; padding:18px; text-align:center; }
  @media (max-width:980px){ .cards{grid-template-columns:repeat(2,1fr)} .cols,.players-grid{grid-template-columns:1fr} .filters{grid-template-columns:1fr 1fr} }
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr">
    <div class="brand">
      <div class="logo">🟤🟡</div>
      <div><div class="bname">Never Lucky 2.0</div><div class="btag">statcast-scored roto · let the signals emerge</div></div>
    </div>
    <div class="ctrls">
      <span class="lbl">season</span>
      <select id="yearSel"></select>
    </div>
  </div>

  <div class="tabs">
    <button class="tab on" id="top-standings" onclick="setTopTab('standings')">Standings</button>
    <button class="tab" id="top-leaderboards" onclick="setTopTab('leaderboards')">Leaderboards</button>
    <button class="tab" id="top-players" onclick="setTopTab('players')">Players</button>
  </div>

  <section class="cyber-hero" id="cyberHero" aria-label="Interactive Never Lucky Signal Room banner">
    <div class="cyber-art-back" aria-hidden="true"></div>
    <div class="cyber-art-main" aria-hidden="true"></div>
    <div class="hero-orbit o1"></div><div class="hero-orbit o2"></div><div class="hero-orbit o3"></div>
    <div class="cyber-copy">
      <div class="cyber-kicker">The Signal Room</div>
      <div class="cyber-title">Never <span>Lucky</span></div>
      <p class="cyber-sub">Fantasy baseball scouting cockpit: isolate skill, discount noise, and investigate where traditional category value is mispricing the player pool.</p>
    </div>
    <div class="cyber-actions">
      <button class="cyber-chip has-tip" data-tip-title="Open Players" data-tip-body="Go to the searchable player table: filter by position, skill gaps, sample size, and percentile shape, then click any row for a player profile." onclick="setTopTab('players')">Open Players</button>
      <button class="cyber-chip amber has-tip" data-tip-title="View Leaderboards" data-tip-body="Go to category leaderboards, including season and rolling-window views when those windows are available." onclick="setTopTab('leaderboards')">View Leaderboards</button>
      <button class="cyber-chip has-tip" data-tip-title="Standings" data-tip-body="Go to the roto standings view and inspect how each team is accumulating category points." onclick="setTopTab('standings')">Standings</button>
    </div>
    <aside class="cyber-readout">
      <div class="cyber-panel">
        <h3>Live Dashboard Readout</h3>
        <div class="cyber-stat has-tip" data-tip-title="Signal State" data-tip-body="A compact status read on whether the current dashboard payload is active and ready for exploration."><span>Signal State</span><span class="cyber-bar"><i style="width:78%"></i></span><b id="cyberState">active</b></div>
        <div class="cyber-stat has-tip" data-tip-title="Top Riser" data-tip-body="The player with the largest positive gap between Statcast/process value and traditional category value in the selected season."><span>Top Riser</span><span class="cyber-bar"><i style="width:63%"></i></span><b id="cyberRiser">—</b></div>
        <div class="cyber-stat has-tip" data-tip-title="Sample Trust" data-tip-body="Share of player rows that are not currently flagged as limited sample. Higher is cleaner; lower means more early-sample volatility."><span>Sample Trust</span><span class="cyber-bar"><i id="cyberTrustBar" style="width:50%"></i></span><b id="cyberTrust">—</b></div>
        <div class="filterline" style="margin:10px 0 0; justify-content:space-between;"><span class="lbl has-tip" data-tip-title="Season" data-tip-body="The global season selector drives standings, leaderboards, and the player table together.">season <b id="cyberSeason" style="color:var(--teal);">—</b></span><span class="lbl has-tip" data-tip-title="Rows" data-tip-body="Number of hitter and pitcher player rows baked into the selected season payload.">rows <b id="cyberRows" style="color:var(--teal);">—</b></span></div>
      </div>
      <div class="cyber-panel">
        <h3>Workflow</h3>
        <div class="workflow">
          <div class="workflow-step has-tip" data-tip-title="Identify" data-tip-body="Find players whose process metrics imply more skill than traditional fantasy outcomes are showing."><span class="ico">⌕</span><span><small>Identify</small><b>Undervalued skill</b></span></div>
          <div class="workflow-step has-tip" data-tip-title="Separate" data-tip-body="Separate outcome from process: box-score production can lie, but xwOBA, barrels, chase, whiffs, and contact quality help explain why."><span class="ico">▥</span><span><small>Separate</small><b>Outcome from process</b></span></div>
          <div class="workflow-step has-tip" data-tip-title="Verify" data-tip-body="Check percentile shape and sample confidence before trusting a signal. A loud small sample is an investigation, not a conclusion."><span class="ico">◎</span><span><small>Verify</small><b>Percentile shape</b></span></div>
          <div class="workflow-step has-tip" data-tip-title="Act" data-tip-body="Use the signal gap to decide whether to add, hold, trade, fade, or monitor a player."><span class="ico">★</span><span><small>Act</small><b>Exploit the edge</b></span></div>
        </div>
      </div>
    </aside>
    <div class="tip-bubble" id="tipBubble"><strong></strong><p></p></div>
  </section>

  <div class="cards">
    <div class="card"><div class="l">hitters scored</div><div class="v" id="m-hit" style="color:var(--teal)">—</div></div>
    <div class="card"><div class="l">pitchers scored</div><div class="v" id="m-pit" style="color:var(--blue)">—</div></div>
    <div class="card"><div class="l">player rows</div><div class="v" id="m-players" style="color:var(--bright)">—</div></div>
    <div class="card"><div class="l">biggest riser</div><div class="v" id="m-riser" style="color:var(--amber); font-size:14px; margin-top:5px;">—</div></div>
  </div>

  <section id="view-standings" class="view on">
    <div class="cols">
      <div>
        <div class="sec">standings · click to inspect</div>
        <div id="standings"></div>
      </div>
      <div>
        <div class="sec">team roster audit</div>
        <div id="teamView"></div>
      </div>
    </div>
  </section>

  <section id="view-leaderboards" class="view">
    <div class="filterline">
      <span class="lbl">leaderboard</span>
      <select id="statSel" style="min-width:280px;"></select>
      <span class="lbl">time</span>
      <select id="timeSel" style="min-width:150px;"></select>
    </div>
    <div class="chartbox"><canvas id="lbChart" role="img" aria-label="Leaderboard chart for the selected stat and season"></canvas></div>
    <div class="lbnote" id="lbNote"></div>
  </section>

  <section id="view-players" class="view">
    <div class="subtoggle">
      <button class="tbtn on" id="side-hitting" onclick="setPlayerSide('hitting')">Hitters</button>
      <button class="tbtn" id="side-pitching" onclick="setPlayerSide('pitching')">Pitchers</button>
    </div>
    <div class="filters">
      <input id="playerSearch" placeholder="Search player, action, archetype…">
      <select id="positionFilter"></select>
      <select id="actionFilter"></select>
      <select id="archetypeFilter"></select>
      <select id="thresholdStat"></select>
      <input id="thresholdValue" placeholder="min / max">
    </div>
    <div class="filterline">
      <select id="thresholdOp" style="width:90px;"><option value=">=">≥</option><option value="<=">≤</option></select>
      <button class="tbtn" onclick="clearPlayerFilters()">Clear filters</button>
      <span class="pill teal" id="playerCount">— players</span>
      <span class="pill amber">click a row for profile</span>
      <span class="pill coral">dimmed = small sample</span>
    </div>
    <div class="players-grid">
      <div class="tablewrap"><table class="players-table" id="playersTable"></table></div>
      <div class="panel profile" id="playerProfile"></div>
    </div>
  </section>

  <div class="foot">
    Signal Score = Statcast category z-score blend · Noise Gap = Statcast value minus traditional value · R/RBI/SB/slash stats should be enriched from season batting tables when available · xwOBA / xFIP / QS remain transparent pitch-data approximations · fully self-contained artifact 🟤🟡
  </div>
</div>

<script>
const PAYLOAD = /*__PAYLOAD__*/;
const C = { teal:'#3fd6a8', amber:'#e0b15a', blue:'#5aa9f0', coral:'#e0735a', muted:'#7a818c', text:'#c8ccd4', bright:'#e8ebf0' };
let curYear = PAYLOAD.tags[0];
let curStat = 'risers';
let curTime = 'season';
let curTeam = null;
let topTab = 'standings';
let chart;
let playerSide = 'hitting';
let playerSort = {key:'signal_score', dir:'desc'};
let selectedPlayerId = null;

const fmt = {
  delta: v => signed(v,2),
  delta2: v => signed(v,2),
  rate3: v => Number(v).toFixed(3),
  rate2: v => Number(v).toFixed(2),
  rate1: v => Number(v).toFixed(1),
  pct:   v => (Number(v)*100).toFixed(1) + '%',
  int:   v => Math.round(Number(v)).toString(),
  text:  v => esc(v),
};
function signed(v,d){ v=Number(v); if(!Number.isFinite(v)) return '—'; return (v>=0?'+':'') + v.toFixed(d); }
function esc(v){ return String(v ?? '—').replace(/[&<>'"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function display(v, key='text'){ if(v===null||v===undefined||Number.isNaN(v)) return '—'; return (fmt[key]||fmt.text)(v); }
function specByKey(k){ return PAYLOAD.specs.find(s=>s.key===k); }
function colSpecs(){ return PAYLOAD.player_columns[playerSide]; }
function profileSpecs(){ return PAYLOAD.profile_stats[playerSide]; }
function currentPlayers(){ return PAYLOAD.seasons[curYear].players[playerSide] || []; }

function initCyberTips(){
  const hero=document.getElementById('cyberHero');
  const bubble=document.getElementById('tipBubble');
  if(!hero || !bubble) return;
  hero.addEventListener('mousemove', e=>{
    const rect=hero.getBoundingClientRect();
    hero.style.setProperty('--mx', ((e.clientX-rect.left)/rect.width*100).toFixed(1)+'%');
    hero.style.setProperty('--my', ((e.clientY-rect.top)/rect.height*100).toFixed(1)+'%');
  });
  function show(el){
    const title=el.getAttribute('data-tip-title');
    const body=el.getAttribute('data-tip-body');
    if(!title || !body) return;
    bubble.querySelector('strong').textContent=title;
    bubble.querySelector('p').textContent=body;
    const r=el.getBoundingClientRect();
    let x=r.left+r.width/2, y=r.top;
    bubble.style.left=x+'px'; bubble.style.top=y+'px';
    bubble.classList.toggle('below', y<120);
    bubble.classList.add('show');
  }
  function hide(){ bubble.classList.remove('show'); }
  hero.querySelectorAll('.has-tip').forEach(el=>{
    el.addEventListener('mouseenter',()=>show(el));
    el.addEventListener('focus',()=>show(el));
    el.addEventListener('click',()=>show(el));
    el.addEventListener('mouseleave',hide);
    el.addEventListener('blur',hide);
  });
  document.addEventListener('keydown', e=>{ if(e.key==='Escape') hide(); });
}
function updateCyberReadout(){
  const s = PAYLOAD.seasons[curYear];
  if(!s) return;
  const total = (s.players.hitting.length + s.players.pitching.length);
  const limited = (s.players.hitting.concat(s.players.pitching).filter(p=>p.small_sample).length);
  const trust = total ? Math.round((1-limited/total)*100) : 0;
  const set=(id,val)=>{ const el=document.getElementById(id); if(el) el.textContent=val; };
  set('cyberRiser', s.top_riser || '—'); set('cyberSeason', curYear); set('cyberRows', total.toLocaleString()); set('cyberTrust', trust+'%');
  const bar=document.getElementById('cyberTrustBar'); if(bar) bar.style.width = Math.max(5, trust)+'%';
}

function initControls(){
  document.getElementById('yearSel').innerHTML = PAYLOAD.tags.map(t=>`<option value="${t}">${t}</option>`).join('');
  document.getElementById('statSel').innerHTML = PAYLOAD.specs.map(s=>`<option value="${s.key}">${s.label}</option>`).join('');
  document.getElementById('yearSel').addEventListener('change', e=>{ curYear=e.target.value; curTeam=null; selectedPlayerId=null; repaint(); });
  document.getElementById('statSel').addEventListener('change', e=>{ curStat=e.target.value; paintBoard(); });
  document.getElementById('timeSel').addEventListener('change', e=>{ curTime=e.target.value; paintBoard(); });
  setTimeOptions();
  ['playerSearch','positionFilter','actionFilter','archetypeFilter','thresholdStat','thresholdValue','thresholdOp'].forEach(id=>{
    document.getElementById(id).addEventListener('input', paintPlayers);
    document.getElementById(id).addEventListener('change', paintPlayers);
  });
  setPlayerFilterOptions();
}


function currentWindows(){ return PAYLOAD.seasons[curYear].leaderboard_windows || {season:{label:'Season', leaderboards:PAYLOAD.seasons[curYear].leaderboards}}; }
function currentWindow(){ return currentWindows()[curTime] || currentWindows().season; }
function setTimeOptions(){
  const el = document.getElementById('timeSel');
  const old = curTime;
  const wins = currentWindows();
  const order = ['season','last7','last14','last30'];
  const keys = order.filter(k=>wins[k]).concat(Object.keys(wins).filter(k=>!order.includes(k)));
  el.innerHTML = keys.map(k=>`<option value="${k}">${esc(wins[k].label || k)}</option>`).join('');
  curTime = keys.includes(old) ? old : 'season';
  el.value = curTime;
}

function setTopTab(tab){
  topTab = tab;
  ['standings','leaderboards','players'].forEach(t=>{
    document.getElementById('top-'+t).classList.toggle('on', t===tab);
    document.getElementById('view-'+t).classList.toggle('on', t===tab);
  });
  if(tab==='leaderboards') paintBoard();
  if(tab==='players') paintPlayers();
  if(tab==='standings') { paintStandings(); paintTeam(); }
}

function repaint(){
  updateCyberReadout();
  const s = PAYLOAD.seasons[curYear];
  document.getElementById('m-hit').textContent = s.n_hitters;
  document.getElementById('m-pit').textContent = s.n_pitchers;
  document.getElementById('m-players').textContent = (s.players.hitting.length + s.players.pitching.length);
  document.getElementById('m-riser').textContent = s.top_riser;
  paintStandings();
  setTimeOptions();
  if(topTab==='leaderboards') paintBoard();
  if(topTab==='players') { setPlayerFilterOptions(); paintPlayers(); }
  paintTeam();
}

function paintStandings(){
  const s = PAYLOAD.seasons[curYear];
  document.getElementById('standings').innerHTML = s.standings.map(r=>{
    const nameCol = r.leader?C.teal:(r.last?C.coral:C.text);
    const valCol  = r.leader?C.teal:(r.last?C.coral:C.amber);
    const rkCol   = r.leader?C.amber:C.muted;
    const sel = r.team===curTeam;
    const bg = sel?'var(--tealbg)':(r.leader?'var(--tealbg2)':'transparent');
    const bd = sel?'0.5px solid var(--teal)':'0.5px solid transparent';
    return `<div class="srow" style="background:${bg}; border:${bd};" onclick="pickTeam('${esc(String(r.team)).replace(/&#39;/g,"\\'")}')">
      <span style="color:${rkCol}; font-size:12px;">${r.rank}</span>
      <span style="color:${nameCol}; font-size:13px;">${esc(r.team)}</span>
      <span style="text-align:right; color:${valCol}; font-size:13px; font-weight:500;">${Number(r.total).toFixed(1)}</span>
    </div>`;
  }).join('');
}
function pickTeam(name){ curTeam=name; paintStandings(); paintTeam(); }

function paintBoard(){
  const s = PAYLOAD.seasons[curYear];
  const spec = specByKey(curStat);
  const win = currentWindow();
  const rows = ((win.leaderboards && win.leaderboards[curStat]) || s.leaderboards[curStat] || []).slice();
  rows.sort((a,b)=> spec.low ? a[1]-b[1] : b[1]-a[1]);
  const dateBit = win.start && win.end ? ` · ${win.start} to ${win.end}` : '';
  const pitchBit = win.n_pitches ? ` · ${win.n_pitches.toLocaleString()} pitches` : '';
  const unavailable = (spec.season_only && curTime !== 'season') ? ' · season-level outcome only; switch to Season for official fantasy outcome stats' : '';
  document.getElementById('lbNote').textContent = `${spec.label} · ${win.label || curTime}${dateBit}${pitchBit}${spec.low?' · lower is better':''}${unavailable}`;
  const col = C[spec.color] || C.teal;
  if(chart) chart.destroy();
  chart = new Chart(document.getElementById('lbChart'), {
    type:'bar',
    data:{ labels:rows.map(r=>r[0]), datasets:[{ data:rows.map(r=>r[1]), backgroundColor:col, borderRadius:4, barThickness:20 }] },
    options:{ indexAxis:'y', responsive:true, maintainAspectRatio:false, animation:{duration:350},
      plugins:{ legend:{display:false}, tooltip:{callbacks:{label:ctx=>display(ctx.parsed.x, spec.fmt)}} },
      scales:{ x:{ reverse:spec.low, ticks:{color:C.muted,font:{size:10},callback:v=>display(v, spec.fmt)}, grid:{color:'#262a32'} },
               y:{ ticks:{color:C.text,font:{size:11}}, grid:{display:false} } } }
  });
}

function cell(val, fmtKey, color){
  if(val===null||val===undefined) return `<td style="padding:6px 8px; text-align:right; color:${C.muted}; font-size:12px;">—</td>`;
  return `<td style="padding:6px 8px; text-align:right; color:${color}; font-size:12px;">${display(val,fmtKey)}</td>`;
}
function paintTeam(){
  const s = PAYLOAD.seasons[curYear];
  if(!curTeam) curTeam = s.standings[0].team;
  const t = s.teams[curTeam];
  const hHead = ['xwOBA','brl','ev90','chase','R+RBI','SB','HR'];
  const pHead = ['xFIP','K','whiff','brl%a','QS'];
  const hRows = t.hitters.map(h=>`<tr><td style="padding:6px 8px; color:${(h.xwoba!==null&&h.xwoba>=0.380)?C.teal:'#dbe0e8'}; font-size:12px;">${esc(h.name)}</td>`
      + cell(h.xwoba,'rate3',C.teal) + cell(h.barrels,'int',C.amber) + cell(h.ev90,'rate1',C.text)
      + cell(h.chase,'pct',C.blue) + cell(h.rrbi,'int',C.amber) + cell(h.sb,'int',C.text) + cell(h.hr,'int',C.amber) + '</tr>').join('');
  const pRows = t.pitchers.map(p=>`<tr><td style="padding:6px 8px; color:${(p.xfip!==null&&p.xfip<=3.40)?C.teal:'#dbe0e8'}; font-size:12px;">${esc(p.name)}</td>`
      + cell(p.xfip,'rate2',C.blue) + cell(p.k,'int',C.amber) + cell(p.whiff,'pct',C.teal) + cell(p.brla,'pct',C.blue) + cell(p.qs,'int',C.amber) + '</tr>').join('');
  const th = c => `<td style="padding:2px 8px; text-align:right; color:${C.muted}; font-size:10px;">${c}</td>`;
  document.getElementById('teamView').innerHTML = `
    <div style="display:flex; align-items:baseline; justify-content:space-between; margin-bottom:12px;">
      <span style="font-size:15px; font-weight:500; color:var(--bright);">${esc(curTeam)}</span>
      <span style="font-size:12px; color:${C.muted};">rank #${t.rank} · <span style="color:${C.amber};">${Number(t.pts).toFixed(1)} pts</span></span>
    </div>
    <div style="background:var(--panel); border-radius:10px; padding:10px 4px; margin-bottom:12px; overflow-x:auto;">
      <div style="font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; padding:0 8px 6px;">hitters</div>
      <table><tr><td style="padding:2px 8px; color:${C.muted}; font-size:10px;">player</td>${hHead.map(th).join('')}</tr>${hRows}</table>
    </div>
    <div style="background:var(--panel); border-radius:10px; padding:10px 4px; overflow-x:auto;">
      <div style="font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:1px; padding:0 8px 6px;">pitchers</div>
      <table><tr><td style="padding:2px 8px; color:${C.muted}; font-size:10px;">player</td>${pHead.map(th).join('')}</tr>${pRows}</table>
    </div>`;
}

function setPlayerSide(side){
  playerSide = side;
  selectedPlayerId = null;
  playerSort = {key:'signal_score', dir:'desc'};
  document.getElementById('side-hitting').classList.toggle('on', side==='hitting');
  document.getElementById('side-pitching').classList.toggle('on', side==='pitching');
  setPlayerFilterOptions();
  paintPlayers();
}
function uniqueValues(rows,key){ return [...new Set(rows.map(r=>r[key]).filter(v=>v!==null&&v!==undefined&&String(v).trim()!==''))].sort((a,b)=>String(a).localeCompare(String(b))); }
function setSelectOptions(id, label, values){
  const el=document.getElementById(id), old=el.value;
  el.innerHTML = `<option value="">${label}</option>` + values.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
  if([...el.options].some(o=>o.value===old)) el.value=old;
}
function setPlayerFilterOptions(){
  const rows=currentPlayers();
  setSelectOptions('positionFilter', playerSide==='hitting'?'All positions':'All roles', playerSide==='hitting'?uniqueValues(rows,'position'):[]);
  setSelectOptions('actionFilter','All actions', uniqueValues(rows,'action'));
  setSelectOptions('archetypeFilter','All archetypes', uniqueValues(rows,'archetype'));
  const numericCols = colSpecs().filter(c=>!['text'].includes(c.fmt) && c.key!=='sample_tag');
  const th=document.getElementById('thresholdStat'), old=th.value;
  th.innerHTML = '<option value="">No stat threshold</option>' + numericCols.map(c=>`<option value="${c.key}">${c.label}</option>`).join('');
  if([...th.options].some(o=>o.value===old)) th.value=old;
}
function clearPlayerFilters(){
  ['playerSearch','thresholdValue'].forEach(id=>document.getElementById(id).value='');
  ['positionFilter','actionFilter','archetypeFilter','thresholdStat'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('thresholdOp').value='>=';
  paintPlayers();
}
function filteredPlayers(){
  const q=document.getElementById('playerSearch').value.trim().toLowerCase();
  const pos=document.getElementById('positionFilter').value;
  const action=document.getElementById('actionFilter').value;
  const arch=document.getElementById('archetypeFilter').value;
  const thStat=document.getElementById('thresholdStat').value;
  const thVal=parseFloat(document.getElementById('thresholdValue').value);
  const op=document.getElementById('thresholdOp').value;
  let rows=currentPlayers().filter(r=>{
    if(q && !(r.search_blob||'').includes(q)) return false;
    if(pos && r.position!==pos) return false;
    if(action && r.action!==action) return false;
    if(arch && r.archetype!==arch) return false;
    if(thStat && Number.isFinite(thVal)){
      const v=Number(r[thStat]);
      if(!Number.isFinite(v)) return false;
      if(op==='>=' && v < thVal) return false;
      if(op==='<=' && v > thVal) return false;
    }
    return true;
  });
  rows.sort((a,b)=>compareRows(a,b,playerSort.key,playerSort.dir));
  return rows;
}
function compareRows(a,b,key,dir){
  let av=a[key], bv=b[key];
  const an=Number(av), bn=Number(bv);
  let cmp;
  if(Number.isFinite(an) && Number.isFinite(bn)) cmp = an-bn;
  else cmp = String(av??'').localeCompare(String(bv??''));
  return dir==='asc'?cmp:-cmp;
}
function sortPlayers(key){
  if(playerSort.key===key) playerSort.dir = playerSort.dir==='asc'?'desc':'asc';
  else playerSort = {key, dir: key==='player_name'?'asc':'desc'};
  paintPlayers();
}
function paintPlayers(){
  const rows=filteredPlayers();
  document.getElementById('playerCount').textContent = `${rows.length} ${playerSide==='hitting'?'hitters':'pitchers'}`;
  if(!selectedPlayerId && rows.length) selectedPlayerId = rows[0].player_id;
  if(selectedPlayerId && !rows.some(r=>r.player_id===selectedPlayerId) && rows.length) selectedPlayerId = rows[0].player_id;
  const cols=colSpecs();
  const ths=cols.map(c=>`<th onclick="sortPlayers('${c.key}')"${c.sticky?' class="sticky"':''}>${esc(c.label)}${playerSort.key===c.key?` ${playerSort.dir==='asc'?'▲':'▼'}`:''}</th>`).join('');
  const body=rows.map(r=>{
    const sel=r.player_id===selectedPlayerId;
    const cls=(r.small_sample?'small ':'')+(sel?'selected':'');
    const cells=cols.map((c,i)=>{
      const v = r[c.key];
      const color = c.color ? (C[c.color]||C.text) : C.text;
      if(i===0) return `<td><div class="namecell"><span class="dot ${r.small_sample?'warn':''}"></span><span>${esc(v)}</span></div></td>`;
      const txt = c.key==='sample_tag' ? (r.small_sample?`<span class="pill coral">${esc(v)}</span>`:`<span class="pill teal">ok</span>`) : display(v,c.fmt);
      return `<td style="color:${color};">${txt}</td>`;
    }).join('');
    return `<tr class="${cls}" onclick="selectPlayer('${r.player_id}')">${cells}</tr>`;
  }).join('');
  document.getElementById('playersTable').innerHTML = `<thead><tr>${ths}</tr></thead><tbody>${body || `<tr><td class="empty" colspan="${cols.length}">No players match the current filters.</td></tr>`}</tbody>`;
  const selected = currentPlayers().find(r=>r.player_id===selectedPlayerId) || rows[0];
  paintProfile(selected);
}
function selectPlayer(id){ selectedPlayerId=id; paintPlayers(); }
function actionClass(a){ if(a==='Positive Skill Gap'||a==='Strong Skill Signal'||a==='Moderate Skill Signal') return 'teal'; if(a==='Negative Skill Gap'||a==='Weak Skill Signal') return 'coral'; return 'amber'; }
function paintProfile(p){
  const el=document.getElementById('playerProfile');
  if(!p){ el.innerHTML='<div class="empty">Select a player.</div>'; return; }
  const meta = playerSide==='hitting' ? `${esc(p.position)} · ${display(p.pa,'int')} PA` : `${display(p.ip,'rate1')} IP`;
  const kvs = [
    ['Signal', display(p.signal_score,'delta2')],
    ['Noise Gap', display(p.noise_gap,'delta2')],
    ['SC Rank', display(p.statcast_rank,'int')],
  ].map(k=>`<div><span>${k[0]}</span><b>${k[1]}</b></div>`).join('');
  const bars = profileSpecs().map(s=>profileBar(p,s)).join('');
  el.innerHTML = `
    <div class="profile-head">
      <div class="sil">${playerSide==='hitting'?'◆':'●'}</div>
      <div>
        <div class="profile-name">${esc(p.player_name)}</div>
        <div class="profile-meta"><span>${curYear}</span><span>·</span><span>${meta}</span><span>·</span><span>${p.small_sample?'small sample':'qualified-ish'}</span></div>
      </div>
    </div>
    <div class="filterline">
      <span class="pill ${actionClass(p.action)}">${esc(p.action)}</span>
      <span class="pill teal">${esc(p.archetype)}</span>
      ${p.ghost?`<span class="pill amber">ghost: ${p.ghost.season}</span>`:'<span class="pill">no prior-year ghost</span>'}
    </div>
    <div class="kv">${kvs}</div>
    <div class="sec">pooled percentile profile</div>
    ${bars}
  `;
}
function profileBar(p,s){
  const pct = Number(p.percentiles?.[s.key] ?? 0);
  const veil = Math.max(0,100-pct);
  const val = display(p[s.key],s.fmt);
  const gPct = p.ghost?.percentiles?.[s.key];
  const gVal = p.ghost?.stats?.[s.key];
  const ghost = Number.isFinite(Number(gPct)) ? `<span class="ghostmark" style="left:${Number(gPct)}%;"></span>` : '';
  const ghostText = Number.isFinite(Number(gPct)) ? `<div class="ghosttext">${p.ghost.season}: ${display(gVal,s.fmt)} · ${Number(gPct).toFixed(0)}th pct</div>` : '';
  return `<div class="metric-row">
    <div class="metric-top"><span class="metric-label">${esc(s.label)}</span><span class="metric-val">${val} · ${pct.toFixed(0)}th pct</span></div>
    <div class="bar"><span class="barveil" style="width:${veil}%;"></span>${ghost}</div>${ghostText}
  </div>`;
}

initControls();
initCyberTips();
repaint();
</script>
</body>
</html>
"""
