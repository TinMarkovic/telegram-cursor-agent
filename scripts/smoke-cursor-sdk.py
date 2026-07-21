#!/usr/bin/env python3
"""One-shot smoke: cursor-sdk (>=1.0.24) + SessionManager path + readonly guard_writes.

Uses local config.toml / .env and the configured workspace_path (throwaway clone).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from telegram_cursor_agent.agent_session import SessionManager  # noqa: E402
from telegram_cursor_agent.config import load_config  # noqa: E402
from telegram_cursor_agent.perms import apply_mode, guard_writes  # noqa: E402


def fail(msg: str) -> None:
    print(f"FAIL  {msg}")
    raise SystemExit(1)


def ok(msg: str) -> None:
    print(f"PASS  {msg}")


async def main() -> None:
    load_dotenv(ROOT / ".env")
    api_key = os.environ["CURSOR_API_KEY"]
    config = load_config(ROOT / "config.toml")
    workspace = config.workspace_path
    if not workspace.is_dir():
        fail(f"workspace missing: {workspace}")

    pip_ver = version("cursor-sdk")
    pip_parts = tuple(int(p) for p in pip_ver.split(".")[:3])
    if pip_parts < (1, 0, 24):
        fail(f"expected cursor-sdk>=1.0.24, got {pip_ver}")
    bridge_pkg = Path(__import__("cursor_sdk").__file__).parent / "_vendor/bridge/node_modules/@cursor/sdk/package.json"
    bridge_ver = json.loads(bridge_pkg.read_text())["version"]
    ok(f"pip={pip_ver} bundled=@cursor/sdk {bridge_ver}")

    data_dir = Path(tempfile.mkdtemp(prefix="tca-sdk-smoke-"))
    print(f"data_dir={data_dir}")
    print(f"workspace={workspace}")

    apply_mode("standard", perms_dir=config.perms_dir, workspace_path=workspace)
    session = SessionManager(
        config=config,
        api_key=api_key,
        state_path=data_dir / "session.toml",
        store_root=data_dir / "agents",
        default_chat_id=next(iter(config.allowed_sender_ids)),
    )
    await session.start()
    session.update_runtime_state(perms_mode="standard")
    reply = await session.send_and_wait("Reply with only the single word: pong")
    if "Agent call failed" in reply or "pong" not in reply.lower():
        fail(f"standard send bad reply: {reply!r}")
    ok(f"standard send: {reply.strip()[:80]!r}")

    # Readonly scar: native Write should still be possible; guard_writes reverts.
    apply_mode("readonly", perms_dir=config.perms_dir, workspace_path=workspace)
    await session.relaunch_bridge()
    session.update_runtime_state(perms_mode="readonly")
    marker = workspace / "SDK_SMOKE_WRITE_PROBE.txt"
    if marker.exists():
        marker.unlink()

    with guard_writes("readonly", workspace) as written:
        probe_reply = await session.send_and_wait(
            "Create a file named SDK_SMOKE_WRITE_PROBE.txt containing exactly: smoke. "
            "Do not ask questions; just write the file."
        )
    if marker.exists():
        fail(f"readonly write survived guard_writes; reply={probe_reply!r} written={written}")
    if not written:
        # Hooks/permissions may have started blocking — still a pass, but note it.
        ok(f"readonly: no writes observed (SDK may have blocked). reply={probe_reply.strip()[:80]!r}")
    else:
        ok(f"readonly: guard_writes reverted {written}; reply={probe_reply.strip()[:80]!r}")

    await session.close()
    ok("smoke complete")


if __name__ == "__main__":
    asyncio.run(main())
