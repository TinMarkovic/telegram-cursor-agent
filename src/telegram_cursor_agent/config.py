"""Deployment config from config.toml and/or environment variables."""

from __future__ import annotations

import os
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


def _parse_sender_ids(raw: str) -> frozenset[int]:
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    if not ids:
        raise ValueError("ALLOWED_SENDER_IDS is empty")
    return frozenset(int(part) for part in ids)


def load_config_from_env() -> Config:
    """Build config from env — enough for Docker with no config.toml."""
    try:
        senders = _parse_sender_ids(os.environ["ALLOWED_SENDER_IDS"])
    except KeyError as err:
        raise ValueError(
            "No config.toml found; set ALLOWED_SENDER_IDS (and usually WORKSPACE_PATH=/workspace)"
        ) from err
    header_raw = os.environ.get("SESSION_HEADER_TEMPLATE")
    if header_raw is None:
        header_template: str | None = DEFAULT_SESSION_HEADER_TEMPLATE
    elif header_raw == "":
        header_template = None
    else:
        header_template = header_raw
    return Config(
        workspace_path=Path(os.environ.get("WORKSPACE_PATH", "/workspace")).expanduser(),
        allowed_sender_ids=senders,
        default_model=os.environ.get("DEFAULT_MODEL", "claude-sonnet-5"),
        default_perms_mode=os.environ.get("DEFAULT_PERMS_MODE", "standard"),
        perms_dir=Path(os.environ.get("PERMS_DIR", "./perms")),
        session_store_dir=Path(os.environ.get("SESSION_STORE_DIR", "./data")),
        session_header_template=header_template,
        model_aliases=dict(DEFAULT_MODEL_ALIASES),
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


def resolve_config(path: Path | None = None) -> Config:
    """Prefer config.toml when present; otherwise env (Docker / no-clone)."""
    config_path = path if path is not None else Path(os.environ.get("TCA_CONFIG", "config.toml"))
    if config_path.is_file():
        return load_config(config_path)
    return load_config_from_env()
