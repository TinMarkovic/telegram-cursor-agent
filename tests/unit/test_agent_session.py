import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from cursor_sdk.errors import CursorAgentError, InternalServerError, UnsupportedRunOperationError

from telegram_cursor_agent.agent_session import (
    BRIDGE_TOKEN_BUG,
    SessionManager,
    SessionState,
    format_run_failure,
    is_bridge_token_bug,
    load_state,
    lookup_run_error,
    save_state,
    validate_model,
    with_bridge_retry,
)
from telegram_cursor_agent.config import DEFAULT_SESSION_HEADER_TEMPLATE, Config
from telegram_cursor_agent.models import DEFAULT_MODEL_ALIASES


def _run_result(status: str, result: str | None = None, run_id: str = "run-1") -> SimpleNamespace:
    return SimpleNamespace(status=status, result=result, id=run_id)


@pytest.fixture
def manager(tmp_path: Path) -> SessionManager:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    data = tmp_path / "data"
    config = Config(
        workspace_path=workspace,
        allowed_sender_ids=frozenset({111111111}),
        default_model="claude-sonnet-5",
        default_perms_mode="standard",
        perms_dir=Path("./perms"),
        session_store_dir=data,
        session_header_template=DEFAULT_SESSION_HEADER_TEMPLATE,
        model_aliases=dict(DEFAULT_MODEL_ALIASES),
    )
    return SessionManager(
        config=config,
        api_key="test-key",
        state_path=data / "session.toml",
        store_root=data / "agents",
        default_chat_id=111111111,
    )


def test_session_state_property_requires_start(manager: SessionManager) -> None:
    with pytest.raises(RuntimeError, match="session not started"):
        _ = manager.state


def test_update_runtime_state_persists_perms_mode(manager: SessionManager, tmp_path: Path) -> None:
    manager._state = SessionState(
        chat_id=111111111,
        agent_id="agent-1",
        model="claude-sonnet-5",
        perms_mode="standard",
    )

    manager.update_runtime_state(perms_mode="readonly")

    loaded = load_state(manager._state_path)
    assert loaded is not None
    assert loaded.perms_mode == "readonly"


def test_lookup_run_error_returns_last_match(tmp_path: Path) -> None:
    store = tmp_path / "agents"
    store.mkdir()
    lines = [
        {"runId": "run-1", "error": "first"},
        {"runId": "run-2", "error": "other"},
        {"runId": "run-1", "error": "Authentication error If you are logged in, try logging out and back in."},
    ]
    (store / "runs.ndjson").write_text("\n".join(json.dumps(o) for o in lines) + "\n", encoding="utf-8")

    assert lookup_run_error(store, "run-1") == (
        "Authentication error If you are logged in, try logging out and back in."
    )
    assert lookup_run_error(store, "missing") is None


def test_format_run_failure_includes_store_error() -> None:
    msg = format_run_failure("error", run_id="run-9", store_error="Authentication error boom")
    assert "status=error" in msg
    assert "run_id=run-9" in msg
    assert "Authentication error boom" in msg


def test_send_and_wait_returns_result_text(manager: SessionManager) -> None:
    run = AsyncMock()
    run.wait = AsyncMock(return_value=_run_result("finished", "hello"))
    agent = AsyncMock()
    agent.send = AsyncMock(return_value=run)
    manager._agent = agent
    manager._state = SessionState(
        chat_id=1, agent_id="a", model="claude-sonnet-5", perms_mode="standard", header_sent=True
    )

    assert asyncio.run(manager.send_and_wait("hi")) == "hello"
    agent.send.assert_awaited_once()


def test_send_and_wait_resumes_after_error_status(manager: SessionManager) -> None:
    fail_run = AsyncMock()
    fail_run.wait = AsyncMock(return_value=_run_result("error", None, "run-err"))
    ok_run = AsyncMock()
    ok_run.wait = AsyncMock(return_value=_run_result("finished", "recovered"))

    agent = AsyncMock()
    agent.send = AsyncMock(side_effect=[fail_run, ok_run])
    agent.close = AsyncMock()
    manager._agent = agent
    manager._state = SessionState(
        chat_id=1, agent_id="agent-a", model="claude-sonnet-5", perms_mode="standard", header_sent=True
    )
    manager._store_root.mkdir(parents=True, exist_ok=True)
    (manager._store_root / "runs.ndjson").write_text(
        json.dumps({"runId": "run-err", "error": "Authentication error stale token"}) + "\n",
        encoding="utf-8",
    )

    resumed = AsyncMock()
    resumed.agent_id = "agent-a"
    resumed.send = AsyncMock(return_value=ok_run)
    manager._client = AsyncMock()
    manager._client.resume_agent = AsyncMock(return_value=resumed)

    assert asyncio.run(manager.send_and_wait("hi")) == "recovered"
    manager._client.resume_agent.assert_awaited_once()
    assert agent.send.await_count == 1
    assert resumed.send.await_count == 1


