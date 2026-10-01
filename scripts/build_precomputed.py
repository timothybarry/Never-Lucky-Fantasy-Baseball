"""
build_precomputed.py
====================

Turn a RAW pitch-level Statcast CSV into the three precomputed files the
engine scores directly:

    <out_dir>/hitters_<tag>.csv
    <out_dir>/pitchers_<tag>.csv
    <out_dir>/rosters_<tag>.csv     (auto-drafted, optional)

This is the data pipeline: raw pitches in, normalized season tables out. It
reuses the exact same aggregation logic the live engine uses
(PitchLevelCSVSource), so what you precompute here is identical to what
``--source pitch`` would compute on the fly -- just cached to disk so future
runs are instant and you can build a multi-season library.

USAGE (from the repo root)
--------------------------
Basic -- aggregate one season and auto-build a matching roster:

    python scripts/build_precomputed.py \\
        --pitches data/raw_sample/Statcast_2021.csv \\
        --tag 2021

That writes data/precomputed/hitters_2021.csv, pitchers_2021.csv, and
rosters_2021.csv. Then score it:

    python -m statcast_roto.cli --source precomputed \\
        --hitters data/precomputed/hitters_2021.csv \\
        --pitchers data/precomputed/pitchers_2021.csv \\
        --rosters data/precomputed/rosters_2021.csv \\
        --outputs outputs_2021

Options
-------
--pitches PATH     Raw pitch-level CSV (Savant / pybaseball schema). Required.
--tag STR          Suffix for output filenames (e.g. 2021). Required.
--out-dir PATH     Where to write (default: data/precomputed).
--min-pa INT       Min PA to keep a hitter (default 50).
--min-ip FLOAT     Min IP to keep a pitcher (default 20).
--no-roster        Skip auto-drafting a roster (you'll supply your own).
--teams INT        Teams in the auto-draft roster (default 10).
--hitters-per INT  Hitters per team (default 9).
--pitchers-per INT Pitchers per team (default 7).
--no-names         Skip Chadwick name resolution (faster/offline; uses IDs).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the package importable when run from the repo root without install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from statcast_roto.pitch_level import PitchLevelCSVSource          # noqa: E402
from statcast_roto.drafting import snake_draft_rosters              # noqa: E402
from statcast_roto.dashboard import build_leaderboard_payload       # noqa: E402
from statcast_roto.value import PlayerValueModel                    # noqa: E402
from statcast_roto.categories import DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES  # noqa: E402
from statcast_roto.schemas import DataBundle                        # noqa: E402
from statcast_roto.fantasy_outcomes import (  # noqa: E402
    enrich_hitters_with_outcomes, enrich_pitchers_with_outcomes, load_or_fetch_outcomes, load_pitching_outcomes,
)

FIELDING_SLOT_POSITIONS = {
    "fielder_2": "C",
    "fielder_3": "1B",
    "fielder_4": "2B",
    "fielder_5": "3B",
    "fielder_6": "SS",
    "fielder_7": "LF",
    "fielder_8": "CF",
    "fielder_9": "RF",
}

WINDOWS = {
    "last7": ("Last 7 days", 7),
    "last14": ("Last 14 days", 14),
    "last30": ("Last 30 days", 30),
}


def _infer_primary_positions(raw):
    """Infer hitter position from modal Statcast fielder_2..fielder_9 IDs.

    This keeps position filtering derived from the raw pitch file instead of
    hardcoded from a lookup. Pure DH / non-fielders are filled as DH/—.
    """
    import pandas as pd

    pieces = []
    for col, pos in FIELDING_SLOT_POSITIONS.items():
        if col not in raw.columns:
            continue
        ids = pd.to_numeric(raw[col], errors="coerce").dropna().astype("int64")
        if ids.empty:
            continue
        counts = ids.value_counts().rename("fielding_appearances").reset_index()
        counts.columns = ["player_id", "fielding_appearances"]
        counts["position"] = pos
        pieces.append(counts)
    if not pieces:
        return pd.DataFrame(columns=["player_id", "position", "fielding_appearances"])
    counts = pd.concat(pieces, ignore_index=True)
    counts = counts.sort_values(["player_id", "fielding_appearances", "position"], ascending=[True, False, True])
    return counts.drop_duplicates("player_id")[["player_id", "position", "fielding_appearances"]]


def _add_positions(hitters, raw):
    pos = _infer_primary_positions(raw)
    if pos.empty:
        hitters = hitters.copy()
        hitters["position"] = "DH/—"
        return hitters
    hitters = hitters.merge(pos, on="player_id", how="left")
    hitters["position"] = hitters["position"].fillna("DH/—")
    # Put position near the identity columns for dashboard readability.
    front = [c for c in ["player_id", "player_name", "position"] if c in hitters.columns]
    rest = [c for c in hitters.columns if c not in front and c != "fielding_appearances"]
    resolved = int(hitters["position"].ne("DH/—").sum())
    print(f"  resolved positions for {resolved}/{len(hitters)} hitters")
    return hitters[front + rest]


def _build_name_map_once(src, raw, hitters, pitchers, no_names: bool):
    import pandas as pd
    if no_names:
        return None
    print("Resolving player names via Chadwick register "
          "(downloads once; falls back to IDs if offline)...")
    ids = pd.concat([hitters["player_id"], pitchers["player_id"]]).unique()
    return src._build_name_map(ids, raw)


def _name_tables(src, raw, hitters, pitchers, no_names: bool, names=None):
    if no_names:
        return hitters, pitchers
    if names is None:
        names = _build_name_map_once(src, raw, hitters, pitchers, no_names)
    hitters = hitters.copy()
    pitchers = pitchers.copy()
    hitters["player_name"] = hitters["player_id"].map(names).fillna(
        "MLBAM " + hitters["player_id"].astype(str))
    pitchers["player_name"] = pitchers["player_id"].map(names).fillna(
        "MLBAM " + pitchers["player_id"].astype(str))
    return hitters, pitchers


def _window_subset(prepped, days: int):
    import pandas as pd
    if "game_date" not in prepped.columns:
        return None, None, None
    dates = pd.to_datetime(prepped["game_date"], errors="coerce")
    if dates.notna().sum() == 0:
        return None, None, None
    end = dates.max().normalize()
    start = end - pd.Timedelta(days=days - 1)
    mask = (dates >= start) & (dates <= end)
    return prepped.loc[mask].copy(), start.date().isoformat(), end.date().isoformat()


def _build_window_leaderboards(src, prepped, raw, args, names=None):
    """Aggregate rolling leaderboards from the same raw file used for the season."""
    timeframes = {}
    for key, (label, days) in WINDOWS.items():
        subset, start, end = _window_subset(prepped, days)
        if subset is None or subset.empty:
            print(f"  skip {label}: no game_date window data")
            continue
        wh = src._aggregate_hitters(subset)
        wp = src._aggregate_pitchers(subset)
        wh, wp = _name_tables(src, raw, wh, wp, args.no_names, names)
        wh = _add_positions(wh, raw)
        # For short windows, keep everyone with actual opportunity and let the
        # chart-specific gates in build_leaderboard_payload handle rate filters.
        wh = wh[wh["pa"] > 0].reset_index(drop=True)
        wp = wp[wp["ip"] > 0].reset_index(drop=True)
        empty_rosters = __import__("pandas").DataFrame(columns=["team", "side", "player_id"])
        bundle = DataBundle(wh, wp, empty_rosters, f"window-{args.tag}-{key}").validate()
        comparison = PlayerValueModel(DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES).compare(bundle)
        timeframes[key] = {
            "label": label,
            "start": start,
            "end": end,
            "n_pitches": int(len(subset)),
            "leaderboards": build_leaderboard_payload(wh, wp, comparison, window_key=key),
        }
        print(f"  built {label}: {len(wh)} hitters, {len(wp)} pitchers, {len(subset)} pitches")
    return {"timeframes": timeframes}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="build_precomputed",
        description="Aggregate a raw pitch-level Statcast CSV into precomputed "
                    "hitter/pitcher/roster tables.",
    )
    p.add_argument("--pitches", type=Path, required=True,
                   help="Raw pitch-level Statcast CSV (one row per pitch).")
    p.add_argument("--tag", type=str, required=True,
                   help="Filename suffix, e.g. 2021 -> hitters_2021.csv.")
    p.add_argument("--out-dir", type=Path,
                   default=Path("data") / "precomputed",
                   help="Output directory (default: data/precomputed).")
    p.add_argument("--min-pa", type=int, default=50)
    p.add_argument("--min-ip", type=float, default=20.0)
    p.add_argument("--no-roster", action="store_true",
                   help="Don't auto-draft a roster CSV.")
    p.add_argument("--teams", type=int, default=10)
    p.add_argument("--hitters-per", type=int, default=9)
    p.add_argument("--pitchers-per", type=int, default=7)
    p.add_argument("--no-names", action="store_true",
                   help="Skip Chadwick name resolution (uses MLBAM IDs).")
    p.add_argument("--no-windows", action="store_true",
                   help="Skip rolling leaderboard windows JSON. By default, writes last7/last14/last30 leaderboards from game_date.")
    p.add_argument("--fantasy-outcomes-mode", choices=["auto", "local", "fetch", "off"], default="auto",
                   help="How to enrich hitter R/RBI/SB/AVG/OBP/SLG from season-level batting data. auto=local CSV if present, otherwise pybaseball if available; off keeps pitch-level approximations.")
    p.add_argument("--fantasy-outcomes", type=Path, default=None,
                   help="Explicit season-level batting/fantasy outcome CSV to merge onto hitters. Supports MLBAM player_id or FanGraphs IDfg plus Chadwick crosswalk.")
    p.add_argument("--fantasy-outcomes-dir", type=Path, default=Path("data") / "fantasy_outcomes",
                   help="Directory for local/cached season batting outcome CSVs, e.g. fangraphs_batting_2021.csv.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.pitches.exists():
        raise SystemExit(f"Raw pitch CSV not found: {args.pitches}")

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # We only need a rosters file for the DataBundle that .load() returns, but
    # we're aggregating the player tables independently of any roster here.
    # So we call the source's internal aggregation directly (same logic as
    # .load(), minus the roster requirement), then write the player tables and
    # optionally draft a fresh roster from the resulting pool.
    print(f"Reading raw pitches: {args.pitches}")
    src = PitchLevelCSVSource(
        pitches_csv=args.pitches,
        rosters_csv=args.pitches,  # placeholder; not used in this path
        min_pa=args.min_pa,
        min_ip=args.min_ip,
        resolve_names=not args.no_names,
    )

    import pandas as pd
    raw = pd.read_csv(args.pitches, low_memory=False)
    src._check_pitch_schema(raw)
    prepped = src._prepare(raw)

    print("Aggregating hitters...")
    hitters = src._aggregate_hitters(prepped)
    print("Aggregating pitchers...")
    pitchers = src._aggregate_pitchers(prepped)

    name_map = _build_name_map_once(src, raw, hitters, pitchers, args.no_names)
    hitters, pitchers = _name_tables(src, raw, hitters, pitchers, args.no_names, name_map)
    hitters = _add_positions(hitters, raw)

    print("Enriching hitter fantasy outcomes (R/RBI/SB/slash) from season-level data if available...")
    outcome_result = load_or_fetch_outcomes(
        args.tag,
        outcome_dir=args.fantasy_outcomes_dir,
        explicit_path=args.fantasy_outcomes,
        mode=args.fantasy_outcomes_mode,
    )
    hitters, outcome_meta = enrich_hitters_with_outcomes(
        hitters,
        outcome_result.outcomes if outcome_result else None,
        source=outcome_result.source if outcome_result else None,
    )
    if outcome_result:
        print(f"  fantasy outcomes source: {outcome_result.source}")
        if outcome_result.cache_path:
            print(f"  cached outcomes: {outcome_result.cache_path}")
    print(f"  matched fantasy outcomes for {outcome_meta['matched']}/{outcome_meta['total']} hitters")
    if not outcome_meta['matched']:
        print("  WARNING: R/RBI/SB remain pitch-level approximations. Provide a season batting CSV or install pybaseball for official fantasy outcomes.")

    if args.fantasy_outcomes_mode != "off":
        pitch_result = load_pitching_outcomes(args.tag, outcome_dir=args.fantasy_outcomes_dir)
        pitchers, pitch_meta = enrich_pitchers_with_outcomes(
            pitchers,
            pitch_result.outcomes if pitch_result else None,
            source=pitch_result.source if pitch_result else None,
        )
        print(f"  matched pitching outcomes (W/SV/ERA/WHIP) for {pitch_meta['matched']}/{pitch_meta['total']} pitchers")

    # Apply the player-pool minimums.
    hitters = hitters[hitters["pa"] >= args.min_pa].reset_index(drop=True)
    pitchers = pitchers[pitchers["ip"] >= args.min_ip].reset_index(drop=True)

    hitters_path = out_dir / f"hitters_{args.tag}.csv"
    pitchers_path = out_dir / f"pitchers_{args.tag}.csv"
    hitters.to_csv(hitters_path, index=False, float_format="%.10g")
    pitchers.to_csv(pitchers_path, index=False, float_format="%.10g")
    print(f"  wrote {hitters_path}  ({len(hitters)} hitters)")
    print(f"  wrote {pitchers_path}  ({len(pitchers)} pitchers)")

    # Auto-draft a matching roster unless told not to.
    if not args.no_roster:
        need_h = args.teams * args.hitters_per
        need_p = args.teams * args.pitchers_per
        if len(hitters) < need_h or len(pitchers) < need_p:
            print(
                f"  WARNING: pool too small for a {args.teams}-team league "
                f"(need {need_h} hitters / {need_p} pitchers, have "
                f"{len(hitters)} / {len(pitchers)}). Skipping roster; lower "
                f"--teams or per-team counts, or pass --no-roster."
            )
        else:
            rosters = snake_draft_rosters(
                hitters, pitchers,
                n_teams=args.teams,
                hitters_per_team=args.hitters_per,
                pitchers_per_team=args.pitchers_per,
            )
            rosters_path = out_dir / f"rosters_{args.tag}.csv"
            rosters.to_csv(rosters_path, index=False)
            print(f"  wrote {rosters_path}  ({len(rosters)} slots, "
                  f"{args.teams} teams)")


    if not args.no_windows:
        print("\nBuilding rolling leaderboard windows...")
        windows = _build_window_leaderboards(src, prepped, raw, args, name_map)
        windows_path = out_dir / f"leaderboards_{args.tag}_windows.json"
        windows_path.write_text(json.dumps(windows, indent=2), encoding="utf-8")
        print(f"  wrote {windows_path}")

    print("\nDone. Score it with:")
    print(f"  python -m statcast_roto.cli --source precomputed \\")
    print(f"      --hitters {hitters_path} \\")
    print(f"      --pitchers {pitchers_path} \\")
    if not args.no_roster:
        print(f"      --rosters {out_dir / f'rosters_{args.tag}.csv'} \\")
    print(f"      --outputs outputs_{args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
