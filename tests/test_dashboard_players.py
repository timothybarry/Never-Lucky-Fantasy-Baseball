from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from statcast_roto.categories import DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES
from statcast_roto.dashboard import build_multi_season_dashboard, extract_season
from statcast_roto.scoring import RotoScorer
from statcast_roto.sources import PrecomputedCSVSource
from statcast_roto.value import PlayerValueModel


def test_dashboard_includes_players_tab_payload(tmp_path):
    root = Path(__file__).resolve().parents[1]
    bundle = PrecomputedCSVSource(
        directory=root / "data" / "precomputed",
        hitters_file="hitters_2020.csv",
        pitchers_file="pitchers_2020.csv",
        rosters_file="rosters_2020.csv",
    ).load()
    result = RotoScorer(DEFAULT_CATEGORIES).score(bundle)
    comparison = PlayerValueModel(DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES).compare(bundle)
    season = extract_season("2020", result, comparison, bundle.hitters, bundle.pitchers)

    out = build_multi_season_dashboard([season], tmp_path / "dashboard.html")
    html = out.read_text(encoding="utf-8")

    assert "Players" in html
    assert "Signal Score" in html
    assert '"players"' in html
    assert '"percentiles"' in html


def test_dashboard_includes_leaderboard_time_filter(tmp_path):
    root = Path(__file__).resolve().parents[1]
    bundle = PrecomputedCSVSource(
        directory=root / "data" / "precomputed",
        hitters_file="hitters_2020.csv",
        pitchers_file="pitchers_2020.csv",
        rosters_file="rosters_2020.csv",
    ).load()
    result = RotoScorer(DEFAULT_CATEGORIES).score(bundle)
    comparison = PlayerValueModel(DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES).compare(bundle)
    windows = {
        "timeframes": {
            "last7": {
                "label": "Last 7 days",
                "start": "2020-09-21",
                "end": "2020-09-27",
                "n_pitches": 123,
                "leaderboards": {"hr": [["Test Hitter", 3]]},
            }
        }
    }
    season = extract_season("2020", result, comparison, bundle.hitters, bundle.pitchers, windows)

    out = build_multi_season_dashboard([season], tmp_path / "dashboard.html")
    html = out.read_text(encoding="utf-8")

    assert "timeSel" in html
    assert "Last 7 days" in html
    assert "leaderboard_windows" in html


def test_build_dashboard_discovers_full_raw_seasons_but_ignores_samples(tmp_path):
    import importlib.util
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_dashboard.py"
    spec = importlib.util.spec_from_file_location("build_dashboard_script", script)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    raw_dir = tmp_path / "raw_sample"
    raw_dir.mkdir()
    (raw_dir / "statcast_2017.csv").write_text("game_date\n", encoding="utf-8")
    (raw_dir / "Statcast_2018.csv").write_text("game_date\n", encoding="utf-8")
    (raw_dir / "statcast_2020_sample.csv").write_text("game_date\n", encoding="utf-8")
    (raw_dir / "notes.csv").write_text("x\n", encoding="utf-8")

    found = mod._discover_raw_files(raw_dir)
    assert sorted(found) == ["2017", "2018"]
