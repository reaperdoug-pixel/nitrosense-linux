#!/bin/bash
# Remove NitroSense for Linux. Fans go back to Auto, CPU policy to balanced.
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo $0" >&2
    exit 1
fi
if [ -S /run/nitrosense/nitrosense.sock ]; then
    python3 -I -c '
import sys; sys.path.insert(0, "/opt/nitrosense")
from nitrosense.client import Client
c = Client()
try:
    c.request("set_fan", mode="auto")
except Exception as e:
    print("could not reset fans:", e)
' || true
fi
systemctl disable --now nitrosensed.service 2>/dev/null || true
if [ -d /opt/nitrosense ]; then
    python3 -I -c 'import sys; sys.path.insert(0, "/opt/nitrosense"); from nitrosense.power import restore_defaults; restore_defaults()' || true
fi
USER_NAME="${SUDO_USER:-}"
if [ -n "$USER_NAME" ] && [ "$USER_NAME" != "root" ] && [ -d /opt/nitrosense ]; then
    USER_ID="$(id -u "$USER_NAME")"
    if [ -S "/run/user/$USER_ID/bus" ]; then
        runuser -u "$USER_NAME" -- env XDG_RUNTIME_DIR="/run/user/$USER_ID" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" \
            python3 -I -c 'import sys; sys.path.insert(0, "/opt/nitrosense"); from nitrosense.shortcut import main; sys.exit(main(["remove"]))' || true
    fi
fi
if [ -f /etc/udev/hwdb.d/61-nitrosense.hwdb ]; then
    rm -f /etc/udev/hwdb.d/61-nitrosense.hwdb
    systemd-hwdb update
    udevadm trigger --sysname-match="event*" || true
fi
pkill -f /opt/nitrosense/bin/nitrosense-watch 2>/dev/null || true
rm -f /etc/xdg/autostart/nitrosense-watch.desktop
rm -f /etc/systemd/system/nitrosensed.service /etc/modules-load.d/nitrosense.conf
rm -f /usr/share/applications/nitrosense.desktop /usr/local/bin/nitrosense
rm -f /usr/share/applications/io.github.napejoon.NitroSense.desktop
rm -f /usr/share/icons/hicolor/256x256/apps/nitrosense.png
rm -f /usr/share/icons/hicolor/scalable/apps/io.github.napejoon.NitroSense.svg
rm -f /usr/share/icons/hicolor/*/apps/io.github.napejoon.NitroSense.png
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
update-desktop-database -q /usr/share/applications 2>/dev/null || true
rm -rf /opt/nitrosense /usr/share/nitrosense /var/lib/nitrosense /etc/nitrosense
systemctl daemon-reload
echo "NitroSense for Linux removed (acpi-call-dkms left installed: sudo apt remove acpi-call-dkms)."
