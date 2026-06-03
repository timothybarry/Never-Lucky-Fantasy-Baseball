"""Small matplotlib chart helpers for the analysis deliverable."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def save_standings_chart(standings: pd.DataFrame, output_path: str | Path) -> Path:
    """Save a horizontal bar chart of total roto points."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plot_df = standings.sort_values("total", ascending=True)
    fig, ax = plt.subplots(figsize=(10, max(4, len(plot_df) * 0.45)))
    ax.barh(plot_df["team"], plot_df["total"])
    ax.set_xlabel("Roto points")
    ax.set_ylabel("Team")
    ax.set_title("Statcast Fantasy Roto Standings")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def save_value_delta_chart(value_df: pd.DataFrame, output_path: str | Path, *, top_n: int = 12) -> Path:
    """Save a chart of biggest Statcast-vs-traditional player value movers."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    plot_df = value_df.reindex(value_df["value_delta"].abs().sort_values(ascending=False).index).head(top_n)
    plot_df = plot_df.sort_values("value_delta")
    labels = plot_df["player_name"] + " (" + plot_df["side"].str[0].str.upper() + ")"
    fig, ax = plt.subplots(figsize=(10, max(4, len(plot_df) * 0.42)))
    ax.barh(labels, plot_df["value_delta"])
    ax.axvline(0, linewidth=1)
    ax.set_xlabel("Statcast value minus traditional value")
    ax.set_title("Who changes when the scoring objective changes?")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path
