"""Which window has focus, via a small KWin script that reports back over D-Bus.

KDE on Wayland gives clients no direct way to ask for the active window, but
KWin scripts can see it. We load assets/kwin/focus.js, which calls our
org.benchpet.Pet /Focus object whenever the active window changes. The same
mechanism activates a window by PID (clicking the speech bubble jumps to the
terminal that produced it).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

from gi.repository import Gio, GLib

log = logging.getLogger(__name__)

BUS_NAME = "org.benchpet.Pet"
SCRIPT = Path(__file__).resolve().parent.parent / "assets" / "kwin" / "focus.js"
PLUGIN = "benchpet-focus"
XML = """<node><interface name="org.benchpet.Focus">
<method name="Activated"><arg type="i" direction="in"/><arg type="s" direction="in"/>
<arg type="s" direction="in"/></method></interface></node>"""

ACTIVATE_JS = """
var pids = %s;  // nearest process first
var wins = workspace.windowList();
search: for (var p = 0; p < pids.length; p++) {
    for (var i = 0; i < wins.length; i++) {
        if (wins[i].pid === pids[p] && wins[i].normalWindow) { workspace.activeWindow = wins[i]; break search; }
    }
}
"""


def ancestor_pids(pid: int | None = None) -> list[int]:
    """PIDs from `pid` (default: this process) up to init."""
    pids, pid = [], pid or os.getpid()
    while pid > 1:
        pids.append(pid)
        try:
            status = Path(f"/proc/{pid}/status").read_text()
        except OSError:
            break
        pid = int(next(line.split()[1] for line in status.splitlines() if line.startswith("PPid:")))
    return pids


class FocusTracker:
    def __init__(self):
        self.active_pid: int | None = None
        self.active_class = ""
        self.available = False
        self.on_change = lambda: None  # called when the active window changes
        self._conn: Gio.DBusConnection | None = None
        self._owner_id = 0

    def start(self) -> None:
        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION, BUS_NAME, Gio.BusNameOwnerFlags.NONE,
            self._on_bus, self._on_name, self._on_name_lost)

    def stop(self) -> None:
        if self._conn and self.available:
            self._kwin("unloadScript", GLib.Variant("(s)", (PLUGIN,)))
        if self._owner_id:
            Gio.bus_unown_name(self._owner_id)

    def is_focused(self, pids: list[int]) -> bool | None:
        """Whether one of `pids` owns the active window; None if we can't tell."""
        if not self.available or self.active_pid is None:
            return None
        return self.active_pid in pids

    def activate(self, pids: list[int]) -> None:
        """Bring the nearest window owned by one of `pids` (child first) to the front."""
        if self._conn and pids:
            self._run_once(ACTIVATE_JS % json.dumps([int(p) for p in pids]))

    # --- internals -------------------------------------------------------

    def _on_bus(self, conn, _name) -> None:
        self._conn = conn
        conn.register_object("/Focus", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0],
                             self._on_call, None, None)

    def _on_name(self, _conn, _name) -> None:
        self._kwin("unloadScript", GLib.Variant("(s)", (PLUGIN,)))  # left over from a crash
        script_id = self._kwin("loadScript", GLib.Variant("(ss)", (str(SCRIPT), PLUGIN)))
        if script_id is None or script_id < 0:
            log.warning("focus: couldn't load the KWin script; focus checks disabled")
            return
        self._call(f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run", None)
        self.available = True

    def _on_name_lost(self, _conn, _name) -> None:
        log.warning("focus: %s is taken (another pet running?); focus checks disabled", BUS_NAME)

    def _on_call(self, conn, sender, path, iface, method, params, invocation) -> None:
        if method == "Activated":
            self.active_pid, self.active_class, _caption = params.unpack()
            self.on_change()
        invocation.return_value(None)

    def _run_once(self, source: str) -> None:
        fd, path = tempfile.mkstemp(prefix="benchpet-", suffix=".js",
                                    dir=os.environ.get("XDG_RUNTIME_DIR"))
        with os.fdopen(fd, "w") as f:
            f.write(source)
        name = Path(path).stem
        script_id = self._kwin("loadScript", GLib.Variant("(ss)", (path, name)))
        if script_id is not None and script_id >= 0:
            self._call(f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run", None)
        GLib.timeout_add(1000, self._cleanup_once, name, path)

    def _cleanup_once(self, name: str, path: str) -> bool:
        self._kwin("unloadScript", GLib.Variant("(s)", (name,)))
        Path(path).unlink(missing_ok=True)
        return False

    def _kwin(self, method: str, args: GLib.Variant):
        result = self._call("/Scripting", "org.kde.kwin.Scripting", method, args)
        return result[0] if result else None

    def _call(self, path: str, iface: str, method: str, args):
        try:
            return self._conn.call_sync("org.kde.KWin", path, iface, method, args, None,
                                        Gio.DBusCallFlags.NONE, 2000, None).unpack()
        except GLib.Error as e:
            log.debug("focus: KWin %s.%s failed: %s", iface, method, e.message)
            return None
