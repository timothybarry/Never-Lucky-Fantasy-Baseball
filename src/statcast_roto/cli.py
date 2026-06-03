"""
cli.py
======

Command-line interface for the Statcast roto engine.

Examples
--------
Run on the bundled precomputed 2020 data (fast, no network):
    python -m statcast_roto.cli --source precomputed --outputs outputs

Aggregate from a raw pitch-level Statcast CSV (the "from scratch" path):
    python -m statcast_roto.cli --source pitch \\
        --pitches data/raw_sample/statcast_2020_sample.csv \\
        --rosters data/precomputed/rosters_2020.csv \\
        --outputs outputs
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless-safe; no display required

from .categories import DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES
from .charts import save_standings_chart, save_value_delta_chart
from .scoring import RotoScorer
from .sources import PrecomputedCSVSource
from .pitch_level import PitchLevelCSVSource
from .value import PlayerValueModel


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="statcast_roto",
        description="Score a fantasy league on Statcast/expected-stat categories.",
    )
    p.add_argument("--source", choices=["precomputed", "pitch"], default="precomputed",
                   help="precomputed = bundled aggregated CSVs; "
                        "pitch = aggregate a raw pitch-level Statcast CSV.")
    p.add_argument("--pitches", type=Path, default=None,
                   help="Raw pitch-level Statcast CSV (required for --source pitch).")
    p.add_argument("--rosters", type=Path, default=None,
                   help="Roster CSV (team, side, player_id). Defaults to bundled.")
    p.add_argument("--outputs", type=Path, default=Path("outputs"),
                   help="Directory for CSV + PNG outputs.")
    p.add_argument("--min-pa", type=int, default=50, help="Min PA for pitch aggregation.")
    p.add_argument("--min-ip", type=float, default=20.0, help="Min IP for pitch aggregation.")
    p.add_argument("--no-charts", action="store_true", help="Skip PNG chart generation.")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out = args.outputs
    out.mkdir(parents=True, exist_ok=True)

    # --- load data via the chosen source ---
    if args.source == "pitch":
        if args.pitches is None:
            raise SystemExit("--source pitch requires --pitches PATH")
        rosters = args.rosters or (PrecomputedCSVSource().directory / "rosters_2020.csv")
        bundle = PitchLevelCSVSource(
            pitches_csv=args.pitches,
            rosters_csv=rosters,
            min_pa=args.min_pa,
            min_ip=args.min_ip,
        ).load()
    else:
        bundle = PrecomputedCSVSource()
        if args.rosters is not None:
            bundle = PrecomputedCSVSource(rosters_file=args.rosters.name,
                                          directory=args.rosters.parent)
        bundle = bundle.load()

    # --- score + compare ---
    result = RotoScorer(DEFAULT_CATEGORIES).score(bundle)
    comparison = PlayerValueModel(DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES).compare(bundle)

    # --- write outputs ---
    result.standings.to_csv(out / "standings.csv", index=False)
    result.category_values.to_csv(out / "team_category_values.csv", index=False)
    result.category_points.to_csv(out / "team_category_points.csv", index=False)
    result.roster_player_stats.to_csv(out / "roster_player_stats.csv", index=False)
    comparison.player_values.to_csv(out / "player_value_comparison.csv", index=False)
    comparison.biggest_statcast_bumps.to_csv(out / "biggest_statcast_bumps.csv", index=False)
    comparison.biggest_traditional_bumps.to_csv(out / "biggest_traditional_bumps.csv", index=False)

    if not args.no_charts:
        save_standings_chart(result.standings, out / "standings.png")
        save_value_delta_chart(comparison.player_values, out / "value_delta.png")

    # --- console summary ---
    print(f"Source: {bundle.source_name}")
    for n in bundle.notes:
        print(f"  note: {n}")
    print("\n=== STANDINGS ===")
    print(result.standings.to_string(index=False))
    print("\n=== Biggest risers under STATCAST scoring ===")
    print(comparison.biggest_statcast_bumps[
        ["player_name", "side", "value_delta", "rank_delta"]].head(8).to_string(index=False))
    print(f"\nOutputs written to: {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
