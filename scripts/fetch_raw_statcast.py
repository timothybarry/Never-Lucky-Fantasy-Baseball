"""
fetch_raw_statcast.py
=====================

Download the raw pitch-level Statcast seasons (about 1.6 GB for 2017-2021) that the
repo does not ship. Only needed to re-derive data/precomputed from scratch; the
site builds from the committed precomputed tables without it.

    pip install -e ".[live]"            # pybaseball
    python scripts/fetch_raw_statcast.py --seasons 2021
    python scripts/fetch_raw_statcast.py --seasons 2017 2018 2019 2020 2021

Each season is pulled from Baseball Savant through pybaseball in date chunks
(slow: expect 10-20 minutes a season) and written as data/raw_sample/statcast_<year>.csv,
regular-season games only. For personal use under MLB's terms; see DATA_NOTICE.md.
"""

from __future__ import annotations

import argparse
from pathlib import Path

# Regular-season date spans (first and last game) for the seasons this project covers.
SEASONS = {
    "2017": ("2017-04-02", "2017-10-01"),
    "2018": ("2018-03-29", "2018-10-01"),
    "2019": ("2019-03-20", "2019-09-29"),
    "2020": ("2020-07-23", "2020-09-27"),
    "2021": ("2021-04-01", "2021-10-03"),
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fetch_raw_statcast")
    ap.add_argument("--seasons", nargs="+", default=list(SEASONS), choices=list(SEASONS))
    ap.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "raw_sample")
    ap.add_argument("--force", action="store_true", help="Re-download seasons that already exist.")
    args = ap.parse_args(argv)

    try:
        from pybaseball import statcast  # type: ignore
    except ImportError:
        raise SystemExit('pybaseball is not installed. Run: pip install -e ".[live]"')

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for season in args.seasons:
        out = args.out_dir / f"statcast_{season}.csv"
        if out.exists() and not args.force:
            print(f"{season}: {out.name} already exists (use --force to re-download)")
            continue
        start, end = SEASONS[season]
        print(f"{season}: downloading {start} to {end} from Baseball Savant via pybaseball...")
        df = statcast(start_dt=start, end_dt=end)
        if "game_type" in df.columns:
            df = df[df["game_type"] == "R"]  # regular season only
        df.to_csv(out, index=False)
        print(f"{season}: wrote {out} ({len(df):,} pitches)")
    print("Next: python scripts/build_precomputed.py --pitches data/raw_sample/statcast_<year>.csv --tag <year>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
