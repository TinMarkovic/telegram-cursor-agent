"""Telegram progress UX — typing indicator + long-run heartbeats."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from telegram.constants import ChatAction

if TYPE_CHECKING:
    from telegram import Bot

log = logging.getLogger(__name__)

TYPING_INTERVAL_S = 4.0
HEARTBEAT_INTERVAL_S = 120.0
HEARTBEAT_STEP_START = 20
HEARTBEAT_STEP_INCREMENT = 30


async def run_with_progress[T](
    bot: Bot,
    chat_id: int,
    coro_factory: Callable[[], Awaitable[T]],
) -> T:
    """Run an agent call with typing action and periodic heartbeat edits until done or failed."""
    done = asyncio.Event()
    step_hint = HEARTBEAT_STEP_START

    progress_msg = await bot.send_message(chat_id, "working on it…")

    async def typing_loop() -> None:
        while not done.is_set():
            try:
                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except Exception as err:
                log.warning("typing action failed: %s", err)
                return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(done.wait(), timeout=TYPING_INTERVAL_S)

    async def heartbeat_loop() -> None:
        nonlocal step_hint
        while not done.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(done.wait(), timeout=HEARTBEAT_INTERVAL_S)
                return
            step_hint += HEARTBEAT_STEP_INCREMENT
            try:
                await progress_msg.edit_text(
                    f"This is taking a while, but I'm still working on it. (~{step_hint} steps)"
                )
            except Exception as err:
                log.warning("heartbeat edit failed: %s", err)

    typing_task = asyncio.create_task(typing_loop())
    heartbeat_task = asyncio.create_task(heartbeat_loop())
    try:
        return await coro_factory()
    finally:
        done.set()
        for task in (typing_task, heartbeat_task):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        with contextlib.suppress(Exception):
            await progress_msg.delete()
