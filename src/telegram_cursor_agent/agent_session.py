"""Persistent Cursor agent session — sqlite store, sidecar state, bridge retry."""

from __future__ import annotations

import asyncio
import json
import logging
import tomllib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from cursor_sdk import AgentOptions, AsyncClient, LocalAgentOptions, LocalAgentStoreConfig, SandboxOptions, SendOptions
from cursor_sdk.errors import CursorAgentError, InternalServerError, NetworkError, UnsupportedRunOperationError

if TYPE_CHECKING:
    from cursor_sdk._async_agent import AsyncAgent
    from cursor_sdk._async_run import AsyncRun

from telegram_cursor_agent.config import Config, build_session_header
from telegram_cursor_agent.models import resolve_model_input
from telegram_cursor_agent.perms import auto_review_for_mode, sandbox_enabled_for_mode, setting_sources_for_mode

log = logging.getLogger(__name__)

BRIDGE_TOKEN_BUG = "Missing value for --tool-callback-auth-token"

T = TypeVar("T")


@dataclass
class SessionState:
    chat_id: int
    agent_id: str | None
    model: str
    perms_mode: str
    header_sent: bool = False


@dataclass
class RunFailed(Exception):
    """Soft run terminal status that may be recoverable via resume/create."""

    status: str
    run_id: str
    message: str

    def __str__(self) -> str:
        return self.message


def lookup_run_error(store_root: Path, run_id: str) -> str | None:
    """Return the last `error` string for run_id from runs.ndjson, if any."""
    if not run_id:
        return None
    path = store_root / "runs.ndjson"
    if not path.is_file():
        return None
    found: str | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as err:
        log.warning("could not read %s: %s", path, err)
        return None
    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("runId") != run_id:
            continue
        error_text = obj.get("error")
        if isinstance(error_text, str) and error_text.strip():
            found = error_text.strip()
    return found


def format_run_failure(
    status: str,
    *,
    run_id: str = "",
    result_text: str = "",
    store_error: str | None = None,
) -> str:
    detail = store_error or result_text or "no text returned"
    if run_id:
        return f"(run finished with status={status}, run_id={run_id}: {detail})"
    return f"(run finished with status={status}: {detail})"


def _toml_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def load_state(path: Path) -> SessionState | None:
    if not path.is_file():
        return None
    with path.open("rb") as f:
        data = tomllib.load(f)
    agent_id = data.get("agent_id") or None
    header_sent = bool(data.get("header_sent", False))
    return SessionState(
        chat_id=int(data["chat_id"]),
        agent_id=str(agent_id) if agent_id else None,
        model=str(data["model"]),
        perms_mode=str(data["perms_mode"]),
        header_sent=header_sent,
    )


