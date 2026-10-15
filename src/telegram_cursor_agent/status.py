"""Deterministic /status — last commit, git status summary, uptime, bridge. No agent call."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from telegram_cursor_agent.bridge import BridgeSnapshot, format_bridge_block

_START_TIME: float = time.monotonic()


def build_status(
    *,
    workspace_path: Path,
    mode: str,
    model: str,
    bridge: BridgeSnapshot | None = None,
) -> str:
    commit = _git(workspace_path, "log", "-1", "--format=%h %s")
    git_status = _git(workspace_path, "status", "--short") or "clean"
    uptime_s = int(time.monotonic() - _START_TIME)
    text = (
        f"mode: {mode}\n"
        f"model: {model}\n"
        f"last commit: {commit}\n"
        f"git status:\n{git_status}\n"
        f"uptime: {uptime_s}s"
    )
    if bridge is None:
        return text
    return f"{text}\n{format_bridge_block(bridge)}"


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10, check=False)
    return result.stdout.strip()
