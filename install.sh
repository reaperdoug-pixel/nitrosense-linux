#!/bin/bash
# NitroSense for Linux installer.
#   sudo ./install.sh "/path/to/Nitro Sense_Acer_..._W10x64_A"
# The path (optional) is your own NitroSense 3.x download for Windows; artwork, fonts,
# strings and the per-model settings are read from it (nothing is executed).
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo $0 <NitroSense package dir>" >&2
    exit 1
fi
PKG="${1:-}"
# The Windows package is optional: without it the GUI runs without the original artwork
# and the model configuration comes from data/models/<product> (if bundled).
if [ -n "$PKG" ] && [ ! -e "$PKG" ]; then
    echo "package path not found: $PKG" >&2
    exit 1
fi
SRC="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="${SUDO_USER:-}"
PRODUCT="$(cat /sys/class/dmi/id/product_name 2>/dev/null || true)"
VENDOR="$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null || true)"

echo "==> Machine: $VENDOR $PRODUCT"
if [ "$VENDOR" != "Acer" ]; then
    echo "This is not an Acer machine; refusing to install." >&2
    exit 1
fi

echo "==> Installing dependencies"
apt-get install -y python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-4.0 acpi-call-dkms

echo "==> Loading acpi_call (signed by DKMS with your enrolled MOK key)"
if ! modprobe acpi_call; then
    echo "acpi_call could not be loaded. With Secure Boot on, the DKMS module must be" >&2
    echo "signed with an enrolled MOK key (see README)." >&2
    exit 1
fi
echo acpi_call > /etc/modules-load.d/nitrosense.conf

echo "==> Read-only hardware probe (getters only)"
if ! python3 -I "$SRC/tools/probe.py"; then
    echo "Probe failed; the service was NOT installed." >&2
    exit 1
fi

echo "==> Copying program to /opt/nitrosense"
rm -rf /opt/nitrosense
install -d /opt/nitrosense/bin
cp -r "$SRC/nitrosense" /opt/nitrosense/
find /opt/nitrosense -name '__pycache__' -prune -exec rm -rf {} +
install -m 0755 "$SRC/bin/nitrosense" "$SRC/bin/nitrosensed" "$SRC/bin/nitrosense-watch" /opt/nitrosense/bin/
chown -R root:root /opt/nitrosense
chmod -R go-w /opt/nitrosense

rm -rf /usr/share/nitrosense/assets
install -d /usr/share/nitrosense/assets
if [ -n "$PKG" ]; then
    echo "==> Extracting NitroSense artwork from the Windows package"
    (cd /opt/nitrosense && python3 -I -c 'import sys; sys.path.insert(0, "."); from nitrosense.extract import main; sys.exit(main(["x", sys.argv[1], sys.argv[2]]))' \
        "$PKG" /usr/share/nitrosense/assets) \
        || echo "    WARNING: could not extract artwork (is this the 3.x package?); continuing without it"
else
    echo "==> No Windows package given: running without the original artwork"
fi

echo "==> Model configuration"
install -d /etc/nitrosense/model
PLUG=""
[ -n "$PKG" ] && PLUG="$(find "$PKG" -type d -path "*/Plugs/$PRODUCT" | head -n1 || true)"
if [ -n "$PLUG" ]; then
    cp "$PLUG"/*.ini /etc/nitrosense/model/
    echo "    using Plugs/$PRODUCT"
elif [ -d "$SRC/data/models/$PRODUCT" ]; then
    cp "$SRC/data/models/$PRODUCT"/*.ini /etc/nitrosense/model/
    echo "    using bundled data/models/$PRODUCT"
else
    echo "    WARNING: no Plugs/$PRODUCT in the package, using AN515-44 defaults"
fi
if [ -n "$USER_NAME" ] && [ "$USER_NAME" != "root" ]; then
    grep -qx "$USER_NAME" /etc/nitrosense/allowed-users 2>/dev/null || echo "$USER_NAME" >> /etc/nitrosense/allowed-users
    echo "    allowed user: $USER_NAME"
fi

echo "==> Icon and menu entry"
rm -f /usr/share/applications/nitrosense.desktop \
      /usr/share/icons/hicolor/256x256/apps/nitrosense.png   # names used by older versions
# The icon is NitroSense's own keycap tile from your package, with the N lit red like the
# backlit NitroSense key; without a tile, the project's own SVG icon is used.
ICON_TILE=/usr/share/nitrosense/assets/icon.png
if [ -f "$ICON_TILE" ] && (cd /opt/nitrosense && python3 -I -c 'import sys; sys.path.insert(0, "."); from nitrosense.iconmaker import main; sys.exit(main(sys.argv[1:]))' \
        "$ICON_TILE" /usr/share/icons/hicolor); then
    rm -f /usr/share/icons/hicolor/scalable/apps/io.github.napejoon.NitroSense.svg
else
    install -D -m 0644 "$SRC/data/icons/io.github.napejoon.NitroSense.svg" \
        /usr/share/icons/hicolor/scalable/apps/io.github.napejoon.NitroSense.svg
fi
gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
install -D -m 0644 "$SRC/data/io.github.napejoon.NitroSense.desktop" \
    /usr/share/applications/io.github.napejoon.NitroSense.desktop
update-desktop-database -q /usr/share/applications 2>/dev/null || true
ln -sf /opt/nitrosense/bin/nitrosense /usr/local/bin/nitrosense

echo "==> Background alert watcher (notifications even with the window closed)"
# Starts with the desktop session. To turn it off for one user, copy this file to
# ~/.config/autostart/ and add the line Hidden=true.
install -D -m 0644 "$SRC/data/nitrosense-watch.desktop" /etc/xdg/autostart/nitrosense-watch.desktop

echo "==> NitroSense key (scancode 0xf5 -> XF86Launch1 -> open NitroSense)"
install -D -m 0644 "$SRC/data/61-nitrosense.hwdb" /etc/udev/hwdb.d/61-nitrosense.hwdb
systemd-hwdb update
udevadm trigger --sysname-match="event*" || true
if [ -n "$USER_NAME" ] && [ "$USER_NAME" != "root" ]; then
    USER_ID="$(id -u "$USER_NAME")"
    if [ -S "/run/user/$USER_ID/bus" ]; then
        runuser -u "$USER_NAME" -- env XDG_RUNTIME_DIR="/run/user/$USER_ID" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$USER_ID/bus" \
            python3 -I -c 'import sys; sys.path.insert(0, "/opt/nitrosense"); from nitrosense.shortcut import main; sys.exit(main(["install"]))' \
            || echo "    could not register the shortcut; run as your user: python3 -m nitrosense.shortcut install"
    else
        echo "    log in to the desktop and run: cd /opt/nitrosense && python3 -m nitrosense.shortcut install"
    fi
fi

echo "==> Service"
install -m 0644 "$SRC/data/nitrosensed.service" /etc/systemd/system/nitrosensed.service
systemctl daemon-reload
systemctl enable nitrosensed.service
systemctl restart nitrosensed.service
sleep 2
systemctl --no-pager --lines=8 status nitrosensed.service || true

echo
echo "Done. Start NitroSense from the app menu or run: nitrosense"
