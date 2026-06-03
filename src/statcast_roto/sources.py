"""
sources.py
==========

Data-source backends. The scoring engine consumes a normalized `DataBundle`;
sources are responsible only for producing one. This decoupling means the
engine never knows or cares whether rows came from precomputed CSVs, raw
pitch-level aggregation, or (later) a live/keyed feed.

Backends provided
------------------
* PrecomputedCSVSource : load already-aggregated hitter/pitcher/roster CSVs
                         (the fast default; what ships in data/precomputed/).
* PitchLevelCSVSource  : aggregate a RAW pitch-level Statcast CSV from scratch
                         (in pitch_level.py; the "from the source" path).

Both satisfy the same `DataSource` protocol and return a validated bundle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .schemas import DataBundle, read_csv

# Repo-root-relative default data locations.
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PRECOMPUTED_DIR = PACKAGE_ROOT / "data" / "precomputed"


class DataSource(Protocol):
    """Interface implemented by every source backend."""

    def load(self) -> DataBundle: ...


@dataclass(frozen=True, slots=True)
class PrecomputedCSVSource:
    """Load already-aggregated hitter, pitcher, and roster CSVs.

    This is the fast, dependency-free default. The bundled files in
    data/precomputed/ were produced by aggregating a real season of
    pitch-level Statcast data (see scripts/build_precomputed in the README),
    with player names resolved via the Chadwick register.
    """

    directory: Path = PRECOMPUTED_DIR
    hitters_file: str = "hitters_2020.csv"
    pitchers_file: str = "pitchers_2020.csv"
    rosters_file: str = "rosters_2020.csv"
    source_name: str = "precomputed-2020"
    notes: tuple[str, ...] = field(default=(
        "Aggregated from real 2020 pitch-level Statcast data.",
        "xwOBA is a per-pitch mean approximation; xFIP and QS are transparent "
        "approximations derived from pitch rows; R and SB are not fully "
        "recoverable from pitch data and are reported as 0 / approximate. "
        "See docs/design_memo.md for the full accounting.",
    ))

    def load(self) -> DataBundle:
        hitters = read_csv(self.directory / self.hitters_file, label="hitters")
        pitchers = read_csv(self.directory / self.pitchers_file, label="pitchers")
        rosters = read_csv(self.directory / self.rosters_file, label="rosters")
        return DataBundle(hitters, pitchers, rosters, self.source_name, self.notes).validate()
