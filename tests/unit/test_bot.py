import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from cursor_sdk.errors import CursorAgentError
from telegram import Message, Update
from telegram.ext import Application, ContextTypes, filters

import telegram_cursor_agent.bot as bot_module
from telegram_cursor_agent.bot import (
    BOT_COMMANDS,
    TELEGRAM_MESSAGE_LIMIT,
    _post_init,
    _split_for_telegram,
    cmd_cancel,
    cmd_new,
    cmd_perms,
    cmd_status,
    handle_message,
)
from telegram_cursor_agent.config import DEFAULT_SESSION_HEADER_TEMPLATE, Config
from telegram_cursor_agent.models import DEFAULT_MODEL_ALIASES

ALLOWED_ID = 111111111
DISALLOWED_ID = 999999999


def _fake_message(user_id: int) -> Message:
    return cast(Message, SimpleNamespace(from_user=SimpleNamespace(id=user_id)))


def _fake_text_message(text: str | None) -> SimpleNamespace:
    return SimpleNamespace(text=text, chat_id=ALLOWED_ID, reply_text=AsyncMock())


def _fake_update(message: SimpleNamespace | None) -> Update:
    return cast(Update, SimpleNamespace(message=message))


def _fake_context(bot_data: dict, args: list[str] | None = None) -> ContextTypes.DEFAULT_TYPE:
    return cast(
        ContextTypes.DEFAULT_TYPE,
        SimpleNamespace(bot_data=bot_data, args=args, bot=SimpleNamespace()),
    )


def _make_config(tmp_path: Path, **overrides: object) -> Config:
    defaults: dict[str, object] = {
        "workspace_path": tmp_path,
        "allowed_sender_ids": frozenset({ALLOWED_ID}),
        "default_model": "claude-sonnet-5",
        "default_perms_mode": "standard",
        "perms_dir": tmp_path,
        "session_store_dir": tmp_path / "data",
        "session_header_template": DEFAULT_SESSION_HEADER_TEMPLATE,
        "model_aliases": dict(DEFAULT_MODEL_ALIASES),
    }
    defaults.update(overrides)
    return Config(**defaults)


@pytest.fixture(autouse=True)
def passthrough_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run(bot: object, chat_id: int, factory: object) -> object:
        coro = factory() if callable(factory) else factory
        assert asyncio.iscoroutine(coro)
        return await coro

    monkeypatch.setattr(bot_module, "run_with_progress", _run)


def _fake_session(
    *,
    send_reply: str = "agent reply",
    send_error: CursorAgentError | None = None,
    new_reply: str = "new session started (model=claude-sonnet-5)",
    new_error: ValueError | None = None,
    cancel_result: bool = False,
) -> SimpleNamespace:
    async def send_and_wait(prompt: str) -> str:
        if send_error is not None:
            raise send_error
        return send_reply

    async def new_session(model: str | None) -> str:
        if new_error is not None:
            raise new_error
        return new_reply

    return SimpleNamespace(
        send_and_wait=send_and_wait,
        new_session=new_session,
        cancel_in_flight=AsyncMock(return_value=cancel_result),
        update_runtime_state=lambda **kwargs: None,
        relaunch_bridge=AsyncMock(),
        header_notice_for_next_send=lambda: None,
        state=SimpleNamespace(model="claude-sonnet-5", perms_mode="standard"),
    )


def test_allowlist_filter_accepts_allowed_sender() -> None:
    allowlist = filters.User(user_id=frozenset({ALLOWED_ID}))

    assert allowlist.filter(_fake_message(ALLOWED_ID)) is True


def test_allowlist_filter_rejects_disallowed_sender() -> None:
    allowlist = filters.User(user_id=frozenset({ALLOWED_ID}))

    assert allowlist.filter(_fake_message(DISALLOWED_ID)) is False


def test_split_for_telegram_returns_empty_list_for_empty_text() -> None:
    assert _split_for_telegram("") == []


def test_split_for_telegram_returns_single_chunk_under_limit() -> None:
    text = "hello world"

    assert _split_for_telegram(text) == [text]


def test_split_for_telegram_splits_and_rejoins_losslessly() -> None:
    text = "x" * 9000

    chunks = _split_for_telegram(text)

    assert all(len(chunk) <= TELEGRAM_MESSAGE_LIMIT for chunk in chunks)
    assert "".join(chunks) == text
    assert len(chunks) == 3


