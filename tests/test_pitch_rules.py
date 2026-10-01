"""Pitch-level aggregation rules, on synthetic rows (no raw data needed, so these run in any clone)."""

import pandas as pd

from statcast_roto.pitch_level import PitchLevelCSVSource

SRC = PitchLevelCSVSource(pitches_csv="unused.csv", rosters_csv="unused.csv", min_pa=1, min_ip=0, resolve_names=False)


def pitch(**kw):
    row = {"game_type": "R", "type": "S", "game_pk": 1, "inning_topbot": "Top", "inning": 1,
           "at_bat_number": 1, "pitch_number": 1, "pitcher": 1, "batter": 9, "events": None,
           "description": "called_strike", "zone": 5, "launch_speed": None, "launch_angle": None,
           "launch_speed_angle": None, "estimated_woba_using_speedangle": None, "bb_type": None,
           "outs_when_up": 0, "bat_score": 0, "post_bat_score": 0}
    row.update(kw)
    return row


def test_regular_season_only_and_strikeout_double_plays_count():
    rows = [pitch(events="strikeout", description="swinging_strike", at_bat_number=1),
            pitch(events="strikeout_double_play", description="swinging_strike", at_bat_number=2),
            pitch(game_type="F", game_pk=2, events="strikeout", description="swinging_strike")]
    prepped = SRC._prepare(pd.DataFrame(rows))
    assert set(prepped["game_type"]) == {"R"}
    pitchers = SRC._aggregate_pitchers(prepped)
    assert pitchers.loc[pitchers.player_id == 1, "k"].item() == 2


def test_fouls_with_exit_velocity_are_not_batted_balls():
    rows = [pitch(type="S", description="foul", launch_speed=80.0, launch_angle=60.0, at_bat_number=1),
            pitch(type="X", description="hit_into_play", events="field_out", launch_speed=101.0,
                  launch_angle=12.0, launch_speed_angle=4, bb_type="line_drive", at_bat_number=2)]
    prepped = SRC._prepare(pd.DataFrame(rows))
    assert prepped["is_bb"].tolist() == [False, True]
    pitchers = SRC._aggregate_pitchers(prepped)
    assert pitchers.loc[pitchers.player_id == 1, "batted_balls_allowed"].item() == 1


def test_quality_start_requires_starting_the_game():
    """Pitcher 1 starts game 1 and goes 6 scoreless; pitcher 2 throws 6 scoreless in relief in game 2."""
    rows = []
    for game, starter, reliever in ((1, 1, 2), (2, 3, 2)):
        rows.append(pitch(game_pk=game, pitcher=starter, at_bat_number=1, events="field_out", type="X"))
        for ab in range(2, 20):
            who = starter if game == 1 else reliever
            rows.append(pitch(game_pk=game, pitcher=who, at_bat_number=ab, events="field_out", type="X"))
    prepped = SRC._prepare(pd.DataFrame(rows))
    qs = SRC._aggregate_pitchers(prepped).set_index("player_id")["qs"]
    assert qs[1] == 1  # 18+ outs as the starter, no runs
    assert qs[2] == 0  # 18 outs in relief is not a quality start
