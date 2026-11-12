"""Background alert watcher: desktop notifications while the NitroSense window is closed.

Runs as the logged-in user (started by an autostart entry), asks the root service for the
sensors and SSD SMART data and evaluates the same rules as the window (alerts.py). It talks
to the notification daemon over D-Bus directly, so it has no GUI toolkit dependency.
"""

from __future__ import annotations

import fcntl
import os
import signal
import sys
import time

from . import alerts, battery, disks, set_process_name
from .client import Client, DaemonError

POLL = 15           # seconds between checks
SMART_EVERY = 4     # ...of which every 4th also reads SMART (once a minute)
REMIND = 30 * 60    # a critical alert that persists is repeated this often

LOCK_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "nitrosense-watch.lock")


def acquire_lock():
    """Take the single-instance lock. -> open file (keep it referenced) or None if held."""
    f = open(LOCK_PATH, "a+")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def running() -> bool:
    """True while a watcher process holds the lock (the window then skips its own popups)."""
    try:
        f = open(LOCK_PATH, "a+")
    except OSError:
        return False
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return True
    finally:
        f.close()  # closing also releases a lock we just took
    return False


class Throttle:
    """Decides which alerts deserve a popup: new ones, worse ones, and critical reminders."""

    def __init__(self, remind: float = REMIND) -> None:
        self.remind = remind
        self.sent: dict[str, tuple[int, float]] = {}

    def filter(self, found: list[tuple[int, str, str]], now: float) -> list[tuple[int, str, str]]:
        keys = {a[1] for a in found}
        for key in [k for k in self.sent if k not in keys]:
            del self.sent[key]  # alert cleared: a recurrence notifies again
        out = []
        for level, key, text in found:
            prev = self.sent.get(key)
            if (prev is None or level > prev[0]
                    or (level == disks.CRIT and now - prev[1] >= self.remind)):
                self.sent[key] = (level, now)
                out.append((level, key, text))
        return out


class Notifier:
    """org.freedesktop.notifications over D-Bus, replacing the previous popup of a key."""

    def __init__(self) -> None:
        from gi.repository import Gio
        self.Gio = Gio
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.ids: dict[str, int] = {}

    def send(self, level: int, key: str, text: str) -> None:
        from gi.repository import GLib
        crit = level == disks.CRIT
        hints = {"urgency": GLib.Variant("y", 2 if crit else 1),
                 "desktop-entry": GLib.Variant("s", "io.github.napejoon.NitroSense")}
        params = GLib.Variant("(susssasa{sv}i)", (
            "NitroSense", self.ids.get(key, 0), "io.github.napejoon.NitroSense",
            "NitroSense: " + ("alerta crítico" if crit else "atenção"), text, [], hints,
            0 if crit else 15000))
        res = self.bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                                 "org.freedesktop.Notifications", "Notify", params,
                                 GLib.VariantType("(u)"), self.Gio.DBusCallFlags.NONE, 3000, None)
        self.ids[key] = res.unpack()[0]


def check(client: Client, smart_cache: dict, read_smart: bool):
    """One evaluation round -> alert list, or None when the service is unreachable."""
    try:
        status = client.request("status")
        if read_smart:
            try:
                smart_cache["smart"] = client.request("disks").get("smart") or {}
            except DaemonError:
                pass
    except DaemonError:
        return None
    sensors = status.get("sensors", {})
    assessed = []
    for d in disks.basic():
        raw = smart_cache.get("smart", {}).get(d["name"])
        assessed.append((d, disks.assess(d, raw if raw and "error" not in raw else None)))
    return alerts.evaluate(sensors.get("cpu_temp"), sensors.get("gpu_temp"),
                           sensors.get("cpu_fan"), sensors.get("gpu_fan"), assessed,
                           [(b, battery.assess(b)) for b in battery.read()],
                           status.get("throttle"),
                           (status.get("gpu_throttle") or {}).get("thermal_for_s", 0) >= alerts.THERMAL_ALERT_S)


def main() -> int:
    lock = acquire_lock()
    if lock is None:
        print("nitrosense-watch is already running", file=sys.stderr)
        return 0
    set_process_name("nitrosense-watch")
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import GLib

    client, throttle, smart_cache = Client(), Throttle(), {}
    notifier = None
    tick = [0]

    def step() -> bool:
        nonlocal notifier
        found = check(client, smart_cache, tick[0] % SMART_EVERY == 0)
        tick[0] += 1
        if found is None:
            return True
        for level, key, text in throttle.filter(found, time.monotonic()):
            try:
                notifier = notifier or Notifier()
                notifier.send(level, key, text)
            except Exception as e:  # no notification daemon yet: try again next round
                print(f"cannot notify: {e}", file=sys.stderr)
                notifier = None
                throttle.sent.pop(key, None)
        return True

    loop = GLib.MainLoop()
    GLib.timeout_add_seconds(POLL, step)
    GLib.idle_add(lambda: (step(), False)[1])
    for sig in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (loop.quit(), False)[1])
    loop.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
