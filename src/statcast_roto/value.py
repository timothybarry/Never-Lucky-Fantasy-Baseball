"""Player-value utilities for showing how Statcast scoring reshapes rankings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from .categories import DEFAULT_CATEGORIES, TRADITIONAL_CATEGORIES, Category
from .schemas import DataBundle


@dataclass(slots=True)
class ValueComparison:
    """Player values under Statcast and traditional objective functions."""

    player_values: pd.DataFrame
    biggest_statcast_bumps: pd.DataFrame
    biggest_traditional_bumps: pd.DataFrame


class PlayerValueModel:
    """Equal-weight category z-score model.

    This is not pretending to be a market-accurate auction calculator. It is a
    transparent diagnostic: which players move when the objective function moves
    from outcome stats to process/statcast categories?
    """

    def __init__(
        self,
        statcast_categories: Iterable[Category] = DEFAULT_CATEGORIES,
        traditional_categories: Iterable[Category] = TRADITIONAL_CATEGORIES,
    ) -> None:
        self.statcast_categories = tuple(statcast_categories)
        self.traditional_categories = tuple(traditional_categories)

    def compare(self, bundle: DataBundle, *, top_n: int = 15) -> ValueComparison:
        bundle.validate()
        hitters = bundle.hitters.assign(side="hitting")
        pitchers = bundle.pitchers.assign(side="pitching")
        players = pd.concat([hitters, pitchers], ignore_index=True, sort=False)

        statcast = self._score_players(players, self.statcast_categories, "statcast_value")
        traditional = self._score_players(players, self.traditional_categories, "traditional_value")

        base_cols = ["player_id", "player_name", "side"]
        merged = statcast[base_cols + ["statcast_value"]].merge(
            traditional[base_cols + ["traditional_value"]], on=base_cols, how="outer"
        )
        merged["value_delta"] = merged["statcast_value"] - merged["traditional_value"]
        merged = merged.sort_values("statcast_value", ascending=False).reset_index(drop=True)
        merged["statcast_rank"] = merged["statcast_value"].rank(method="min", ascending=False).astype("Int64")
        merged["traditional_rank"] = merged["traditional_value"].rank(method="min", ascending=False).astype("Int64")
        merged["rank_delta"] = merged["traditional_rank"] - merged["statcast_rank"]

        return ValueComparison(
            player_values=merged,
            biggest_statcast_bumps=merged.sort_values("value_delta", ascending=False).head(top_n).reset_index(drop=True),
            biggest_traditional_bumps=merged.sort_values("value_delta", ascending=True).head(top_n).reset_index(drop=True),
        )

    @staticmethod
    def _score_players(players: pd.DataFrame, categories: tuple[Category, ...], output_col: str) -> pd.DataFrame:
        pieces = []
        for side in ["hitting", "pitching"]:
            side_players = players[players["side"] == side].copy()
            side_categories = [c for c in categories if c.side == side]
            if side_players.empty or not side_categories:
                continue

            z_parts = []
            for category in side_categories:
                if category.stat not in side_players.columns:
                    continue
                values = pd.to_numeric(side_players[category.stat], errors="coerce")
                qualified = pd.Series(True, index=side_players.index)
                if category.kind == "rate" and category.minimum_column in side_players.columns:
                    qualified = pd.to_numeric(side_players[category.minimum_column], errors="coerce").fillna(0) >= category.minimum
                transformed = values * category.direction
                mean = transformed[qualified].mean()
                std = transformed[qualified].std(ddof=0)
                if pd.isna(std) or std == 0:
                    z = pd.Series(0.0, index=side_players.index)
                else:
                    z = (transformed - mean) / std
                # Do not let a 9-PA monster top a rate leaderboard. Unqualified
                # rate entries get replacement-level credit for that category.
                if category.kind == "rate":
                    z = z.where(qualified, z[qualified].quantile(0.15) if qualified.any() else 0.0)
                z_parts.append(z.rename(category.key))

            if not z_parts:
                side_players[output_col] = np.nan
            else:
                z_frame = pd.concat(z_parts, axis=1)
                side_players[output_col] = z_frame.mean(axis=1)
            pieces.append(side_players[["player_id", "player_name", "side", output_col]])
        return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def compare_player_values(bundle: DataBundle, *, top_n: int = 15) -> ValueComparison:
    """Convenience wrapper for the default value comparison."""
    return PlayerValueModel().compare(bundle, top_n=top_n)