def test_send_and_wait_create_fallback_when_resume_retry_fails(manager: SessionManager) -> None:
    err_run = AsyncMock()
    err_run.wait = AsyncMock(return_value=_run_result("error", None, "run-e"))
    ok_run = AsyncMock()
    ok_run.wait = AsyncMock(return_value=_run_result("finished", "fresh"))

    old_agent = AsyncMock()
    old_agent.send = AsyncMock(return_value=err_run)
    old_agent.close = AsyncMock()
    resumed_agent = AsyncMock()
    resumed_agent.send = AsyncMock(return_value=err_run)
    resumed_agent.close = AsyncMock()
    resumed_agent.agent_id = "agent-a"
    new_agent = AsyncMock()
    new_agent.send = AsyncMock(return_value=ok_run)
    new_agent.agent_id = "agent-b"

    manager._agent = old_agent
    manager._state = SessionState(
        chat_id=1, agent_id="agent-a", model="claude-sonnet-5", perms_mode="standard", header_sent=True
    )
    manager._client = AsyncMock()
    manager._client.resume_agent = AsyncMock(return_value=resumed_agent)
    manager._client.create_agent = AsyncMock(return_value=new_agent)

    assert asyncio.run(manager.send_and_wait("hi")) == "fresh"
    manager._client.resume_agent.assert_awaited_once()
    manager._client.create_agent.assert_awaited_once()
    assert manager._state.agent_id == "agent-b"


def test_send_and_wait_surfaces_store_error_when_recovery_exhausted(manager: SessionManager) -> None:
    err_run = AsyncMock()
    err_run.wait = AsyncMock(return_value=_run_result("error", None, "run-e"))
    agent = AsyncMock()
    agent.send = AsyncMock(return_value=err_run)
    agent.close = AsyncMock()
    agent.agent_id = "agent-x"

    manager._agent = agent
    manager._state = SessionState(
        chat_id=1, agent_id="agent-a", model="claude-sonnet-5", perms_mode="standard", header_sent=True
    )
    manager._store_root.mkdir(parents=True, exist_ok=True)
    (manager._store_root / "runs.ndjson").write_text(
        json.dumps({"runId": "run-e", "error": "Authentication error If you are logged in"}) + "\n",
        encoding="utf-8",
    )
    manager._client = AsyncMock()
    manager._client.resume_agent = AsyncMock(return_value=agent)
    manager._client.create_agent = AsyncMock(return_value=agent)

    reply = asyncio.run(manager.send_and_wait("hi"))
    assert "status=error" in reply
    assert "Authentication error" in reply


def test_send_and_wait_cancelled_does_not_resume(manager: SessionManager) -> None:
    run = AsyncMock()
    run.wait = AsyncMock(return_value=_run_result("cancelled", None, "run-c"))
    agent = AsyncMock()
    agent.send = AsyncMock(return_value=run)
    manager._agent = agent
    manager._state = SessionState(
        chat_id=1, agent_id="agent-a", model="claude-sonnet-5", perms_mode="standard", header_sent=True
    )
    manager._client = AsyncMock()

    reply = asyncio.run(manager.send_and_wait("hi"))
    assert "status=cancelled" in reply
    manager._client.resume_agent.assert_not_awaited()
    manager._client.create_agent.assert_not_awaited()


def test_send_and_wait_internal_server_error_resumes_first(manager: SessionManager) -> None:
    ok_run = AsyncMock()
    ok_run.wait = AsyncMock(return_value=_run_result("finished", "ok"))
    agent = AsyncMock()
    agent.send = AsyncMock(side_effect=InternalServerError("boom"))
    agent.close = AsyncMock()
    manager._agent = agent
    manager._state = SessionState(
        chat_id=1, agent_id="agent-a", model="claude-sonnet-5", perms_mode="standard", header_sent=True
    )
    resumed = AsyncMock()
    resumed.agent_id = "agent-a"
    resumed.send = AsyncMock(return_value=ok_run)
    manager._client = AsyncMock()
    manager._client.resume_agent = AsyncMock(return_value=resumed)

    assert asyncio.run(manager.send_and_wait("hi")) == "ok"
    manager._client.resume_agent.assert_awaited_once()
    manager._client.create_agent.assert_not_awaited()


