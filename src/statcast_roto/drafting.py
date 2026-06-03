"""
drafting.py
===========

Utility to build a league roster from a player pool via a snake draft. Useful
for demos and tests: given aggregated hitters/pitchers, deal out a balanced
N-team league so the scoring engine has a self-consistent set of rosters.

This is a *convenience* for generating example leagues; a real league would
supply its own rosters CSV (team, side, player_id).
"""

from __future__ import annotations

import pandas as pd


def snake_draft_rosters(
    hitters: pd.DataFrame,
    pitchers: pd.DataFrame,
    *,
    n_teams: int = 10,
    hitters_per_team: int = 9,
    pitchers_per_team: int = 7,
    hitter_rank_col: str = "barrels",
    pitcher_rank_col: str = "k",
    team_prefix: str = "Team",
) -> pd.DataFrame:
    """Deal a balanced league via snake draft and return a rosters DataFrame.

    Players are ranked by `hitter_rank_col` / `pitcher_rank_col` (descending)
    and dealt in snake order (1..N, N..1, ...) so talent is spread evenly.

    Returns a DataFrame with columns: team, side, player_id.
    Raises if the pool is too small for the requested league size.
    """
    need_h = n_teams * hitters_per_team
    need_p = n_teams * pitchers_per_team
    if len(hitters) < need_h:
        raise ValueError(f"Need {need_h} hitters, pool has {len(hitters)}.")
    if len(pitchers) < need_p:
        raise ValueError(f"Need {need_p} pitchers, pool has {len(pitchers)}.")

    hpool = hitters.nlargest(need_h, hitter_rank_col).reset_index(drop=True)
    ppool = pitchers.nlargest(need_p, pitcher_rank_col).reset_index(drop=True)

    rows: list[dict] = []

    def _deal(pool: pd.DataFrame, per_team: int, side: str) -> None:
        idx = 0
        for rnd in range(per_team):
            order = range(n_teams) if rnd % 2 == 0 else reversed(range(n_teams))
            for t in order:
                if idx < len(pool):
                    rows.append({
                        "team": f"{team_prefix} {t + 1:02d}",
                        "side": side,
                        "player_id": int(pool.iloc[idx]["player_id"]),
                    })
                    idx += 1

    _deal(hpool, hitters_per_team, "hitting")
    _deal(ppool, pitchers_per_team, "pitching")
    return pd.DataFrame(rows)
