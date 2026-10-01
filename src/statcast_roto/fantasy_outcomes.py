"""
fantasy_outcomes.py
===================

Season-level fantasy category enrichment for hitter tables.

Pitch-level Statcast is excellent for process metrics (xwOBA, barrels, EV90,
chase rate), but it is not a clean source for runner-scored fantasy categories
like R and SB. This module keeps the architecture honest: use Statcast as the
skill engine, then join season-level batting outcomes from a fantasy/stat table.

Supported inputs:
  * local CSVs in data/fantasy_outcomes/ such as batting_2021.csv,
    fangraphs_batting_2021.csv, or fantasy_outcomes_2021.csv
  * optional pybaseball/FanGraphs fetch with a Chadwick ID crosswalk

The normalized output overwrites/fills R, RBI, SB, HR, AVG, OBP, SLG, and
r_plus_rbi while preserving Statcast-derived process columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

FANTASY_OUTCOME_COLUMNS = ["pa", "r", "hr", "rbi", "sb", "avg", "obp", "slg", "ops", "bb", "so", "cs", "babip"]

# Common file names we will auto-detect for a given season.
OUTCOME_FILE_PATTERNS = (
    "mlb_batting_{season}.csv",  # official MLB Stats API pull first: keyed by MLBAM id, no crosswalk
    "fantasy_outcomes_{season}.csv",
    "batting_{season}.csv",
    "fangraphs_batting_{season}.csv",
    "fg_batting_{season}.csv",
)

COLUMN_ALIASES = {
    "player_id": ["player_id", "mlbam", "mlbam_id", "key_mlbam", "MLBAMID", "MLBAM"],
    "player_name": ["player_name", "Name", "name", "Player", "player"],
    "season": ["season", "Season", "year", "Year"],
    "fg_id": ["IDfg", "idfg", "fangraphs_id", "key_fangraphs"],
    "pa": ["PA", "pa", "plate_appearances"],
    "r": ["R", "r", "runs"],
    "hr": ["HR", "hr", "home_runs"],
    "rbi": ["RBI", "rbi"],
    "sb": ["SB", "sb", "stolen_bases"],
    "avg": ["AVG", "avg", "BA", "ba"],
    "obp": ["OBP", "obp"],
    "slg": ["SLG", "slg"],
    "ops": ["OPS", "ops"],
    "bb": ["BB", "bb", "walks"],
    "so": ["SO", "so", "strikeouts"],
    "cs": ["CS", "cs", "caught_stealing"],
    "babip": ["BABIP", "babip"],
}

# Pitcher outcomes the pitch rows can't recover (W, SV, ERA, WHIP) plus official
# volume lines for audit. Statcast K and IP stay the scoring source.
PITCHING_OUTCOME_COLUMNS = ["w", "l", "sv", "hld", "g", "gs", "era", "whip", "er", "tbf", "bb", "so", "ip"]
PITCHING_ALIASES = {
    "w": ["W", "w", "wins"], "l": ["L", "l", "losses"], "sv": ["SV", "sv", "saves"],
    "hld": ["HLD", "hld", "holds"], "g": ["G", "g", "games"], "gs": ["GS", "gs", "games_started"],
    "era": ["ERA", "era"], "whip": ["WHIP", "whip"], "er": ["ER", "er", "earned_runs"],
    "tbf": ["TBF", "tbf", "batters_faced"], "bb": ["BB", "bb", "walks"], "so": ["SO", "so", "strikeouts"],
    "ip": ["IP", "ip", "innings_pitched"],
}
PITCHING_FILE_PATTERNS = ("mlb_pitching_{season}.csv", "pitching_{season}.csv", "fangraphs_pitching_{season}.csv")


@dataclass(frozen=True, slots=True)
class OutcomeLoadResult:
    outcomes: pd.DataFrame
    source: str
    cache_path: Path | None = None


def _first_present(df: pd.DataFrame, aliases: Iterable[str]) -> str | None:
    for col in aliases:
        if col in df.columns:
            return col
    # Case-insensitive fallback.
    lower = {str(c).lower(): c for c in df.columns}
    for col in aliases:
        hit = lower.get(str(col).lower())
        if hit is not None:
            return hit
    return None


def find_outcome_file(outcome_dir: Path, season: str | int) -> Path | None:
    """Return a likely local fantasy outcome CSV for a season, if present."""
    season = str(season)
    if not outcome_dir.exists():
        return None
    for pattern in OUTCOME_FILE_PATTERNS:
        path = outcome_dir / pattern.format(season=season)
        if path.exists():
            return path
    # Looser fallback: any CSV with the season and batting/outcome in the name.
    for path in outcome_dir.glob(f"*{season}*.csv"):
        name = path.name.lower()
        if any(token in name for token in ("bat", "fg", "fangraph", "outcome", "fantasy")):
            return path
    return None


def _load_chadwick_register() -> pd.DataFrame:
    """Load Chadwick people register for ID crosswalks.

    The same public register already used elsewhere in the project contains
    MLBAM and FanGraphs IDs. This requires internet the first time unless the
    caller supplies direct player_id values in the outcome CSV.
    """
    base = "https://raw.githubusercontent.com/chadwickbureau/register/master/data"
    frames = []
    cols = ["key_mlbam", "key_fangraphs", "name_first", "name_last"]
    for shard in "0123456789abcdef":
        frames.append(pd.read_csv(f"{base}/people-{shard}.csv", usecols=cols, low_memory=False))
    reg = pd.concat(frames, ignore_index=True)
    reg = reg.dropna(subset=["key_mlbam"])
    reg["key_mlbam"] = pd.to_numeric(reg["key_mlbam"], errors="coerce")
    reg["key_fangraphs"] = pd.to_numeric(reg["key_fangraphs"], errors="coerce")
    reg = reg.dropna(subset=["key_mlbam"]).copy()
    reg["key_mlbam"] = reg["key_mlbam"].astype("int64")
    return reg


def _normalize_name(value: object) -> str:
    text = str(value or "").strip().lower()
    return " ".join(text.replace(".", "").replace("'", "").split())


def normalize_outcome_table(raw: pd.DataFrame, *, season: str | int | None = None) -> pd.DataFrame:
    """Normalize a FanGraphs/MLB/custom batting table to our outcome schema.

    If a direct MLBAM column is unavailable but IDfg/key_fangraphs exists, we
    map to MLBAM via Chadwick. If no ID can be found, the table keeps a normalized
    player_name for a conservative name-based fallback at merge time.
    """
    season_s = str(season) if season is not None else None
    df = raw.copy()
    # Only filter by season when the tag is an actual year. This keeps tests and
    # custom tags like "sample" from accidentally filtering a valid CSV to zero.
    if season_s is not None and season_s.isdigit():
        season_col = _first_present(df, COLUMN_ALIASES["season"])
        if season_col:
            df = df[pd.to_numeric(df[season_col], errors="coerce").astype("Int64").astype(str).eq(season_s)]

    out = pd.DataFrame(index=df.index)
    name_col = _first_present(df, COLUMN_ALIASES["player_name"])
    if name_col:
        out["player_name"] = df[name_col].astype(str)
        out["name_key"] = out["player_name"].map(_normalize_name)

    pid_col = _first_present(df, COLUMN_ALIASES["player_id"])
    if pid_col:
        out["player_id"] = pd.to_numeric(df[pid_col], errors="coerce")

    fg_col = _first_present(df, COLUMN_ALIASES["fg_id"])
    if "player_id" not in out.columns and fg_col:
        fg_ids = pd.to_numeric(df[fg_col], errors="coerce")
        try:
            reg = _load_chadwick_register()
            crosswalk = reg.dropna(subset=["key_fangraphs"]).drop_duplicates("key_fangraphs")
            mapped = pd.DataFrame({"key_fangraphs": fg_ids}).merge(
                crosswalk[["key_fangraphs", "key_mlbam"]], on="key_fangraphs", how="left"
            )
            out["player_id"] = mapped["key_mlbam"].to_numpy()
        except Exception:
            # Keep name_key fallback; caller will warn about match rate.
            pass

    for key in FANTASY_OUTCOME_COLUMNS:
        col = _first_present(df, COLUMN_ALIASES[key])
        if col:
            out[key] = pd.to_numeric(df[col], errors="coerce")

    keep_cols = [c for c in ["player_id", "player_name", "name_key"] + FANTASY_OUTCOME_COLUMNS if c in out.columns]
    out = out[keep_cols].copy()
    if "player_id" in out.columns:
        out = out.dropna(subset=["player_id"])
        if not out.empty:
            out["player_id"] = out["player_id"].astype("int64")
    if "player_id" in out.columns:
        out = out.sort_values(["player_id"] + (["pa"] if "pa" in out.columns else []), ascending=[True, False] if "pa" in out.columns else [True])
        out = out.drop_duplicates("player_id", keep="first")
    elif "name_key" in out.columns:
        out = out.sort_values(["name_key"] + (["pa"] if "pa" in out.columns else []), ascending=[True, False] if "pa" in out.columns else [True])
        out = out.drop_duplicates("name_key", keep="first")
    return out.reset_index(drop=True)


def load_outcomes_from_csv(path: Path, *, season: str | int | None = None) -> OutcomeLoadResult:
    raw = pd.read_csv(path, low_memory=False)
    return OutcomeLoadResult(normalize_outcome_table(raw, season=season), f"local:{path.name}", path)


def fetch_fangraphs_outcomes(season: str | int, *, cache_dir: Path | None = None) -> OutcomeLoadResult:
    """Fetch season batting outcomes via pybaseball/FanGraphs and normalize.

    This is optional. The project still works offline if you provide a local CSV
    or skip enrichment, but this is the convenient path on the user's machine.
    """
    try:
        from pybaseball import batting_stats  # type: ignore
    except Exception as exc:  # pragma: no cover - environment-specific
        raise RuntimeError("pybaseball is not installed. Run `pip install pybaseball` or provide a local outcome CSV.") from exc

    season_i = int(season)
    raw = batting_stats(season_i, season_i, qual=0)
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"fangraphs_batting_{season_i}.csv"
        raw.to_csv(cache_path, index=False)
    else:
        cache_path = None
    return OutcomeLoadResult(normalize_outcome_table(raw, season=season_i), "pybaseball:fangraphs_batting_stats", cache_path)


def load_or_fetch_outcomes(
    season: str | int,
    *,
    outcome_dir: Path = Path("data") / "fantasy_outcomes",
    explicit_path: Path | None = None,
    mode: str = "auto",
) -> OutcomeLoadResult | None:
    """Find/fetch season-level hitter outcomes.

    mode:
      off   -> never load/fetch
      local -> local CSV only
      fetch -> pybaseball fetch only
      auto  -> explicit path, then local CSV, then pybaseball fetch
    """
    mode = mode.lower()
    if mode == "off":
        return None
    if explicit_path is not None:
        if not explicit_path.exists():
            raise FileNotFoundError(f"Fantasy outcome CSV not found: {explicit_path}")
        return load_outcomes_from_csv(explicit_path, season=season)
    if mode in {"auto", "local"}:
        found = find_outcome_file(outcome_dir, season)
        if found:
            return load_outcomes_from_csv(found, season=season)
        if mode == "local":
            return None
    if mode in {"auto", "fetch"}:
        try:
            return fetch_fangraphs_outcomes(season, cache_dir=outcome_dir)
        except Exception as exc:
            if mode == "fetch":
                raise
            print(f"  fantasy outcome enrichment unavailable: {exc}")
            return None
    raise ValueError("mode must be one of: auto, local, fetch, off")


def enrich_hitters_with_outcomes(
    hitters: pd.DataFrame,
    outcomes: pd.DataFrame | None,
    *,
    source: str | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Overwrite/fill fantasy outcome stats on hitter table.

    Returns the enriched table plus match metadata for logging/tests.
    """
    h = hitters.copy()
    h["fantasy_outcomes_source"] = "statcast_pitch_approx"
    h["fantasy_outcomes_matched"] = False
    if outcomes is None or outcomes.empty:
        h["r_plus_rbi"] = pd.to_numeric(h.get("r", 0), errors="coerce").fillna(0) + pd.to_numeric(h.get("rbi", 0), errors="coerce").fillna(0)
        return h, {"matched": 0, "total": int(len(h)), "source": None}

    out = outcomes.copy()
    source_name = source or "fantasy_outcomes"
    merge_cols = [c for c in FANTASY_OUTCOME_COLUMNS if c in out.columns]
    # Preserve Statcast PA for audit if official PA is supplied.
    if "pa" in merge_cols and "pa" in h.columns and "pa_statcast" not in h.columns:  # keep the first (Statcast) PA on re-runs
        h["pa_statcast"] = h["pa"]

    if "player_id" in out.columns:
        m = h.merge(out[["player_id"] + merge_cols], on="player_id", how="left", suffixes=("", "_official"))
        matched = m[merge_cols[0] + "_official"].notna() if merge_cols else pd.Series(False, index=m.index)
    elif "name_key" in out.columns:
        h["name_key"] = h["player_name"].map(_normalize_name)
        m = h.merge(out[["name_key"] + merge_cols], on="name_key", how="left", suffixes=("", "_official"))
        matched = m[merge_cols[0] + "_official"].notna() if merge_cols else pd.Series(False, index=m.index)
    else:
        return h, {"matched": 0, "total": int(len(h)), "source": source_name}

    for col in merge_cols:
        official = f"{col}_official"
        if official in m.columns:
            m[col] = m[official].where(m[official].notna(), m[col] if col in m.columns else np.nan)
            m = m.drop(columns=[official])
    m["fantasy_outcomes_matched"] = matched.fillna(False).astype(bool)
    m.loc[m["fantasy_outcomes_matched"], "fantasy_outcomes_source"] = source_name
    m["r"] = pd.to_numeric(m.get("r", 0), errors="coerce").fillna(0)
    m["rbi"] = pd.to_numeric(m.get("rbi", 0), errors="coerce").fillna(0)
    m["sb"] = pd.to_numeric(m.get("sb", 0), errors="coerce").fillna(0)
    m["hr"] = pd.to_numeric(m.get("hr", 0), errors="coerce").fillna(0)
    m["r_plus_rbi"] = m["r"] + m["rbi"]
    if "name_key" in m.columns:
        m = m.drop(columns=["name_key"])
    meta = {"matched": int(m["fantasy_outcomes_matched"].sum()), "total": int(len(m)), "source": source_name}
    return m, meta


