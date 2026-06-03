"""Rotisserie aggregation and standings logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from .categories import DEFAULT_CATEGORIES, Category
from .schemas import DataBundle


@dataclass(slots=True)
class RotoResult:
    """Outputs from a roto scoring run."""

    standings: pd.DataFrame
    category_values: pd.DataFrame
    category_points: pd.DataFrame
    roster_player_stats: pd.DataFrame


class RotoScorer:
    """Score teams using classic roto points across configurable categories."""

    def __init__(self, categories: Iterable[Category] = DEFAULT_CATEGORIES) -> None:
        self.categories = tuple(categories)
        if not self.categories:
            raise ValueError("At least one category is required")

    def score(self, bundle: DataBundle) -> RotoResult:
        """Aggregate roster stats, rank categories, and return standings."""
        bundle.validate()
        roster_stats = self._join_rosters_to_players(bundle)
        category_values = self._team_category_values(roster_stats)
        category_points = self._category_points(category_values)
        standings = self._standings(category_points)
        return RotoResult(
            standings=standings,
            category_values=category_values,
            category_points=category_points,
            roster_player_stats=roster_stats,
        )

    def _join_rosters_to_players(self, bundle: DataBundle) -> pd.DataFrame:
        hitters = bundle.hitters.copy()
        pitchers = bundle.pitchers.copy()
        hitters["side"] = "hitting"
        pitchers["side"] = "pitching"
        players = pd.concat([hitters, pitchers], ignore_index=True, sort=False)
        merged = bundle.rosters.merge(players, on=["player_id", "side"], how="left", validate="many_to_one")
        missing = merged[merged["player_name"].isna()][["team", "side", "player_id"]]
        if not missing.empty:
            raise ValueError(
                "Roster contains player IDs missing from player tables:\n"
                + missing.to_string(index=False)
            )
        return merged

    def _team_category_values(self, roster_stats: pd.DataFrame) -> pd.DataFrame:
        teams = sorted(roster_stats["team"].unique())
        values = pd.DataFrame(index=teams)
        values.index.name = "team"

        for category in self.categories:
            side_stats = roster_stats[roster_stats["side"] == category.side]
            if category.stat not in side_stats.columns:
                raise ValueError(f"Missing stat column {category.stat!r} for category {category.key!r}")
            if category.kind == "counting":
                series = side_stats.groupby("team")[category.stat].sum(min_count=1)
            else:
                series = self._weighted_team_rate(side_stats, category)
            values[category.key] = series.reindex(teams)

        return values.reset_index()

    @staticmethod
    def _weighted_team_rate(side_stats: pd.DataFrame, category: Category) -> pd.Series:
        if category.minimum_column and category.minimum_column in side_stats.columns:
            weight_col = category.minimum_column
        else:
            weight_col = None

        pieces: dict[str, float] = {}
        for team, group in side_stats.groupby("team"):
            stat = pd.to_numeric(group[category.stat], errors="coerce")
            if weight_col is None:
                pieces[team] = float(stat.mean())
                continue
            weights = pd.to_numeric(group[weight_col], errors="coerce").fillna(0.0)
            valid = stat.notna() & weights.gt(0)
            if not valid.any():
                pieces[team] = np.nan
            else:
                pieces[team] = float(np.average(stat[valid], weights=weights[valid]))
        return pd.Series(pieces)

    def _category_points(self, category_values: pd.DataFrame) -> pd.DataFrame:
        points = pd.DataFrame({"team": category_values["team"]})
        n_teams = len(category_values)
        for category in self.categories:
            raw = pd.to_numeric(category_values[category.key], errors="coerce")
            # Missing values are last-place scores in either direction.
            if raw.isna().any():
                fill = raw.min() - 1 if category.higher_is_better else raw.max() + 1
                raw = raw.fillna(fill)
            rank = raw.rank(method="average", ascending=not category.higher_is_better)
            points[category.key] = n_teams + 1 - rank
        points["total"] = points[[c.key for c in self.categories]].sum(axis=1)
        return points

    @staticmethod
    def _standings(category_points: pd.DataFrame) -> pd.DataFrame:
        standings = category_points.copy()
        standings["rank"] = standings["total"].rank(method="min", ascending=False).astype(int)
        standings = standings.sort_values(["total", "team"], ascending=[False, True])
        columns = ["rank", "team", "total"] + [c for c in standings.columns if c not in {"rank", "team", "total"}]
        return standings[columns].reset_index(drop=True)


def score_roto(bundle: DataBundle, categories: Iterable[Category] = DEFAULT_CATEGORIES) -> RotoResult:
    """Convenience wrapper around :class:`RotoScorer`."""
    return RotoScorer(categories).score(bundle)
