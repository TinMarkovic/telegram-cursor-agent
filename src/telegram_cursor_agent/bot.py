"""Telegram polling bot — sender allowlist, persistent agent session, /status, /perms."""

from __future__ import annotations

import logging
import os
import sys
import traceback
from typing import cast

from cursor_sdk.errors import CursorAgentError
from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram.error import NetworkError
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from telegram_cursor_agent import perms, status
from telegram_cursor_agent.agent_session import SessionManager
from telegram_cursor_agent.config import Config, resolve_config
from telegram_cursor_agent.progress import run_with_progress

TELEGRAM_MESSAGE_LIMIT: int = 4096

BOT_COMMANDS: tuple[BotCommand, ...] = (
    BotCommand("status", "Repo snapshot: mode, model, git status, uptime"),
    BotCommand("perms", "Show or switch permission mode"),
    BotCommand("new", "Fresh agent session; optional model"),
    BotCommand("cancel", "Cancel the in-flight agent run"),
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)


def _split_for_telegram(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split text into <=limit-char chunks that rejoin to the original exactly."""
    if not text:
        return []
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def _session(context: ContextTypes.DEFAULT_TYPE) -> SessionManager:
    return cast(SessionManager, context.bot_data["session"])


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    config: Config = context.bot_data["config"]
    mode: str = context.bot_data["perms_mode"]
    model: str = context.bot_data["model"]
    reply = status.build_status(workspace_path=config.workspace_path, mode=mode, model=model)
    log.info("status requested (mode=%s, model=%s)", mode, model)
    await update.message.reply_text(reply)


async def cmd_perms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    if not context.args:
        mode = context.bot_data["perms_mode"]
        model = context.bot_data["model"]
        await update.message.reply_text(
            f"mode: {mode}\nmodel: {model}\navailable modes: {', '.join(perms.SUPPORTED_MODES)}"
        )
        return

    config: Config = context.bot_data["config"]
    requested_mode = context.args[0]
    try:
        perms.apply_mode(requested_mode, perms_dir=config.perms_dir, workspace_path=config.workspace_path)
    except ValueError as err:
        await update.message.reply_text(str(err))
        return

    context.bot_data["perms_mode"] = requested_mode
    session = _session(context)
    session.update_runtime_state(perms_mode=requested_mode)
    await session.relaunch_bridge()
    log.info("perms mode switched to %s", requested_mode)
    await update.message.reply_text(f"perms mode set to {requested_mode}")


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    model = context.args[0] if context.args else None
    try:
        reply = await _session(context).new_session(model)
    except ValueError as err:
        await update.message.reply_text(str(err))
        return
    except CursorAgentError as err:
        log.error("new session failed: %s", err.message)
        await update.message.reply_text(f"Agent call failed: {err.message}")
        return
    except Exception as err:
        log.exception("new session unexpected error")
        await update.message.reply_text(f"Unexpected error: {type(err).__name__}: {err}"[:TELEGRAM_MESSAGE_LIMIT])
        return

    context.bot_data["model"] = _session(context).state.model
    await update.message.reply_text(reply)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    cancelled = await _session(context).cancel_in_flight()
    if cancelled:
        await update.message.reply_text("cancelled in-flight run")
    else:
        await update.message.reply_text("no in-flight run to cancel")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None or not message.text:
        return
    text = message.text

    config: Config = context.bot_data["config"]
    mode: str = context.bot_data["perms_mode"]

    if mode == "locked":
        await message.reply_text("received (locked — not forwarded to agent)")
        return

    session = _session(context)
    header_notice = session.header_notice_for_next_send()
    if header_notice:
        await message.reply_text(header_notice)

    try:
        with perms.guard_writes(mode, config.workspace_path) as reverted:
            reply_text = await run_with_progress(
                context.bot,
                message.chat_id,
                lambda: session.send_and_wait(text),
            )
    except CursorAgentError as err:
        log.error("agent send failed: %s", err.message)
        await message.reply_text(f"Agent call failed: {err.message}")
        return
    except Exception as err:
        log.exception("message handler unexpected error")
        await message.reply_text(f"Unexpected error: {type(err).__name__}: {err}"[:TELEGRAM_MESSAGE_LIMIT])
        return

    if reverted:
        log.warning("readonly mode: reverted %d write attempt(s): %s", len(reverted), ", ".join(reverted))
        reply_text += f"\n\n⚠️ readonly mode: reverted {len(reverted)} write attempt(s): {', '.join(reverted)}"
    for chunk in _split_for_telegram(reply_text):
        await message.reply_text(chunk)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    err = context.error
    if isinstance(err, NetworkError):
        log.warning("telegram network error: %s", err)
        return
    log.error(
        "unhandled telegram error: %s\n%s",
        err,
        "".join(traceback.format_exception(type(err), err, err.__traceback__)) if err else "",
    )


async def _post_init(app: Application) -> None:
    config: Config = app.bot_data["config"]
    api_key: str = app.bot_data["cursor_api_key"]
    default_chat_id = next(iter(config.allowed_sender_ids))
    store_root = config.session_store_dir / "agents"
    state_path = config.session_store_dir / "session.toml"
    session = SessionManager(
        config=config,
        api_key=api_key,
        state_path=state_path,
        store_root=store_root,
        default_chat_id=default_chat_id,
    )
    await session.start()
    app.bot_data["session"] = session
    app.bot_data["model"] = session.state.model
    app.bot_data["perms_mode"] = session.state.perms_mode
    if session.state.perms_mode != "locked":
        perms.apply_mode(
            session.state.perms_mode,
            perms_dir=config.perms_dir,
            workspace_path=config.workspace_path,
        )
    await app.bot.set_my_commands(BOT_COMMANDS)
    log.info("registered bot commands: %s", ", ".join(c.command for c in BOT_COMMANDS))


async def _post_shutdown(app: Application) -> None:
    await app.bot_data["session"].close()


def main() -> None:
    load_dotenv()
    config = resolve_config()

    app = (
        Application.builder()
        .token(os.environ["TELEGRAM_BOT_TOKEN"])
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data.update(
        config=config,
        cursor_api_key=os.environ["CURSOR_API_KEY"],
    )

    allowlist = filters.User(user_id=config.allowed_sender_ids)
    app.add_handler(CommandHandler("status", cmd_status, filters=allowlist))
    app.add_handler(CommandHandler("perms", cmd_perms, filters=allowlist))
    app.add_handler(CommandHandler("new", cmd_new, filters=allowlist))
    app.add_handler(CommandHandler("cancel", cmd_cancel, filters=allowlist))
    app.add_handler(MessageHandler(allowlist & filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(on_error)

    log.info("telegram-cursor-agent starting — polling, workspace=%s", config.workspace_path)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