def load_pitching_outcomes(season: str | int, *, outcome_dir: Path = Path("data") / "fantasy_outcomes") -> OutcomeLoadResult | None:
    """Local season pitching CSV (e.g. mlb_pitching_2021.csv) normalized to our schema, or None."""
    for pattern in PITCHING_FILE_PATTERNS:
        path = outcome_dir / pattern.format(season=season)
        if path.exists():
            return OutcomeLoadResult(normalize_pitching_table(pd.read_csv(path, low_memory=False), season=season),
                                     f"local:{path.name}", path)
    return None


def normalize_pitching_table(raw: pd.DataFrame, *, season: str | int | None = None) -> pd.DataFrame:
    """Normalize an MLB/FanGraphs pitching table to player_id + PITCHING_OUTCOME_COLUMNS."""
    df = raw.copy()
    season_s = str(season) if season is not None else None
    if season_s is not None and season_s.isdigit():
        season_col = _first_present(df, COLUMN_ALIASES["season"])
        if season_col:
            df = df[pd.to_numeric(df[season_col], errors="coerce").astype("Int64").astype(str).eq(season_s)]
    pid_col = _first_present(df, COLUMN_ALIASES["player_id"])
    if pid_col is None:
        raise ValueError("pitching outcome table needs an MLBAM id column (player_id / MLBAMID / key_mlbam)")
    out = pd.DataFrame({"player_id": pd.to_numeric(df[pid_col], errors="coerce")})
    for key in PITCHING_OUTCOME_COLUMNS:
        col = _first_present(df, PITCHING_ALIASES[key])
        if col:
            out[key] = pd.to_numeric(df[col], errors="coerce")
    out = out.dropna(subset=["player_id"])
    out["player_id"] = out["player_id"].astype("int64")
    return out.drop_duplicates("player_id").reset_index(drop=True)


