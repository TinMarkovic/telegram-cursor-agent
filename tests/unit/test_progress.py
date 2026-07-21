import asyncio

import pytest
from telegram.constants import ChatAction

from telegram_cursor_agent import progress


def test_run_with_progress_returns_result_and_cleans_up() -> None:
    sent_typing = 0
    deleted = False

    class FakeMessage:
        async def edit_text(self, text: str) -> None:
            pass

        async def delete(self) -> None:
            nonlocal deleted
            deleted = True

    class FakeBot:
        async def send_message(self, chat_id: int, text: str) -> FakeMessage:
            return FakeMessage()

        async def send_chat_action(self, chat_id: int, action: str) -> None:
            nonlocal sent_typing
            if action == ChatAction.TYPING:
                sent_typing += 1

    async def work() -> str:
        await asyncio.sleep(0.05)
        return "done"

    bot = FakeBot()
    result = asyncio.run(progress.run_with_progress(bot, 1, work))

    assert result == "done"
    assert sent_typing >= 1
    assert deleted is True


def test_run_with_progress_cleans_up_on_failure() -> None:
    deleted = False

    class FakeMessage:
        async def edit_text(self, text: str) -> None:
            pass

        async def delete(self) -> None:
            nonlocal deleted
            deleted = True

    class FakeBot:
        async def send_message(self, chat_id: int, text: str) -> FakeMessage:
            return FakeMessage()

        async def send_chat_action(self, chat_id: int, action: str) -> None:
            pass

    async def work() -> None:
        raise RuntimeError("boom")

    bot = FakeBot()
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(progress.run_with_progress(bot, 1, work))

    assert deleted is True
