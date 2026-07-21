"""Permission-mode switching — copies static perms/*.permissions.json,
perms/*.sandbox.json, and perms/*.hooks.json profiles into the target
workspace's .cursor/ before the next agent call.

Three files, and as of this commit NONE of the three actually block a native
write — all three are live-retested and confirmed insufficient (2026-07-06):
- permissions.json steers the auto_review classifier — shell/MCP/Fetch only.
- sandbox.json + sandbox_options constrains shell-spawned processes
  (filesystem/shell/network) per the SDK docs — does not cover the native
  write/edit tool.
- hooks.json's `preToolUse` hook (matcher `Write|Delete`, readonly.hooks.json
  runs perms/hooks/deny-write.sh) was the next candidate — the hook script
  never even executes during a local Agent.prompt() run (confirmed by
  instrumenting it and finding no invocation), regardless of setting_sources.
  The hook schema/validation code exists in the vendored bridge's bundled
  @cursor/sdk, but nothing appears to wire up file-based hooks.json dispatch
  for the local SDK runtime — still true on 1.0.24 live smoke (2026-07-21);
  hooks may remain IDE/cloud-only for this path.

Left in place because it's cheap and harmless (may start working in a future
SDK version), but do not rely on it. Actual enforcement is `guard_writes()`
below: a git snapshot/revert safety net around each readonly-mode call,
chosen 2026-07-06 after all three SDK mechanisms failed live retests.

`interactive` is deliberately absent from SUPPORTED_MODES — confirmed unshippable
in V1 (no held-call resolution hook in this SDK version). `locked` is a kill
switch handled in bot.py (no agent forwarding); apply_mode() is a no-op for it.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

SUPPORTED_MODES: Final[tuple[str, ...]] = ("locked", "readonly", "standard")


def sandbox_enabled_for_mode(mode: str) -> bool:
    """Whether to enable the SDK sandbox for shell/git subprocesses.

    Readonly: on — workspace_readonly fence (+ guard_writes git revert).
    Standard: off — workspace_readwrite still blocks git push to a bare repo
    path outside workspace_path; disabling sandbox matches README's commit/push
    promise for that layout.
    """
    return mode == "readonly"


def auto_review_for_mode(mode: str) -> bool:
    """Whether Smart Auto Review classifies shell/MCP before running.

    Standard: off — headless Telegram has no interactive approve/deny (V1).
    Readonly: on — classifier + terminalAllowlist limits shell to git read cmds.
    """
    return mode == "readonly"


def setting_sources_for_mode(mode: str) -> tuple[str, ...]:
    """Load workspace .cursor/permissions.json copied by apply_mode()."""
    return ("project",) if mode in ("readonly", "standard") else ()


def apply_mode(mode: str, *, perms_dir: Path, workspace_path: Path) -> None:
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"unsupported perms mode: {mode!r} (available: {', '.join(SUPPORTED_MODES)})")
    if mode == "locked":
        return
    dest_dir = workspace_path / ".cursor"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(perms_dir / f"{mode}.permissions.json", dest_dir / "permissions.json")
    shutil.copyfile(perms_dir / f"{mode}.sandbox.json", dest_dir / "sandbox.json")
    shutil.copyfile(perms_dir / f"{mode}.hooks.json", dest_dir / "hooks.json")
    hooks_dest_dir = dest_dir / "hooks"
    hooks_dest_dir.mkdir(exist_ok=True)
    shutil.copy(perms_dir / "hooks" / "deny-write.sh", hooks_dest_dir / "deny-write.sh")


def _status_lines(workspace_path: Path) -> set[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    # .cursor/*.json churn is our own apply_mode() writes, not agent content —
    # excluded so switching modes never looks like a "write" to revert.
    return {line for line in result.stdout.splitlines() if not line[3:].startswith(".cursor/")}


def _revert_path(workspace_path: Path, path: str) -> None:
    restored = subprocess.run(
        ["git", "checkout", "-q", "HEAD", "--", path],
        cwd=workspace_path,
        capture_output=True,
        timeout=10,
        check=False,
    )
    if restored.returncode != 0:
        # No HEAD version — it's a new file. Unstage (if staged) and delete.
        subprocess.run(["git", "reset", "-q", "--", path], cwd=workspace_path, timeout=10, check=False)
        (workspace_path / path).unlink(missing_ok=True)


@contextmanager
def guard_writes(mode: str, workspace_path: Path) -> Iterator[list[str]]:
    """Best-effort readonly enforcement via git, not the SDK.

    Not preventive — the write briefly happens, then gets reverted once the
    call finishes (including on error, via try/finally). Snapshots `git
    status --porcelain` (excluding `.cursor/`) before and after; any path
    that's new in the "after" snapshot gets checked out from HEAD (or
    deleted, if it has no HEAD version) and reported back via the yielded
    list.

    ponytail: only catches paths that were clean *before* the call. A
    pre-existing dirty path modified further during the call keeps the same
    status line and won't be detected as new. Upgrade path if that matters:
    diff file *contents*/hashes instead of just status lines.

    No-op outside readonly mode (`standard` is meant to allow writes).
    """
    reverted: list[str] = []
    if mode != "readonly":
        yield reverted
        return
    before = _status_lines(workspace_path)
    try:
        yield reverted
    finally:
        for line in _status_lines(workspace_path) - before:
            path = line[3:]
            _revert_path(workspace_path, path)
            reverted.append(path)
