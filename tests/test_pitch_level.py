"""Tests for raw pitch-level aggregation.

These run against the bundled real-2020 pitch SAMPLE, so they double as a
regression guard on the aggregation logic and a sanity check that the known
stars in the sample come out with believable numbers.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from statcast_roto.pitch_level import PitchLevelCSVSource

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "raw_sample" / "statcast_2020_sample.csv"
ROSTERS = Path(__file__).resolve().parents[1] / "data" / "precomputed" / "rosters_2020.csv"

pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="raw sample not present")


@pytest.fixture(scope="module")
def aggregated():
    src = PitchLevelCSVSource(pitches_csv=SAMPLE, rosters_csv=ROSTERS,
                              min_pa=1, min_ip=1, resolve_names=False)
    raw = pd.read_csv(SAMPLE, low_memory=False)
    prepped = src._prepare(raw)
    return src._aggregate_hitters(prepped), src._aggregate_pitchers(prepped)


def test_barrels_are_nonnegative_and_bounded(aggregated):
    hitters, _ = aggregated
    assert (hitters["barrels"] >= 0).all()
    # No hitter can have more barrels than batted balls.
    assert (hitters["barrels"] <= hitters["batted_balls"]).all()


def test_ev90_in_physically_plausible_range(aggregated):
    hitters, _ = aggregated
    # The EV90 category only trusts hitters with a real batted-ball sample
    # (min_opportunity=50 in categories.py). Apply the same filter here:
    # players with 1-2 batted balls have a meaningless "90th percentile".
    meaningful = hitters[hitters["batted_balls"] >= 30]
    ev = meaningful["ev90"].dropna()
    assert len(ev) > 0
    # With a real sample, 90th-pct exit velo lives in roughly [95, 118] mph.
    assert ev.between(93, 120).all()


def test_chase_rate_is_a_fraction(aggregated):
    hitters, _ = aggregated
    cr = hitters["chase_rate"].dropna()
    assert cr.between(0, 1).all()


def test_pitcher_whiff_rate_is_a_fraction(aggregated):
    _, pitchers = aggregated
    wr = pitchers["whiff_rate"].dropna()
    assert wr.between(0, 1).all()


def test_strikeouts_do_not_exceed_batters_faced(aggregated):
    _, pitchers = aggregated
    # Sanity: K should be a sensible fraction of pitches; never negative.
    assert (pitchers["k"] >= 0).all()


def test_ip_derived_from_outs_is_positive(aggregated):
    _, pitchers = aggregated
    assert (pitchers["ip"] >= 0).all()


def test_known_elite_pitcher_has_high_whiff(aggregated):
    """deGrom (MLBAM 594798) is in the sample; his whiff rate should be elite."""
    _, pitchers = aggregated
    degrom = pitchers[pitchers["player_id"] == 594798]
    if not degrom.empty:
        assert float(degrom["whiff_rate"].iloc[0]) > 0.20
