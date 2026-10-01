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
            if response.status_code == 429 and attempt + 1 < attempts:
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = max(float(retry_after), 5.0) if retry_after else min(15.0 * (attempt + 1), 45.0)
                except (TypeError, ValueError):
                    delay = min(15.0 * (attempt + 1), 45.0)
                print(f"Warning: NHL rate limit for {url}; retrying in {delay:.0f}s")
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 8))
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
        "limit": 100,
        "sort": json.dumps([{"property": "points", "direction": "DESC"}]),
        "cayenneExp": f"seasonId={season} and gameTypeId=2",
    }
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for start in range(0, 10000, 100):
        params["start"] = start
        payload = get_json(f"{STATS_API}/{report}", params=params)
        page = payload.get("data", [])
        if not page:
            return rows
        ids = {int(row["playerId"]) for row in page if row.get("playerId")}
        if ids and ids <= seen:
            raise DataError("NHL stats pagination returned a repeated page")
        seen.update(ids)
        rows.extend(page)
        total = payload.get("total")
        if len(page) < 100 or (total is not None and len(rows) >= int(total)):
            return rows
    raise DataError("NHL stats exceeded the pagination safety limit")


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



def fetch_game_active_player_ids(game_id: int) -> set[int]:
    """Return skater IDs confirmed on the NHL gamecenter roster/boxscore.

    Active-roster verification is protective but non-critical. If the NHL
    gamecenter endpoint is unavailable or rate-limited, return an empty set so
    the caller keeps the statistical player pool instead of aborting the entire
    daily email pipeline.
    """
    url = f"{WEB_API}/gamecenter/{game_id}/boxscore"
    try:
        payload = get_json(url, attempts=3)
    except DataError as exc:
        print(f"Warning: active-player verification unavailable for game {game_id}: {exc}")
        return set()

    stats = payload.get("playerByGameStats", {}) or {}
    active: set[int] = set()
    for side in ("awayTeam", "homeTeam"):
        side_stats = stats.get(side, {}) or {}
        for group in ("forwards", "defense", "defensemen"):
            for row in side_stats.get(group, []) or []:
                player_id = row.get("playerId")
                if player_id:
                    active.add(int(player_id))
    return active

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
