#!/bin/bash
# Reload the in-kernel acer_wmi driver with predator_v4=1 and report what it exposes
# (fan RPM, temperatures, PWM, platform profile). Works under kernel lockdown, since
# acer_wmi is a signed in-tree module. Run as root: sudo tools/probe-acer-wmi.sh
# Output goes to stdout and to /tmp/acer-wmi-probe.txt.
set -u
[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }
OUT=/tmp/acer-wmi-probe.txt
exec > >(tee "$OUT") 2>&1

echo "== kernel $(uname -r), $(cat /sys/class/dmi/id/product_name)"
echo "== reloading acer_wmi predator_v4=1"
modprobe -r acer_wmi && modprobe acer_wmi predator_v4=1
echo "predator_v4=$(cat /sys/module/acer_wmi/parameters/predator_v4)"
sleep 1
echo "== dmesg"
dmesg | grep -i -e acer -e "platform_profile" | tail -20

echo "== hwmon"
for h in /sys/class/hwmon/hwmon*; do
    n=$(cat "$h/name")
    echo "-- $h ($n)"
    for f in "$h"/fan*_input "$h"/temp*_input "$h"/temp*_label "$h"/pwm* "$h"/fan*_label; do
        [ -e "$f" ] && echo "   $(basename "$f") = $(cat "$f" 2>&1)"
    done
done

echo "== platform_profile"
for f in /sys/firmware/acpi/platform_profile /sys/firmware/acpi/platform_profile_choices; do
    [ -e "$f" ] && echo "$f = $(cat "$f")"
done
for d in /sys/class/platform-profile/*; do
    [ -d "$d" ] && echo "$d: name=$(cat "$d/name" 2>/dev/null) profile=$(cat "$d/profile" 2>/dev/null) choices=$(cat "$d/choices" 2>/dev/null)"
done

echo "== acer platform device"
ls -la /sys/devices/platform/acer-wmi/ 2>/dev/null
for f in /sys/devices/platform/acer-wmi/predator_sense/*; do
    [ -f "$f" ] && echo "   $(basename "$f") = $(cat "$f" 2>&1)"
done
chmod 0644 "$OUT"
echo "== saved to $OUT"
