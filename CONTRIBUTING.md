# Contributing

Small, focused changes welcome. This is a thin Telegram ↔ Cursor SDK bridge — keep the footprint small.

## Setup

```bash
git clone https://github.com/TinMarkovic/telegram-cursor-agent.git
cd telegram-cursor-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cp config.example.toml config.toml   # fill with non-secret test values as needed
```

Run the gate before opening a PR:

```bash
./scripts/check.sh
```

Optional local hook: `git config core.hooksPath .githooks`

## Docker (contributors)

Published image: `ghcr.io/tinmarkovic/telegram-cursor-agent:latest` via `compose.yml`.

To test a local build:

```bash
docker build -t ghcr.io/tinmarkovic/telegram-cursor-agent:local .
# temporarily set image: in compose.yml to that tag, then docker compose up
```

## Scope

- Prefer fixing the shared helper once over per-caller patches.
- No new dependencies unless unavoidable.
- Docs that belong in the public repo: root `README`, `SECURITY.md`, this file, `CHANGELOG.md`, and `skills/deploy/`. Maintainer-only SDLC notes live privately under `llm/` (gitignored).

## Pull requests

1. One concern per PR when practical.
2. Include or update unit tests for behavior changes.
3. Note verification you ran (`./scripts/check.sh`, smoke script if SDK-touching).
