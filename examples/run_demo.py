"""
run_demo.py
===========

End-to-end demonstration of the Statcast roto engine on real 2020 data.

Run from the repo root:
    python examples/run_demo.py

What it does
------------
1. Loads the bundled precomputed 2020 player pool (real Statcast aggregates).
2. Scores the bundled 10-team league on the Statcast category slate.
3. Computes how player VALUES shift between Statcast and traditional scoring
   -- the core analytical payoff.
4. Writes CSV + PNG outputs to ./outputs.
5. (Optional) Demonstrates the raw-pitch aggregation path on the bundled
   sample, building a self-consistent roster via snake draft.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

# Make `statcast_roto` importable when run from the repo root without install.
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from statcast_roto import (  # noqa: E402
    PrecomputedCSVSource,
    PitchLevelCSVSource,
    RotoScorer,
    PlayerValueModel,
    DEFAULT_CATEGORIES,
    TRADITIONAL_CATEGORIES,
    score_roto,
    snake_draft_rosters,
)
from statcast_roto.charts import save_standings_chart, save_value_delta_chart  # noqa: E402
from statcast_roto.schemas import DataBundle  # noqa: E402


def main() -> None:
    out = Path("outputs")
    out.mkdir(exist_ok=True)

    # 1) Precomputed real-2020 pool + bundled league -----------------------
    print("=" * 70)
    print("STATCAST ROTO  --  real 2020 season, process-stat scoring")
    print("=" * 70)
    bundle = PrecomputedCSVSource().load()
    print(f"\nData source: {bundle.source_name}")
    for n in bundle.notes:
        print(f"  note: {n}")
    print(f"\nPool: {len(bundle.hitters)} hitters, {len(bundle.pitchers)} pitchers, "
          f"{len(bundle.rosters)} roster slots "
          f"({bundle.rosters['team'].nunique()} teams)")

    result = score_roto(bundle)
    print("\n--- STANDINGS (Statcast categories) ---")
    print(result.standings.to_string(index=False))

    # 2) Value shift: Statcast vs traditional objective --------------------
    comparison = PlayerValueModel(DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES).compare(bundle)
    print("\n--- Players who GAIN the most under Statcast scoring ---")
    print("(elite stuff/contact-quality the old stats undervalue)")
    print(comparison.biggest_statcast_bumps[
        ["player_name", "side", "value_delta", "rank_delta"]].head(10).to_string(index=False))
    print("\n--- Players who look better under TRADITIONAL scoring ---")
    print("(results/luck the process stats see through)")
    print(comparison.biggest_traditional_bumps[
        ["player_name", "side", "value_delta", "rank_delta"]].head(10).to_string(index=False))

    # 3) Write outputs -----------------------------------------------------
    result.standings.to_csv(out / "standings.csv", index=False)
    result.category_values.to_csv(out / "team_category_values.csv", index=False)
    result.category_points.to_csv(out / "team_category_points.csv", index=False)
    comparison.player_values.to_csv(out / "player_value_comparison.csv", index=False)
    comparison.biggest_statcast_bumps.to_csv(out / "biggest_statcast_bumps.csv", index=False)
    comparison.biggest_traditional_bumps.to_csv(out / "biggest_traditional_bumps.csv", index=False)
    save_standings_chart(result.standings, out / "standings.png")
    save_value_delta_chart(comparison.player_values, out / "value_delta.png")
    print(f"\nOutputs written to {out.resolve()}")

    # 4) (Optional) raw-pitch aggregation demo -----------------------------
    sample = Path("data/raw_sample/statcast_2020_sample.csv")
    if sample.exists():
        print("\n" + "=" * 70)
        print("BONUS: aggregating the RAW pitch-level sample from scratch")
        print("=" * 70)
        rosters_path = PrecomputedCSVSource().directory / "rosters_2020.csv"
        src = PitchLevelCSVSource(pitches_csv=sample, rosters_csv=rosters_path,
                                  min_pa=25, min_ip=10)
        # Aggregate, then build a self-consistent small league from the sample
        # pool (the sample only contains a handful of players).
        raw = src.load.__wrapped__ if hasattr(src.load, "__wrapped__") else None
        # Simplest robust path: aggregate via the source internals, re-draft.
        import pandas as pd
        pitches = pd.read_csv(sample, low_memory=False)
        prepped = src._prepare(pitches)
        hitters = src._aggregate_hitters(prepped)
        pitchers = src._aggregate_pitchers(prepped)
        names = src._build_name_map(
            pd.concat([hitters["player_id"], pitchers["player_id"]]).unique(), pitches)
        hitters["player_name"] = hitters["player_id"].map(names).fillna(
            "MLBAM " + hitters["player_id"].astype(str))
        pitchers["player_name"] = pitchers["player_id"].map(names).fillna(
            "MLBAM " + pitchers["player_id"].astype(str))
        hitters = hitters[hitters["pa"] >= 25].reset_index(drop=True)
        pitchers = pitchers[pitchers["ip"] >= 10].reset_index(drop=True)
        print(f"Aggregated from raw pitches: {len(hitters)} hitters, "
              f"{len(pitchers)} pitchers")
        print("Top barrel hitters in the sample:")
        print(hitters.nlargest(5, "barrels")[
            ["player_name", "pa", "barrels", "hr", "ev90", "xwoba"]].to_string(index=False))


if __name__ == "__main__":
    main()
