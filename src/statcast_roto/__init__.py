"""
statcast_roto
=============

A fantasy baseball rotisserie engine scored on Statcast / expected-stat
categories instead of luck-polluted traditional stats.

The thesis: traditional roto categories (HR, R, RBI, SB, AVG / W, K, SV, ERA,
WHIP) measure *outcomes*, which are contaminated by luck, park, defense, and
lineup context. This engine scores teams on *skill/process* metrics -- barrels,
xwOBA, 90th-pct exit velocity, chase rate, xFIP, whiff rate, barrel% allowed --
blending counting stats (volume) with rate/expected stats (per-PA quality).

Quick start
-----------
    from statcast_roto import PrecomputedCSVSource, score_roto
    bundle = PrecomputedCSVSource().load()      # real 2020 data, bundled
    result = score_roto(bundle)
    print(result.standings)

Build from raw pitch data instead:
    from statcast_roto import PitchLevelCSVSource
    bundle = PitchLevelCSVSource("path/to/statcast.csv", "rosters.csv").load()
"""

from .categories import (
    DEFAULT_CATEGORIES,
    TRADITIONAL_CATEGORIES,
    HITTING_CATEGORIES,
    PITCHING_CATEGORIES,
    Category,
    categories_for,
    category_by_key,
)
from .schemas import DataBundle
from .scoring import RotoScorer, RotoResult, score_roto
from .value import PlayerValueModel, ValueComparison
from .sources import DataSource, PrecomputedCSVSource
from .pitch_level import PitchLevelCSVSource
from .drafting import snake_draft_rosters

__all__ = [
    "Category",
    "DEFAULT_CATEGORIES",
    "TRADITIONAL_CATEGORIES",
    "HITTING_CATEGORIES",
    "PITCHING_CATEGORIES",
    "categories_for",
    "category_by_key",
    "DataBundle",
    "RotoScorer",
    "RotoResult",
    "score_roto",
    "PlayerValueModel",
    "ValueComparison",
    "DataSource",
    "PrecomputedCSVSource",
    "PitchLevelCSVSource",
    "snake_draft_rosters",
]

__version__ = "1.0.0"
