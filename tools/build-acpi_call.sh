#!/bin/bash
# Build the acpi_call kernel module for the running kernel on image-based distributions
# (Bluefin, Bazzite, Aurora, GNOME OS, ...) that ship neither DKMS nor kernel headers.
#
#   tools/build-acpi_call.sh            # build as your user, then install with sudo
#   tools/build-acpi_call.sh --no-install
#
# Run it again after every system update that brings a new kernel.
#
# How it works: the image ships the kernel's .config in /usr/lib/modules/<version>/config, and
# for a stock kernel.org kernel that is enough to prepare a matching tree. The build runs in a
# throwaway Fedora container (podman, no root needed); the vanilla source tarball is checked
# against kernel.org's sha256sums. Before installing, the size of `struct module` in the new
# module is compared with the running kernel's BTF: a mismatch would make the kernel refuse the
# module ("Invalid module format"), so the script stops instead.
set -euo pipefail

KVER="$(uname -r)"
INSTALL=1
[ "${1:-}" = "--no-install" ] && INSTALL=0

ACPI_CALL_REPO="https://github.com/nix-community/acpi_call"
ACPI_CALL_COMMIT="6ad1e676dbfb5dcb1ec1f973c10ef5c57ffb4069"
IMAGE="registry.fedoraproject.org/fedora:45"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/nitrosense-kmod"
DEST="/var/lib/nitrosense-kmod/$KVER"
CONFIG="/usr/lib/modules/$KVER/config"

die() { echo "error: $*" >&2; exit 1; }

[ "$(id -u)" -ne 0 ] || die "run as your normal user (the build runs in a rootless container)"
command -v podman >/dev/null || die "podman is required"
[ -r "$CONFIG" ] || die "$CONFIG not found: this kernel does not ship its configuration"
[ -r /sys/kernel/btf/vmlinux ] || die "/sys/kernel/btf/vmlinux not found: cannot verify the build"
# Only stock kernel.org releases (7.2.6, 6.18.3, ...) can be rebuilt from the vanilla tarball.
[[ "$KVER" =~ ^([0-9]+)\.[0-9]+(\.[0-9]+)?$ ]] \
    || die "kernel $KVER is not a stock kernel.org release; build acpi_call with your distribution's tools"
MAJOR="${BASH_REMATCH[1]}"

mkdir -p "$CACHE"
cd "$CACHE"
TARBALL="linux-$KVER.tar.xz"
if [ ! -f "$TARBALL" ]; then
    echo "==> Downloading $TARBALL"
    curl -fL --progress-bar -o "$TARBALL.part" "https://cdn.kernel.org/pub/linux/kernel/v$MAJOR.x/$TARBALL"
    mv "$TARBALL.part" "$TARBALL"
fi
echo "==> Verifying $TARBALL"
curl -fsSL -o sha256sums.asc "https://cdn.kernel.org/pub/linux/kernel/v$MAJOR.x/sha256sums.asc"
grep " $TARBALL\$" sha256sums.asc | sha256sum -c --quiet - || { rm -f "$TARBALL"; die "checksum mismatch"; }

if [ ! -d acpi_call/.git ]; then
    git clone -q "$ACPI_CALL_REPO" acpi_call
fi
git -C acpi_call fetch -q origin
git -C acpi_call checkout -q --detach "$ACPI_CALL_COMMIT"

cp "$CONFIG" kconfig
rm -f acpi_call.ko

echo "==> Building acpi_call for $KVER (Fedora container)"
podman run --rm --security-opt label=disable \
    -v "$CACHE:/b" -v /sys/kernel/btf/vmlinux:/host_btf:ro \
    -e KVER="$KVER" "$IMAGE" bash -euo pipefail -c '
dnf -y -q install gcc gcc-plugin-devel make flex bison bc elfutils-libelf-devel \
    openssl-devel perl diffutils dwarves xz > /tmp/dnf.log 2>&1 || { cat /tmp/dnf.log >&2; exit 1; }
cd /tmp && tar -xf "/b/linux-$KVER.tar.xz" && cd "linux-$KVER"
cp /b/kconfig .config
make -s olddefconfig
make -s -j"$(nproc)" modules_prepare
cp -r /b/acpi_call /tmp/acpi_call && cd /tmp/acpi_call
# No Module.symvers without the distribution headers: unresolved symbols are only warnings
# here and are checked against System.map below.
make -s KDIR="/tmp/linux-$KVER" KBUILD_MODPOST_WARN=1 > build.log 2>&1 || { cat build.log >&2; exit 1; }
grep -v -e "undefined!" -e "unresolved symbol" build.log || true
kernel_size=$(pahole -C module /host_btf | grep -o "size: [0-9]*" | head -1)
module_size=$(pahole -C module acpi_call.ko | grep -o "size: [0-9]*" | head -1)
echo "    struct module: kernel $kernel_size, module $module_size"
[ -n "$kernel_size" ] && [ "$kernel_size" = "$module_size" ] || { echo "struct module size mismatch" >&2; exit 1; }
cp acpi_call.ko /b/acpi_call.ko
'

echo "==> Checking the module against the running kernel"
vermagic="$(modinfo -F vermagic acpi_call.ko)"
[ "${vermagic%% *}" = "$KVER" ] || die "vermagic '$vermagic' does not match $KVER"
SYSMAP="/usr/lib/modules/$KVER/System.map"
if [ -r "$SYSMAP" ]; then
    for sym in $(nm -u acpi_call.ko | awk '{print $2}'); do
        grep -q " __ksymtab_$sym\$" "$SYSMAP" || die "symbol $sym is not exported by this kernel"
    done
fi
echo "    vermagic: $vermagic"

if [ "$INSTALL" -eq 0 ]; then
    echo "Built $CACHE/acpi_call.ko (not installed)."
    exit 0
fi
echo "==> Installing to $DEST (sudo)"
sudo install -D -m 0644 -o root -g root acpi_call.ko "$DEST/acpi_call.ko"
if systemctl cat nitrosense-acpi-call.service >/dev/null 2>&1; then
    sudo systemctl restart nitrosense-acpi-call.service
    sudo systemctl restart nitrosensed.service 2>/dev/null || true
    echo "Done: acpi_call loaded and the NitroSense service restarted."
else
    echo "Done. Now run: sudo ./install.sh"
fi
