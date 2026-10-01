"""League-wide per-season aggregates from the five raw Statcast pitch files."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]  # the engine root (site/ lives inside it)
RAW = ROOT / "data" / "raw_sample"
PRE = ROOT / "data" / "precomputed"
FILES = {
    "2017": "statcast_2017.csv", "2018": "Statcast_2018.csv", "2019": "Statcast_2019.csv",
    "2020": "Statcast_2020.csv", "2021": "Statcast_2021.csv",
}
COLS = ["type", "bb_type", "pitch_type", "game_date", "release_speed", "player_name", "batter", "pitcher", "events",
        "description", "zone", "game_type", "launch_speed", "launch_angle", "launch_speed_angle",
        "hit_distance_sc", "release_spin_rate", "woba_value", "woba_denom",
        "estimated_woba_using_speedangle", "game_pk", "home_team", "stand", "p_throws"]
SWING = {"swinging_strike", "swinging_strike_blocked", "foul", "foul_tip", "foul_bunt",
         "bunt_foul_tip", "missed_bunt", "hit_into_play", "hit_into_play_no_out", "hit_into_play_score"}
WHIFF = {"swinging_strike", "swinging_strike_blocked", "missed_bunt"}

names = {}
for tag in FILES:
    for side in ("hitters", "pitchers"):
        d = pd.read_csv(PRE / f"{side}_{tag}.csv", usecols=["player_id", "player_name"])
        names.update(dict(zip(d.player_id.astype(int), d.player_name)))


def nm(pid):
    try:
        return names.get(int(pid), f"MLBAM {int(pid)}")
    except Exception:
        return "?"


out = {}
for tag, fn in FILES.items():
    df = pd.read_csv(RAW / fn, usecols=lambda c: c in COLS, low_memory=False)
    types = df["game_type"].value_counts().to_dict()
    df = df[df["game_type"] == "R"].copy()
    ls = pd.to_numeric(df["launch_speed"], errors="coerce")
    la = pd.to_numeric(df["launch_angle"], errors="coerce")
    bip = ls.notna() & la.notna()
    zone = pd.to_numeric(df["zone"], errors="coerce")
    swing = df["description"].isin(SWING)
    whiff = df["description"].isin(WHIFF)
    oz = zone > 9
    ev = df["events"]
    rs = pd.to_numeric(df["release_speed"], errors="coerce")
    spin = pd.to_numeric(df["release_spin_rate"], errors="coerce")
    dist = pd.to_numeric(df["hit_distance_sc"], errors="coerce")
    wv = pd.to_numeric(df["woba_value"], errors="coerce")
    wd = pd.to_numeric(df["woba_denom"], errors="coerce")
    xw = pd.to_numeric(df["estimated_woba_using_speedangle"], errors="coerce")

    # xwOBA: batted balls use the speed/angle estimate, other PA endings keep their actual wOBA value.
    x_num = np.where(bip & xw.notna() & (wd > 0), xw, np.where(wd > 0, wv, 0.0))
    ff = df["pitch_type"].isin(["FF", "FA"])

    # Batted-ball events only: tracking glitches log 143-299 mph on non-contact pitches.
    contact = ev.notna() & bip & ~ev.isin(["strikeout", "walk", "hit_by_pitch", "strikeout_double_play"]) & (ls < 125)
    hard = ls.where(contact).idxmax()
    fast = rs.idxmax()
    hr = df[ev == "home_run"]
    hr_d = pd.to_numeric(hr["hit_distance_sc"], errors="coerce")
    longest = hr_d.idxmax() if hr_d.notna().any() else None
    spin_ff = spin.where(ff)
    spinmax = spin_ff.idxmax()

    mix = df["pitch_type"].replace({"FA": "FF", "KN": "OT", "EP": "OT", "SC": "OT", "FO": "OT", "CS": "CU", "ST": "SL", "SV": "SL"})
    mix = mix.fillna("OT").value_counts(normalize=True).round(4).to_dict()

    dates = pd.to_datetime(df["game_date"])
    monthly = []
    for m, g in df.groupby(dates.dt.to_period("M")):
        gls = pd.to_numeric(g["launch_speed_angle"], errors="coerce")
        gbip = pd.to_numeric(g["launch_speed"], errors="coerce").notna()
        monthly.append({"m": str(m), "pitches": int(len(g)),
                        "hr": int((g["events"] == "home_run").sum()),
                        "barrels": int(gls.eq(6).sum()), "bip": int(gbip.sum())})

    pa = int(ev.notna().sum())
    rec = {
        "game_types": {k: int(v) for k, v in types.items()},
        "pitches": int(len(df)),
        "games": int(df["game_pk"].nunique()),
        "first": str(dates.min().date()), "last": str(dates.max().date()),
        "pa": pa,
        "bip": int(bip.sum()),
        "barrels": int(pd.to_numeric(df["launch_speed_angle"], errors="coerce").eq(6).sum()),
        "hr": int((ev == "home_run").sum()),
        "k": int(ev.isin(["strikeout", "strikeout_double_play"]).sum()),
        "bb": int(ev.isin(["walk"]).sum()),
        "hbp": int((ev == "hit_by_pitch").sum()),
        "swings": int(swing.sum()), "whiffs": int(whiff.sum()),
        "chase_rate": round(float((oz & swing).sum() / oz.sum()), 4),
        "whiff_rate": round(float(whiff.sum() / swing.sum()), 4),
        "k_rate": round(float(ev.isin(["strikeout", "strikeout_double_play"]).sum() / pa), 4),
        "bb_rate": round(float((ev == "walk").sum() / pa), 4),
        "woba": round(float(wv[wd > 0].sum() / wd[wd > 0].sum()), 4),
        "xwoba": round(float(np.nansum(x_num) / wd[wd > 0].sum()), 4),
        "avg_ev": round(float(ls[bip].mean()), 2),
        "ev95_share": round(float((ls[bip] >= 95).mean()), 4),
        "avg_la": round(float(la[bip].mean()), 2),
        "ff_velo": round(float(rs[ff].mean()), 2),
        "ff_spin": round(float(spin[ff].mean()), 0),
        "velo_95plus_share": round(float((rs[ff] >= 95).mean()), 4),
        "velo_100plus": int((rs >= 100).sum()),
        "hardest_hit": {"ev": float(ls[hard]), "batter": nm(df.at[hard, "batter"]), "date": str(df.at[hard, "game_date"]), "event": str(df.at[hard, "events"])},
        "fastest_pitch": {"mph": float(rs[fast]), "pitcher": str(df.at[fast, "player_name"]), "date": str(df.at[fast, "game_date"])},
        "longest_hr": None if longest is None else {"ft": float(hr_d[longest]), "batter": nm(df.at[longest, "batter"]), "date": str(df.at[longest, "game_date"]), "ev": float(ls[longest]) if pd.notna(ls[longest]) else None},
        "max_spin_ff": {"rpm": float(spin_ff[spinmax]), "pitcher": str(df.at[spinmax, "player_name"])},
        "pitch_mix": mix,
        "monthly": monthly,
        "unique_batters": int(df["batter"].nunique()),
        "unique_pitchers": int(df["pitcher"].nunique()),
    }
    out[tag] = rec
    print(tag, rec["pitches"], rec["games"], rec["barrels"], rec["hr"], rec["hardest_hit"], rec["longest_hr"], flush=True)

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("league.json")
OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
print("wrote", OUT)
