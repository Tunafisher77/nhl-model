from datetime import date

from nhl_common import Game, deterministic_rng
from nhl_models import best_cards, evaluate_games, goal_scorer_email


def player(pid, team, goal, assist, shot):
    return {"player_id": pid, "name": f"P{pid}", "team": team, "goal_score": goal,
            "assist_score": assist, "shot_score": shot, "goal_rate": goal / 100,
            "assist_rate": assist / 100, "shot_rate": shot / 25}


def games():
    return [Game(i, "2026-10-01", "2026-10-02T00:00:00Z", f"A{i}", f"H{i}", 2) for i in range(1, 7)]


def pool_for(gs):
    result = {}
    pid = 1
    for g in gs:
        for team in (g.away, g.home):
            result[team] = [player(pid + j, team, 40-j, 50-j, 90-j) for j in range(6)]
            pid += 10
    return result


def test_random_seed_is_stable_and_namespaced():
    assert deterministic_rng(date(2026, 10, 1), "x").random() == deterministic_rng(date(2026, 10, 1), "x").random()
    assert deterministic_rng(date(2026, 10, 1), "x").random() != deterministic_rng(date(2026, 10, 2), "x").random()


def test_goal_email_uses_five_distinct_games():
    gs = games()
    rows = goal_scorer_email(gs, pool_for(gs), date(2026, 10, 1))
    assert len(rows) == 5
    assert len({r["game_id"] for r in rows}) == 5


def test_small_slate_sends_only_available_games():
    gs = games()[:2]
    rows = goal_scorer_email(gs, pool_for(gs), date(2026, 10, 1))
    assert len(rows) == 2


def test_best_card_is_seven_picks_per_game_and_max_three_cards():
    gs = games()
    pool = pool_for(gs)
    standings = {team: {"gp": 10, "points_pct": .6, "goal_diff_pg": .5, "last10_pct": .6}
                 for g in gs for team in (g.away, g.home)}
    evaluations = evaluate_games(gs, standings)
    cards = best_cards(gs, evaluations, pool, date(2026, 10, 1))
    assert len(cards) == 3
    for card in cards:
        assert 1 + len(card["goal_scorers"]) + len(card["assists"]) + len(card["shots"]) == 7
        assert {p["team"] for p in card["goal_scorers"]} == set(card["matchup"].split(" at "))

