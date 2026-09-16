from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

from nhl_common import Game, blend_player, confidence, deterministic_rng, fetch_roster


def evaluate_games(games: list[Game], standings: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    default = {"gp": 0, "points_pct": .5, "goal_diff_pg": 0, "last10_pct": .5}
    for game in games:
        away = standings.get(game.away, default)
        home = standings.get(game.home, default)
        home_score = (
            50
            + 34 * (home["points_pct"] - away["points_pct"])
            + 7 * (home["goal_diff_pg"] - away["goal_diff_pg"])
            + 10 * (home["last10_pct"] - away["last10_pct"])
            + 3.0
        )
        home_score = max(20.0, min(80.0, home_score))
        pick = game.home if home_score >= 50 else game.away
        probability = home_score if pick == game.home else 100 - home_score
        rows.append({
            **asdict(game), "pick": pick, "win_probability": round(probability, 1),
            "confidence": confidence(probability, high=61, medium=55),
            "edge_score": round(abs(home_score - 50), 2),
            "reason": f"Points%, goal differential, recent form, and home ice favor {pick}",
        })
    return sorted(rows, key=lambda r: (-r["win_probability"], r["game_id"]))


def build_player_pool(
    teams: set[str], current: dict[int, dict[str, Any]], prior: dict[int, dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for team in sorted(teams):
        rows: list[dict[str, Any]] = []
        for player in fetch_roster(team):
            metrics = blend_player(current.get(player["player_id"]), prior.get(player["player_id"]))
            if metrics["sample_gp"] < 3:
                continue
            goal_score = 100 * (0.72 * metrics["goal_rate"] + 0.18 * metrics["shot_rate"] / 3 + 0.10 * metrics["points_rate"] / 1.2)
            assist_score = 100 * (0.72 * metrics["assist_rate"] + 0.28 * metrics["points_rate"] / 1.2)
            shot_score = 100 * metrics["shot_rate"] / 4
            rows.append({**player, **metrics, "team": team, "goal_score": round(goal_score, 2),
                         "assist_score": round(assist_score, 2), "shot_score": round(shot_score, 2)})
        result[team] = rows
    return result


def goal_scorer_email(games: list[Game], pool: dict[str, list[dict[str, Any]]], day: date) -> list[dict[str, Any]]:
    ranked_games = []
    for game in games:
        game_players = sorted(pool.get(game.away, []) + pool.get(game.home, []), key=lambda p: (-p["goal_score"], p["player_id"]))
        if game_players:
            ranked_games.append((game_players[0]["goal_score"], game, game_players[:3]))
    candidates: list[dict[str, Any]] = []
    for _, game, top_three in sorted(ranked_games, key=lambda row: (-row[0], row[1].game_id))[:5]:
        rng = deterministic_rng(day, f"goal-email-{game.game_id}")
        chosen = rng.choice(top_three)
        candidates.append({"game_id": game.game_id, "matchup": f"{game.away} at {game.home}", **chosen,
                           "rank_pool": 3, "confidence": confidence(chosen["goal_score"], high=32, medium=23)})
    return sorted(candidates, key=lambda r: (-r["goal_score"], r["game_id"]))


def _top_distinct(players: list[dict[str, Any]], key: str, count: int, excluded: set[int]) -> list[dict[str, Any]]:
    chosen = []
    for player in sorted(players, key=lambda p: (-p[key], p["player_id"])):
        if player["player_id"] not in excluded:
            chosen.append(player)
            excluded.add(player["player_id"])
            if len(chosen) == count:
                break
    return chosen


def best_cards(
    games: list[Game], game_rows: list[dict[str, Any]], pool: dict[str, list[dict[str, Any]]], day: date
) -> list[dict[str, Any]]:
    lookup = {r["game_id"]: r for r in game_rows}
    eligible = []
    for game in games:
        if len(pool.get(game.away, [])) >= 3 and len(pool.get(game.home, [])) >= 3:
            strength = lookup[game.game_id]["win_probability"] + max(
                max(p["goal_score"] for p in pool[game.away]), max(p["goal_score"] for p in pool[game.home]))
            eligible.append((strength, game))
    selected = [g for _, g in sorted(eligible, key=lambda x: (-x[0], x[1].game_id))[:3]]
    cards: list[dict[str, Any]] = []
    for card_number, game in enumerate(selected, 1):
        rng = deterministic_rng(day, f"best-card-{game.game_id}")
        away_top = sorted(pool[game.away], key=lambda p: (-p["goal_score"], p["player_id"]))[:3]
        home_top = sorted(pool[game.home], key=lambda p: (-p["goal_score"], p["player_id"]))[:3]
        away_goal = rng.choice(away_top)
        home_goal = rng.choice(home_top)
        all_players = pool[game.away] + pool[game.home]
        excluded = {away_goal["player_id"], home_goal["player_id"]}
        assists = _top_distinct(all_players, "assist_score", 2, excluded)
        shots = _top_distinct(all_players, "shot_score", 2, excluded)
        if len(assists) < 2 or len(shots) < 2:
            continue
        cards.append({
            "card": card_number, "game_id": game.game_id, "matchup": f"{game.away} at {game.home}",
            "game_pick": lookup[game.game_id]["pick"], "game_confidence": lookup[game.game_id]["confidence"],
            "goal_scorers": [away_goal, home_goal], "assists": assists, "shots": shots,
        })
    return cards