def test_cancel_in_flight_no_op_when_idle(manager: SessionManager) -> None:
    assert asyncio.run(manager.cancel_in_flight()) is False


def test_cancel_in_flight_returns_false_when_unsupported(manager: SessionManager) -> None:
    run = MagicMock()
    run.supports.return_value = False
    manager._active_run = run

    assert asyncio.run(manager.cancel_in_flight()) is False


def test_cancel_in_flight_cancels_active_run(manager: SessionManager) -> None:
    # supports() is sync — MagicMock; only cancel() is awaited
    run = MagicMock()
    run.supports.return_value = True
    run.cancel = AsyncMock()
    manager._active_run = run

    assert asyncio.run(manager.cancel_in_flight()) is True
    run.cancel.assert_awaited_once()


def test_cancel_in_flight_swallows_unsupported_operation(manager: SessionManager) -> None:
    run = MagicMock()
    run.supports.return_value = True
    run.cancel = AsyncMock(side_effect=UnsupportedRunOperationError("done"))
    manager._active_run = run

    assert asyncio.run(manager.cancel_in_flight()) is False


def test_load_state_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_state(tmp_path / "session.toml") is None


def test_sidecar_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "session.toml"
    original = SessionState(
        chat_id=111111111,
        agent_id="local-abc123",
        model="claude-sonnet-5",
        perms_mode="readonly",
        header_sent=True,
    )

    save_state(path, original)
    loaded = load_state(path)

    assert loaded == original


def test_is_bridge_token_bug_matches_signature() -> None:
    err = CursorAgentError(BRIDGE_TOKEN_BUG, code="invalid_argument")

    assert is_bridge_token_bug(err) is True


def test_is_bridge_token_bug_rejects_other_errors() -> None:
    err = CursorAgentError("boom", code="unauthenticated")

    assert is_bridge_token_bug(err) is False


def test_with_bridge_retry_retries_exactly_once_on_token_bug() -> None:
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise CursorAgentError(BRIDGE_TOKEN_BUG, code="invalid_argument")
        return "ok"

    result = asyncio.run(with_bridge_retry(flaky))

    assert result == "ok"
    assert calls == 2


def test_with_bridge_retry_reraises_other_cursor_agent_errors() -> None:
    calls = 0

    async def fail() -> None:
        nonlocal calls
        calls += 1
        raise CursorAgentError("boom", code="unauthenticated")

    with pytest.raises(CursorAgentError, match="boom"):
        asyncio.run(with_bridge_retry(fail))

    assert calls == 1


def test_validate_model_rejects_unknown_id() -> None:
    client = AsyncMock()
    client.list_models = AsyncMock(return_value=[type("M", (), {"id": "claude-sonnet-5"})()])

    with pytest.raises(ValueError, match="unknown model"):
        asyncio.run(validate_model("nope", api_key="key", client=client, aliases=DEFAULT_MODEL_ALIASES))


def test_validate_model_accepts_known_id() -> None:
    client = AsyncMock()
    client.list_models = AsyncMock(return_value=[type("M", (), {"id": "claude-sonnet-5"})()])

    assert (
        asyncio.run(validate_model("claude-sonnet-5", api_key="key", client=client, aliases=DEFAULT_MODEL_ALIASES))
        == "claude-sonnet-5"
    )


def test_validate_model_resolves_alias() -> None:
    client = AsyncMock()
    client.list_models = AsyncMock(
        return_value=[
            type("M", (), {"id": "claude-sonnet-5"})(),
            type("M", (), {"id": "composer-2.5"})(),
        ]
    )

    assert (
        asyncio.run(validate_model("s5", api_key="key", client=client, aliases=DEFAULT_MODEL_ALIASES))
        == "claude-sonnet-5"
    )


def test_wrap_with_session_header_prepends_once(manager: SessionManager) -> None:
    manager._state = SessionState(
        chat_id=1, agent_id="a", model="claude-sonnet-5", perms_mode="standard", header_sent=False
    )

    wrapped = manager._wrap_with_session_header("hello")

    assert "Telegram bridge context" in wrapped
    assert wrapped.endswith("hello")
    assert manager._state.header_sent is True
    assert manager._wrap_with_session_header("again") == "again"
