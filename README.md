# telegram-cursor-agent

A minimal, non-autonomous Telegram bridge to the Cursor SDK — tool use, doc
writing, and git check-in/commit from a phone, gated by explicit, switchable
permission modes rather than open-ended autonomy.

The tool itself carries no personal data or opinions about any particular
workspace. Everything specific — which repo to operate on, whose Telegram ID
is allowed, which permission profile to run — is external configuration.
Clone it, write your own config, point it at your own repo.

**Status:** persistent session shipped — polling bot, sender allowlist, `/status`,
`/perms`, `/new`, `/cancel`, `locked`/`readonly`/`standard` modes, conversation
survives restarts via jsonl store + sidecar. See [Roadmap](#roadmap).

## What it does

- **Tool use** — send a freeform prompt from Telegram, get an answer/action back.
- **Writing docs** — draft/update files in the configured workspace.
- **Checking in and committing** — review `git status`/diff, draft a commit message, stage, commit, push.
- **Running the workspace's own workflows** — whatever playbooks the target repo defines, on request.

## Quickstart

### Have an LLM do it

```
Read https://github.com/TinMarkovic/telegram-cursor-agent/blob/main/skills/deploy/SKILL.md
and follow it to deploy telegram-cursor-agent on this machine with Docker.
```

Have ready: BotFather token, Cursor API key, numeric Telegram user id, workspace path.

### Docker (no clone)

```bash
mkdir tca && cd tca
curl -fsSL https://raw.githubusercontent.com/TinMarkovic/telegram-cursor-agent/main/compose.yml -o compose.yml
curl -fsSL https://raw.githubusercontent.com/TinMarkovic/telegram-cursor-agent/main/.env.example -o .env

# fill these in .env (editor, or echo/export — whatever you normally use):
#   TELEGRAM_BOT_TOKEN=...
#   CURSOR_API_KEY=...
#   ALLOWED_SENDER_IDS=...          # numeric Telegram user id
#   TCA_WORKSPACE=/absolute/path/to/your/repo

docker compose up -d
```

Image: `ghcr.io/tinmarkovic/telegram-cursor-agent:latest`. Then `/status` in Telegram.

### Local (no Docker)

Requires Python 3.12+.

```bash
git clone https://github.com/TinMarkovic/telegram-cursor-agent.git && cd telegram-cursor-agent
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
cp .env.example .env && cp config.example.toml config.toml   # fill values
python -m telegram_cursor_agent.bot
```

Optional: `./scripts/check.sh` and `.githooks/pre-commit`.

### Build the image yourself

From a clone (contributors / offline). There is one compose file: `compose.yml`.

```bash
docker build -t ghcr.io/tinmarkovic/telegram-cursor-agent:local .
```

Point `compose.yml`'s `image:` at that tag (or retag as `:latest`) before `docker compose up`.
Prefer the published GHCR image unless you are changing the bot itself.

## Example workflows

Typical session: `/status` → set mode with `/perms` → freeform prompts →
`/new` when context gets muddy → `/cancel` if a run hangs.

```
/status
/perms
```

```
/perms readonly
What's changed since the last commit? Summarize the diff.
```

```
/perms standard
Update the README section on X. Show me the diff, then commit with a sensible message.
```

```
/new
Draft a short runbook for restarting this service and rotating secrets.
```

```
/new s5
/new c25
/new op
```

```
/perms locked
```

(Anything you send while locked is acked but not forwarded until `/perms standard` or `/perms readonly`.)

```
/cancel
```

## Telegram commands

On startup the bot registers these with Telegram's command menu (`setMyCommands`).
Send them as plain `/command` messages. Anything else is forwarded to the agent
as a freeform prompt.

| Command | Args | What it does |
|---------|------|--------------|
| `/status` | — | Repo snapshot without calling the agent: active mode, model, last commit, `git status --short`, bot uptime. |
| `/perms` | — | Report current mode, model, and available modes. |
| `/perms` | `<mode>` | Switch mode (`locked`, `readonly`, or `standard`). |
| `/new` | — | Fresh agent session, same model. Conversation history resets. |
| `/new` | `<model>` | Same, but switch model first. Aliases: `s5` → Sonnet 5, `c25` → Composer 2.5, `op` → Opus 4.8. Full list: [Model IDs](#model-ids). |
| `/cancel` | — | Cancel an in-flight agent run. No-op if nothing is running. |

While the agent runs: Telegram **typing** indicator stays active, a `working on it…`
message appears, and every **2 minutes** that message is edited with progress.
Progress clears when the run ends.

On the **first message** after `/new` (or a fresh session), the bot sends a short
ack (`→ agent (standard, claude-sonnet-5)`) and prepends a configurable context
block to the agent prompt. Customize via `session_header_template` in `config.toml`.

## Permission modes

Switch anytime with `/perms <mode>` — the power/friction tradeoff is a conscious,
visible choice each session, not baked into the code.

| Mode | Tool access | Git / writes | Sandbox |
|---|---|---|---|
| `locked` | none — bot doesn't forward messages to the agent | never | n/a |
| `readonly` | file read, `git status/diff/log`, fetch/search | never (git revert safety net) | on — workspace fenced |
| `standard` (default) | file read/write in-repo, `git add/commit/push`, repo scripts | yes, including push to remotes outside `workspace_path` (e.g. local bare repos) | **off** — needed when git must write outside the clone (e.g. a bare repo beside it) |
| `interactive` | same as `standard`, plus anything the classifier would otherwise hold | yes, with an Approve/Deny prompt | n/a (not shipped) |

`permissions.json` is loaded via `setting_sources=["project"]`. **Standard** runs
with `auto_review=False` — headless Telegram cannot approve held shell commands.
**Readonly** keeps auto_review on with a narrow `terminalAllowlist`. The sandbox
fences **subprocess** filesystem access; it does not reliably block the native
Write tool (see [Limitations](#limitations)).

Each mode maps to a static profile under [`perms/`](perms/) — reviewable and
diffable like any other config. Tune the allowlists for your workspace.

## Configuration

Docker needs **no `config.toml`** — four values in `.env` are enough:

```
TELEGRAM_BOT_TOKEN=
CURSOR_API_KEY=
ALLOWED_SENDER_IDS=
TCA_WORKSPACE=
```

`TCA_WORKSPACE` is the host path compose mounts at `/workspace`. Optional overrides:
`DEFAULT_MODEL`, `DEFAULT_PERMS_MODE`. If a `config.toml` is present, it wins over env
for agent settings (see [`config.example.toml`](config.example.toml)).

## Architecture

```mermaid
flowchart LR
    Phone["Your phone (Telegram)"] --> TgApi["Telegram Bot API"]
    TgApi --> BotSvc["Bot service<br/>(this repo, own systemd unit)"]
    Config["config.toml + .env<br/>(gitignored, per-deployment)"] --> BotSvc
    BotSvc -->|"AsyncAgent.send()"| SdkBridge["Cursor Python SDK<br/>(local runtime, async bridge)"]
    SdkBridge -->|"tool calls gated by active perms profile"| Workspace["configured workspace_path"]
    Workspace -->|"git push"| BareRepo["workspace's own origin"]
```

## Non-goals

- No proactive / unsolicited messages — purely call-and-response (no persona loop).
- No multi-repo router — one configured workspace per running instance.
- No cloud SDK runtime — local runtime only, against a fixed, configured `cwd`.
- No custom slash-command grammar for domain actions — natural language does that work.
- No multi-user collaboration — the allowlist can list multiple Telegram IDs, but
  they share one agent session, model, and perms mode (one `/new` resets everyone).

## Security

See [SECURITY.md](SECURITY.md) for reporting. Short version:

- Keep `.env` out of git (already gitignored). Never commit tokens or API keys.
- Only Telegram user IDs in `ALLOWED_SENDER_IDS` / `allowed_sender_ids` can talk to the bot.
- Multiple allowlisted IDs share one session — do not treat the allowlist as multi-tenant isolation.
- In `standard` mode the agent can run shell with sandbox off — treat `CURSOR_API_KEY` (and anything else in the process environment) as **leakable**. Do not ask the agent to dump `env` / `printenv`. Prefer a dedicated Cursor API key for this bot.
- Give the bot its **own** Telegram token. Do not share a token with another polling process (Telegram allows only one `getUpdates` consumer per bot).
- The Docker image runs as uid `1000` after startup (entrypoint drops root). Host workspace files written by the agent will usually be owned by uid 1000.

## Limitations

Honest gaps on Cursor SDK **1.0.24** (the version this bot targets). Starting with
`1.0.24`, the Python package and `@cursor/sdk` share one version and are built
from the same commit — Python jumps from `0.1.9` to `1.0.24` with no missing
releases in between; that does not change the public-beta status.

- **`interactive` is not shipped** — there is no held-call approve/deny hook in this SDK version.
- **`readonly` is not preToolUse-enforced** — permissions.json, sandbox, and hooks.json do not reliably block the native Write tool. Enforcement is `guard_writes()`: snapshot git state, revert if the agent wrote.
- **`standard` runs with sandbox off and `auto_review=False`** — required for headless Telegram and for git push layouts that write outside the clone.
- **No multi-workspace routing, no proactive agent, no persona store** — one `workspace_path`, call-and-response only.

## Release

Versioning is semver in `pyproject.toml` (`[project].version`). Tags: `vX.Y.Z`.

Suggested release checklist:

1. Bump version → `./scripts/check.sh` → commit on `main`.
2. `git tag -a vX.Y.Z -m "…"` and push the tag (triggers GHCR publish via Release workflow).
3. Deploy: `docker compose pull && docker compose up -d`, or build from the tagged commit.
4. Confirm `ghcr.io/tinmarkovic/telegram-cursor-agent:X.Y.Z` (and `:latest`) on GHCR.

## Roadmap

0. ~~**Repo scaffolding**~~ — pyproject, tooling, license, config templates.
1. ~~**Spike**~~ — cursor-sdk auth; `interactive` not shippable in V1; default model id.
2. ~~**Service skeleton**~~ — allowlist, modes, `/status`, `/perms`.
3. ~~**Persistent session**~~ — session store, `/new [model]`, `/cancel`, `locked`.
4. **Interactive mode** — inline-keyboard approve/deny, if/when the SDK supports it.
5. ~~**Telegram command menu**~~ — `setMyCommands` on startup.

## Model IDs

Pass full slugs to `/new <model>`, or use built-in aliases. Slugs come from
`Cursor.models.list()` on your account — the list below matches a typical Cursor
account as of 2026-07; run `Cursor.models.list()` if a slug 404s.
Override or extend aliases in `config.toml` under `[model_aliases]`.

### Short aliases (built-in)

| Alias | Resolves to |
|-------|-------------|
| `s5` | `claude-sonnet-5` |
| `s46` | `claude-sonnet-4-6` |
| `s45` | `claude-sonnet-4-5` |
| `c25` | `composer-2.5` |
| `c2` | `composer-2` |
| `op` / `op48` | `claude-opus-4-8` |
| `op46` | `claude-opus-4-6` |
| `haiku` | `claude-haiku-4-5` |
| `auto` | `default` |

### Anthropic (Claude)

| Slug | Display name |
|------|----------------|
| `claude-sonnet-5` | Sonnet 5 |
| `claude-sonnet-4-6` | Sonnet 4.6 |
| `claude-sonnet-4-5` | Sonnet 4.5 |
| `claude-sonnet-4` | Sonnet 4 |
| `claude-opus-4-8` | Opus 4.8 |
| `claude-opus-4-7` | Opus 4.7 |
| `claude-opus-4-6` | Opus 4.6 |
| `claude-opus-4-5` | Opus 4.5 |
| `claude-haiku-4-5` | Haiku 4.5 |
| `claude-fable-5` | Fable 5 |

### Cursor

| Slug | Display name |
|------|----------------|
| `composer-2.5` | Composer 2.5 |
| `composer-2` | Composer 2 |
| `default` | Auto |

### OpenAI

| Slug | Display name |
|------|----------------|
| `gpt-5.5` | GPT-5.5 |
| `gpt-5.4` | GPT-5.4 |
| `gpt-5.4-mini` | GPT-5.4 Mini |
| `gpt-5.4-nano` | GPT-5.4 Nano |
| `gpt-5.2` | GPT-5.2 |
| `gpt-5.2-codex` | Codex 5.2 |
| `gpt-5.3-codex` | Codex 5.3 |
| `gpt-5.1` | GPT-5.1 |
| `gpt-5.1-codex-max` | Codex 5.1 Max |
| `gpt-5.1-codex-mini` | Codex 5.1 Mini |
| `gpt-5-mini` | GPT-5 Mini |

### Google (Gemini)

| Slug | Display name |
|------|----------------|
| `gemini-3.1-pro` | Gemini 3.1 Pro |
| `gemini-3.5-flash` | Gemini 3.5 Flash |
| `gemini-3-flash` | Gemini 3 Flash |
| `gemini-2.5-flash` | Gemini 2.5 Flash |

### Other

| Slug | Display name |
|------|----------------|
| `grok-4.3` | Grok 4.3 |
| `grok-build-0.1` | Grok Build 0.1 |
| `glm-5.2` | GLM 5.2 |
| `kimi-k2.7-code` | Kimi K2.7 Code |

## License

MIT — see [LICENSE](LICENSE).

See also [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [CHANGELOG.md](CHANGELOG.md).
