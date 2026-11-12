"""Desktop keyboard shortcut: NitroSense key (XF86Launch1) -> open NitroSense.

GNOME (media-keys custom keybindings) and Cinnamon (Linux Mint) are supported.

Run as the desktop user: python3 -m nitrosense.shortcut install|remove|status
"""

from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA = SCHEMA + ".custom-keybinding"
PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/nitrosense/"
COMMAND = "/opt/nitrosense/bin/nitrosense"
BINDING = "XF86Launch1"

CIN_SCHEMA = "org.cinnamon.desktop.keybindings"
CIN_CUSTOM_SCHEMA = CIN_SCHEMA + ".custom-keybinding"
CIN_ID = "nitrosense"
CIN_PATH = "/org/cinnamon/desktop/keybindings/custom-keybindings/nitrosense/"


def _cinnamon() -> bool:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "cinnamon" not in desktop:
        return False
    src = Gio.SettingsSchemaSource.get_default()
    return bool(src and src.lookup(CIN_SCHEMA, True) and src.lookup(CIN_CUSTOM_SCHEMA, True))


def _available() -> bool:
    src = Gio.SettingsSchemaSource.get_default()
    return bool(src and src.lookup(SCHEMA, True) and src.lookup(CUSTOM_SCHEMA, True))


def install(command: str = COMMAND, binding: str = BINDING) -> bool:
    if _cinnamon():
        custom = Gio.Settings.new_with_path(CIN_CUSTOM_SCHEMA, CIN_PATH)
        custom.set_string("name", "NitroSense")
        custom.set_string("command", command)
        custom.set_strv("binding", [binding])
        keys = Gio.Settings.new(CIN_SCHEMA)
        ids = list(keys.get_strv("custom-list"))
        if CIN_ID not in ids:
            keys.set_strv("custom-list", ids + [CIN_ID])
        Gio.Settings.sync()
        return True
    if not _available():
        return False
    custom = Gio.Settings.new_with_path(CUSTOM_SCHEMA, PATH)
    custom.set_string("name", "NitroSense")
    custom.set_string("command", command)
    custom.set_string("binding", binding)
    keys = Gio.Settings.new(SCHEMA)
    paths = list(keys.get_strv("custom-keybindings"))
    if PATH not in paths:
        keys.set_strv("custom-keybindings", paths + [PATH])
    Gio.Settings.sync()
    return True


def remove() -> bool:
    if _cinnamon():
        keys = Gio.Settings.new(CIN_SCHEMA)
        keys.set_strv("custom-list", [i for i in keys.get_strv("custom-list") if i != CIN_ID])
        custom = Gio.Settings.new_with_path(CIN_CUSTOM_SCHEMA, CIN_PATH)
        for k in ("name", "command", "binding"):
            custom.reset(k)
        Gio.Settings.sync()
        return True
    if not _available():
        return False
    keys = Gio.Settings.new(SCHEMA)
    paths = [p for p in keys.get_strv("custom-keybindings") if p != PATH]
    keys.set_strv("custom-keybindings", paths)
    custom = Gio.Settings.new_with_path(CUSTOM_SCHEMA, PATH)
    for k in ("name", "command", "binding"):
        custom.reset(k)
    Gio.Settings.sync()
    return True


def status() -> str:
    if _cinnamon():
        if CIN_ID not in Gio.Settings.new(CIN_SCHEMA).get_strv("custom-list"):
            return "not registered"
        c = Gio.Settings.new_with_path(CIN_CUSTOM_SCHEMA, CIN_PATH)
        return f"{','.join(c.get_strv('binding'))} -> {c.get_string('command')}"
    if not _available():
        return "GNOME media-keys schema not available"
    keys = Gio.Settings.new(SCHEMA)
    if PATH not in keys.get_strv("custom-keybindings"):
        return "not registered"
    c = Gio.Settings.new_with_path(CUSTOM_SCHEMA, PATH)
    return f"{c.get_string('binding')} -> {c.get_string('command')}"


def main(argv: list[str]) -> int:
    action = argv[0] if argv else "status"
    if action == "install":
        ok = install()
        print("NitroSense key shortcut:", status() if ok else "skipped (not a GNOME or Cinnamon session)")
        return 0
    if action == "remove":
        remove()
        print("NitroSense key shortcut removed")
        return 0
    print(status())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
