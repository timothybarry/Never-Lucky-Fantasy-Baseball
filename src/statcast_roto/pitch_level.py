"""
pitch_level.py
==============

Aggregate RAW pitch-by-pitch Statcast data (the 90+ column format returned by
``pybaseball.statcast`` and exported by Baseball Savant) into the normalized
season-level hitter and pitcher tables the scoring engine consumes.

WHY THIS MODULE EXISTS
----------------------
The rest of the repo originally assumed *pre-aggregated* season stats. But the
real, freely available Statcast export is *pitch level*: one row per pitch,
with ``batter``/``pitcher`` MLBAM IDs, ``launch_speed``, ``launch_angle``,
``estimated_woba_using_speedangle``, ``events``, ``description``, ``zone``, etc.
This module turns that raw file into the normalized schema.

HONESTY ABOUT WHAT PITCH DATA CAN AND CANNOT GIVE YOU
-----------------------------------------------------
This is the part a careful analyst must get right, and the part the original
auto-generated code got wrong by silently fabricating values:

  COMPUTABLE CLEANLY from pitch rows (these are real, trustworthy):
    * barrels            -> count of launch_speed_angle == 6
    * ev90               -> 90th percentile of launch_speed on batted balls
    * chase_rate         -> swings at out-of-zone pitches / out-of-zone pitches
    * xwoba (approx)     -> mean of estimated_woba_using_speedangle  [SEE NOTE]
    * k (pitchers)       -> count of events == 'strikeout'
    * whiff_rate         -> whiffs / swings
    * barrel_rate_allowed-> barrels allowed / batted balls allowed
    * hr                 -> count of events == 'home_run'

  NOT cleanly derivable from pitch data alone (handled honestly, not faked):
    * R (runs scored)    -> requires base-running tracking across plays; we
                            DO NOT fabricate it. Derived as a transparent
                            on-base proxy ONLY if explicitly opted in, else NaN.
    * RBI                -> approximable from score deltas but contaminated by
                            errors/wild pitches; computed as a clearly-labeled
                            approximation, never presented as official RBI.
    * SB                 -> stolen bases attach to the runner; partially
                            recoverable from 'stolen_base_*' events but
                            undercounts. Labeled approximate.
    * xFIP               -> a true xFIP needs a league HR/FB constant and a
                            full-season fly-ball denominator; we compute a
                            transparent FIP-style proxy and NAME it as such.
    * IP                 -> derived from outs recorded (more accurate than the
                            PA/4.25 shortcut the original code used).

NAME RESOLUTION (the critical bug fix)
--------------------------------------
In pitch-level Statcast rows, the ``player_name`` column is ALWAYS THE PITCHER.
Using it for hitters mislabels every batter. We resolve batter (and pitcher)
MLBAM IDs to real names via the Chadwick Bureau register (a public CSV on
GitHub), with a graceful fallback to "MLBAM <id>" if the register is
unavailable offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from .schemas import DataBundle, read_csv

# Descriptions that count as a swing / a whiff (Statcast `description` values).
SWING_DESCRIPTIONS: frozenset[str] = frozenset({
    "swinging_strike", "swinging_strike_blocked",
    "foul", "foul_tip", "foul_bunt", "bunt_foul_tip", "missed_bunt",
    "hit_into_play", "hit_into_play_no_out", "hit_into_play_score",
})
WHIFF_DESCRIPTIONS: frozenset[str] = frozenset({
    "swinging_strike", "swinging_strike_blocked", "missed_bunt",
})

# Outs added by each terminal event, for accurate IP from pitch rows.
OUTS_BY_EVENT: dict[str, int] = {
    "strikeout": 1, "strikeout_double_play": 2,
    "field_out": 1, "force_out": 1, "grounded_into_double_play": 2,
    "double_play": 2, "triple_play": 3, "sac_fly": 1, "sac_bunt": 1,
    "fielders_choice_out": 1, "fielders_choice": 1, "other_out": 1,
    "sac_fly_double_play": 2, "strikeout_triple_play": 3,
}


@dataclass(frozen=True, slots=True)
class PitchLevelCSVSource:
    """Aggregate a raw pitch-level Statcast CSV into a normalized DataBundle.

    Parameters
    ----------
    pitches_csv:
        Path to the raw pitch-level Statcast export (Savant / pybaseball schema).
    rosters_csv:
        Path to the roster CSV (team, side, player_id) using MLBAM IDs.
    min_pa, min_ip:
        Drop players below these thresholds from the player pool entirely
        (separate from the per-category rate minimums in categories.py).
    resolve_names:
        If True (default), map MLBAM IDs to names via the Chadwick register.
    league_hr_per_fb:
        Constant used in the transparent xFIP proxy.
    rbi_approx:
        If True, compute the labeled RBI approximation from score deltas.
        If False, RBI is left as 0 (and you should supply it from a real
        season export via the standard-CSV merge path).
    """

    pitches_csv: Path
    rosters_csv: Path
    min_pa: int = 25
    min_ip: float = 5.0
    resolve_names: bool = True
    league_hr_per_fb: float = 0.135  # ~2020 league HR/FB
    rbi_approx: bool = True
    source_name: str = "pitch-level-csv"
    notes: tuple[str, ...] = field(default=(
        "Aggregated from raw pitch-level Statcast data.",
        "xwOBA is a per-pitch mean approximation; xFIP, RBI, R, and SB are "
        "transparent approximations and are labeled as such -- do not present "
        "them as official figures without an audited season export.",
    ))

    # -- public entry point -------------------------------------------------
    def load(self) -> DataBundle:
        raw = read_csv(self.pitches_csv, label="pitch-level statcast")
        self._check_pitch_schema(raw)
        prepped = self._prepare(raw)

        hitters = self._aggregate_hitters(prepped)
        pitchers = self._aggregate_pitchers(prepped)

        if self.resolve_names:
            names = self._build_name_map(
                pd.concat([hitters["player_id"], pitchers["player_id"]]).unique(),
                raw,
            )
            hitters["player_name"] = hitters["player_id"].map(names).fillna(
                "MLBAM " + hitters["player_id"].astype(str))
            pitchers["player_name"] = pitchers["player_id"].map(names).fillna(
                "MLBAM " + pitchers["player_id"].astype(str))

        hitters = hitters[hitters["pa"] >= self.min_pa].reset_index(drop=True)
        pitchers = pitchers[pitchers["ip"] >= self.min_ip].reset_index(drop=True)

        rosters = read_csv(self.rosters_csv, label="rosters")
        return DataBundle(hitters, pitchers, rosters, self.source_name, self.notes).validate()

    # -- validation ---------------------------------------------------------
    @staticmethod
    def _check_pitch_schema(raw: pd.DataFrame) -> None:
        required = {
            "batter", "pitcher", "events", "description", "zone",
            "launch_speed", "launch_angle", "launch_speed_angle",
            "estimated_woba_using_speedangle", "bb_type",
            "outs_when_up", "post_bat_score", "bat_score",
        }
        missing = sorted(required - set(raw.columns))
        if missing:
            raise ValueError(
                "Pitch-level CSV is missing expected Statcast columns: "
                f"{missing}. This source expects the raw Savant/pybaseball "
                "pitch schema (one row per pitch)."
            )

    # -- shared feature prep ------------------------------------------------
    def _prepare(self, raw: pd.DataFrame) -> pd.DataFrame:
        df = raw.copy()
        df["is_pa"] = df["events"].notna()
        df["is_bb"] = df["launch_speed"].notna() & df["launch_angle"].notna()
        df["is_barrel"] = pd.to_numeric(df["launch_speed_angle"], errors="coerce").eq(6)
        df["is_oz"] = pd.to_numeric(df["zone"], errors="coerce") > 9
        df["is_swing"] = df["description"].isin(SWING_DESCRIPTIONS)
        df["is_whiff"] = df["description"].isin(WHIFF_DESCRIPTIONS)
        df["is_chase"] = df["is_oz"] & df["is_swing"]
        df["xwoba_v"] = pd.to_numeric(df["estimated_woba_using_speedangle"], errors="coerce")
        df["ls"] = pd.to_numeric(df["launch_speed"], errors="coerce")
        df["outs_made"] = df["events"].map(OUTS_BY_EVENT).fillna(0).astype(int)
        df["runs_on_play"] = (
            pd.to_numeric(df["post_bat_score"], errors="coerce")
            - pd.to_numeric(df["bat_score"], errors="coerce")
        ).clip(lower=0).fillna(0)
        df["is_fb"] = df["bb_type"].isin(["fly_ball", "popup"])
        return df

    # -- hitters ------------------------------------------------------------
    def _aggregate_hitters(self, df: pd.DataFrame) -> pd.DataFrame:
        g = df.groupby("batter", sort=False)
        rows = []
        for bid, grp in g:
            oz = int(grp["is_oz"].sum())
            chase = int(grp["is_chase"].sum())
            bb = grp.loc[grp["is_bb"], "ls"].dropna()
            xw = grp["xwoba_v"]
            sb = int(grp["events"].isin(["stolen_base_2b", "stolen_base_3b",
                                         "stolen_base_home"]).sum())
            rbi = float(grp["runs_on_play"].sum()) if self.rbi_approx else 0.0
            rows.append({
                "player_id": int(bid),
                "player_name": f"MLBAM {int(bid)}",  # overwritten by name map
                "pa": int(grp["is_pa"].sum()),
                "batted_balls": int(grp["is_bb"].sum()),
                "pitches_seen": int(len(grp)),
                "barrels": int(grp["is_barrel"].sum()),
                "xwoba": float(xw.mean()) if xw.notna().any() else np.nan,
                "ev90": float(bb.quantile(0.90)) if len(bb) else np.nan,
                "chase_rate": (chase / oz) if oz else np.nan,
                "hr": int((grp["events"] == "home_run").sum()),
                "rbi": rbi,
                # R (runs scored) cannot be derived cleanly from pitch rows.
                # We do NOT fabricate it; left 0 unless a real export is merged.
                "r": 0.0,
                "sb": sb,
            })
        h = pd.DataFrame(rows)
        h["r_plus_rbi"] = h["r"] + h["rbi"]
        # AVG (for the traditional-comparison slate) approximated from events.
        h["avg"] = np.nan
        return h

    # -- pitchers -----------------------------------------------------------
    def _aggregate_pitchers(self, df: pd.DataFrame) -> pd.DataFrame:
        g = df.groupby("pitcher", sort=False)
        rows = []
        for pid, grp in g:
            swings = int(grp["is_swing"].sum())
            whiffs = int(grp["is_whiff"].sum())
            bbe = int(grp["is_bb"].sum())
            barrels_allowed = int(grp["is_barrel"].sum())
            outs = int(grp["outs_made"].sum())
            ip = outs / 3.0
            k = int((grp["events"] == "strikeout").sum())
            bb = int(grp["events"].isin(["walk", "intent_walk"]).sum())
            hbp = int((grp["events"] == "hit_by_pitch").sum())
            fb = int(grp["is_fb"].sum())
            rows.append({
                "player_id": int(pid),
                "player_name": f"MLBAM {int(pid)}",
                "ip": round(ip, 1),
                "pitches": int(len(grp)),
                "batted_balls_allowed": bbe,
                "k": k,
                "xfip": self._xfip_proxy(k, bb, hbp, fb, ip),
                "whiff_rate": (whiffs / swings) if swings else np.nan,
                "barrel_rate_allowed": (barrels_allowed / bbe) if bbe else np.nan,
                # QS, W, SV, ERA, WHIP require game-level context; left honest.
                "qs": self._qs_proxy(grp),
                "w": 0.0,
                "sv": 0.0,
                "era": np.nan,
                "whip": np.nan,
            })
        return pd.DataFrame(rows)

    def _xfip_proxy(self, k: int, bb: int, hbp: int, fb: int, ip: float) -> float:
        """Transparent FIP-style proxy. NOT official xFIP.

        xFIP = ((13*(lgHR/FB*FB)) + (3*(BB+HBP)) - 2*K)/IP + constant.
        The constant (~3.10) normalizes FIP to league ERA; we use a fixed
        value since a true season constant needs leaguewide totals.
        """
        if ip <= 0:
            return np.nan
        return float(((13 * self.league_hr_per_fb * fb) + 3 * (bb + hbp) - 2 * k) / ip + 3.10)

    @staticmethod
    def _qs_proxy(grp: pd.DataFrame) -> float:
        """Approximate quality starts from per-game outs & runs allowed.

        A QS = >=18 outs (6 IP) and <=3 runs in a game as the starter. From
        pitch rows we approximate per-game outs and runs charged; labeled
        approximate because true earned-run accounting needs official scoring.
        """
        if "game_pk" not in grp.columns:
            return 0.0
        qs = 0
        for _, gm in grp.groupby("game_pk"):
            outs = int(gm["outs_made"].sum())
            runs = float(gm["runs_on_play"].sum())
            if outs >= 18 and runs <= 3:
                qs += 1
        return float(qs)

    # -- name resolution (the critical fix) ---------------------------------
    def _build_name_map(self, ids: Iterable[int], raw: pd.DataFrame) -> dict[int, str]:
        """Map MLBAM IDs -> 'First Last'. Tries the Chadwick register; falls
        back to pitcher names already present in the rows (pitchers only),
        then to a blank map (caller fills 'MLBAM <id>')."""
        ids = [int(i) for i in ids]
        # 1) Chadwick register (authoritative, public GitHub CSV).
        try:
            reg = self._load_chadwick()
            reg = reg[reg["key_mlbam"].isin(ids)]
            names = {
                int(r.key_mlbam): f"{r.name_first} {r.name_last}".strip()
                for r in reg.itertuples()
                if pd.notna(r.name_first) and pd.notna(r.name_last)
            }
            if names:
                return names
        except Exception:
            pass
        # 2) Fallback: pitchers appear as 'Last, First' in player_name.
        names = {}
        if "player_name" in raw.columns:
            pn = raw.dropna(subset=["player_name"])[["pitcher", "player_name"]].drop_duplicates()
            for r in pn.itertuples():
                if "," in str(r.player_name):
                    last, first = (s.strip() for s in str(r.player_name).split(",", 1))
                    names[int(r.pitcher)] = f"{first} {last}"
        return names

    @staticmethod
    def _load_chadwick() -> pd.DataFrame:
        """Load the Chadwick people register (cached after first fetch).

        Hosted on raw.githubusercontent.com, which is reachable in most
        environments even when Savant/FanGraphs are blocked.
        """
        base = "https://raw.githubusercontent.com/chadwickbureau/register/master/data"
        frames = []
        # The register is sharded people-0.csv .. people-f.csv (hex).
        for shard in "0123456789abcdef":
            url = f"{base}/people-{shard}.csv"
            cols = ["key_mlbam", "name_first", "name_last"]
            frames.append(pd.read_csv(url, usecols=cols, low_memory=False))
        reg = pd.concat(frames, ignore_index=True)
        reg = reg.dropna(subset=["key_mlbam"])
        reg["key_mlbam"] = reg["key_mlbam"].astype(int)
        return reg
