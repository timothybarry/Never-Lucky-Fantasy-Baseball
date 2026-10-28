"""
fetch_bat_tracking.py
=====================

Download the Baseball Savant bat-tracking leaderboards the Swing Lab is built from
(regular season, every batter, 2023 on) into data/bat_tracking/.

    python scripts/fetch_bat_tracking.py                       # 2023-2026
    python scripts/fetch_bat_tracking.py --years 2025 2026 --force

About 27 requests: 20 to Baseball Savant (five leaderboards for each of the four
seasons), three seconds apart, and 7 to the MLB Stats API for batting sides (977
hitters, 150 a request). Files already in the folder are used as they are, so you
can also save each CSV by hand with the leaderboard's Download CSV button, named
as below. The pages' defaults differ from these settings, so set them and press
Update before downloading:

    swing_path_<year>.csv  Bat Tracking > Swing Path / Attack Angle: Type Batters,
                           Game Type Regular, Min. Total Swings 1, Min. Results 1
                           (the URL's minSwings and minGroupSwings), Start and End
                           Year both <year>
    league_<year>.csv      the same page and settings with Type League (one row)
    bat_speed_<year>.csv   Bat Tracking: the same settings as swing_path
    expected_<year>.csv    Expected Statistics: Batters, <year>, Minimum PA, minimum 1
    statcast_<year>.csv    Exit Velocity & Barrels: Batters, <year>, Minimum BBE 1

site/build_payload.py stops with a message naming the file and the setting when a
swing path table was saved at Min. Total Swings "Qualified", when the bat tracking
table lists other hitters than swing path, or when a league table isn't one row.
For personal, non-commercial use; see DATA_NOTICE.md.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from statcast_roto.bat_tracking import bat_sides, fetch_tables  # noqa: E402

import pandas as pd  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fetch_bat_tracking")
    ap.add_argument("--years", nargs="+", default=["2023", "2024", "2025", "2026"])
    ap.add_argument("--out-dir", type=Path, default=ROOT / "data" / "bat_tracking")
    ap.add_argument("--force", action="store_true", help="Re-download files that are already there.")
    args = ap.parse_args(argv)

    fetch_tables(args.years, args.out_dir, force=args.force)
    ids = []
    for y in args.years:
        ids += pd.read_csv(args.out_dir / f"swing_path_{y}.csv", encoding="utf-8-sig")["id"].tolist()
    bat_sides(ids, args.out_dir / "bat_sides.json")
    print("Next: python site/build_payload.py && python site/build_site.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
