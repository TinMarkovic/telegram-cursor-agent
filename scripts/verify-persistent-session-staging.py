#!/usr/bin/env python3
"""Walk llm/verify/persistent-session.md Steps 7–13 against live SDK + throwaway clone."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from dotenv import load_dotenv
from telegram.ext import ContextTypes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from telegram_cursor_agent import bot as bot_module  # noqa: E402
from telegram_cursor_agent.agent_session import SessionManager, load_state  # noqa: E402
from telegram_cursor_agent.config import Config, load_config  # noqa: E402
from telegram_cursor_agent.perms import apply_mode  # noqa: E402


def ok(step: str, detail: str = "") -> None:
    msg = f"PASS  {step}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def fail(step: str, detail: str) -> None:
    print(f"FAIL  {step} — {detail}", file=sys.stderr)
    sys.exit(1)


class AsyncMockWrapper:
    def __init__(self) -> None:
        self.last: str = ""
        self.calls: list[str] = []

    async def __call__(self, text: str, *args: object, **kwargs: object) -> None:
        self.last = text
        self.calls.append(text)


def fake_update(message: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(message=message)


def fake_bot_context(
    config: object,
    api_key: str,
    session: SessionManager,
    *,
    args: list[str] | None = None,
    perms_mode: str | None = None,
) -> ContextTypes.DEFAULT_TYPE:
    mode = perms_mode if perms_mode is not None else session.state.perms_mode
    return cast(
        ContextTypes.DEFAULT_TYPE,
        SimpleNamespace(
            bot_data={
                "config": config,
                "cursor_api_key": api_key,
                "session": session,
                "model": session.state.model,
                "perms_mode": mode,
            },
            args=args or [],
        ),
    )


async def make_session(data_dir: Path, config: Config, api_key: str) -> SessionManager:
    chat_id = next(iter(config.allowed_sender_ids))
    session = SessionManager(
        config=config,
        api_key=api_key,
        state_path=data_dir / "session.toml",
        store_root=data_dir / "agents",
        default_chat_id=chat_id,
    )
    await session.start()
    return session


async def run_staging() -> None:
    load_dotenv(ROOT / ".env")
    api_key = os.environ["CURSOR_API_KEY"]
    config = load_config(ROOT / "config.toml")
    workspace = config.workspace_path

    data_dir = Path(tempfile.mkdtemp(prefix="tca-verify-"))
    print(f"staging data_dir={data_dir}")
    print(f"workspace={workspace}")

    try:
        session = await make_session(data_dir, config, api_key)
        reply1 = await session.send_and_wait("Remember the codeword PERSIST-TEST-42. Reply with only: acknowledged")
        if "Agent call failed" in reply1 or not reply1.strip():
            fail("Step 7", f"bad reply: {reply1!r}")
        ok("Step 7", f"reply={reply1[:100]!r}")

        agent_id_before = session.state.agent_id
        if not agent_id_before:
            fail("Step 7", "no agent_id after first send")

        sidecar = load_state(data_dir / "session.toml")
        if not sidecar or not sidecar.agent_id:
            fail("Step 7", "session.toml missing agent_id")
        ok("Step 7 sidecar", f"agent_id={sidecar.agent_id}")

        await session.close()

        session2 = await make_session(data_dir, config, api_key)
        if session2.state.agent_id != agent_id_before:
            fail("Step 8", f"agent_id changed: {agent_id_before} -> {session2.state.agent_id}")
        reply2 = await session2.send_and_wait("What codeword did I ask you to remember? Reply with only the codeword.")
        if "PERSIST-TEST-42" not in reply2:
            fail("Step 8", f"expected codeword in reply, got: {reply2!r}")
        ok("Step 8", "remembered codeword, agent_id unchanged")

        message = SimpleNamespace(reply_text=AsyncMockWrapper())
        await bot_module.cmd_new(
            fake_update(message),
            fake_bot_context(config, api_key, session2, args=["not-a-real-model-id"]),
        )
        if "unknown model" not in message.reply_text.last:
            fail("Step 9", f"expected unknown model error, got: {message.reply_text.last!r}")
        ok("Step 9", message.reply_text.last)

        old_agent_id = session2.state.agent_id
        message2 = SimpleNamespace(reply_text=AsyncMockWrapper())
        await bot_module.cmd_new(fake_update(message2), fake_bot_context(config, api_key, session2, args=[]))
        if session2.state.agent_id == old_agent_id:
            fail("Step 10", "agent_id did not change after /new")
        reply3 = await session2.send_and_wait(
            "What was the exact first message I sent you in this conversation? "
            "Reply with only that message text, verbatim."
        )
        if "PERSIST-TEST-42" in reply3 or "codeword" in reply3.lower():
            fail("Step 10", f"still has prior conversation after /new: {reply3!r}")
        ok("Step 10", f"forgot codeword, new agent_id={session2.state.agent_id}")

        msg_locked = SimpleNamespace(text="Say hello", reply_text=AsyncMockWrapper())
        await bot_module.handle_message(
            fake_update(msg_locked),
            fake_bot_context(config, api_key, session2, perms_mode="locked"),
        )
        if "locked" not in msg_locked.reply_text.last:
            fail("Step 11", f"expected locked ack, got: {msg_locked.reply_text.last!r}")
        ok("Step 11", msg_locked.reply_text.last)

        apply_mode("standard", perms_dir=config.perms_dir, workspace_path=workspace)
        session2.update_runtime_state(perms_mode="standard")

        slow_task = asyncio.create_task(
            session2.send_and_wait("Read every file under src/ and summarize each in one sentence")
        )
        await asyncio.sleep(3)
        msg_cancel = SimpleNamespace(reply_text=AsyncMockWrapper())
        await bot_module.cmd_cancel(fake_update(msg_cancel), fake_bot_context(config, api_key, session2))
        cancel_reply = msg_cancel.reply_text.last or ""
        if "cancelled" not in cancel_reply and "no in-flight" not in cancel_reply:
            fail("Step 12", f"unexpected cancel reply: {cancel_reply!r}")
        ok("Step 12", cancel_reply)

        try:
            await asyncio.wait_for(slow_task, timeout=180)
        except Exception:
            pass

        msg_status = SimpleNamespace(reply_text=AsyncMockWrapper())
        ctx_status = fake_bot_context(config, api_key, session2, perms_mode="standard")
        await bot_module.cmd_status(fake_update(msg_status), ctx_status)
        if "mode:" not in msg_status.reply_text.last:
            fail("Step 12", "/status failed after cancel")
        ok("Step 12 /status", "instant reply after cancel")

        apply_mode("readonly", perms_dir=config.perms_dir, workspace_path=workspace)
        session2.update_runtime_state(perms_mode="readonly")
        probe = workspace / "telegram-agent-readonly-probe.txt"
        probe.unlink(missing_ok=True)

        with bot_module.perms.guard_writes("readonly", workspace):
            await session2.send_and_wait(
                "Create a new file named telegram-agent-readonly-probe.txt containing the word probe"
            )

        porcelain = subprocess.run(
            ["git", "status", "--porcelain"], cwd=workspace, capture_output=True, text=True, check=False
        ).stdout
        if "telegram-agent-readonly-probe" in porcelain:
            fail("Step 13", f"file still in git status: {porcelain!r}")
        if probe.exists():
            fail("Step 13", "probe file still on disk")
        ok("Step 13", "file absent, git clean")

        apply_mode("standard", perms_dir=config.perms_dir, workspace_path=workspace)
        await session2.close()

        print("\nAll staging steps 7–13 passed.")
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(run_staging())
