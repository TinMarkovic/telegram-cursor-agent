# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning is [SemVer](https://semver.org/) in `pyproject.toml`.

## [Unreleased]

## [0.2.8] - 2026-09-01

### Fixed

- Stop forcing `LocalAgentStoreConfig(type="jsonl")`. Long-lived local store is SQLite under `{session_store_dir}/agents/` (SDK default for Node >= 22.13). JSONL rewrite-all+fsync was the ~400ms/event drip on a grown store. Not a live migrate — archive `*.ndjson` and `/new` after upgrade.

## [0.2.7] - 2026-07-21

### Fixed

- Docker: set system `safe.directory` and drop to uid 1000 so git works on host-owned bind mounts and `/status` / `readonly` `guard_writes` no longer silently no-op.
- Remove shadowed `docker-compose.yml` (Compose preferred `compose.yml`); document local image builds in README / CONTRIBUTING.
- Clarify `.env.example`: `TCA_WORKSPACE` is compose-only; bare-metal env-only uses `WORKSPACE_PATH`.
- Cancel-path unit tests no longer mock sync `supports()` as async (pytest RuntimeWarning).

### Changed

- Simplify Docker deploy to env-only (no clone required); `compose.yml` + GHCR image path.
- Use-first README: Quickstart and workflows near the top; full Model IDs catalog at the bottom.
- Stop publishing maintainer `.cursor/` rules/skills (they referenced private `llm/`); keep them local via `.gitignore`.
- Remove private staging harness `scripts/verify-persistent-session-staging.py` from the public tree.
- Document that multiple allowlisted senders share one agent session.
- Add `SECURITY.md`, `CONTRIBUTING.md`, and this changelog.

## [0.2.6] - 2026-07

Prior tagged release — see git history / GHCR tags for detail.

## [0.2.5] - 2026-07

Prior tagged release — see git history / GHCR tags for detail.
