---
name: deploy-telegram-cursor-agent
description: >-
  Deploy telegram-cursor-agent with Docker Compose on the user's machine.
  Use when asked to set up, install, or run the Telegram ↔ Cursor SDK bridge,
  or when pointed at this skill URL / file.
---

# Deploy telegram-cursor-agent (Docker)

You are setting up **telegram-cursor-agent**: a Telegram polling bot that
bridges allowlisted senders to a **local** Cursor SDK agent on one mounted
workspace. Call-and-response only. Permission modes: `locked` / `readonly` /
`standard`.

Repo: https://github.com/TinMarkovic/telegram-cursor-agent  
Image: `ghcr.io/tinmarkovic/telegram-cursor-agent:latest`  
Default path: Docker Compose pulling that image. Prefer this over building from
source or bare-metal Python unless the user insists.

## Ask the human first (do not invent)

Collect before writing secrets or starting the bot:

1. **Telegram bot token** — from [@BotFather](https://t.me/BotFather). Must be a
   **dedicated** bot (not shared with another `getUpdates` poller).
2. **Cursor API key** — Cursor Dashboard → Integrations (`CURSOR_API_KEY`).
3. **Their Telegram user id** (numeric) — for `allowed_sender_ids`.
4. **Workspace path** — absolute path to the git repo the agent should operate on.
5. **Where to clone / run this project** — directory on disk (default: clone into
   a sibling folder they choose).

If any of these are missing, stop and ask. Never invent tokens or user ids.

## Done when

- `docker compose ps` shows the service running (or logs show
  `telegram-cursor-agent starting` + `registered bot commands`)
- Human can message the bot `/status` and get a reply
- `.env` and `config.toml` exist locally and are **not** committed

## Steps

### 1. Clone (if needed)

```bash
git clone https://github.com/TinMarkovic/telegram-cursor-agent.git
cd telegram-cursor-agent
```

If they already have a clone, `cd` there and `git pull` on `main`.

### 2. Config + secrets

```bash
cp .env.example .env
cp config.docker.example.toml config.toml
```

Edit `.env` (real values, no quotes needed):

```
TELEGRAM_BOT_TOKEN=<from BotFather>
CURSOR_API_KEY=<from Cursor dashboard>
```

Edit `config.toml`:

- Set `allowed_sender_ids = [<their numeric Telegram id>]`
- Leave `workspace_path = "/workspace"` for Docker

Do **not** commit `.env` or `config.toml` (already gitignored).

### 3. Point at their workspace

Either:

```bash
export TCA_WORKSPACE=/absolute/path/to/their/repo
```

or copy/clone that repo into `./workspace` in the project directory
(`TCA_WORKSPACE` defaults to `./workspace`).

The compose file mounts that host path at `/workspace` in the container.

### 4. Up

```bash
docker compose up -d
docker compose logs -f --tail=50
```

Compose pulls `ghcr.io/tinmarkovic/telegram-cursor-agent:latest` by default.
Use `docker compose up --build -d` only if they want to build from the local
checkout instead.

Expect log lines like:

- `telegram-cursor-agent starting — polling, workspace=/workspace`
- `registered bot commands: status, perms, new, cancel`
- `Application started`

### 5. Verify with the human

In Telegram, they message **their** bot:

1. `/status` — mode, model, git snapshot, uptime
2. `/perms readonly` then a harmless question about the repo
3. Optional: `/perms standard` only after they understand write/push risk

## Layout reminder

| Host | Container |
|---|---|
| `.env` | loaded via `env_file` |
| `./config.toml` | `/app/config.toml` (read-only) |
| `$TCA_WORKSPACE` or `./workspace` | `/workspace` |
| Docker volume `tca_data` | `/app/data` (session store) |

## Constraints

- One workspace per instance. No multi-repo router.
- `interactive` approve/deny mode is **not** shipped.
- `readonly` does not reliably block native Write via SDK hooks; the bot uses
  `guard_writes()` (git revert). Do not promise preToolUse enforcement.
- In `standard`, sandbox is off and the agent shell can see process env —
  treat `CURSOR_API_KEY` as leakable; never ask the agent to dump `env`.
- SDK sandbox / bubblewrap inside Docker is best-effort; do not require
  `--privileged` unless the human asks and understands the tradeoff.
- Prefer `docker compose`; only use local `python -m telegram_cursor_agent.bot`
  if Docker is unavailable (see README “Local (no Docker)”).

## Ops cheatsheet

```bash
docker compose logs -f
docker compose restart
docker compose down
# rotate secrets: edit .env → docker compose up -d --force-recreate
```

## Out of scope

- Creating the BotFather bot or Cursor account for them (guide only)
- Hosting a multi-tenant / shared demo bot
- Rewriting permission enforcement or upgrading Cursor SDK beyond what the
  repo pins
- Publishing the GHCR image (CI does that on `v*` tags; do not push ad-hoc
  images unless the human asks)
