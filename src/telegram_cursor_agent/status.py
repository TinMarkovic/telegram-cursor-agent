"""Deterministic /status — last commit, git status summary, uptime. No agent call."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

_START_TIME: float = time.monotonic()


def build_status(*, workspace_path: Path, mode: str, model: str) -> str:
    commit = _git(workspace_path, "log", "-1", "--format=%h %s")
    git_status = _git(workspace_path, "status", "--short") or "clean"
    uptime_s = int(time.monotonic() - _START_TIME)
    return (
        f"mode: {mode}\n"
        f"model: {model}\n"
        f"last commit: {commit}\n"
        f"git status:\n{git_status}\n"
        f"uptime: {uptime_s}s"
    )


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10, check=False)
    return result.stdout.strip()
