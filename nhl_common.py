from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

WEB_API = "https://api-web.nhle.com/v1"
STATS_API = "https://api.nhle.com/stats/rest/en"
PACIFIC = ZoneInfo("America/Los_Angeles")
START_DATE = date(2026, 9, 29)


class DataError(RuntimeError):
    pass


@dataclass(frozen=True)
class Game:
    game_id: int
    game_date: str
    start_time_utc: str
    away: str
    home: str
    game_type: int


def target_date() -> date:
    raw = os.getenv("NHL_TARGET_DATE")
    return date.fromisoformat(raw) if raw else datetime.now(PACIFIC).date()


def season_id(day: date) -> int:
    start = day.year if day.month >= 7 else day.year - 1
    return int(f"{start}{start + 1}")


def previous_season_id(day: date) -> int:
    current = str(season_id(day))
    start = int(current[:4]) - 1
    return int(f"{start}{start + 1}")


def deterministic_rng(day: date, namespace: str) -> random.Random:
    digest = hashlib.sha256(f"{day.isoformat()}|{namespace}|nhl-v1".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def get_json(url: str, *, params: dict[str, Any] | None = None, attempts: int = 4) -> Any:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2 ** attempt)
    raise DataError(f"NHL request failed after {attempts} attempts: {url}: {last}")


def fetch_games(day: date) -> list[Game]:
    payload = get_json(f"{WEB_API}/schedule/{day.isoformat()}")
    games: list[Game] = []
    for week in payload.get("gameWeek", []):
        if week.get("date") != day.isoformat():
            continue
        for raw in week.get("games", []):
            if int(raw.get("gameType", 0)) != 2:
                continue
            away = raw.get("awayTeam", {}).get("abbrev")
            home = raw.get("homeTeam", {}).get("abbrev")
            if not away or not home or away == home:
                raise DataError(f"Invalid schedule game: {raw}")
            games.append(Game(int(raw["id"]), day.isoformat(), raw["startTimeUTC"], away, home, 2))
    ids = [g.game_id for g in games]
    if len(ids) != len(set(ids)):
        raise DataError("Duplicate NHL game IDs returned by schedule")
    return sorted(games, key=lambda g: (g.start_time_utc, g.game_id))


def fetch_standings() -> dict[str, dict[str, float]]:
    payload = get_json(f"{WEB_API}/standings/now")
    result: dict[str, dict[str, float]] = {}
    for row in payload.get("standings", []):
        team = row.get("teamAbbrev", {}).get("default")
        gp = float(row.get("gamesPlayed", 0) or 0)
        if not team:
            continue
        result[team] = {
            "gp": gp,
            "points_pct": float(row.get("pointPctg", 0) or 0),
            "goal_diff_pg": float(row.get("goalDifferential", 0) or 0) / max(gp, 1),
            "last10_pct": (2 * float(row.get("l10Wins", 0) or 0) + float(row.get("l10OtLosses", 0) or 0)) / max(2 * min(gp, 10), 1),
        }
    return result


def _stats_query(report: str, season: int) -> list[dict[str, Any]]:
    params = {
        "isAggregate": "false",
        "isGame": "false",
        "start": 0,
        "limit": 5000,
        "sort": json.dumps([{"property": "points", "direction": "DESC"}]),
        "cayenneExp": f"seasonId={season} and gameTypeId=2",
    }
    return get_json(f"{STATS_API}/{report}", params=params).get("data", [])


def fetch_skater_stats(season: int) -> dict[int, dict[str, Any]]:
    rows = _stats_query("skater/summary", season)
    return {int(r["playerId"]): r for r in rows if r.get("playerId")}


def fetch_roster(team: str) -> list[dict[str, Any]]:
    payload = get_json(f"{WEB_API}/roster/{team}/current")
    players: list[dict[str, Any]] = []
    for group in ("forwards", "defensemen"):
        for row in payload.get(group, []):
            player_id = row.get("id")
            name = row.get("fullName", {}).get("default")
            if not name:
                first = row.get("firstName", {}).get("default", "").strip()
                last = row.get("lastName", {}).get("default", "").strip()
                name = " ".join(part for part in (first, last) if part)
            if player_id and name:
                players.append({"player_id": int(player_id), "name": name, "position": row.get("positionCode", "")})
    return players


def blend_player(current: dict[str, Any] | None, prior: dict[str, Any] | None) -> dict[str, float]:
    current = current or {}
    prior = prior or {}
    cgp = float(current.get("gamesPlayed", 0) or 0)
    pgp = float(prior.get("gamesPlayed", 0) or 0)
    current_weight = min(cgp / 20.0, 0.75)
    prior_weight = 1.0 - current_weight

    def rate(key: str, row: dict[str, Any], gp: float) -> float:
        return float(row.get(key, 0) or 0) / max(gp, 1)

    return {
        "gp": cgp,
        "goal_rate": current_weight * rate("goals", current, cgp) + prior_weight * rate("goals", prior, pgp),
        "assist_rate": current_weight * rate("assists", current, cgp) + prior_weight * rate("assists", prior, pgp),
        "shot_rate": current_weight * rate("shots", current, cgp) + prior_weight * rate("shots", prior, pgp),
        "points_rate": current_weight * rate("points", current, cgp) + prior_weight * rate("points", prior, pgp),
        "sample_gp": cgp + min(pgp, 82) * prior_weight,
    }


def confidence(score: float, *, high: float, medium: float) -> str:
    if score >= high:
        return "HIGH"
    if score >= medium:
        return "MEDIUM"
    return "LOW"


def chunked(values: Iterable[Any], size: int) -> Iterable[list[Any]]:
    batch: list[Any] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
