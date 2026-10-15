#!/usr/bin/env python3
"""SIGKILL the cursor-sdk-bridge ancestor of this process.

The agent runs this as a shell tool, which is the Oct 14 shape: a tool call
is already in flight, so recovery must not replay the prompt. SIGKILL stops
the bridge from marking the run terminal itself.

Refuses to run without --i-mean-it. Never signals the process group, and
never kills the telegram_cursor_agent parent.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path


def read_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace")


def read_ppid(pid: int) -> int | None:
    try:
        text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("PPid:"):
            return int(line.split()[1])
    return None


def bridge_ancestor(
    pid: int,
    read_cmdline: Callable[[int], str],
    read_ppid: Callable[[int], int | None],
) -> int | None:
    """Nearest ancestor whose cmdline contains cursor-sdk-bridge.

    Returns None when a telegram_cursor_agent process is closer, or when no
    bridge ancestor exists. Starts at the parent of pid, not pid itself.
    """
    current = read_ppid(pid)
    seen: set[int] = set()
    while current is not None and current > 1 and current not in seen and len(seen) < 20:
        seen.add(current)
        command = read_cmdline(current)
        if "telegram_cursor_agent" in command:
            return None
        if "cursor-sdk-bridge" in command:
            return current
        current = read_ppid(current)
    return None


def main() -> None:
    if "--i-mean-it" not in sys.argv:
        print("refusing: pass --i-mean-it", file=sys.stderr)
        raise SystemExit(2)
    target = bridge_ancestor(os.getpid(), read_cmdline, read_ppid)
    if target is None:
        print("crash_bridge: no cursor-sdk-bridge ancestor; nothing killed", file=sys.stderr)
        raise SystemExit(1)
    print(f"crash_bridge: killing pid={target}", flush=True)
    time.sleep(1)
    os.kill(target, signal.SIGKILL)


if __name__ == "__main__":
    main()