def enrich_pitchers_with_outcomes(
    pitchers: pd.DataFrame,
    outcomes: pd.DataFrame | None,
    *,
    source: str | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Fill W/SV/ERA/WHIP (and official volume lines) on the pitcher table by MLBAM id.

    Statcast-derived k stays the scoring source (official strikeouts land in
    so_official for audit). Innings come from the official line, because
    pitch rows miss outs made on the bases; the Statcast value is kept in
    ip_statcast.
    """
    p = pitchers.copy()
    p["pitching_outcomes_source"] = "statcast_pitch_approx"
    p["pitching_outcomes_matched"] = False
    if outcomes is None or outcomes.empty:
        return p, {"matched": 0, "total": int(len(p)), "source": None}

    out = outcomes.rename(columns={"so": "so_official", "ip": "ip_official"})
    cols = [c for c in out.columns if c != "player_id"]
    m = p.merge(out[["player_id"] + cols], on="player_id", how="left", suffixes=("", "_official"))
    probe = "era_official" if "era_official" in m.columns else ("era" if "era" in cols else cols[0])
    matched = m[probe].notna() | (m["w_official"].notna() if "w_official" in m.columns else False)
    for col in cols:
        official = f"{col}_official"
        if official in m.columns:  # column existed on the Statcast table: official value wins where present
            m[col] = m[official].where(m[official].notna(), m[col])
            m = m.drop(columns=[official])
    m["pitching_outcomes_matched"] = matched.fillna(False).astype(bool)
    m.loc[m["pitching_outcomes_matched"], "pitching_outcomes_source"] = source or "pitching_outcomes"
    for col in ("w", "sv"):
        if col in m.columns:
            m[col] = pd.to_numeric(m[col], errors="coerce").fillna(0)
    if "ip_official" in m.columns and "ip" in m.columns:
        if "ip_statcast" not in m.columns:  # keep the first (Statcast) innings on re-runs
            m["ip_statcast"] = m["ip"]
        m["ip"] = m["ip_official"].where(m["ip_official"].notna(), m["ip_statcast"]).round(4)
    return m, {"matched": int(m["pitching_outcomes_matched"].sum()), "total": int(len(m)), "source": source}
