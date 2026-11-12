"""CPU power in watts from the Intel RAPL energy counters (/sys/class/powercap).

The counters are readable by root only (since kernel 5.10), so the service reads them.
Watts are the energy used between two consecutive samples divided by the time between
them, so each Rapl object measures the average since its own previous sample.
"""

from __future__ import annotations

import glob
import os
import time

POWERCAP = "/sys/class/powercap"
# powercap zone name -> our key
ZONES = {"package-0": "cpu", "core": "core", "uncore": "igpu", "dram": "dram", "psys": "sys"}


def _read_int(path: str) -> int | None:
    try:
        with open(path) as f:
            return int(f.read())
    except (OSError, ValueError):
        return None


class Rapl:
    def __init__(self, root: str = POWERCAP, clock=time.monotonic) -> None:
        self.clock = clock
        self.zones: dict[str, tuple[str, int]] = {}  # key -> (energy file, wrap-around range)
        for path in sorted(glob.glob(os.path.join(root, "intel-rapl:*"))):
            try:
                with open(os.path.join(path, "name")) as f:
                    key = ZONES.get(f.read().strip())
            except OSError:
                continue
            if key and key not in self.zones:
                span = _read_int(os.path.join(path, "max_energy_range_uj")) or (1 << 32)
                self.zones[key] = (os.path.join(path, "energy_uj"), span)
        self._prev: tuple[float, dict[str, int]] | None = None
        self._last: dict[str, float] = {}

    def _energies(self) -> dict[str, int]:
        out = {}
        for key, (path, _span) in self.zones.items():
            v = _read_int(path)
            if v is not None:
                out[key] = v
        return out

    def sample(self) -> dict[str, float]:
        """-> {'cpu': W, 'core': W, 'igpu': W, 'sys': W ...} since the previous call.

        Empty on the first call (no baseline yet) or when the counters are unreadable.
        """
        now, cur = self.clock(), self._energies()
        prev, self._prev = self._prev, (now, cur)
        if prev is None or not cur:
            return {}
        dt = now - prev[0]
        if dt < 0.05:  # two calls back to back: repeat the last answer
            self._prev = prev
            return self._last
        out = {}
        for key, e in cur.items():
            if key not in prev[1]:
                continue
            delta = e - prev[1][key]
            if delta < 0:  # the counter wrapped around
                delta += self.zones[key][1]
            out[key] = round(delta / 1e6 / dt, 2)
        self._last = out
        return out
