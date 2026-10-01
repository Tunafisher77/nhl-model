from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from nhl_common import PACIFIC, START_DATE, fetch_games, fetch_skater_stats, fetch_standings, previous_season_id, season_id, target_date, fetch_game_active_player_ids, fetch_roster
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
    # Protect all player-pick emails from known scratches/injuries. When the NHL
    # gamecenter feed exposes the active game roster, only those skaters remain
    # eligible. If it is not available yet, keep the statistical pool rather than
    # guessing an inactive status; the morning recovery run can refresh it later.
    active_by_team: dict[str, set[int]] = {}
    for team in ({g.away for g in games} | {g.home for g in games}):
        try:
            roster_ids = {p["player_id"] for p in fetch_roster(team)}
            if roster_ids:
                active_by_team[team] = roster_ids
        except Exception as exc:
            print(f"Warning: current-roster fallback unavailable for {team}: {exc}")
    for game in games:
        active = fetch_game_active_player_ids(game.game_id)
        if active:
            for team in (game.away, game.home):
                team_roster_ids = {p["player_id"] for p in pool.get(team, [])}
                confirmed = active & team_roster_ids
                if confirmed:
                    active_by_team[team] = confirmed
    for team, active_ids in active_by_team.items():
        pool[team] = [p for p in pool.get(team, []) if p["player_id"] in active_ids]
    game_rows = evaluate_games(games, standings)
    goal_rows = goal_scorer_email(games, pool, day)
    cards = best_cards(games, game_rows, pool, day)
    print(json.dumps({"date": day.isoformat(), "scheduled_games": len(games),
                      "current_stat_players": len(current), "prior_stat_players": len(prior),
                      "eligible_players_by_team": {team: len(players) for team, players in pool.items()},
                      "game_picks": len(game_rows), "goal_picks": len(goal_rows), "cards": len(cards)}))
    if not game_rows or not goal_rows or not cards:
        raise RuntimeError("Fail closed: one or more email models produced no verified output")
    if os.getenv("NHL_DRY_RUN") != "1":
        from nhl_results_tracker import run as grade_results
        grade_results()
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

