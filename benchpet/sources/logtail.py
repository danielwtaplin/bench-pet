"""Log tail source: follows a file like `tail -F` and publishes its last lines.

Polls rather than watching for changes: an append is just a bigger size, and the
same check copes with rotation (a new file at the path), truncation, and a file
that doesn't exist yet. `Tail` does the file work without Qt, so it's easy to test.
"""

from __future__ import annotations

import errno
import os
import re
import stat
from collections import deque
from pathlib import Path

from PySide6.QtCore import QTimer

from benchpet.events import EventBus, LogTailUpdated
from benchpet.sources.base import Source

POLL_MS = 500
BACKLOG_BYTES = 64 * 1024  # read back this far for the lines already in the file
MAX_READ = 1024 * 1024  # more than this new in one poll: skip ahead to the last BACKLOG_BYTES
MAX_LINE = 1000  # chars kept of a very long line
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def expand(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path.strip())))


def clean(raw: bytes) -> str:
    """One line as text: colour codes and control characters out, tabs expanded."""
    text = ANSI.sub("", raw.decode("utf-8", errors="replace")).rstrip("\r").expandtabs(4)
    return "".join(ch for ch in text if ch.isprintable())[:MAX_LINE]


def describe(error: OSError, path: Path) -> str:
    if isinstance(error, FileNotFoundError):
        return f"Waiting for {path.name}…"
    if isinstance(error, PermissionError):
        return f"Can't read {path.name}: permission denied"
    return f"Can't read {path.name}: {error.strerror or error}"


class Tail:
    """The last `keep` complete lines of a file, kept up to date by poll()."""

    def __init__(self, path: str, keep: int):
        self.path = expand(path)
        self.lines: deque[str] = deque(maxlen=max(1, keep))
        self.error = ""
        self._file_id: tuple[int, int] | None = None  # (st_dev, st_ino) being followed
        self._pos = 0
        self._partial = b""  # an unfinished last line, completed by a later read
        self._backlog = True  # the first file found: its lines were there already, not new
        self._polled = False

    def poll(self) -> int | None:
        """Catch up with the file: how many lines are new, or None if nothing changed."""
        first, self._polled = not self._polled, True
        old_error = self.error
        try:
            data, backlog = self._read_new()
            self.error = ""
        except OSError as e:
            # Whatever turns up at the path next is a new file: follow it from its start.
            self._file_id, self._partial, self._backlog = None, b"", False
            self.error = describe(e, self.path)
            data, backlog = b"", False
        if not data:
            return 0 if first or self.error != old_error else None
        *complete, self._partial = (self._partial + data).split(b"\n")
        for raw in complete:
            self.lines.append(clean(raw))
        if not complete and not first and self.error == old_error:
            return None  # only part of a line so far
        return 0 if backlog else len(complete)

    def _read_new(self) -> tuple[bytes, bool]:
        st = os.stat(self.path)
        if stat.S_ISDIR(st.st_mode):
            raise IsADirectoryError(errno.EISDIR, "it's a folder")
        backlog = False
        file_id = (st.st_dev, st.st_ino)
        if file_id != self._file_id:  # first look, or rotated
            backlog, self._backlog = self._backlog, False
            self._file_id, self._partial = file_id, b""
            self._pos = max(0, st.st_size - BACKLOG_BYTES) if backlog else 0
        elif st.st_size < self._pos:  # truncated: start again from the top
            self._pos, self._partial = 0, b""
        start = self._pos
        if st.st_size - start > MAX_READ:
            start, self._partial = st.st_size - BACKLOG_BYTES, b""
        if st.st_size <= start:
            return b"", backlog
        with open(self.path, "rb") as f:
            f.seek(start)
            data = f.read(st.st_size - start)
        mid_line = start != self._pos or (backlog and start > 0)
        self._pos = start + len(data)
        if mid_line:  # skipped ahead: drop the cut-off first line
            data = data.split(b"\n", 1)[1] if b"\n" in data else b""
        return data, backlog


class LogTailSource(Source):
    name = "log_tail"

    def __init__(self, bus: EventBus, config: dict):
        super().__init__(bus)
        self.config = config
        self.tail: Tail | None = None
        self._following: tuple[str, int] | None = None
        self._timer = QTimer()
        self._timer.timeout.connect(self.poll)

    def start(self) -> None:
        self.reconfigure(self.config)

    def reconfigure(self, config: dict) -> None:
        """Settings changed: start over if it's a different file or line count."""
        self.config = config
        path = (config.get("path") or "").strip()
        following = (path, int(config.get("lines", 12)))
        if following == self._following:
            return
        self._following = following
        self.tail = Tail(*following) if path else None
        if self.tail:
            self._timer.start(POLL_MS)
            self.poll()
        else:
            self._timer.stop()
            self.bus.publish(LogTailUpdated("", (), 0))

    def stop(self) -> None:
        self._timer.stop()

    def poll(self) -> None:
        if self.tail is None:
            return
        appended = self.tail.poll()
        if appended is not None:
            self.bus.publish(LogTailUpdated(str(self.tail.path), tuple(self.tail.lines), appended,
                                            self.tail.error))
