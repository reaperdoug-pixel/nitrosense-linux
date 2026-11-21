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
# Run a command as the invoking user (runuser is missing on some image-based systems).
as_user() {
    if command -v runuser >/dev/null 2>&1; then
        runuser -u "$USER_NAME" -- "$@"
    else
        sudo -u "$USER_NAME" -- "$@"
    fi
}
PRODUCT="$(cat /sys/class/dmi/id/product_name 2>/dev/null || true)"
VENDOR="$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null || true)"

echo "==> Machine: $VENDOR $PRODUCT"
if [ "$VENDOR" != "Acer" ]; then
    echo "This is not an Acer machine; refusing to install." >&2
    exit 1
fi

# Image-based systems (Bluefin, Bazzite, Aurora, GNOME OS, ...) have a read-only /usr and no
# apt: the menu entry, icons and command go to the user's ~/.local, and acpi_call comes from
# tools/build-acpi_call.sh instead of DKMS. /opt, /etc and /var stay writable there.
IMMUTABLE=0
if [ ! -w /usr/share ] || ! command -v apt-get >/dev/null 2>&1; then
    IMMUTABLE=1
    echo "==> Image-based system (read-only /usr or no apt): per-user menu entry and icons"
fi
USER_HOME=""
if [ -n "$USER_NAME" ] && [ "$USER_NAME" != "root" ]; then
    USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
fi
if [ "$IMMUTABLE" -eq 1 ]; then
    if [ -z "$USER_HOME" ]; then
        echo "Run with sudo from your user account (the menu entry goes to your home)." >&2
        exit 1
    fi
    APPS_DIR="$USER_HOME/.local/share/applications"
    ICON_THEME="$USER_HOME/.local/share/icons/hicolor"
    BIN_LINK="$USER_HOME/.local/bin/nitrosense"
    ASSETS_DIR=/opt/nitrosense/share/assets
else
    APPS_DIR=/usr/share/applications
    ICON_THEME=/usr/share/icons/hicolor
    BIN_LINK=/usr/local/bin/nitrosense
    ASSETS_DIR=/usr/share/nitrosense/assets
fi

if [ "$IMMUTABLE" -eq 0 ]; then
    echo "==> Installing dependencies"
    apt-get install -y python3-gi python3-gi-cairo python3-cairo gir1.2-gtk-4.0 acpi-call-dkms
    # optional: the tray icon of the alert watcher (without them the watcher still notifies)
    apt-get install -y gir1.2-gtk-3.0 gir1.2-xapp-1.0 || echo "    tray icon libraries not installed (optional)"
    # optional: SMART for SATA/HDD disks (NVMe is read natively and needs nothing)
    apt-get install -y smartmontools || echo "    smartmontools not installed (optional: SATA/HDD health)"
else
    echo "==> Checking dependencies (no package manager: they must come with the image)"
    if ! python3 -I -c 'import gi, cairo; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk; assert (Gtk.get_major_version(), Gtk.get_minor_version()) >= (4, 10)' 2>/dev/null; then
        echo "The system python3 lacks PyGObject, pycairo or GTK 4.10+; NitroSense cannot run here." >&2
        exit 1
    fi
    python3 -I -c 'import gi; gi.require_version("XApp", "1.0")' 2>/dev/null \
        || echo "    XApp not available: no tray icon (the watcher still sends notifications)"
    command -v smartctl >/dev/null 2>&1 \
        || echo "    smartctl not in root's PATH: SATA/HDD health unavailable (NVMe is read natively)"
fi

# Options for the in-kernel acer_wmi driver, for models that ship them (data/models/<model>/
# acer-wmi.conf). On the ANV15-51 they expose fan RPM and fan control (hwmon pwm) and the
# firmware thermal profiles. force_caps replaces the driver's whole capability mask, so it is
# only installed for the model it was written for.
ACER_WMI_CONF=/etc/modprobe.d/nitrosense-acer-wmi.conf
if [ -f "$SRC/data/models/$PRODUCT/acer-wmi.conf" ]; then
    echo "==> acer_wmi options for $PRODUCT"
    install -m 0644 "$SRC/data/models/$PRODUCT/acer-wmi.conf" "$ACER_WMI_CONF"
    if modprobe -r acer_wmi 2>/dev/null && modprobe acer_wmi; then
        echo "    acer_wmi reloaded"
    else
        echo "    acer_wmi is in use: the options take effect after a reboot"
    fi
fi

# acer_wmi's hwmon fan control (pwm1/pwm2): the service drives the fans through it when
# acpi_call cannot be loaded, e.g. under kernel lockdown=integrity.
acer_wmi_fans() {
    local hw
    for hw in /sys/class/hwmon/hwmon*; do
        [ "$(cat "$hw/name" 2>/dev/null)" = acer ] && [ -e "$hw/pwm1_enable" ] && return 0
    done
    return 1
}
ACPI_CALL=1
no_acpi_call() {
    if acer_wmi_fans; then
        echo "    WARNING: continuing without acpi_call. The fans work through acer_wmi;" >&2
        echo "    CoolBoost, the battery charge limit and keyboard lighting stay unavailable." >&2
        ACPI_CALL=0
    else
        exit 1
    fi
}

