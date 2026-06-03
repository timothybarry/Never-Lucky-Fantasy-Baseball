"""
schemas.py
==========

The normalized data contract that every data source must satisfy and that the
scoring engine consumes. Keeping the schema explicit (and validated) means a
source can never silently feed malformed data into scoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

REQUIRED_HITTER_COLUMNS = {
    "player_id", "player_name", "pa", "batted_balls", "pitches_seen",
    "barrels", "r_plus_rbi", "xwoba", "ev90", "chase_rate", "sb",
    "hr", "r", "rbi", "avg",
}
REQUIRED_PITCHER_COLUMNS = {
    "player_id", "player_name", "ip", "pitches", "batted_balls_allowed",
    "k", "xfip", "whiff_rate", "barrel_rate_allowed", "qs",
    "w", "sv", "era", "whip",
}
REQUIRED_ROSTER_COLUMNS = {"team", "side", "player_id"}


@dataclass(frozen=True, slots=True)
class DataBundle:
    """Normalized data needed by the scoring engine.

    `notes` carries provenance / honesty flags (e.g. "synthetic" or "xFIP is a
    proxy") so they can surface in output and never be silently lost.
    """

    hitters: pd.DataFrame
    pitchers: pd.DataFrame
    rosters: pd.DataFrame
    source_name: str
    notes: tuple[str, ...] = ()

    def validate(self) -> "DataBundle":
        validate_columns(self.hitters, REQUIRED_HITTER_COLUMNS, "hitters")
        validate_columns(self.pitchers, REQUIRED_PITCHER_COLUMNS, "pitchers")
        validate_columns(self.rosters, REQUIRED_ROSTER_COLUMNS, "rosters")
        bad = set(self.rosters["side"].dropna().unique()) - {"hitting", "pitching"}
        if bad:
            raise ValueError(f"rosters.side has invalid values: {sorted(bad)}")
        return self


def validate_columns(df: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def read_csv(path: str | Path, *, label: str) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Could not find {label} CSV: {path}")
    return pd.read_csv(path)