def save_state(path: Path, state: SessionState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    agent_id_line = f"agent_id = {_toml_quote(state.agent_id)}\n" if state.agent_id else 'agent_id = ""\n'
    path.write_text(
        f"chat_id = {state.chat_id}\n"
        f"{agent_id_line}"
        f"model = {_toml_quote(state.model)}\n"
        f"perms_mode = {_toml_quote(state.perms_mode)}\n"
        f"header_sent = {'true' if state.header_sent else 'false'}\n",
        encoding="utf-8",
    )


def is_bridge_token_bug(err: CursorAgentError) -> bool:
    return BRIDGE_TOKEN_BUG in err.message


async def with_bridge_retry[T](coro_factory: Callable[[], Awaitable[T]]) -> T:
    try:
        return await coro_factory()
    except CursorAgentError as err:
        if is_bridge_token_bug(err):
            return await coro_factory()
        raise


async def validate_model(model: str, *, api_key: str, client: AsyncClient, aliases: dict[str, str]) -> str:
    resolved = resolve_model_input(model, aliases)
    models = await client.list_models(api_key=api_key)
    known = {entry.id for entry in models}
    if resolved not in known:
        raise ValueError(f"unknown model: {model!r}")
    return resolved


class SessionManager:
    def __init__(
        self,
        *,
        config: Config,
        api_key: str,
        state_path: Path,
        store_root: Path,
        default_chat_id: int,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._state_path = state_path
        self._store_root = store_root
        self._default_chat_id = default_chat_id
        self._client: AsyncClient | None = None
        self._agent: AsyncAgent | None = None
        self._state: SessionState | None = None
        self._active_run: AsyncRun | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> SessionState:
        if self._state is None:
            raise RuntimeError("session not started")
        return self._state

    def _local_options(self) -> LocalAgentOptions:
        self._store_root.mkdir(parents=True, exist_ok=True)
        mode = self._state.perms_mode if self._state else self._config.default_perms_mode
        sources = setting_sources_for_mode(mode)
        return LocalAgentOptions(
            cwd=str(self._config.workspace_path),
            setting_sources=list(sources),
            auto_review=auto_review_for_mode(mode),
            sandbox_options=SandboxOptions(enabled=sandbox_enabled_for_mode(mode)),
            store=LocalAgentStoreConfig(type="sqlite", root_dir=str(self._store_root)),
        )

    async def relaunch_bridge(self) -> None:
        """Restart bridge so sandbox_options match the current perms mode."""
        if self._agent is not None:
            try:
                await self._agent.close()
            except NetworkError as err:
                log.warning("agent close failed during bridge relaunch: %s", err.message)
            self._agent = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except NetworkError as err:
                log.warning("client close failed during bridge relaunch: %s", err.message)
            self._client = None

        async def launch() -> AsyncClient:
            return await AsyncClient.launch_bridge(
                workspace=str(self._config.workspace_path),
                state_root=str(self._store_root),
                local=self._local_options(),
            )

        self._client = await with_bridge_retry(launch)
        if self._state is None:
            return
        if self._state.agent_id:
            try:
                await self._resume_agent(self._state.agent_id)
                return
            except CursorAgentError as err:
                log.warning("resume failed after bridge relaunch: %s", err.message)
        await self._create_agent(self._state.model)

    async def start(self) -> None:
        self._store_root.mkdir(parents=True, exist_ok=True)

        async def launch() -> AsyncClient:
            return await AsyncClient.launch_bridge(
                workspace=str(self._config.workspace_path),
                state_root=str(self._store_root),
                local=self._local_options(),
            )

        self._client = await with_bridge_retry(launch)
        saved = load_state(self._state_path)
        if saved is None:
            self._state = SessionState(
                chat_id=self._default_chat_id,
                agent_id=None,
                model=self._config.default_model,
                perms_mode=self._config.default_perms_mode,
            )
            await self._create_agent(self._state.model)
            return

        self._state = saved
        if saved.agent_id:
            try:
                await self._resume_agent(saved.agent_id)
                return
            except CursorAgentError as err:
                log.warning("resume failed for %s: %s — creating fresh session", saved.agent_id, err.message)
        await self._create_agent(saved.model)

    async def close(self) -> None:
        if self._agent is not None:
            try:
                await self._agent.close()
            except NetworkError as err:
                log.warning("agent close failed (bridge gone): %s", err.message)
            self._agent = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except NetworkError as err:
                log.warning("client close failed: %s", err.message)
            self._client = None

    def persist(self) -> None:
        if self._state is not None:
            save_state(self._state_path, self._state)

    def update_runtime_state(self, *, model: str | None = None, perms_mode: str | None = None) -> None:
        if self._state is None:
            return
        if model is not None:
            self._state.model = model
        if perms_mode is not None:
            self._state.perms_mode = perms_mode
        self.persist()

    def header_notice_for_next_send(self) -> str | None:
        if self._state is not None and not self._state.header_sent and self._config.session_header_template is not None:
            return f"→ agent ({self._state.perms_mode}, {self._state.model})"
        return None

    def _wrap_with_session_header(self, prompt: str) -> str:
        if self._state is None or self._state.header_sent or self._config.session_header_template is None:
            return prompt
        header = build_session_header(
            template=self._config.session_header_template,
            workspace=self._config.workspace_path,
            mode=self._state.perms_mode,
            model=self._state.model,
        )
        self._state.header_sent = True
        self.persist()
        return f"{header}\n\n---\n\n{prompt}"

    async def new_session(self, model: str | None) -> str:
        assert self._client is not None and self._state is not None
        raw = model if model is not None else self._state.model
        chosen = await validate_model(
            raw, api_key=self._api_key, client=self._client, aliases=self._config.model_aliases
        )
        self._state.header_sent = False
        await self._create_agent(chosen)
        return f"new session started (model={chosen})"

    async def send_and_wait(self, prompt: str) -> str:
        if self._agent is None:
            raise RuntimeError("session agent not available")
        wrapped = self._wrap_with_session_header(prompt)
        try:
            return await self._send_and_wait_once(wrapped)
        except RunFailed as err:
            return await self._recover_send(prompt, wrapped, reason=str(err))
        except InternalServerError as err:
            return await self._recover_send(prompt, wrapped, reason=err.message)

    async def _recover_send(self, prompt: str, wrapped: str, *, reason: str) -> str:
        if self._state is None:
            raise RuntimeError("session not started")

        agent_id = self._state.agent_id
        if agent_id:
            try:
                log.warning("run failed (%s) — resuming agent %s", reason, agent_id)
                await self._resume_agent(agent_id)
                return await self._send_and_wait_once(wrapped)
            except RunFailed as err:
                log.warning("retry after resume still failed (%s) — creating fresh session", err)
            except InternalServerError as err:
                log.warning(
                    "retry after resume still failed (%s) — creating fresh session",
                    err.message,
                )
            except CursorAgentError as err:
                log.warning("resume failed (%s) — creating fresh session", err.message)

        log.warning("creating fresh session after recovery (%s)", reason)
        self._state.header_sent = False
        await self._create_agent(self._state.model)
        wrapped = self._wrap_with_session_header(prompt)
        try:
            return await self._send_and_wait_once(wrapped)
        except RunFailed as err:
            return err.message
        except InternalServerError as err:
            return f"Agent call failed: {err.message}"

    async def _send_and_wait_once(self, prompt: str) -> str:
        agent = self._agent
        if agent is None:
            raise RuntimeError("session agent not available")
        async with self._lock:
            run = await agent.send(prompt, SendOptions(model=self._state.model if self._state else None))
            self._active_run = run
            try:
                result = await run.wait()
            except CursorAgentError:
                raise
            finally:
                self._active_run = None

        run_id = getattr(result, "id", "") or ""
        store_error = lookup_run_error(self._store_root, run_id)
        log.info("agent run finished: status=%s run_id=%s", result.status, run_id or "-")
        if result.status == "finished":
            return result.result or ""

        message = format_run_failure(
            str(result.status),
            run_id=run_id,
            result_text=result.result or "",
            store_error=store_error,
        )
        if store_error:
            log.warning("run failure detail: %s", store_error)
        else:
            log.warning("run failure: %s", message)

        if result.status == "cancelled":
            return message
        # error / expired / unknown non-success — recover in send_and_wait
        raise RunFailed(status=str(result.status), run_id=run_id, message=message)

    async def cancel_in_flight(self) -> bool:
        run = self._active_run
        if run is None:
            return False
        if not run.supports("cancel"):
            return False
        try:
            await run.cancel()
            return True
        except UnsupportedRunOperationError:
            return False

    async def _close_agent(self) -> None:
        if self._agent is None:
            return
        try:
            await self._agent.close()
        except NetworkError as err:
            log.warning("agent close failed: %s", err.message)
        self._agent = None

    async def _resume_agent(self, agent_id: str) -> None:
        client = self._client
        assert client is not None
        model = self._state.model if self._state else None

        async def do_resume() -> AsyncAgent:
            return await client.resume_agent(
                agent_id,
                AgentOptions(api_key=self._api_key, model=model, local=self._local_options()),
            )

        await self._close_agent()
        self._agent = await with_bridge_retry(do_resume)
        if self._state is not None:
            self._state.agent_id = self._agent.agent_id
            self.persist()

    async def _create_agent(self, model: str) -> None:
        client = self._client
        assert client is not None and self._state is not None

        async def do_create() -> AsyncAgent:
            return await client.create_agent(
                api_key=self._api_key,
                model=model,
                local=self._local_options(),
            )

        await self._close_agent()
        self._agent = await with_bridge_retry(do_create)
        self._state.model = model
        self._state.agent_id = self._agent.agent_id
        self.persist()
