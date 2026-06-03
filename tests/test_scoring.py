"""Tests for the rotisserie scoring engine."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from statcast_roto.categories import Category, DEFAULT_CATEGORIES
from statcast_roto.scoring import RotoScorer, score_roto
from statcast_roto.schemas import DataBundle


def _toy_bundle() -> DataBundle:
    """A tiny, hand-checkable 2-team league.

    Two hitters per team, two pitchers per team. Numbers chosen so the roto
    ranking is obvious by inspection.
    """
    hitters = pd.DataFrame([
        # Team A: big barrels + high xwOBA over lots of PA
        dict(player_id=1, player_name="A1", pa=400, batted_balls=300, pitches_seen=1500,
             barrels=40, r_plus_rbi=120, xwoba=0.400, ev90=108.0, chase_rate=0.20, sb=10,
             hr=30, r=60, rbi=60, avg=0.300),
        dict(player_id=2, player_name="A2", pa=380, batted_balls=280, pitches_seen=1400,
             barrels=35, r_plus_rbi=110, xwoba=0.380, ev90=106.0, chase_rate=0.22, sb=5,
             hr=25, r=55, rbi=55, avg=0.290),
        # Team B: weaker bats
        dict(player_id=3, player_name="B1", pa=350, batted_balls=250, pitches_seen=1300,
             barrels=10, r_plus_rbi=70, xwoba=0.300, ev90=100.0, chase_rate=0.32, sb=20,
             hr=8, r=35, rbi=35, avg=0.250),
        dict(player_id=4, player_name="B2", pa=300, batted_balls=210, pitches_seen=1100,
             barrels=8, r_plus_rbi=60, xwoba=0.290, ev90=99.0, chase_rate=0.34, sb=15,
             hr=6, r=30, rbi=30, avg=0.240),
    ])
    pitchers = pd.DataFrame([
        dict(player_id=11, player_name="AP1", ip=180, pitches=2800, batted_balls_allowed=400,
             k=240, xfip=2.80, whiff_rate=0.16, barrel_rate_allowed=0.05, qs=22,
             w=15, sv=0, era=2.70, whip=1.00),
        dict(player_id=12, player_name="AP2", ip=170, pitches=2700, batted_balls_allowed=380,
             k=210, xfip=3.10, whiff_rate=0.14, barrel_rate_allowed=0.06, qs=20,
             w=13, sv=0, era=3.10, whip=1.10),
        dict(player_id=13, player_name="BP1", ip=150, pitches=2400, batted_balls_allowed=420,
             k=120, xfip=4.50, whiff_rate=0.09, barrel_rate_allowed=0.10, qs=10,
             w=8, sv=0, era=4.60, whip=1.40),
        dict(player_id=14, player_name="BP2", ip=140, pitches=2200, batted_balls_allowed=400,
             k=110, xfip=4.80, whiff_rate=0.08, barrel_rate_allowed=0.11, qs=8,
             w=7, sv=0, era=4.90, whip=1.45),
    ])
    rosters = pd.DataFrame([
        dict(team="A", side="hitting", player_id=1),
        dict(team="A", side="hitting", player_id=2),
        dict(team="A", side="pitching", player_id=11),
        dict(team="A", side="pitching", player_id=12),
        dict(team="B", side="hitting", player_id=3),
        dict(team="B", side="hitting", player_id=4),
        dict(team="B", side="pitching", player_id=13),
        dict(team="B", side="pitching", player_id=14),
    ])
    return DataBundle(hitters, pitchers, rosters, "toy").validate()


def test_team_a_wins_most_categories_and_standings():
    """Team A is better in 10 of 11 categories (Team B is built to win SB),
    so A should still rank #1 but NOT post a perfect sweep. This verifies the
    standings sum and that a single conceded category is handled correctly."""
    result = score_roto(_toy_bundle())
    standings = result.standings.set_index("team")
    assert standings.loc["A", "rank"] == 1
    assert standings.loc["B", "rank"] == 2
    # 11 categories, 2 teams. A wins 10 (2 pts each) and loses SB (1 pt):
    #   A = 10*2 + 1 = 21 ;  B = 10*1 + 2 = 12
    assert standings.loc["A", "total"] == pytest.approx(10 * 2 + 1)
    assert standings.loc["B", "total"] == pytest.approx(10 * 1 + 2)


def test_team_b_wins_only_stolen_bases():
    """Team B was constructed with more SB; it should win exactly that cat."""
    result = score_roto(_toy_bundle())
    points = result.category_points.set_index("team")
    assert points.loc["B", "sb"] == 2.0  # B wins SB
    assert points.loc["A", "sb"] == 1.0


def test_counting_categories_sum_across_roster():
    """Barrels (counting) should equal the sum of the roster's barrels."""
    result = score_roto(_toy_bundle())
    vals = result.category_values.set_index("team")
    assert vals.loc["A", "barrels"] == 40 + 35
    assert vals.loc["B", "barrels"] == 10 + 8


def test_rate_categories_are_opportunity_weighted():
    """xwOBA (rate) should be PA-weighted across the roster, not a plain mean."""
    result = score_roto(_toy_bundle())
    vals = result.category_values.set_index("team")
    # Team A PA-weighted xwOBA = (400*.400 + 380*.380) / (400+380)
    expected = (400 * 0.400 + 380 * 0.380) / (400 + 380)
    assert vals.loc["A", "xwoba"] == pytest.approx(expected, abs=1e-6)


def test_lower_is_better_categories_invert_ranking():
    """For xFIP (lower better), the team with the lower xFIP should win the cat."""
    result = score_roto(_toy_bundle())
    points = result.category_points.set_index("team")
    # Team A has lower (better) xFIP -> should earn the 2 points.
    assert points.loc["A", "xfip"] == 2.0
    assert points.loc["B", "xfip"] == 1.0


def test_missing_roster_player_raises():
    bundle = _toy_bundle()
    bad = bundle.rosters.copy()
    bad.loc[len(bad)] = dict(team="A", side="hitting", player_id=999)
    broken = DataBundle(bundle.hitters, bundle.pitchers, bad, "broken")
    with pytest.raises(ValueError, match="missing"):
        score_roto(broken)


def test_empty_categories_rejected():
    with pytest.raises(ValueError):
        RotoScorer([])


def test_category_direction_property():
    hi = Category("x", "X", "hitting", "x", True, "counting")
    lo = Category("y", "Y", "hitting", "y", False, "counting")
    assert hi.direction == 1
    assert lo.direction == -1
