import subprocess
from pathlib import Path

import pytest

from telegram_cursor_agent.perms import (
    apply_mode,
    auto_review_for_mode,
    guard_writes,
    sandbox_enabled_for_mode,
    setting_sources_for_mode,
)

PROFILE_MODES = ("readonly", "standard")


def test_standard_permissions_includes_git_allowlist() -> None:
    import json

    repo_perms = Path(__file__).resolve().parents[2] / "perms" / "standard.permissions.json"
    data = json.loads(repo_perms.read_text())
    assert "git" in data["terminalAllowlist"]


def test_sandbox_enabled_only_in_readonly() -> None:
    assert sandbox_enabled_for_mode("readonly") is True
    assert sandbox_enabled_for_mode("standard") is False
    assert sandbox_enabled_for_mode("locked") is False


def test_auto_review_only_in_readonly() -> None:
    assert auto_review_for_mode("readonly") is True
    assert auto_review_for_mode("standard") is False


def test_setting_sources_loads_project_profiles() -> None:
    assert setting_sources_for_mode("standard") == ("project",)
    assert setting_sources_for_mode("readonly") == ("project",)
    assert setting_sources_for_mode("locked") == ()


@pytest.fixture
def perms_dir(tmp_path: Path) -> Path:
    d = tmp_path / "perms"
    d.mkdir()
    (d / "readonly.permissions.json").write_text('{"terminalAllowlist": []}')
    (d / "standard.permissions.json").write_text('{"terminalAllowlist": ["git status"]}')
    (d / "readonly.sandbox.json").write_text('{"type": "workspace_readonly"}')
    (d / "standard.sandbox.json").write_text('{"type": "workspace_readwrite"}')
    (d / "readonly.hooks.json").write_text(
        '{"version": 1, "hooks": {"preToolUse": [{"command": "hooks/deny-write.sh"}]}}'
    )
    (d / "standard.hooks.json").write_text('{"version": 1, "hooks": {}}')
    (d / "hooks").mkdir()
    (d / "hooks" / "deny-write.sh").write_text('#!/usr/bin/env bash\necho \'{"permission": "deny"}\'\n')
    return d


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    d = tmp_path / "workspace"
    d.mkdir()
    return d


@pytest.mark.parametrize("mode", PROFILE_MODES)
def test_apply_mode_copies_exact_profile_content(mode: str, perms_dir: Path, workspace: Path) -> None:
    apply_mode(mode, perms_dir=perms_dir, workspace_path=workspace)

    dest = workspace / ".cursor" / "permissions.json"
    assert dest.read_text() == (perms_dir / f"{mode}.permissions.json").read_text()


@pytest.mark.parametrize("mode", PROFILE_MODES)
def test_apply_mode_copies_exact_sandbox_content(mode: str, perms_dir: Path, workspace: Path) -> None:
    apply_mode(mode, perms_dir=perms_dir, workspace_path=workspace)

    dest = workspace / ".cursor" / "sandbox.json"
    assert dest.read_text() == (perms_dir / f"{mode}.sandbox.json").read_text()


@pytest.mark.parametrize("mode", PROFILE_MODES)
def test_apply_mode_copies_exact_hooks_content(mode: str, perms_dir: Path, workspace: Path) -> None:
    apply_mode(mode, perms_dir=perms_dir, workspace_path=workspace)

    dest = workspace / ".cursor" / "hooks.json"
    assert dest.read_text() == (perms_dir / f"{mode}.hooks.json").read_text()


def test_apply_mode_copies_hook_script(perms_dir: Path, workspace: Path) -> None:
    apply_mode("readonly", perms_dir=perms_dir, workspace_path=workspace)

    dest = workspace / ".cursor" / "hooks" / "deny-write.sh"
    assert dest.read_text() == (perms_dir / "hooks" / "deny-write.sh").read_text()


def test_apply_mode_creates_missing_cursor_dir(perms_dir: Path, workspace: Path) -> None:
    assert not (workspace / ".cursor").exists()

    apply_mode("readonly", perms_dir=perms_dir, workspace_path=workspace)

    assert (workspace / ".cursor" / "permissions.json").exists()
    assert (workspace / ".cursor" / "sandbox.json").exists()
    assert (workspace / ".cursor" / "hooks.json").exists()


def test_apply_mode_rejects_unsupported_mode(perms_dir: Path, workspace: Path) -> None:
    with pytest.raises(ValueError, match="unsupported perms mode"):
        apply_mode("interactive", perms_dir=perms_dir, workspace_path=workspace)

    assert not (workspace / ".cursor").exists()


def test_apply_mode_locked_is_noop(perms_dir: Path, workspace: Path) -> None:
    apply_mode("locked", perms_dir=perms_dir, workspace_path=workspace)

    assert not (workspace / ".cursor").exists()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    run = lambda *args: subprocess.run(["git", *args], cwd=d, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "test")
    (d / "tracked.txt").write_text("original\n")
    run("add", "tracked.txt")
    run("commit", "-q", "-m", "initial")
    return d


def _porcelain(repo: Path) -> str:
    return subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True).stdout


def test_guard_writes_is_noop_outside_readonly(git_repo: Path) -> None:
    with guard_writes("standard", git_repo) as reverted:
        (git_repo / "new.txt").write_text("agent wrote this\n")

    assert reverted == []
    assert (git_repo / "new.txt").exists()


def test_guard_writes_reverts_new_untracked_file(git_repo: Path) -> None:
    with guard_writes("readonly", git_repo) as reverted:
        (git_repo / "new.txt").write_text("agent wrote this\n")

    assert reverted == ["new.txt"]
    assert not (git_repo / "new.txt").exists()
    assert _porcelain(git_repo) == ""


def test_guard_writes_reverts_modified_tracked_file(git_repo: Path) -> None:
    with guard_writes("readonly", git_repo) as reverted:
        (git_repo / "tracked.txt").write_text("agent overwrote this\n")

    assert reverted == ["tracked.txt"]
    assert (git_repo / "tracked.txt").read_text() == "original\n"


def test_guard_writes_reports_nothing_when_nothing_changes(git_repo: Path) -> None:
    with guard_writes("readonly", git_repo) as reverted:
        pass

    assert reverted == []


def test_guard_writes_ignores_dot_cursor_churn(git_repo: Path) -> None:
    (git_repo / ".cursor").mkdir()
    with guard_writes("readonly", git_repo) as reverted:
        (git_repo / ".cursor" / "permissions.json").write_text("{}")

    assert reverted == []
    assert (git_repo / ".cursor" / "permissions.json").exists()


def test_guard_writes_reverts_even_when_call_raises(git_repo: Path) -> None:
    with pytest.raises(RuntimeError), guard_writes("readonly", git_repo) as reverted:
        (git_repo / "new.txt").write_text("agent wrote this\n")
        raise RuntimeError("boom")

    assert reverted == ["new.txt"]
    assert not (git_repo / "new.txt").exists()
