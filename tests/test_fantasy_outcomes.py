import pandas as pd

from statcast_roto.fantasy_outcomes import normalize_outcome_table, enrich_hitters_with_outcomes


def test_enrich_hitters_overwrites_broken_pitch_level_steals_and_runs():
    hitters = pd.DataFrame({
        "player_id": [1, 2],
        "player_name": ["Fast Guy", "Power Guy"],
        "pa": [100, 100],
        "r": [0, 0],
        "rbi": [1, 2],
        "sb": [0, 0],
        "hr": [3, 4],
        "avg": [float("nan"), float("nan")],
    })
    outcomes = pd.DataFrame({
        "player_id": [1, 2],
        "pa": [550, 480],
        "r": [90, 60],
        "hr": [12, 30],
        "rbi": [55, 88],
        "sb": [38, 4],
        "avg": [0.281, 0.252],
        "obp": [0.355, 0.331],
        "slg": [0.421, 0.510],
    })

    enriched, meta = enrich_hitters_with_outcomes(hitters, outcomes, source="unit-test")

    assert meta["matched"] == 2
    assert enriched.loc[enriched.player_id == 1, "sb"].item() == 38
    assert enriched.loc[enriched.player_id == 1, "r_plus_rbi"].item() == 145
    assert enriched.loc[enriched.player_id == 2, "hr"].item() == 30
    assert enriched.loc[enriched.player_id == 2, "fantasy_outcomes_source"].item() == "unit-test"
    assert "pa_statcast" in enriched.columns


def test_normalize_fangraphs_style_columns():
    raw = pd.DataFrame({
        "Season": [2021],
        "Name": ["Example Player"],
        "MLBAMID": [12345],
        "PA": [501],
        "R": [77],
        "HR": [21],
        "RBI": [81],
        "SB": [9],
        "AVG": [0.275],
        "OBP": [0.351],
        "SLG": [0.472],
    })
    norm = normalize_outcome_table(raw, season=2021)
    assert list(norm["player_id"]) == [12345]
    assert norm.loc[0, "r"] == 77
    assert norm.loc[0, "sb"] == 9
    assert norm.loc[0, "obp"] == 0.351
