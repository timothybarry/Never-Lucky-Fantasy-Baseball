"""
build_dashboard.py
==================

Generate the interactive multi-season dark dashboard from precomputed seasons.

Usage (from repo root) -- one or more tags:
    python scripts/build_dashboard.py --tags 2017 2018 2019 2020 2021

For each tag it reads data/precomputed/{hitters,pitchers,rosters}_<tag>.csv,
scores the league, computes leaderboards + team rosters, and bakes ALL seasons
into a single self-contained outputs/never_lucky_dashboard.html with:
  - a season switcher
  - a leaderboard-stat selector (every scoring category + value risers)
  - clickable team rosters showing per-player contributions

Tags with missing files are skipped with a warning, so you can build a partial
dashboard while you assemble seasons.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from statcast_roto.sources import PrecomputedCSVSource  # noqa: E402
from statcast_roto.scoring import RotoScorer  # noqa: E402
from statcast_roto.value import PlayerValueModel  # noqa: E402
from statcast_roto.categories import DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES  # noqa: E402
from statcast_roto.dashboard import extract_season, build_multi_season_dashboard  # noqa: E402


def _discover_tags(precomputed_dir: Path) -> list[str]:
    tags = []
    for h in precomputed_dir.glob("hitters_*.csv"):
        tag = h.stem.replace("hitters_", "", 1)
        if (precomputed_dir / f"pitchers_{tag}.csv").exists() and (precomputed_dir / f"rosters_{tag}.csv").exists():
            tags.append(tag)
    def key(t: str):
        return (0, int(t)) if re.fullmatch(r"\d+", t) else (1, t)
    return sorted(set(tags), key=key)


def _load_leaderboard_windows(precomputed_dir: Path, tag: str) -> dict | None:
    path = precomputed_dir / f"leaderboards_{tag}_windows.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)




def _discover_raw_files(raw_dir: Path) -> dict[str, Path]:
    """Find exact full-season raw Statcast files, ignoring sample CSVs."""
    raw: dict[str, Path] = {}
    if not raw_dir.exists():
        return raw
    for path in raw_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".csv":
            continue
        m = re.fullmatch(r"[Ss]tatcast_(\d{4})\.csv", path.name)
        if m:
            raw[m.group(1)] = path
    return raw


def _precomputed_complete(precomputed_dir: Path, tag: str) -> bool:
    return all((precomputed_dir / f"{stem}_{tag}.csv").exists()
               for stem in ("hitters", "pitchers", "rosters"))


def _windows_complete(precomputed_dir: Path, tag: str) -> bool:
    path = precomputed_dir / f"leaderboards_{tag}_windows.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    frames = data.get("timeframes", data) if isinstance(data, dict) else {}
    return all(k in frames for k in ("last7", "last14", "last30"))


def _ensure_precomputed_from_raw(args, tags: list[str], raw_files: dict[str, Path]) -> None:
    """Build missing triplets or missing leaderboard windows from local raw files.

    This fixes the quiet one-season footgun: if the updated repo only carries the
    bundled 2020 precomputed files but the user's data/raw_sample folder contains
    full raw 2017-2021 files, build_dashboard can now self-heal the payload.
    """
    if args.no_auto_precompute:
        return
    for tag in tags:
        raw_path = raw_files.get(tag)
        missing_triplet = not _precomputed_complete(args.precomputed_dir, tag)
        missing_windows = not _windows_complete(args.precomputed_dir, tag)
        if not raw_path or not (missing_triplet or missing_windows):
            continue
        reason = []
        if missing_triplet:
            reason.append("season triplet")
        if missing_windows:
            reason.append("time-window leaderboards")
        print(f"  auto-precompute {tag}: missing {' + '.join(reason)}; using {raw_path}")
        cmd = [
            sys.executable,
            str(Path(__file__).resolve().parent / "build_precomputed.py"),
            "--pitches", str(raw_path),
            "--tag", str(tag),
            "--out-dir", str(args.precomputed_dir),
            "--min-pa", str(args.min_pa),
            "--min-ip", str(args.min_ip),
            "--fantasy-outcomes-mode", str(args.fantasy_outcomes_mode),
            "--fantasy-outcomes-dir", str(args.fantasy_outcomes_dir),
        ]
        subprocess.run(cmd, check=True)

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="build_dashboard")
    ap.add_argument("--tags", nargs="+", default=None,
                    help="Season tags to include (e.g. 2017 2018 2019 2020 2021). If omitted, all complete season triplets in data/precomputed are discovered automatically.")
    ap.add_argument("--precomputed-dir", type=Path, default=Path("data") / "precomputed")
    ap.add_argument("--raw-dir", type=Path, default=Path("data") / "raw_sample",
                    help="Directory containing full raw Statcast CSVs. Exact files like statcast_2017.csv / Statcast_2018.csv are auto-detected; *_sample.csv is ignored.")
    ap.add_argument("--no-auto-precompute", action="store_true",
                    help="Disable automatic precompute from local raw CSVs when seasons or time-window JSON are missing.")
    ap.add_argument("--min-pa", type=int, default=50, help="Minimum PA used if auto-precomputing from raw CSVs.")
    ap.add_argument("--min-ip", type=float, default=20.0, help="Minimum IP used if auto-precomputing from raw CSVs.")
    ap.add_argument("--strict-tags", action="store_true",
                    help="Fail if any requested season is missing instead of building the seasons that exist.")
    ap.add_argument("--fantasy-outcomes-mode", choices=["auto", "local", "fetch", "off"], default="auto",
                    help="Passed to auto-precompute: enrich R/RBI/SB/slash stats from season batting outcomes where possible.")
    ap.add_argument("--fantasy-outcomes-dir", type=Path, default=Path("data") / "fantasy_outcomes",
                    help="Directory for local/cached season batting outcome CSVs used during auto-precompute.")
    ap.add_argument("--output", type=Path, default=Path("outputs") / "never_lucky_dashboard.html")
    args = ap.parse_args(argv)

    d = args.precomputed_dir
    args.output.parent.mkdir(parents=True, exist_ok=True)

    raw_files = _discover_raw_files(args.raw_dir)
    pre_tags = _discover_tags(d)
    if args.tags:
        tags = args.tags
    else:
        # Include both already-built seasons and full raw seasons we can build now.
        tags = sorted(set(pre_tags) | set(raw_files), key=lambda t: (0, int(t)) if re.fullmatch(r"\d+", t) else (1, t))
    if not tags:
        raise SystemExit(f"No complete precomputed seasons found in {d}, and no full raw Statcast files found in {args.raw_dir}. Expected hitters_<tag>.csv/pitchers_<tag>.csv/rosters_<tag>.csv or raw files like Statcast_2021.csv.")
    if args.tags is None:
        built = ', '.join(pre_tags) if pre_tags else 'none'
        raw = ', '.join(sorted(raw_files, key=lambda t: int(t))) if raw_files else 'none'
        print(f"  discovered precomputed seasons: {built}")
        print(f"  discovered raw seasons: {raw}")

    _ensure_precomputed_from_raw(args, tags, raw_files)

    seasons = []
    missing = []
    for tag in tags:
        h = d / f"hitters_{tag}.csv"
        p = d / f"pitchers_{tag}.csv"
        r = d / f"rosters_{tag}.csv"
        if not (h.exists() and p.exists() and r.exists()):
            msg = f"{tag}: missing one of {h.name}/{p.name}/{r.name}"
            missing.append(msg)
            print(f"  skip {msg}")
            continue
        bundle = PrecomputedCSVSource.from_paths(hitters=h, pitchers=p, rosters=r,
                                                 source_name=f"precomputed-{tag}").load()
        result = RotoScorer(DEFAULT_CATEGORIES).score(bundle)
        comparison = PlayerValueModel(DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES).compare(bundle)
        windows = _load_leaderboard_windows(d, tag)
        seasons.append(extract_season(tag, result, comparison, bundle.hitters, bundle.pitchers, windows))
        win_note = " + time windows" if windows else ""
        print(f"  added {tag}: {len(bundle.hitters)} hitters, {len(bundle.pitchers)} pitchers{win_note}")

    if missing and args.strict_tags:
        raise SystemExit("Missing requested seasons:\n  " + "\n  ".join(missing))

    if not seasons:
        raise SystemExit("No seasons found. Build precomputed files first with "
                         "scripts/build_precomputed.py.")

    path = build_multi_season_dashboard(seasons, args.output)
    print(f"\nDashboard written to: {path.resolve()}")
    print(f"Seasons included: {', '.join(s.tag for s in seasons)}")
    print("Open it in any browser — self-contained, no server needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
