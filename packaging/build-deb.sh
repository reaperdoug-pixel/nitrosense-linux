#!/bin/bash
# Build nitrosense_<version>_all.deb from this checkout.
#   packaging/build-deb.sh            -> dist/nitrosense_<version>_all.deb
# Needs only dpkg-deb. Install the result with: sudo apt install ./dist/nitrosense_*.deb
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$(dirname "$HERE")"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/nitrosense/__init__.py")"
[ -n "$VERSION" ] || { echo "could not read __version__" >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/pkg"

install -d "$ROOT/DEBIAN" "$ROOT/opt/nitrosense/bin" "$ROOT/usr/bin" \
    "$ROOT/etc/nitrosense/model" "$ROOT/etc/xdg/autostart" \
    "$ROOT/usr/lib/systemd/system" "$ROOT/usr/lib/udev/hwdb.d" "$ROOT/usr/lib/modules-load.d" \
    "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/scalable/apps" \
    "$ROOT/usr/share/doc/nitrosense"

# program (no bytecode caches)
cp -r "$SRC/nitrosense" "$ROOT/opt/nitrosense/"
find "$ROOT/opt/nitrosense" -name '__pycache__' -prune -exec rm -rf {} +
install -m 0755 "$SRC/bin/nitrosense" "$SRC/bin/nitrosensed" "$SRC/bin/nitrosense-watch" "$ROOT/opt/nitrosense/bin/"
ln -s /opt/nitrosense/bin/nitrosense "$ROOT/usr/bin/nitrosense"

# system integration
install -m 0644 "$SRC/data/nitrosensed.service" "$ROOT/usr/lib/systemd/system/nitrosensed.service"
install -m 0644 "$SRC/data/61-nitrosense.hwdb" "$ROOT/usr/lib/udev/hwdb.d/61-nitrosense.hwdb"
echo acpi_call > "$ROOT/usr/lib/modules-load.d/nitrosense.conf"
install -m 0644 "$SRC/data/nitrosense-watch.desktop" "$ROOT/etc/xdg/autostart/nitrosense-watch.desktop"
install -m 0644 "$SRC/data/io.github.napejoon.NitroSense.desktop" "$ROOT/usr/share/applications/"
install -m 0644 "$SRC/data/icons/"*.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/"
install -m 0644 "$SRC/LICENSE" "$ROOT/usr/share/doc/nitrosense/copyright"

# control files
SIZE="$(du -sk --exclude=DEBIAN "$ROOT" | cut -f1)"
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" "$HERE/debian/control" > "$ROOT/DEBIAN/control"
install -m 0755 "$HERE/debian/preinst" "$HERE/debian/postinst" "$HERE/debian/prerm" "$HERE/debian/postrm" "$ROOT/DEBIAN/"
echo /etc/xdg/autostart/nitrosense-watch.desktop > "$ROOT/DEBIAN/conffiles"

# no group/other write, root-owned regardless of who builds
chmod -R go-w "$ROOT"
mkdir -p "$SRC/dist"
OUT="$SRC/dist/nitrosense_${VERSION}_all.deb"
fakeroot sh -c "chown -R 0:0 '$ROOT' && dpkg-deb --build --root-owner-group -Zxz '$ROOT' '$OUT'" >/dev/null
echo "$OUT"
