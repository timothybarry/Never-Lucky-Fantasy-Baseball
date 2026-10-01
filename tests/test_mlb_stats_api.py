import pandas as pd

from statcast_roto.fantasy_outcomes import (
    enrich_hitters_with_outcomes,
    enrich_pitchers_with_outcomes,
    normalize_outcome_table,
    normalize_pitching_table,
)
from statcast_roto.mlb_stats_api import BATTING_FIELDS, PITCHING_FIELDS, splits_to_frame


def _split(pid, name, stat, num_teams=1):
    return {"player": {"id": pid, "fullName": name}, "team": {"abbreviation": "NYY"}, "numTeams": num_teams, "stat": stat}


def test_batting_splits_flatten_to_outcome_schema():
    splits = [
        _split(592450, "Aaron Judge", {"plateAppearances": 678, "runs": 128, "homeRuns": 52, "rbi": 114,
                                       "stolenBases": 9, "avg": ".284", "obp": ".422", "slg": ".627", "ops": "1.049"}),
        _split(502110, "J.D. Martinez", {"plateAppearances": 489, "runs": 85, "homeRuns": 45, "rbi": 104,
                                         "stolenBases": 4, "avg": ".303", "obp": ".376", "slg": ".690"}, num_teams=2),
        _split(1, "Pitcher Batting", {"plateAppearances": 0, "avg": ".---", "obp": ".---"}),
    ]
    frame = splits_to_frame(splits, 2017, BATTING_FIELDS)
    assert list(frame["MLBAMID"]) == [1, 502110, 592450]
    assert frame.loc[frame.MLBAMID == 502110, "NumTeams"].item() == 2
    assert pd.isna(frame.loc[frame.MLBAMID == 1, "AVG"].item())  # undefined rates stay NaN, not 0

    norm = normalize_outcome_table(frame, season=2017)
    judge = norm[norm.player_id == 592450].iloc[0]
    assert (judge["r"], judge["sb"], judge["obp"]) == (128, 9, 0.422)


def test_pitching_merge_fills_box_score_and_keeps_statcast_k():
    splits = [_split(477132, "Kenley Jansen", {"wins": 1, "losses": 5, "saves": 38, "era": "3.01", "whip": "0.99",
                                                "outs": 215, "strikeOuts": 82, "gamesStarted": 0})]
    official = normalize_pitching_table(splits_to_frame(splits, 2018, PITCHING_FIELDS), season=2018)
    assert round(official.loc[0, "ip"], 2) == 71.67

    pitchers = pd.DataFrame({"player_id": [477132, 999], "player_name": ["Kenley Jansen", "Unmatched"],
                             "ip": [71.7, 30.0], "k": [83, 25], "w": [0.0, 0.0], "sv": [0.0, 0.0],
                             "era": [float("nan")] * 2, "whip": [float("nan")] * 2})
    enriched, meta = enrich_pitchers_with_outcomes(pitchers, official, source="unit-test")
    jansen = enriched[enriched.player_id == 477132].iloc[0]
    assert meta["matched"] == 1
    assert (jansen["sv"], jansen["era"], jansen["k"], jansen["so_official"]) == (38, 3.01, 83, 82)
    assert enriched.loc[enriched.player_id == 999, "sv"].item() == 0
    assert round(jansen["ip"], 2) == 71.67 and jansen["ip_statcast"] == 71.7  # official innings, Statcast kept
    assert enriched.loc[enriched.player_id == 999, "ip"].item() == 30.0  # unmatched keeps Statcast innings

    again, _ = enrich_pitchers_with_outcomes(enriched, official, source="unit-test")  # re-run is a no-op
    assert again.loc[again.player_id == 477132, "sv"].item() == 38
    assert list(again.columns) == list(enriched.columns)


def test_hitter_rerun_keeps_original_statcast_pa():
    hitters = pd.DataFrame({"player_id": [1], "player_name": ["A"], "pa": [480], "r": [0], "rbi": [50], "sb": [0], "hr": [20]})
    official = pd.DataFrame({"player_id": [1], "pa": [512], "r": [70], "rbi": [61], "sb": [12], "hr": [21]})
    once, _ = enrich_hitters_with_outcomes(hitters, official, source="t")
    twice, _ = enrich_hitters_with_outcomes(once, official, source="t")
    assert once["pa_statcast"].item() == 480 and twice["pa_statcast"].item() == 480
    assert twice["pa"].item() == 512 and twice["r_plus_rbi"].item() == 131
