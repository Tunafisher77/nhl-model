from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from nhl_common import PACIFIC, START_DATE, fetch_games, fetch_skater_stats, fetch_standings, previous_season_id, season_id, target_date
from nhl_models import best_cards, build_player_pool, evaluate_games, goal_scorer_email
from nhl_publish import publish_best_cards, publish_game_email, publish_goal_email


def run() -> dict:
    day = target_date()
    if day < START_DATE and os.getenv("NHL_ALLOW_PRESTART") != "1":
        print(f"No-op: production starts {START_DATE.isoformat()}")
        return {"date": day.isoformat(), "status": "prestart"}
    games = fetch_games(day)
    if not games:
        print(f"No regular-season NHL games on {day}")
        return {"date": day.isoformat(), "status": "no-games"}
    standings = fetch_standings()
    current = fetch_skater_stats(season_id(day))
    prior = fetch_skater_stats(previous_season_id(day))
    pool = build_player_pool({g.away for g in games} | {g.home for g in games}, current, prior)
    game_rows = evaluate_games(games, standings)
    goal_rows = goal_scorer_email(games, pool, day)
    cards = best_cards(games, game_rows, pool, day)
    if not game_rows or not goal_rows or not cards:
        raise RuntimeError("Fail closed: one or more email models produced no verified output")
    if os.getenv("NHL_DRY_RUN") != "1":
        publish_game_email(day, game_rows)
        publish_goal_email(day, goal_rows)
        publish_best_cards(day, cards)
    result = {"date": day.isoformat(), "generated_at_pacific": datetime.now(PACIFIC).isoformat(),
              "games": game_rows, "goal_scorers": goal_rows, "best_cards": cards}
    Path("nhl_output.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"date": day.isoformat(), "games": len(game_rows), "goal_picks": len(goal_rows), "cards": len(cards)}))
    return result


if __name__ == "__main__":
    run()

