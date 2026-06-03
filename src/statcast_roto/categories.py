"""
categories.py
=============

The scoring categories, defined as declarative data. In a fantasy league the
**categories ARE the objective function**: they define what "good" means and
therefore what every manager optimizes toward. This file is intentionally the
most readable in the project because the choice of categories is the entire
thesis of a Statcast-scored league.

Design principles encoded here
------------------------------
1. Blend COUNTING and RATE stats. Counting stats (barrels, K, R+RBI) reward
   volume and the season-long grind; rate/expected stats (xwOBA, chase%, xFIP)
   reward per-opportunity quality/skill. A good slate rewards both.
2. Every category measures a DIFFERENT skill (no redundancy).
3. Rate categories carry a minimum-opportunity threshold so a tiny-sample
   waiver legend cannot top a rate category.
4. `higher_is_better` is explicit, so lower-is-better stats (chase%, xFIP,
   barrel% allowed) are handled by the engine without special-casing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

Side = Literal["hitting", "pitching"]
Kind = Literal["counting", "rate"]


@dataclass(frozen=True, slots=True)
class Category:
    """A single rotisserie scoring category.

    key:               stable machine name + standings column label
    label:             human-facing label for tables/charts
    side:              "hitting" or "pitching"
    stat:              column in the normalized stats table to score
    higher_is_better:  False for chase%, xFIP, barrel% allowed
    kind:              "counting" (summed) or "rate" (opportunity-weighted)
    minimum_column:    PA/IP column used to qualify a rate stat per player
    minimum:           min PA/IP before a player's rate value is trusted
    description:       why this category exists (the design rationale)
    fmt:               display format string
    """

    key: str
    label: str
    side: Side
    stat: str
    higher_is_better: bool
    kind: Kind
    minimum_column: str | None = None
    minimum: float = 0.0
    description: str = ""
    fmt: str = "{:.0f}"

    @property
    def direction(self) -> int:
        """+1 if higher is better, -1 if lower is better."""
        return 1 if self.higher_is_better else -1


# ---------------------------------------------------------------------------
# STATCAST SLATE  (the point of the project)
# ---------------------------------------------------------------------------
HITTING_CATEGORIES: tuple[Category, ...] = (
    Category("barrels", "Barrels", "hitting", "barrels", True, "counting",
             description="Power-quality counting stat: HR-like accumulation "
                         "that rewards elite contact even when it doesn't clear "
                         "the wall. Replaces HR.",
             fmt="{:.0f}"),
    Category("r_plus_rbi", "R+RBI", "hitting", "r_plus_rbi", True, "counting",
             description="Volume/lineup-context lane that keeps playing time "
                         "and roster role valuable.",
             fmt="{:.0f}"),
    Category("xwoba", "xwOBA", "hitting", "xwoba", True, "rate",
             minimum_column="pa", minimum=100,
             description="Overall expected offensive quality -- the anchor "
                         "rate, stripped of luck and defense.",
             fmt="{:.3f}"),
    Category("ev90", "90th-pct EV", "hitting", "ev90", True, "rate",
             minimum_column="batted_balls", minimum=50,
             description="Raw power CEILING. Sticky year-to-year and a strong "
                         "predictor of power output.",
             fmt="{:.1f}"),
    Category("chase_rate", "Chase%", "hitting", "chase_rate", False, "rate",
             minimum_column="pitches_seen", minimum=300,
             description="Plate-discipline lane (lower is better). Makes swing "
                         "decisions a draftable skill.",
             fmt="{:.1%}"),
    Category("sb", "SB", "hitting", "sb", True, "counting",
             description="Speed lane so the slate isn't only power & contact.",
             fmt="{:.0f}"),
)

PITCHING_CATEGORIES: tuple[Category, ...] = (
    Category("k", "K", "pitching", "k", True, "counting",
             description="Classic volume strikeout lane.",
             fmt="{:.0f}"),
    Category("xfip", "xFIP", "pitching", "xfip", False, "rate",
             minimum_column="ip", minimum=25,
             description="Run-prevention SKILL (lower is better). Strips out "
                         "HR/park/defense noise. Replaces ERA.",
             fmt="{:.2f}"),
    Category("whiff_rate", "Whiff%", "pitching", "whiff_rate", True, "rate",
             minimum_column="pitches", minimum=400,
             description="Stuff / swing-and-miss skill.",
             fmt="{:.1%}"),
    Category("barrel_rate_allowed", "Barrel% Allowed", "pitching",
             "barrel_rate_allowed", False, "rate",
             minimum_column="batted_balls_allowed", minimum=60,
             description="Contact management (lower is better) -- the hitting "
                         "mirror on the pitching side.",
             fmt="{:.1%}"),
    Category("qs", "QS", "pitching", "qs", True, "counting",
             description="Durability/role lane so low-inning relievers can't "
                         "dominate every pitcher slot.",
             fmt="{:.0f}"),
)

DEFAULT_CATEGORIES: tuple[Category, ...] = HITTING_CATEGORIES + PITCHING_CATEGORIES


# ---------------------------------------------------------------------------
# TRADITIONAL SLATE  (for the side-by-side "how would values differ" analysis)
# ---------------------------------------------------------------------------
TRADITIONAL_HITTING_CATEGORIES: tuple[Category, ...] = (
    Category("hr", "HR", "hitting", "hr", True, "counting", fmt="{:.0f}"),
    Category("r", "R", "hitting", "r", True, "counting", fmt="{:.0f}"),
    Category("rbi", "RBI", "hitting", "rbi", True, "counting", fmt="{:.0f}"),
    Category("sb", "SB", "hitting", "sb", True, "counting", fmt="{:.0f}"),
    Category("avg", "AVG", "hitting", "avg", True, "rate", "pa", 100, fmt="{:.3f}"),
)
TRADITIONAL_PITCHING_CATEGORIES: tuple[Category, ...] = (
    Category("w", "W", "pitching", "w", True, "counting", fmt="{:.0f}"),
    Category("k", "K", "pitching", "k", True, "counting", fmt="{:.0f}"),
    Category("sv", "SV", "pitching", "sv", True, "counting", fmt="{:.0f}"),
    Category("era", "ERA", "pitching", "era", False, "rate", "ip", 25, fmt="{:.2f}"),
    Category("whip", "WHIP", "pitching", "whip", False, "rate", "ip", 25, fmt="{:.2f}"),
)
TRADITIONAL_CATEGORIES: tuple[Category, ...] = (
    TRADITIONAL_HITTING_CATEGORIES + TRADITIONAL_PITCHING_CATEGORIES
)


def categories_for(side: Side | None = None, *, statcast: bool = True) -> tuple[Category, ...]:
    """Return categories for one side, or the full league."""
    cats = DEFAULT_CATEGORIES if statcast else TRADITIONAL_CATEGORIES
    if side is None:
        return cats
    return tuple(c for c in cats if c.side == side)


def category_by_key(key: str, categories: Iterable[Category] = DEFAULT_CATEGORIES) -> Category:
    """Find a category by key with a helpful error."""
    for c in categories:
        if c.key == key:
            return c
    available = ", ".join(c.key for c in categories)
    raise KeyError(f"Unknown category {key!r}. Available: {available}")
