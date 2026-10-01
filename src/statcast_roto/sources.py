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
        "approximations derived from pitch rows. R/RBI/SB/slash stats should "
        "be enriched from a season-level batting table when available. "
        "See docs/design_memo.md for the full accounting.",
    ))

    def load(self) -> DataBundle:
        hitters = read_csv(self.directory / self.hitters_file, label="hitters")
        pitchers = read_csv(self.directory / self.pitchers_file, label="pitchers")
        rosters = read_csv(self.directory / self.rosters_file, label="rosters")
        return DataBundle(hitters, pitchers, rosters, self.source_name, self.notes).validate()

    @classmethod
    def from_paths(
        cls,
        hitters: str | Path,
        pitchers: str | Path,
        rosters: str | Path,
        *,
        source_name: str = "precomputed-custom",
    ) -> "PrecomputedCSVSource":
        """Build a source from three explicit file paths (any location).

        Lets you point the engine at precomputed files you generated yourself
        (e.g. via scripts/build_precomputed.py for a different season) rather
        than the bundled defaults.
        """
        hitters, pitchers, rosters = Path(hitters), Path(pitchers), Path(rosters)
        # All three must share a parent for the directory/filename split, so we
        # validate existence here and load by absolute path in a tiny subclass
        # instance via the directory+name fields.
        for p, lbl in [(hitters, "hitters"), (pitchers, "pitchers"), (rosters, "rosters")]:
            if not p.exists():
                raise FileNotFoundError(f"Could not find {lbl} CSV: {p}")
        # Use each file's own parent dir; load() joins directory/file, so set
        # directory per-file by reading directly instead. Simplest: a thin
        # instance whose load() reads the absolute paths.
        inst = cls(
            directory=hitters.parent,
            hitters_file=hitters.name,
            pitchers_file=pitchers.name,
            rosters_file=rosters.name,
            source_name=source_name,
            notes=(
                "Custom precomputed tables (user-generated).",
                "If aggregated from raw pitch data, the same honesty caveats "
                "apply: xwOBA/xFIP/QS are approximations; R/RBI/SB/slash "
                "need season batting enrichment for official fantasy outcomes. "
                "See docs/design_memo.md.",
            ),
        )
        # If pitchers/rosters live in a different folder than hitters, fall back
        # to absolute reads.
        if not (inst.directory / inst.pitchers_file) == pitchers or \
           not (inst.directory / inst.rosters_file) == rosters:
            return _ExplicitPathSource(hitters, pitchers, rosters, source_name)
        return inst


@dataclass(frozen=True, slots=True)
class _ExplicitPathSource:
    """Fallback source when the three CSVs live in different directories."""

    hitters_path: Path
    pitchers_path: Path
    rosters_path: Path
    source_name: str = "precomputed-custom"

    def load(self) -> DataBundle:
        hitters = read_csv(self.hitters_path, label="hitters")
        pitchers = read_csv(self.pitchers_path, label="pitchers")
        rosters = read_csv(self.rosters_path, label="rosters")
        notes = ("Custom precomputed tables (user-generated, mixed dirs).",)
        return DataBundle(hitters, pitchers, rosters, self.source_name, notes).validate()
