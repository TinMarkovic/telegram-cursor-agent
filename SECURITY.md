# Security Policy

## Supported versions

Security fixes land on `main` and are published with the next semver tag / GHCR image.
There is no long-term support branch.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Email the maintainer (see the GitHub profile for [Tin Markovic](https://github.com/TinMarkovic))
with a description, impact, and repro steps if possible. You will get an acknowledgment
when the report is seen.

## What this project trusts

- Telegram user IDs in `ALLOWED_SENDER_IDS` / `allowed_sender_ids` — the only authorization boundary.
- Your Cursor API key and Telegram bot token in `.env` (never commit these).
- The mounted workspace — in `standard` mode the agent can read/write and run shell with sandbox off.

## Operational notes

- Prefer a dedicated Cursor API key for this bot; treat it as leakable via agent shell in `standard`.
- Use a dedicated BotFather token; only one process may poll a given bot.
- `readonly` is best-effort (`guard_writes` git revert); do not rely on it as a hard security boundary.
- Docker: process drops to uid 1000 after entrypoint; git `safe.directory` is set system-wide so bind-mounted host repos work.
