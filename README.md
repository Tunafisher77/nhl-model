# Daily NHL Picks

Statistics-only daily NHL model modeled on the established MLB/NFL pipeline:

1. GitHub Actions verifies the official regular-season slate and active rosters.
2. The model publishes three fresh summary tabs to Google Sheets.
3. Apps Script checks hourly and sends each email once per Pacific slate date.

## Emails

- **Game Picks:** every regular-season game, ranked by model confidence.
- **Goal Scorers:** one player from each of the five strongest available games. First the five games are selected using their strongest scorer candidate; then each selection is deterministic-random from that game's top three candidates. On slates under five games, one pick is sent for every available game.
- **Best Cards:** up to three games, each with a seven-pick card: game winner, one goal scorer from each team, two assist candidates, and two shots-on-goal candidates. One- and two-game slates send one and two cards.

No betting lines are ingested or used.

## Production start

Scheduled production is gated until **2026-09-29**, the first day of the 2026-27 regular season. Preseason games are excluded by NHL `gameType=2` validation.

## Required GitHub secrets

- `GOOGLE_SERVICE_ACCOUNT_JSON`: the complete service-account JSON used for Google Sheets.
- `NHL_SPREADSHEET_ID`: ID of the Google workbook shared with that service account.

The workflow runs at 13:05, 13:35, and 14:05 UTC. Multiple attempts cover Pacific daylight/standard time and transient upstream failures. Apps Script sent markers prevent duplicate emails.

## Google Sheets / Apps Script

Create or choose a Google Sheet, share it with the service-account email, and save its ID as `NHL_SPREADSHEET_ID`. Add `apps_script/NhlDailyEmails.gs` to the bound Apps Script project. Set the Script Property `NHL_EMAIL_TO`, then run `installNhlEmailTrigger()` once and authorize Gmail/Sheets access.

Generated tabs:

- `NHL Game Email Summary`
- `NHL Goal Scorer Email Summary`
- `NHL Best Card Email Summary`

## Manual validation

Use **Actions → Daily NHL Picks → Run workflow** with a target date. Before September 29, add repository variable `NHL_ALLOW_PRESTART=1` only for deliberate testing, or test a prior regular-season date locally with `NHL_DRY_RUN=1`.

## Model v1.0

- Game score: points percentage, goal differential per game, recent form, and home ice.
- Player goal score: goal rate (72%), shot generation (18%), and points rate (10%).
- Assist score: assist rate (72%) and points rate (28%).
- Shot score: shots per game.
- Early season: current statistics gradually replace prior-season statistics through 20 games, capped at 75% current-season weight to reduce small-sample volatility.
- Random picks are seeded by date and game, so retries reproduce the same selections.
