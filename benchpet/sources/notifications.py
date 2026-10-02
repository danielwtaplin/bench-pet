"""Desktop notification source: watches Notify calls on the session bus.

Anything that already shows up as a Linux notification (mail clients, chat
apps, browsers) is surfaced without per-service accounts. A dedicated
connection becomes a bus monitor (org.freedesktop.DBus.Monitoring), which is
allowed for the session owner without extra privileges.
"""

from __future__ import annotations

import html
import logging
import re

from gi.repository import Gio, GLib

from benchpet.events import AgentResponse, EventBus, NotificationReceived
from benchpet.sources.base import Source

log = logging.getLogger(__name__)

MATCH = "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"
OWN_APP = "bench-pet"
BROWSERS = ("chrome", "chromium", "firefox", "brave", "vivaldi", "edge", "opera", "zen")


def strip_markup(text: str) -> str:
    """Notification bodies may contain a small HTML subset; reduce to plain text."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"[ \t]+", " ", html.unescape(text)).strip()


def classify(app: str, desktop_entry: str, category: str, email_apps, message_apps) -> str:
    """email | message | other, from the category hint first, then app lists."""
    if category.startswith("email"):
        return "email"
    if category.startswith("im"):
        return "message"
    names = f"{app} {desktop_entry}".lower()
    if any(a.lower() in names for a in email_apps):
        return "email"
    if any(a.lower() in names for a in message_apps):
        return "message"
    return "other"


def ai_agent(app: str, desktop_entry: str, summary: str, body: str, ai_apps: dict) -> str | None:
    """Which AI agent a notification is a reply from, if any.

    ai_apps maps agent → {"apps": [...], "sites": [...]}. Apps match the sending app's
    name; sites match the text, but only for browser notifications (web apps), so an
    email that merely mentions "Claude" isn't mistaken for a reply.
    """
    sender = f"{app} {desktop_entry}".lower()
    is_browser = any(b in sender for b in BROWSERS)
    text = f"{summary} {body}".lower()
    for agent, match in ai_apps.items():
        if any(a.lower() in sender for a in match.get("apps", [])):
            return agent
        if is_browser and any(s.lower() in text for s in match.get("sites", [])):
            return agent
    return None


class NotificationSource(Source):
    name = "notifications"

    def __init__(self, bus: EventBus, email_apps, message_apps, ignore_apps, ai_apps=None):
        super().__init__(bus)
        self.ai_apps = dict(ai_apps or {})
        self.email_apps = list(email_apps)
        self.message_apps = list(message_apps)
        self.ignore_apps = [a.lower() for a in ignore_apps] + [OWN_APP]
        self._conn: Gio.DBusConnection | None = None

    def start(self) -> None:
        try:
            address = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION)
            self._conn = Gio.DBusConnection.new_for_address_sync(
                address,
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                None, None)
            self._conn.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus.Monitoring", "BecomeMonitor",
                GLib.Variant("(asu)", ([MATCH], 0)), None, Gio.DBusCallFlags.NONE, -1, None)
        except GLib.Error as e:
            log.warning("notifications: can't monitor the session bus (%s); disabled", e.message)
            self._conn = None
            return
        self._conn.add_filter(self._filter)

    def stop(self) -> None:
        if self._conn:
            self._conn.close_sync(None)
            self._conn = None

    def _filter(self, conn, message: Gio.DBusMessage, incoming: bool):
        # Runs on GDBus's worker thread: hop to the main loop before touching Qt.
        if message.get_member() == "Notify" and message.get_body() is not None:
            try:
                args = message.get_body().unpack()
            except Exception:
                return None
            GLib.idle_add(self._handle, args)
        return None

    def _handle(self, args) -> bool:
        app, _replaces, _icon, summary, body, _actions, hints, _timeout = args
        desktop_entry = str(hints.get("desktop-entry", ""))
        if any(i in f"{app} {desktop_entry}".lower() for i in self.ignore_apps):
            return False
        summary, body = strip_markup(summary), strip_markup(body)
        agent = ai_agent(app, desktop_entry, summary, body, self.ai_apps)
        if agent:
            # A desktop/web AI app replied: treat it like an agent hook. There's no
            # process chain to focus-check, and these apps generally only notify
            # when they're in the background anyway.
            sites = {x.lower() for x in self.ai_apps[agent].get("sites", [])}
            lines = [ln for ln in (body or summary).splitlines() if ln.strip().lower() not in sites]
            text = "\n".join(lines).strip()  # browsers put the site on its own line
            if text:
                self.bus.publish(AgentResponse(agent, text))
            return False
        kind = classify(app, desktop_entry, str(hints.get("category", "")),
                        self.email_apps, self.message_apps)
        self.bus.publish(NotificationReceived(
            app=app or desktop_entry or "Notification",
            summary=summary,
            body=body,
            kind=kind,
        ))
        return False  # one-shot idle callback
