"""
enrich_precomputed.py
=====================

Merge official MLB season lines onto seasons that are already precomputed,
without re-reading the raw pitch files.

    python scripts/enrich_precomputed.py --tags 2017 2018 2019 2020 2021 --fetch

--fetch downloads any missing data/fantasy_outcomes/mlb_{batting,pitching}_<tag>.csv
from the public MLB Stats API first. Safe to re-run: official values overwrite,
and the original Statcast PA is kept once in pa_statcast.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from statcast_roto.fantasy_outcomes import (  # noqa: E402
    enrich_hitters_with_outcomes, enrich_pitchers_with_outcomes, load_outcomes_from_csv, normalize_pitching_table,
)
from statcast_roto.mlb_stats_api import write_season_csvs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="enrich_precomputed")
    ap.add_argument("--tags", nargs="+", required=True)
    root = Path(__file__).resolve().parents[1]
    ap.add_argument("--precomputed-dir", type=Path, default=root / "data" / "precomputed")
    ap.add_argument("--outcomes-dir", type=Path, default=root / "data" / "fantasy_outcomes")
    ap.add_argument("--fetch", action="store_true", help="Download missing season CSVs from statsapi.mlb.com.")
    args = ap.parse_args(argv)

    for tag in args.tags:
        need = [args.outcomes_dir / f"mlb_{k}_{tag}.csv" for k in ("batting", "pitching")]
        if args.fetch and not all(p.exists() for p in need):
            paths = write_season_csvs(tag, args.outcomes_dir)
            print(f"{tag}: fetched {', '.join(p.name for p in paths.values())}")

        if not all(p.exists() for p in need):
            missing = ", ".join(p.name for p in need if not p.exists())
            raise SystemExit(f"{tag}: missing {missing}. Run with --fetch to download them; nothing was written.")
        hp = args.precomputed_dir / f"hitters_{tag}.csv"
        pp = args.precomputed_dir / f"pitchers_{tag}.csv"
        hitters = pd.read_csv(hp, low_memory=False)
        pitchers = pd.read_csv(pp, low_memory=False)

        # Load the exact MLB files, never a stray cached FanGraphs export that happens to match the season.
        bat = load_outcomes_from_csv(need[0], season=tag)
        hitters, hmeta = enrich_hitters_with_outcomes(hitters, bat.outcomes, source=bat.source)
        pit = normalize_pitching_table(pd.read_csv(need[1], low_memory=False), season=tag)
        pitchers, pmeta = enrich_pitchers_with_outcomes(pitchers, pit, source=f"local:{need[1].name}")

        # 10 significant digits round-trips exactly, so re-runs don't rewrite unchanged files.
        hitters.to_csv(hp, index=False, float_format="%.10g")
        pitchers.to_csv(pp, index=False, float_format="%.10g")
        print(f"{tag}: hitters {hmeta['matched']}/{hmeta['total']} matched ({hmeta['source']}), "
              f"pitchers {pmeta['matched']}/{pmeta['total']} matched ({pmeta['source']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
