---
name: deploy-telegram-cursor-agent
description: >-
  Deploy telegram-cursor-agent with Docker — no repo clone required.
  Use when asked to set up, install, or run the Telegram ↔ Cursor SDK bridge,
  or when pointed at this skill URL / file.
---

# Deploy telegram-cursor-agent (Docker, no clone)

You are setting up **telegram-cursor-agent**: a Telegram polling bot that
bridges allowlisted senders to a **local** Cursor SDK agent on one mounted
workspace. Call-and-response only. Modes: `locked` / `readonly` / `standard`.

Image: `ghcr.io/tinmarkovic/telegram-cursor-agent:latest`  
Skill: https://github.com/TinMarkovic/telegram-cursor-agent/blob/main/skills/deploy/SKILL.md  
Compose: https://raw.githubusercontent.com/TinMarkovic/telegram-cursor-agent/main/compose.yml

Prefer the **no-clone** path below. Do not `git clone` unless the human wants to
hack on the bot itself.

## Ask the human first (do not invent)

1. **Telegram bot token** — [@BotFather](https://t.me/BotFather). Dedicated bot only.
2. **Cursor API key** — Dashboard → Integrations.
3. **Telegram user id** (numeric) — allowlist.
4. **Workspace path** — absolute path to the git repo the agent should operate on.

Never invent tokens or ids. Stop and ask if anything is missing.

## Done when

- Container is running; logs show `starting` + `registered bot commands`
- Human gets a `/status` reply from their bot
- Secrets live only in a local `.env` (not committed anywhere)

## Steps (no clone)

### 1. Empty directory + compose + env template

```bash
mkdir -p tca && cd tca
curl -fsSL https://raw.githubusercontent.com/TinMarkovic/telegram-cursor-agent/main/compose.yml -o compose.yml
curl -fsSL https://raw.githubusercontent.com/TinMarkovic/telegram-cursor-agent/main/.env.example -o .env
```

Ask the human for the four values and write them into `.env` (editor, or
`echo KEY=value >> .env` / `export` + rewrite — match how they already manage secrets).
Do not invent tokens or ids.

### 2. Start

```bash
docker compose up -d
docker compose logs -f --tail=50
```

Expect:

- `telegram-cursor-agent starting — polling, workspace=/workspace`
- `registered bot commands: status, perms, new, cancel`
- `Application started`

### 3. Verify with the human

They message **their** bot:

1. `/status`
2. `/perms readonly` + a harmless repo question
3. `/perms standard` only after they accept write/push risk

## What the four vars mean

| Var | Where | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | container | BotFather token |
| `CURSOR_API_KEY` | container | Cursor API key |
| `ALLOWED_SENDER_IDS` | container | Comma-separated Telegram user ids |
| `TCA_WORKSPACE` | host (compose) | Absolute path mounted at `/workspace` |

`WORKSPACE_PATH=/workspace` is set by compose. Do **not** set `WORKSPACE_PATH` in
`.env` for Docker — that is only for bare-metal env-only runs without `config.toml`.
Optional overrides: `DEFAULT_MODEL`, `DEFAULT_PERMS_MODE`.

## Constraints

- One workspace per instance.
- Multiple `ALLOWED_SENDER_IDS` share one agent session / mode (not multi-tenant).
- `interactive` mode is not shipped.
- `readonly` uses `guard_writes()` (git revert), not reliable preToolUse blocks.
- In `standard`, treat `CURSOR_API_KEY` as leakable via agent shell — never dump `env`.
- Container drops to uid 1000 after entrypoint; do not add `--privileged` unless asked.

## Ops

```bash
docker compose logs -f
docker compose restart
docker compose pull && docker compose up -d
# rotate: edit .env → docker compose up -d --force-recreate
```

## Out of scope

- Cloning this repo / building from source (unless asked)
- Creating BotFather / Cursor accounts
- Multi-tenant hosted bots
- Publishing GHCR images
