"""Bridge child watch, stderr tail, and sqlite unwedge after a dead bridge.

The SDK reads stderr only until the discovery line, then stops. A full pipe
can stall the child, and a crash leaves no exit status. This module owns the
rest of the child's life. It does not log argv: the bridge command line
carries the tool-callback auth token.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cursor_sdk.errors import CursorAgentError

log = logging.getLogger(__name__)

STDERR_TAIL_BYTES = 8192
TERMINAL_RUN_STATUSES = ("FINISHED", "ERROR", "CANCELLED", "EXPIRED")
_DISCONNECT_MARKERS = (
    "RemoteProtocolError",
    "ConnectError",
    "incomplete chunked read",
    "peer closed connection",
    "All connection attempts failed",
)
_TOOL_MARKERS = ("tool_call", "toolCall", "tool-call")
_SECRET_MARKERS = ("--tool-callback-auth-token", "authToken", "cursor-sdk-bridge ready")


@dataclass(frozen=True)
class BridgeSnapshot:
    up: bool
    pid: int | None
    uptime_s: int | None
    exit_code: int | None
    signal: int | None
    stderr_tail: str


class BridgeWatch:
    """Mutable record for one bridge child. Exit is recorded as soon as wait() returns."""

    def __init__(self, pid: int | None) -> None:
        self.pid = pid
        self.started = time.monotonic()
        self.exited = False
        self.exit_code: int | None = None
        self.signal: int | None = None
        self.intentional_close = False
        self._stderr = bytearray()
        self._pending = ""
        self._exit_at: float | None = None

    def record_exit(self, returncode: int) -> None:
        if returncode < 0:
            self.exit_code = None
            self.signal = -returncode
        else:
            self.exit_code = returncode
            self.signal = None
        self.exited = True
        self._exit_at = time.monotonic()

    def add_stderr(self, text: str) -> None:
        self._stderr.extend(text.encode("utf-8", errors="replace"))
        if len(self._stderr) > STDERR_TAIL_BYTES:
            self._stderr = self._stderr[-STDERR_TAIL_BYTES:]
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            redacted = redact_bridge_line(line)
            if redacted:
                log.info("bridge stderr: %s", redacted)

    def stderr_tail(self) -> str:
        return self._stderr.decode("utf-8", errors="replace")

    def snapshot(self) -> BridgeSnapshot:
        end = self._exit_at if self._exit_at is not None else time.monotonic()
        return BridgeSnapshot(
            up=not self.exited,
            pid=self.pid,
            uptime_s=int(end - self.started),
            exit_code=self.exit_code,
            signal=self.signal,
            stderr_tail=self.stderr_tail(),
        )


def redact_bridge_line(line: str) -> str | None:
    """Drop discovery and token lines. Return None when the line must not be logged."""
    if any(marker in line for marker in _SECRET_MARKERS):
        return None
    stripped = line.rstrip("\r")
    return stripped or None


def redact_tail(text: str) -> str:
    kept = [redacted for line in text.splitlines() if (redacted := redact_bridge_line(line))]
    return "\n".join(kept)


def _none(value: int | None) -> str:
    return "none" if value is None else str(value)


def format_bridge_block(snapshot: BridgeSnapshot) -> str:
    if snapshot.exit_code is None and snapshot.signal is None:
        last = "none"
    else:
        last = f"code={_none(snapshot.exit_code)} signal={_none(snapshot.signal)}"
    lines = [
        f"bridge: {'up' if snapshot.up else 'down'}",
        f"bridge pid: {_none(snapshot.pid)}",
        f"bridge uptime: {'none' if snapshot.uptime_s is None else f'{snapshot.uptime_s}s'}",
        f"bridge last exit: {last}",
        "bridge stderr:",
    ]
    tail = redact_tail(snapshot.stderr_tail).strip()
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def format_bridge_failure(snapshot: BridgeSnapshot, *, message: str) -> str:
    lines = [
        f"Agent call failed: {message}",
        f"bridge exit: pid={_none(snapshot.pid)} code={_none(snapshot.exit_code)} signal={_none(snapshot.signal)}",
    ]
    tail = redact_tail(snapshot.stderr_tail).strip()
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def resend_notice(snapshot: BridgeSnapshot) -> str:
    text = (
        "bridge restarted (was down, "
        f"pid={_none(snapshot.pid)} code={_none(snapshot.exit_code)} signal={_none(snapshot.signal)}); "
        "resend your message — a tool call was already running"
    )
    tail = redact_tail(snapshot.stderr_tail).strip()
    if tail:
        return f"{text}\n{tail}"
    return text


def log_bridge_failure(
    *,
    exc: BaseException | None,
    agent_id: str | None,
    run_id: str | None,
    snapshot: BridgeSnapshot,
) -> None:
    exc_name = type(exc).__name__ if exc is not None else "BridgeExit"
    message = getattr(exc, "message", None) if exc is not None else None
    if not isinstance(message, str) or not message:
        message = str(exc) if exc is not None else "bridge exited"
    log.error(
        "bridge disconnect: %s: %s agent=%s run=%s pid=%s code=%s signal=%s",
        exc_name,
        message,
        agent_id or "-",
        run_id or "-",
        snapshot.pid,
        snapshot.exit_code,
        snapshot.signal,
    )
    for line in redact_tail(snapshot.stderr_tail).splitlines():
        if line.strip():
            log.error("bridge stderr: %s", line)


def is_bridge_disconnect(err: BaseException) -> bool:
    if not isinstance(err, CursorAgentError):
        return False
    return any(marker in err.message for marker in _DISCONNECT_MARKERS)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _connect(db_path: Path) -> sqlite3.Connection | None:
    try:
        return sqlite3.connect(db_path, timeout=5)
    except sqlite3.Error as err:
        log.warning("could not open %s: %s", db_path, err)
        return None


def close_wedged_run(db_path: Path, agent_id: str) -> bool:
    """Mark this agent's non-terminal runs ERROR and the agent IDLE.

    No-op when index.db is missing. Other agent ids are left alone.
    ponytail: a busy database (orphan bridge still holding the file) logs and
    returns False. start() already creates a fresh agent when resume fails.
    Upgrade path is killing that orphan pid by hand.
    """
    if not agent_id or not db_path.is_file():
        return False
    conn = _connect(db_path)
    if conn is None:
        return False
    now = _utc_now()
    changed = False
    try:
        runs = conn.execute(
            """
            UPDATE runs
            SET status = 'ERROR',
                error_code = COALESCE(NULLIF(error_code, ''), 'bridge_exited'),
                updated_at = ?
            WHERE agent_id = ?
              AND status NOT IN ('FINISHED', 'ERROR', 'CANCELLED', 'EXPIRED')
            """,
            (now, agent_id),
        )
        agents = conn.execute(
            """
            UPDATE agents
            SET status = 'IDLE', active_run_id = NULL, updated_at = ?
            WHERE agent_id = ? AND status != 'ARCHIVED'
            """,
            (now, agent_id),
        )
        changed = runs.rowcount > 0 or agents.rowcount > 0
        conn.commit()
    except sqlite3.OperationalError as err:
        log.warning("index.db busy, leaving wedge: %s", err)
        return False
    finally:
        conn.close()
    return changed


def active_run_id(db_path: Path, agent_id: str) -> str | None:
    if not agent_id or not db_path.is_file():
        return None
    conn = _connect(db_path)
    if conn is None:
        return None
    try:
        row = conn.execute("SELECT active_run_id FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
    except sqlite3.Error as err:
        log.warning("could not read active run from %s: %s", db_path, err)
        return None
    finally:
        conn.close()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def run_dispatched_tool(db_path: Path, run_id: str) -> bool:
    """True when this run's events already mention a tool call.

    ponytail: substring scan of one run. A prompt that merely contains these
    tokens can suppress a retry. Upgrade path is a typed event parser.
    """
    if not run_id or not db_path.is_file():
        return False
    conn = _connect(db_path)
    if conn is None:
        return False
    try:
        rows = conn.execute(
            "SELECT event_type, payload_json FROM run_events WHERE run_id = ?",
            (run_id,),
        ).fetchall()
    except sqlite3.Error as err:
        log.warning("could not read run events from %s: %s", db_path, err)
        return False
    finally:
        conn.close()
    for event_type, payload in rows:
        blob = f"{event_type or ''}\n{payload or ''}"
        if any(marker in blob for marker in _TOOL_MARKERS):
            return True
    return False


async def watch_bridge(process: asyncio.subprocess.Process, sink: BridgeWatch) -> None:
    """Read stderr in chunks until EOF, and record the exit as soon as the child ends."""

    async def drain() -> None:
        stream = process.stderr
        if stream is None:
            return
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                return
            sink.add_stderr(chunk.decode("utf-8", errors="replace"))

    drain_task = asyncio.create_task(drain())
    try:
        returncode = await process.wait()
        sink.record_exit(0 if returncode is None else returncode)
    finally:
        try:
            await asyncio.wait_for(drain_task, timeout=1)
        except TimeoutError:
            drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await drain_task
