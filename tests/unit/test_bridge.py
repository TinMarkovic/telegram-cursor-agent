import asyncio
import importlib.util
import logging
import sqlite3
import sys
from pathlib import Path

import pytest
from cursor_sdk.errors import InternalServerError, NetworkError

from telegram_cursor_agent.bridge import (
    BridgeSnapshot,
    BridgeWatch,
    close_wedged_run,
    is_bridge_disconnect,
    log_bridge_failure,
    sdk_index_db,
    watch_bridge,
)

_SCHEMA = """
CREATE TABLE agents (
    agent_id TEXT PRIMARY KEY,
    workspace_ref TEXT NOT NULL,
    status TEXT NOT NULL,
    active_run_id TEXT,
    latest_checkpoint_ref_json TEXT,
    name TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    request_id TEXT,
    agent_id TEXT NOT NULL,
    turn_number INTEGER NOT NULL,
    status TEXT NOT NULL,
    model TEXT,
    model_params_json TEXT,
    start_checkpoint_ref_json TEXT,
    latest_checkpoint_ref_json TEXT,
    error_code TEXT,
    usage_ref TEXT,
    usage_json TEXT,
    result TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    cancelled_at TEXT,
    expired_at TEXT
);
CREATE TABLE run_events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    offset TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT,
    payload_ref TEXT,
    idempotency_key TEXT,
    created_at TEXT NOT NULL
);
"""

_NOW = "2026-10-14T15:59:21.000Z"
_PIPE_CHILD = """
import sys
sys.stderr.buffer.write(b"cursor-sdk-bridge ready {}\\n")
sys.stderr.buffer.write(b"x" * 70000)
sys.stderr.buffer.write(b"\\nSENTINEL-AFTER-PIPE\\n")
sys.stderr.buffer.flush()
"""
_SIGNAL_CHILD = """
import os, signal, sys
sys.stderr.write("after-discovery\\n")
sys.stderr.flush()
os.kill(os.getpid(), signal.SIGKILL)
"""


