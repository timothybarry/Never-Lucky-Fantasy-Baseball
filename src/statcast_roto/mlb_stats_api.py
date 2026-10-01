"""
mlb_stats_api.py
================

Official season lines from the public MLB Stats API (statsapi.mlb.com).

Pitch-level Statcast can't recover runs, steals, batting average, wins, saves,
ERA or WHIP. The MLB Stats API can, and it keys every player by the same MLBAM
id the Statcast files use, so no name crosswalk is needed.

This module only fetches and normalizes. It writes the CSVs that
``fantasy_outcomes.py`` already looks for (``mlb_batting_<season>.csv`` and
``mlb_pitching_<season>.csv``), so scoring and value code never learn where the
numbers came from.

Traded players come back as one combined row per season (``numTeams`` > 1).
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd

API = "https://statsapi.mlb.com/api/v1/stats"
USER_AGENT = "statcast-roto/1.0 (season stats for a fantasy roto engine)"

# API field -> column name. Column names match the aliases in fantasy_outcomes.py.
BATTING_FIELDS: dict[str, str] = {
    "gamesPlayed": "G", "plateAppearances": "PA", "atBats": "AB", "runs": "R", "hits": "H",
    "doubles": "2B", "triples": "3B", "homeRuns": "HR", "rbi": "RBI", "stolenBases": "SB",
    "caughtStealing": "CS", "baseOnBalls": "BB", "strikeOuts": "SO", "hitByPitch": "HBP",
    "sacFlies": "SF", "avg": "AVG", "obp": "OBP", "slg": "SLG", "ops": "OPS", "babip": "BABIP",
}
PITCHING_FIELDS: dict[str, str] = {
    "gamesPlayed": "G", "gamesStarted": "GS", "wins": "W", "losses": "L", "saves": "SV",
    "holds": "HLD", "blownSaves": "BS", "outs": "OUTS", "battersFaced": "TBF", "hits": "H",
    "earnedRuns": "ER", "homeRuns": "HR", "baseOnBalls": "BB", "hitBatsmen": "HBP",
    "strikeOuts": "SO", "era": "ERA", "whip": "WHIP",
}


def fetch_season_splits(season: int | str, group: str, *, page: int = 1000, timeout: int = 60) -> list[dict[str, Any]]:
    """Every MLB player's season line for one group ('hitting' or 'pitching')."""
    if group not in {"hitting", "pitching"}:
        raise ValueError("group must be 'hitting' or 'pitching'")
    splits: list[dict[str, Any]] = []
    offset = 0
    while True:
        url = (f"{API}?stats=season&group={group}&season={int(season)}&sportId=1"
               f"&playerPool=ALL&limit={page}&offset={offset}")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            block = json.load(resp)["stats"][0]
        batch = block.get("splits", [])
        splits.extend(batch)
        offset += len(batch)
        if not batch or offset >= int(block.get("totalSplits", offset)):
            return splits


def splits_to_frame(splits: list[dict[str, Any]], season: int | str, fields: dict[str, str]) -> pd.DataFrame:
    """Flatten API splits into one row per player with MLBAMID + the mapped fields."""
    rows = []
    for sp in splits:
        stat = sp.get("stat", {})
        row = {
            "Season": int(season),
            "MLBAMID": int(sp["player"]["id"]),
            "Name": sp["player"].get("fullName", ""),
            "Team": (sp.get("team") or {}).get("abbreviation") or (sp.get("team") or {}).get("name", ""),
            "NumTeams": int(sp.get("numTeams", 1) or 1),
        }
        for api_key, col in fields.items():
            row[col] = stat.get(api_key)
        rows.append(row)
    df = pd.DataFrame(rows)
    for col in fields.values():
        # Rate fields arrive as strings like ".284" or "-.--"; coerce, keeping NaN for undefined rates.
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "OUTS" in df.columns:
        df["IP"] = (df["OUTS"] / 3).round(4)
    return df.drop_duplicates("MLBAMID").sort_values("MLBAMID").reset_index(drop=True)


def write_season_csvs(season: int | str, out_dir: Path) -> dict[str, Path]:
    """Fetch both groups for a season and write mlb_batting_/mlb_pitching_ CSVs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for group, fields, stem in (("hitting", BATTING_FIELDS, "mlb_batting"), ("pitching", PITCHING_FIELDS, "mlb_pitching")):
        frame = splits_to_frame(fetch_season_splits(season, group), season, fields)
        path = out_dir / f"{stem}_{int(season)}.csv"
        frame.to_csv(path, index=False)
        paths[group] = path
    return paths
