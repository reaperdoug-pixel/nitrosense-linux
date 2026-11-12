#!/usr/bin/python3 -I
"""Read-only probe: does this firmware offer Acer's battery health mode (charge limit)?

sudo python3 -I tools/probe_battery.py

Sends only the *get* request (WMI method 20 of GUID 79772EC5-..., the one the out-of-tree
acer-wmi-battery driver uses to read the state). Nothing is changed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from nitrosense import wmi  # noqa: E402

BATTERY_GUID = "79772EC5-04B1-4BFD-843C-61E7F77B6CC9"
# input (4 bytes): battery 1, function query 1, 2 reserved bytes
wmi.METHODS["GetBatteryHealth"] = (BATTERY_GUID, 20, 4)


def main() -> int:
    if os.geteuid() != 0:
        print("run as root (sudo)")
        return 2
    w = wmi.AcerWmi()
    if not os.path.exists(wmi.ACPI_CALL):
        print("acpi_call is not loaded")
        return 1
    try:
        print("ACPI method:", w._path(BATTERY_GUID))
        out = w.call_bytes("GetBatteryHealth", 0x0101)
    except wmi.WmiError as e:
        print("the firmware did not answer:", e)
        return 1
    print("raw output:", out.hex(" "), f"({len(out)} bytes)")
    if len(out) < 8:
        print("unexpected length (the driver expects 8 bytes): cannot interpret")
        return 1
    funcs, status = out[0], out[3:8]
    for bit, name, idx in ((1, "health mode (charge limit)", 0), (2, "calibration mode", 1)):
        if funcs & bit:
            print(f"{name}: supported, currently {'ON' if status[idx] > 0 else 'off'}")
        else:
            print(f"{name}: not supported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
