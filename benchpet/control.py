"""Local control socket, so scripts and hooks can drive the pet.

    bench-pet working "Refactoring auth"   # laptop/typing until done (or timeout)
    bench-pet done "Tests pass"            # celebrate
    bench-pet failed "Build broke"         # facepalm
    bench-pet celebrate                    # just celebrate
    bench-pet clear                        # stop working without a reaction
    bench-pet pomodoro start|stop|skip     # the pet's pomodoro timer
    bench-pet agent claude                 # Claude Code Stop hook (payload on stdin)
    bench-pet agent codex '<json>'         # Codex notify program

The protocol is one JSON object per line: {"cmd": "...", "message": "..."}.
The client side uses the plain socket module so it starts instantly.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path

from PySide6.QtNetwork import QLocalServer, QLocalSocket

from benchpet.agent import MAX_SEND
from benchpet.events import AgentResponse, EventBus, PomodoroCommand, TaskEvent
from benchpet.sources.base import Source

log = logging.getLogger(__name__)

COMMANDS = ("working", "done", "failed", "celebrate", "clear", "pomodoro", "agent")
POMODORO_ACTIONS = ("start", "stop", "skip")
SOCKET_PATH = Path(os.environ.get("BENCH_PET_SOCKET")
                   or Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "bench-pet.sock")


def send(cmd: str, message: str = "", path: Path = SOCKET_PATH, **extra) -> bool:
    """Send a command to a running pet. False if none is listening."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(str(path))
            s.sendall(json.dumps({"cmd": cmd, "message": message, **extra}).encode() + b"\n")
            return s.recv(64).startswith(b"ok")
    except OSError:
        return False


def is_running(path: Path = SOCKET_PATH) -> bool:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(str(path))
            return True
    except OSError:
        return False


def parse(line: bytes) -> TaskEvent | PomodoroCommand | AgentResponse | None:
    try:
        data = json.loads(line)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("cmd") not in COMMANDS:
        return None
    if data["cmd"] == "agent":
        text = str(data.get("message", ""))[:MAX_SEND].strip()
        if not text:
            return None
        pids = tuple(int(p) for p in data.get("pids", []) if str(p).isdigit())
        return AgentResponse(str(data.get("agent", "agent"))[:40], text,
                             str(data.get("project", ""))[:80], pids)
    message = str(data.get("message", ""))[:200]
    if data["cmd"] == "pomodoro":
        return PomodoroCommand(message) if message in POMODORO_ACTIONS else None
    return TaskEvent(data["cmd"], message)


class ControlSource(Source):
    name = "control"

    def __init__(self, bus: EventBus, path: Path = SOCKET_PATH):
        super().__init__(bus)
        self.path = path
        self._server = QLocalServer()
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)

    def start(self) -> None:
        QLocalServer.removeServer(str(self.path))  # stale socket from a crash
        if not self._server.listen(str(self.path)):
            log.warning("control: can't listen on %s: %s", self.path, self._server.errorString())

    def stop(self) -> None:
        self._server.close()

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            conn: QLocalSocket = self._server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: self._on_ready(c))
            conn.disconnected.connect(conn.deleteLater)

    def _on_ready(self, conn: QLocalSocket) -> None:
        while conn.canReadLine():
            event = parse(bytes(conn.readLine()))
            conn.write(b"ok\n" if event else b"error\n")
            conn.flush()
            if event:
                self.bus.publish(event)
