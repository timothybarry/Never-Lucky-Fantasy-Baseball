"""Tests for the Statcast-vs-traditional player value model."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from statcast_roto.sources import PrecomputedCSVSource
from statcast_roto.value import PlayerValueModel
from statcast_roto.categories import DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES

DATA = Path(__file__).resolve().parents[1] / "data" / "precomputed" / "hitters_2020.csv"
pytestmark = pytest.mark.skipif(not DATA.exists(), reason="precomputed data not present")


@pytest.fixture(scope="module")
def comparison():
    bundle = PrecomputedCSVSource().load()
    return PlayerValueModel(DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES).compare(bundle)


def test_value_comparison_has_expected_columns(comparison):
    cols = set(comparison.player_values.columns)
    for required in {"player_name", "side", "statcast_value", "traditional_value",
                     "value_delta", "rank_delta"}:
        assert required in cols


def test_bumps_are_sorted(comparison):
    # Biggest statcast bumps should be sorted by value_delta descending.
    deltas = comparison.biggest_statcast_bumps["value_delta"].tolist()
    assert deltas == sorted(deltas, reverse=True)


def test_statcast_and_traditional_bumps_are_opposite_ends(comparison):
    top_statcast = comparison.biggest_statcast_bumps["value_delta"].iloc[0]
    top_trad = comparison.biggest_traditional_bumps["value_delta"].iloc[0]
    # By construction, statcast risers have positive delta, traditional negative.
    assert top_statcast > 0
    assert top_trad < 0