if [ "$IMMUTABLE" -eq 0 ]; then
    echo "==> Loading acpi_call (signed by DKMS with your enrolled MOK key)"
    if modprobe acpi_call; then
        echo acpi_call > /etc/modules-load.d/nitrosense.conf
    else
        echo "acpi_call could not be loaded. With Secure Boot on, the DKMS module must be" >&2
        echo "signed with an enrolled MOK key (see README)." >&2
        no_acpi_call
    fi
else
    echo "==> Loading acpi_call (built by tools/build-acpi_call.sh)"
    install -m 0644 "$SRC/data/nitrosense-acpi-call.service" /etc/systemd/system/nitrosense-acpi-call.service
    systemctl daemon-reload
    # the file must exist even if acpi_call is already loaded, or it would be gone after a reboot
    if [ ! -f "/var/lib/nitrosense-kmod/$(uname -r)/acpi_call.ko" ]; then
        echo "No acpi_call module for kernel $(uname -r). As your user (not root), run:" >&2
        echo "    $SRC/tools/build-acpi_call.sh" >&2
        echo "then run this installer again." >&2
        no_acpi_call
    else
        systemctl enable nitrosense-acpi-call.service
        systemctl start nitrosense-acpi-call.service || true
        if [ ! -e /proc/acpi/call ]; then
            echo "acpi_call could not be loaded; see: journalctl -u nitrosense-acpi-call" >&2
            no_acpi_call
        fi
    fi
fi

if [ "$ACPI_CALL" -eq 1 ]; then
    echo "==> Read-only hardware probe (getters only)"
    if ! python3 -I "$SRC/tools/probe.py"; then
        echo "Probe failed; the service was NOT installed." >&2
        exit 1
    fi
fi

echo "==> Copying program to /opt/nitrosense"
rm -rf /opt/nitrosense
install -d /opt/nitrosense/bin
cp -r "$SRC/nitrosense" /opt/nitrosense/
find /opt/nitrosense -name '__pycache__' -prune -exec rm -rf {} +
install -m 0755 "$SRC/bin/nitrosense" "$SRC/bin/nitrosensed" "$SRC/bin/nitrosense-watch" /opt/nitrosense/bin/
# kept installed so the module can be rebuilt after a kernel update without the source tree
install -D -m 0755 "$SRC/tools/build-acpi_call.sh" /opt/nitrosense/tools/build-acpi_call.sh
chown -R root:root /opt/nitrosense
chmod -R go-w /opt/nitrosense

rm -rf "$ASSETS_DIR"
install -d "$ASSETS_DIR"
if [ -n "$PKG" ]; then
    echo "==> Extracting NitroSense artwork from the Windows package"
    (cd /opt/nitrosense && python3 -I -c 'import sys; sys.path.insert(0, "."); from nitrosense.extract import main; sys.exit(main(["x", sys.argv[1], sys.argv[2]]))' \
        "$PKG" "$ASSETS_DIR") \
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
if [ "$IMMUTABLE" -eq 1 ]; then
    # create the per-user directories as the user, so none of them ends up owned by root
    as_user mkdir -p "$ICON_THEME" "$APPS_DIR" "$(dirname "$BIN_LINK")"
else
    rm -f /usr/share/applications/nitrosense.desktop \
          /usr/share/icons/hicolor/256x256/apps/nitrosense.png   # names used by older versions
fi
# The icon is NitroSense's own keycap tile from your package, with the N lit red like the
# backlit NitroSense key; without a tile, the project's own SVG icon is used.
ICON_TILE="$ASSETS_DIR/icon.png"
if [ -f "$ICON_TILE" ] && (cd /opt/nitrosense && python3 -I -c 'import sys; sys.path.insert(0, "."); from nitrosense.iconmaker import main; sys.exit(main(sys.argv[1:]))' \
        "$ICON_TILE" "$ICON_THEME"); then
    rm -f "$ICON_THEME/scalable/apps/io.github.napejoon.NitroSense.svg"
else
    install -D -m 0644 "$SRC/data/icons/io.github.napejoon.NitroSense.svg" \
        "$ICON_THEME/scalable/apps/io.github.napejoon.NitroSense.svg"
fi
for t in nitrosense-tray nitrosense-tray-warning nitrosense-tray-critical; do
    install -D -m 0644 "$SRC/data/icons/$t.svg" "$ICON_THEME/scalable/apps/$t.svg"
done
gtk-update-icon-cache -q -t -f "$ICON_THEME" 2>/dev/null || true
install -D -m 0644 "$SRC/data/io.github.napejoon.NitroSense.desktop" \
    "$APPS_DIR/io.github.napejoon.NitroSense.desktop"
update-desktop-database -q "$APPS_DIR" 2>/dev/null || true
install -d "$(dirname "$BIN_LINK")"
ln -sf /opt/nitrosense/bin/nitrosense "$BIN_LINK"
if [ "$IMMUTABLE" -eq 1 ]; then
    # files created by root inside the user's home: hand them back
    chown -R "$USER_NAME:" "$ICON_THEME" "$APPS_DIR/io.github.napejoon.NitroSense.desktop"
    if [ -f "$APPS_DIR/mimeinfo.cache" ]; then chown "$USER_NAME:" "$APPS_DIR/mimeinfo.cache"; fi
    chown -h "$USER_NAME:" "$BIN_LINK"
fi

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
        as_user env XDG_RUNTIME_DIR="/run/user/$USER_ID" \
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
