from datetime import date

from nhl_common import blend_player, previous_season_id, season_id


def test_season_ids():
    assert season_id(date(2026, 9, 29)) == 20262027
    assert previous_season_id(date(2026, 9, 29)) == 20252026


def test_prior_stats_power_early_season():
    row = blend_player({"gamesPlayed": 0}, {"gamesPlayed": 82, "goals": 41, "assists": 50, "shots": 246, "points": 91})
    assert row["goal_rate"] == .5
    assert row["shot_rate"] == 3


def test_current_season_weight_is_capped():
    row = blend_player({"gamesPlayed": 40, "goals": 40, "assists": 0, "shots": 160, "points": 40},
                       {"gamesPlayed": 80, "goals": 0, "assists": 40, "shots": 160, "points": 40})
    assert round(row["goal_rate"], 3) == .75


def test_nhl_roster_name_shape_is_documented():
    row = {"firstName": {"default": "Connor"}, "lastName": {"default": "McDavid"}}
    name = " ".join(part for part in (
        row.get("firstName", {}).get("default", "").strip(),
        row.get("lastName", {}).get("default", "").strip(),
    ) if part)
    assert name == "Connor McDavid"
