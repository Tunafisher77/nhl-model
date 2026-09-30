from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import gspread

from nhl_common import PACIFIC, WEB_API, get_json, fetch_roster
from nhl_publish import _client, _sheet, append_unique_rows


HISTORY_TAB = "NHL Best Card Results"
SUMMARY_TAB = "NHL Best Card Results Email Summary"
PUBLISHED_TAB = "NHL Best Card Email Summary"
HEADERS = ["Run Date", "Card", "Game ID", "Matchup", "Pick Type", "Selection", "Team",
           "Model Score", "Confidence", "Game Status", "Final Score", "Actual", "Result", "Graded At UTC"]
SUMMARY_HEADERS = ["Result Date", "Card", "Matchup", "Final Score", "Pick Type", "Selection", "Actual", "Result", "Status"]


def _records(values: list[list[str]]) -> list[dict[str, str]]:
    if not values:
        return []
    return [{h: row[i] if i < len(row) else "" for i, h in enumerate(values[0])}
            for row in values[1:] if any(str(v).strip() for v in row)]


def _players(box: dict[str, Any], roster_names: dict[int, str] | None = None) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    stats = box.get("playerByGameStats", {}) or {}
    for side in ("awayTeam", "homeTeam"):
        for group in ("forwards", "defense", "defensemen"):
            for player in stats.get(side, {}).get(group, []) or []:
                name = player.get("name", {}).get("default", "")
                if name:
                    result[name.casefold()] = player
                full_name = (roster_names or {}).get(int(player.get("playerId", 0) or 0))
                if full_name:
                    result[full_name.casefold()] = player
    return result


def _game_details(game_id: str) -> tuple[str, str, dict[str, dict[str, Any]]]:
    box = get_json(f"{WEB_API}/gamecenter/{game_id}/boxscore")
    state = str(box.get("gameState", ""))
    away = box.get("awayTeam", {}) or {}
    home = box.get("homeTeam", {}) or {}
    away_name = away.get("abbrev", "AWAY")
    home_name = home.get("abbrev", "HOME")
    score = f"{away_name} {away.get('score', '')} - {home_name} {home.get('score', '')}" if state in {"OFF", "FINAL"} else ""
    roster_names = {}
    for team in (away_name, home_name):
        for player in fetch_roster(team):
            roster_names[player["player_id"]] = player["name"]
    return state, score, _players(box, roster_names)


def _grade(row: dict[str, str], state: str, score: str, players: dict[str, dict[str, Any]]) -> tuple[str, str]:
    if state not in {"OFF", "FINAL"}:
        return "", "Pending"
    pick_type = row["Pick Type"]
    selection = row["Selection"]
    if pick_type == "Game Winner":
        parts = score.split()
        away_score = int(parts[1]); home_score = int(parts[4])
        winner = parts[0] if away_score > home_score else parts[3]
        return winner, "HIT" if selection == winner else "MISS"
    player = players.get(selection.casefold())
    if not player:
        # A missing lookup is not evidence that the player did not play. Keep it
        # pending so feed/schema mismatches cannot corrupt historical results.
        return "", "Pending"
    if pick_type == "Goal Scorer":
        actual = int(player.get("goals", 0) or 0)
        return str(actual), "HIT" if actual >= 1 else "MISS"
    if pick_type == "Player Assist":
        actual = int(player.get("assists", 0) or 0)
        return str(actual), "HIT" if actual >= 1 else "MISS"
    if pick_type == "Shots on Goal":
        actual = int(player.get("sog", 0) or 0)
        return str(actual), "HIT" if actual >= 1 else "MISS"
    return "", "UNSUPPORTED"


def run() -> dict[str, int]:
    book = _client().open_by_key(os.environ["NHL_SPREADSHEET_ID"])
    history = _sheet(book, HISTORY_TAB, rows=5000, cols=len(HEADERS))
    values = [row for row in history.get_all_values() if any(str(v).strip() for v in row)]
    if values:
        while values[0] and not str(values[0][-1]).strip():
            values[0].pop()
    if not values:
        history.update(values=[HEADERS], range_name="A1:N1")
        values = [HEADERS]
    if values[0] != HEADERS:
        raise RuntimeError("NHL Best Card Results header schema mismatch")
    # Recover the exact published prior-day snapshot before today's publication.
    result_date = (datetime.now(PACIFIC).date() - timedelta(days=1)).isoformat()
    snapshot = _records(book.worksheet(PUBLISHED_TAB).get_all_values())
    snapshot_rows = [[row.get(h, "") for h in HEADERS[:9]] + ["Pending", "", "", "", ""]
                     for row in snapshot if row.get("Run Date") == result_date]
    if snapshot_rows:
        append_unique_rows(HISTORY_TAB, HEADERS, snapshot_rows, key_columns=6)
        values = history.get_all_values()
    records = _records(values)
    cache: dict[str, tuple[str, str, dict[str, dict[str, Any]]]] = {}
    graded = 0
    for index, row in enumerate(records, start=2):
        if row.get("Result") not in {"", "Pending", "DNP"}:
            continue
        game_id = row.get("Game ID", "")
        if not game_id:
            continue
        if game_id not in cache:
            cache[game_id] = _game_details(game_id)
        state, score, players = cache[game_id]
        actual, result = _grade(row, state, score, players)
        status = "Final" if state in {"OFF", "FINAL"} else state or "Pending"
        history.update(values=[[status, score, actual, result,
                                datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if status == "Final" else ""]],
                       range_name=f"J{index}:N{index}")
        if status == "Final":
            graded += 1
        row.update({"Game Status": status, "Final Score": score, "Actual": actual, "Result": result})

    result_date = (datetime.now(PACIFIC).date() - timedelta(days=1)).isoformat()

    # Use the exact final card that was published for the result date. History may
    # contain revised same-day selections from reruns; those older versions must
    # not be mixed into the email or historical card totals.
    published = _records(book.worksheet(PUBLISHED_TAB).get_all_values())
    published_for_date = [
        row for row in published if row.get("Run Date") == result_date
    ]
    if not published_for_date:
        # The morning publication may already have replaced the live snapshot.
        # Recover only this prior date's archived selections.
        published_for_date = [row for row in records if row.get("Run Date") == result_date]
    published_keys = {
        (
            row.get("Run Date", ""),
            row.get("Card", ""),
            row.get("Game ID", ""),
            row.get("Matchup", ""),
            row.get("Pick Type", ""),
            row.get("Selection", ""),
        )
        for row in published_for_date
    }
    final_rows = [
        row for row in records
        if (
            row.get("Run Date", ""),
            row.get("Card", ""),
            row.get("Game ID", ""),
            row.get("Matchup", ""),
            row.get("Pick Type", ""),
            row.get("Selection", ""),
        ) in published_keys
    ]
    output = [[result_date, r["Card"], r["Matchup"], r["Final Score"], r["Pick Type"],
               r["Selection"], r["Actual"], r["Result"], r["Game Status"]]
              for r in final_rows]
    summary = _sheet(book, SUMMARY_TAB, rows=100, cols=len(SUMMARY_HEADERS))
    summary.clear()
    summary.update(values=[SUMMARY_HEADERS] + output,
                   range_name=f"A1:I{max(1, len(output) + 1)}")
    summary.freeze(rows=1)
    return {"graded": graded, "summary_rows": len(output)}


if __name__ == "__main__":
    print(run())
