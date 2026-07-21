"""Deployment config loaded from config.toml (gitignored, see config.example.toml)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from telegram_cursor_agent.models import DEFAULT_MODEL_ALIASES

DEFAULT_SESSION_HEADER_TEMPLATE = """\
[Telegram bridge context]
Runtime: Cursor SDK local bridge on a remote server (not your IDE).
Workspace: {workspace}
Mode: {mode} — {mode_notes}
Model: {model}\
"""

MODE_NOTES: dict[str, str] = {
    "readonly": "read-only; any writes are reverted after the fact if attempted",
    "standard": "in-repo writes and git push allowed (sandbox off for bare-repo remotes)",
    "locked": "messages are not forwarded to the agent",
}


@dataclass(frozen=True)
class Config:
    workspace_path: Path
    allowed_sender_ids: frozenset[int]
    default_model: str
    default_perms_mode: str
    perms_dir: Path
    session_store_dir: Path
    session_header_template: str | None
    model_aliases: dict[str, str]


def build_session_header(*, template: str, workspace: Path, mode: str, model: str) -> str:
    return template.format(
        workspace=workspace,
        mode=mode,
        mode_notes=MODE_NOTES.get(mode, mode),
        model=model,
    )


def load_config(path: Path) -> Config:
    with path.open("rb") as f:
        data = tomllib.load(f)
    aliases = dict(DEFAULT_MODEL_ALIASES)
    if "model_aliases" in data:
        aliases.update({str(k).lower(): str(v) for k, v in data["model_aliases"].items()})
    header_raw = data.get("session_header_template")
    if header_raw is None:
        header_template: str | None = DEFAULT_SESSION_HEADER_TEMPLATE
    elif header_raw == "":
        header_template = None
    else:
        header_template = str(header_raw)
    return Config(
        workspace_path=Path(data["workspace_path"]).expanduser(),
        allowed_sender_ids=frozenset(data["allowed_sender_ids"]),
        default_model=data["default_model"],
        default_perms_mode=data["default_perms_mode"],
        perms_dir=Path(data.get("perms_dir", "./perms")),
        session_store_dir=Path(data.get("session_store_dir", "./data")),
        session_header_template=header_template,
        model_aliases=aliases,
    )
