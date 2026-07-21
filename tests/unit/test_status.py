from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from telegram_cursor_agent import status


def _fake_run(cmd: list[str], **_: Any) -> SimpleNamespace:
    if cmd[1] == "log":
        return SimpleNamespace(stdout="abc1234 fix: something\n")
    if cmd[1] == "status":
        return SimpleNamespace(stdout=" M README.md\n")
    raise AssertionError(f"unexpected git subcommand: {cmd}")


def test_build_status_shape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(status.subprocess, "run", _fake_run)

    output = status.build_status(workspace_path=tmp_path, mode="readonly", model="claude-sonnet-5")

    assert "mode: readonly" in output
    assert "model: claude-sonnet-5" in output
    assert "abc1234 fix: something" in output
    assert "M README.md" in output


def test_build_status_reports_clean_when_no_status_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _clean_run(cmd: list[str], **_: Any) -> SimpleNamespace:
        if cmd[1] == "log":
            return SimpleNamespace(stdout="abc1234 initial\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(status.subprocess, "run", _clean_run)

    output = status.build_status(workspace_path=tmp_path, mode="standard", model="claude-sonnet-5")

    assert "git status:\nclean" in output