def write_index(
    path: Path,
    *,
    agents: list[tuple[str, str, str | None]],
    runs: list[tuple[str, str, str]],
    events: list[tuple[str, int, str, str]] | None = None,
) -> None:
    """agents: (agent_id, status, active_run_id). runs: (run_id, agent_id, status)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    conn.executemany(
        """
        INSERT INTO agents (
            agent_id, workspace_ref, status, active_run_id, metadata_json, created_at, updated_at
        ) VALUES (?, 'ws', ?, ?, '{}', ?, ?)
        """,
        [(agent_id, status, active, _NOW, _NOW) for agent_id, status, active in agents],
    )
    conn.executemany(
        """
        INSERT INTO runs (
            run_id, agent_id, turn_number, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [(run_id, agent_id, index + 1, status, _NOW, _NOW) for index, (run_id, agent_id, status) in enumerate(runs)],
    )
    if events:
        conn.executemany(
            """
            INSERT INTO run_events (run_id, seq, offset, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(run_id, seq, str(seq), event_type, payload, _NOW) for run_id, seq, event_type, payload in events],
        )
    conn.commit()
    conn.close()


def _load_crash_bridge() -> object:
    path = Path(__file__).resolve().parents[2] / "scripts" / "crash_bridge.py"
    spec = importlib.util.spec_from_file_location("crash_bridge", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_watch_bridge_drains_stderr_past_pipe_buffer(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    async def scenario() -> BridgeWatch:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _PIPE_CHILD,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        sink = BridgeWatch(pid=proc.pid)
        await asyncio.wait_for(watch_bridge(proc, sink), timeout=5)
        return sink

    sink = asyncio.run(scenario())

    assert sink.exited is True
    assert sink.exit_code == 0
    assert sink.signal is None
    assert "SENTINEL-AFTER-PIPE" in caplog.text


def test_watch_bridge_records_signal_on_exit() -> None:
    async def scenario() -> BridgeWatch:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _SIGNAL_CHILD,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        sink = BridgeWatch(pid=proc.pid)
        await asyncio.wait_for(watch_bridge(proc, sink), timeout=5)
        return sink

    sink = asyncio.run(scenario())
    snapshot = sink.snapshot()

    assert snapshot.up is False
    assert snapshot.exit_code is None
    assert snapshot.signal == 9
    assert snapshot.pid == sink.pid


def test_record_exit_maps_shell_wrapper_137_to_sigkill() -> None:
    killed = BridgeWatch(pid=1)
    killed.record_exit(137)
    plain = BridgeWatch(pid=1)
    plain.record_exit(1)

    assert killed.exit_code is None
    assert killed.signal == 9
    assert plain.exit_code == 1
    assert plain.signal is None


def test_sdk_index_db_matches_cursor_sdk_default_layout() -> None:
    path = sdk_index_db(Path("/root/projects/cursor_pa"), home=Path("/root"))

    assert path == Path(
        "/root/.cursor/projects/root-projects-cursor-pa/sdk-agent-store" "/2bd7fa1cf3753c792ebe7b5e589b93b3/index.db"
    )


def test_close_wedged_run_leaves_sibling_running(tmp_path: Path) -> None:
    db = tmp_path / "index.db"
    write_index(
        db,
        agents=[("agent-live", "RUNNING", "run-live"), ("agent-572f452f", "RUNNING", "run-old")],
        runs=[("run-live", "agent-live", "RUNNING"), ("run-old", "agent-572f452f", "RUNNING")],
    )

    assert close_wedged_run(db, "agent-live") is True

    conn = sqlite3.connect(db)
    live = conn.execute("SELECT status, active_run_id FROM agents WHERE agent_id = 'agent-live'").fetchone()
    live_run = conn.execute("SELECT status, error_code FROM runs WHERE run_id = 'run-live'").fetchone()
    sibling = conn.execute("SELECT status, active_run_id FROM agents WHERE agent_id = 'agent-572f452f'").fetchone()
    sibling_run = conn.execute("SELECT status FROM runs WHERE run_id = 'run-old'").fetchone()
    conn.close()

    assert live == ("IDLE", None)
    assert live_run == ("ERROR", "bridge_exited")
    assert sibling == ("RUNNING", "run-old")
    assert sibling_run == ("RUNNING",)


def test_log_bridge_failure_redacts_argv_token(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    snapshot = BridgeSnapshot(
        up=False,
        pid=7,
        uptime_s=1,
        exit_code=None,
        signal=9,
        stderr_tail=(
            "plain line\n"
            "launch --tool-callback-auth-token secret-token\n"
            '{"authToken":"secret-token"}\n'
            "cursor-sdk-bridge ready {}\n"
        ),
    )

    log_bridge_failure(
        exc=NetworkError("Bridge request failed: ConnectError: All connection attempts failed"),
        agent_id="agent-a",
        run_id="run-1",
        snapshot=snapshot,
    )

    text = caplog.text
    assert "ConnectError" in text
    assert "agent-a" in text
    assert "run-1" in text
    assert "9" in text
    assert "plain line" in text
    assert "secret-token" not in text
    assert "--tool-callback-auth-token" not in text
    assert "authToken" not in text


def test_is_bridge_disconnect_matches_production_messages() -> None:
    incomplete = NetworkError(
        "Bridge request failed: RemoteProtocolError: peer closed connection without sending "
        "complete message body (incomplete chunked read)"
    )
    refused = NetworkError("Bridge request failed: ConnectError: All connection attempts failed")

    assert is_bridge_disconnect(incomplete) is True
    assert is_bridge_disconnect(refused) is True
    assert is_bridge_disconnect(InternalServerError("boom")) is False


def test_bridge_ancestor_picks_nearest_bridge_and_refuses_bot() -> None:
    crash = _load_crash_bridge()
    ancestor = crash.bridge_ancestor  # type: ignore[attr-defined]

    def command_of(pid: int) -> str:
        return {
            10: "python tool.py",
            9: "node cursor-sdk-bridge.js --workspace x",
            8: "python -m telegram_cursor_agent.bot",
            1: "systemd",
        }.get(pid, "")

    def parent_of(pid: int) -> int | None:
        return {10: 9, 9: 8, 8: 1}.get(pid)

    assert ancestor(10, command_of, parent_of) == 9

    def bot_parent(pid: int) -> int | None:
        return {4: 5, 5: 1}.get(pid)

    def bot_command(pid: int) -> str:
        return {5: "python -m telegram_cursor_agent.bot"}.get(pid, "")

    assert ancestor(4, bot_command, bot_parent) is None
    assert ancestor(4, lambda _pid: "bash", bot_parent) is None
