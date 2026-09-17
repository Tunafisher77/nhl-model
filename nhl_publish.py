from __future__ import annotations

import os
from datetime import date
from typing import Any

import gspread
import google.auth
from google.oauth2.service_account import Credentials


SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]


def _client() -> gspread.Client:
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        import json
        credentials = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    else:
        credentials, _ = google.auth.default(scopes=SCOPES)
    return gspread.authorize(credentials)


def _sheet(book: gspread.Spreadsheet, title: str, rows: int = 200, cols: int = 20) -> gspread.Worksheet:
    try:
        return book.worksheet(title)
    except gspread.WorksheetNotFound:
        return book.add_worksheet(title, rows=rows, cols=cols)


def replace_rows(title: str, headers: list[str], rows: list[list[Any]]) -> None:
    book = _client().open_by_key(os.environ["NHL_SPREADSHEET_ID"])
    sheet = _sheet(book, title, rows=max(100, len(rows) + 20), cols=max(12, len(headers)))
    sheet.clear()
    values = [headers] + rows
    sheet.update(values=values, range_name=f"A1:{gspread.utils.rowcol_to_a1(len(values), len(headers))}")
    sheet.freeze(rows=1)
    sheet.format("1:1", {"textFormat": {"bold": True}, "backgroundColor": {"red": .1, "green": .25, "blue": .45},
                              "horizontalAlignment": "CENTER"})


def append_unique_rows(title: str, headers: list[str], rows: list[list[Any]], key_columns: int) -> None:
    book = _client().open_by_key(os.environ["NHL_SPREADSHEET_ID"])
    sheet = _sheet(book, title, rows=max(1000, len(rows) + 20), cols=max(12, len(headers)))
    existing = sheet.get_all_values()
    if existing and existing[0] != headers:
        raise RuntimeError(f"Refusing to write {title}: header schema mismatch")
    if not existing:
        sheet.update(values=[headers], range_name=f"A1:{gspread.utils.rowcol_to_a1(1, len(headers))}")
        existing = [headers]
    keys = {tuple(row[:key_columns]) for row in existing[1:]}
    new_rows = [row for row in rows if tuple(str(v) for v in row[:key_columns]) not in keys]
    if new_rows:
        sheet.append_rows(new_rows, value_input_option="USER_ENTERED")
    sheet.freeze(rows=1)


def publish_game_email(day: date, rows: list[dict[str, Any]]) -> None:
    headers = ["Run Date", "Game ID", "Start UTC", "Matchup", "Pick", "Win Probability", "Confidence", "Reason"]
    values = [[day.isoformat(), r["game_id"], r["start_time_utc"], f'{r["away"]} at {r["home"]}', r["pick"],
               r["win_probability"], r["confidence"], r["reason"]] for r in rows]
    replace_rows("NHL Game Email Summary", headers, values)


def publish_goal_email(day: date, rows: list[dict[str, Any]]) -> None:
    headers = ["Run Date", "Game ID", "Matchup", "Player", "Team", "Goal Score", "Goal Rate", "Shots/Game", "Confidence"]
    values = [[day.isoformat(), r["game_id"], r["matchup"], r["name"], r["team"], r["goal_score"],
               round(r["goal_rate"], 3), round(r["shot_rate"], 2), r["confidence"]] for r in rows]
    replace_rows("NHL Goal Scorer Email Summary", headers, values)


def publish_best_cards(day: date, cards: list[dict[str, Any]]) -> None:
    headers = ["Run Date", "Card", "Game ID", "Matchup", "Pick Type", "Selection", "Team", "Model Score", "Confidence"]
    values: list[list[Any]] = []
    for card in cards:
        base = [day.isoformat(), card["card"], card["game_id"], card["matchup"]]
        values.append(base + ["Game Winner", card["game_pick"], card["game_pick"], "", card["game_confidence"]])
        for p in card["goal_scorers"]:
            values.append(base + ["Goal Scorer", p["name"], p["team"], p["goal_score"], confidence_label(p["goal_score"], 32, 23)])
        for p in card["assists"]:
            values.append(base + ["Player Assist", p["name"], p["team"], p["assist_score"], confidence_label(p["assist_score"], 40, 28)])
        for p in card["shots"]:
            values.append(base + ["Shots on Goal", p["name"], p["team"], p["shot_score"], confidence_label(p["shot_score"], 80, 60)])
    history_headers = headers + ["Game Status", "Final Score", "Actual", "Result", "Graded At UTC"]
    history_values = [row + ["Pending", "", "", "", ""] for row in values]
    append_unique_rows("NHL Best Card Results", history_headers, history_values, key_columns=6)
    replace_rows("NHL Best Card Email Summary", headers, values)


def confidence_label(score: float, high: float, medium: float) -> str:
    return "HIGH" if score >= high else "MEDIUM" if score >= medium else "LOW"