def test_cmd_status_replies_without_agent_call(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    message = _fake_text_message("/status")
    context = _fake_context({"config": config, "perms_mode": "standard", "model": "claude-sonnet-5"})

    asyncio.run(cmd_status(_fake_update(message), context))

    message.reply_text.assert_awaited_once()
    reply = message.reply_text.await_args.args[0]
    assert "mode: standard" in reply
    assert "model: claude-sonnet-5" in reply


def test_cmd_perms_no_args_reports_state() -> None:
    context = _fake_context({"perms_mode": "standard", "model": "claude-sonnet-5"}, args=[])
    message = _fake_text_message("/perms")

    asyncio.run(cmd_perms(_fake_update(message), context))

    reply = message.reply_text.await_args.args[0]
    assert "mode: standard" in reply
    assert "available modes: locked, readonly, standard" in reply


def test_cmd_perms_switches_to_valid_mode(tmp_path: Path) -> None:
    perms_dir = tmp_path / "perms"
    perms_dir.mkdir()
    (perms_dir / "readonly.permissions.json").write_text("{}")
    (perms_dir / "readonly.sandbox.json").write_text('{"type": "workspace_readonly"}')
    (perms_dir / "readonly.hooks.json").write_text('{"version": 1, "hooks": {}}')
    (perms_dir / "hooks").mkdir()
    (perms_dir / "hooks" / "deny-write.sh").write_text('#!/usr/bin/env bash\necho \'{"permission": "deny"}\'\n')
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _make_config(tmp_path, workspace_path=workspace, perms_dir=perms_dir)
    session = _fake_session()
    bot_data = {
        "config": config,
        "perms_mode": "standard",
        "model": "claude-sonnet-5",
        "session": session,
    }
    context = _fake_context(bot_data, args=["readonly"])
    message = _fake_text_message("/perms readonly")

    asyncio.run(cmd_perms(_fake_update(message), context))

    assert bot_data["perms_mode"] == "readonly"
    assert (workspace / ".cursor" / "permissions.json").exists()
    message.reply_text.assert_awaited_once_with("perms mode set to readonly")


def test_cmd_perms_accepts_locked_mode(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    session = _fake_session()
    bot_data = {"config": config, "perms_mode": "standard", "model": "claude-sonnet-5", "session": session}
    context = _fake_context(bot_data, args=["locked"])
    message = _fake_text_message("/perms locked")

    asyncio.run(cmd_perms(_fake_update(message), context))

    assert bot_data["perms_mode"] == "locked"
    assert not (tmp_path / ".cursor").exists()
    message.reply_text.assert_awaited_once_with("perms mode set to locked")


def test_cmd_perms_rejects_unsupported_mode(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    session = _fake_session()
    bot_data = {"config": config, "perms_mode": "standard", "model": "claude-sonnet-5", "session": session}
    context = _fake_context(bot_data, args=["interactive"])
    message = _fake_text_message("/perms interactive")

    asyncio.run(cmd_perms(_fake_update(message), context))

    assert bot_data["perms_mode"] == "standard"
    reply = message.reply_text.await_args.args[0]
    assert "unsupported perms mode" in reply


def test_cmd_new_rejects_invalid_model(tmp_path: Path) -> None:
    session = _fake_session(new_error=ValueError("unknown model: 'nope'"))
    context = _fake_context({"session": session, "model": "claude-sonnet-5"}, args=["nope"])
    message = _fake_text_message("/new nope")

    asyncio.run(cmd_new(_fake_update(message), context))

    message.reply_text.assert_awaited_once_with("unknown model: 'nope'")


def test_cmd_cancel_no_op_when_idle(tmp_path: Path) -> None:
    session = _fake_session(cancel_result=False)
    context = _fake_context({"session": session})
    message = _fake_text_message("/cancel")

    asyncio.run(cmd_cancel(_fake_update(message), context))

    session.cancel_in_flight.assert_awaited_once()
    message.reply_text.assert_awaited_once_with("no in-flight run to cancel")


def test_cmd_cancel_reports_cancelled(tmp_path: Path) -> None:
    session = _fake_session(cancel_result=True)
    context = _fake_context({"session": session})
    message = _fake_text_message("/cancel")

    asyncio.run(cmd_cancel(_fake_update(message), context))

    message.reply_text.assert_awaited_once_with("cancelled in-flight run")


def test_handle_message_ignores_update_without_text(tmp_path: Path) -> None:
    context = _fake_context(
        {
            "config": _make_config(tmp_path),
            "model": "claude-sonnet-5",
            "cursor_api_key": "x",
            "perms_mode": "standard",
            "session": _fake_session(),
        }
    )
    message = _fake_text_message(None)

    asyncio.run(handle_message(_fake_update(message), context))

    message.reply_text.assert_not_awaited()


def test_handle_message_locked_does_not_call_session(tmp_path: Path) -> None:
    session = _fake_session()
    context = _fake_context(
        {
            "config": _make_config(tmp_path),
            "model": "claude-sonnet-5",
            "cursor_api_key": "x",
            "perms_mode": "locked",
            "session": session,
        }
    )
    message = _fake_text_message("hello")

    asyncio.run(handle_message(_fake_update(message), context))

    message.reply_text.assert_awaited_once_with("received (locked — not forwarded to agent)")


def test_handle_message_forwards_to_session_and_replies(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    async def send_and_wait(prompt: str) -> str:
        captured["prompt"] = prompt
        return "README first line"

    session = SimpleNamespace(send_and_wait=send_and_wait, header_notice_for_next_send=lambda: None)
    config = _make_config(tmp_path)
    context = _fake_context(
        {
            "config": config,
            "model": "claude-sonnet-5",
            "cursor_api_key": "test-key",
            "perms_mode": "standard",
            "session": session,
        }
    )
    message = _fake_text_message("what's the first line of README.md?")

    asyncio.run(handle_message(_fake_update(message), context))

    assert captured["prompt"] == "what's the first line of README.md?"
    assert message.reply_text.await_args_list[-1].args[0] == "README first line"


def test_handle_message_reports_cursor_agent_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    session = _fake_session(send_error=CursorAgentError("boom", code="unauthenticated"))
    config = _make_config(tmp_path)
    context = _fake_context(
        {
            "config": config,
            "model": "claude-sonnet-5",
            "cursor_api_key": "bad-key",
            "perms_mode": "standard",
            "session": session,
        }
    )
    message = _fake_text_message("hello")

    asyncio.run(handle_message(_fake_update(message), context))

    assert message.reply_text.await_args_list[-1].args[0] == "Agent call failed: boom"


def test_bot_commands_cover_slash_menu() -> None:
    assert [c.command for c in BOT_COMMANDS] == ["status", "perms", "new", "cancel"]
    assert all(c.description for c in BOT_COMMANDS)


def test_post_init_registers_bot_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    session = _fake_session()
    session.start = AsyncMock()
    session.state = SimpleNamespace(model="claude-sonnet-5", perms_mode="locked")
    monkeypatch.setattr(bot_module, "SessionManager", lambda **_kwargs: session)

    set_my_commands = AsyncMock()
    app = cast(
        Application,
        SimpleNamespace(
            bot_data={
                "config": _make_config(tmp_path),
                "cursor_api_key": "test-key",
            },
            bot=SimpleNamespace(set_my_commands=set_my_commands),
        ),
    )

    asyncio.run(_post_init(app))

    set_my_commands.assert_awaited_once_with(BOT_COMMANDS)
    assert app.bot_data["session"] is session
    assert app.bot_data["model"] == "claude-sonnet-5"
    assert app.bot_data["perms_mode"] == "locked"


def test_handle_message_appends_reverted_note_when_guard_reports_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    session = _fake_session(send_reply="done")

    @contextmanager
    def fake_guard_writes(mode: str, workspace_path: Path) -> Iterator[list[str]]:
        yield ["sneaky.txt"]

    monkeypatch.setattr(bot_module.perms, "guard_writes", fake_guard_writes)

    config = _make_config(tmp_path)
    context = _fake_context(
        {
            "config": config,
            "model": "claude-sonnet-5",
            "cursor_api_key": "test-key",
            "perms_mode": "readonly",
            "session": session,
        }
    )
    message = _fake_text_message("touch sneaky.txt")

    asyncio.run(handle_message(_fake_update(message), context))

    reply = message.reply_text.await_args_list[-1].args[0]
    assert "reverted 1 write attempt(s): sneaky.txt" in reply
