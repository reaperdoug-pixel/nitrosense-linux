"""CPU throttling detection from kernel interfaces (no MSRs, no privileges needed).

Signals, all read from sysfs:
  * hardware thermal events: x86 thermal_throttle package/core counters (count and time)
  * thermal management: "Processor" / intel_powerclamp cooling devices above state 0
    (thermald / Intel DPTF are holding the CPU back)
  * power limit: package power (from RAPL, passed in) close to the long/short-term limit
  * frequency cap: scaling_max_freq below the hardware maximum (information only: a power
    plan may do this on purpose)
update() is meant to be called every couple of seconds by one owner (the service).
"""

from __future__ import annotations

import glob
import os
import time

SYS_CPU = "/sys/devices/system/cpu"
SYS_THERMAL = "/sys/class/thermal"
POWERCAP = "/sys/class/powercap"
SYS_HWMON = "/sys/class/hwmon"

POWER_LIMIT_MARGIN = 0.97   # package power at or above this share of PL1/PL2 counts as limited
THERMAL_ALERT_S = 10        # continuous thermal throttling before the alert is raised


def _int(path: str) -> int | None:
    try:
        with open(path) as f:
            return int(f.read())
    except (OSError, ValueError):
        return None


def _text(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


class CpuThrottle:
    def __init__(self, cpu_root: str = SYS_CPU, thermal_root: str = SYS_THERMAL,
                 powercap: str = POWERCAP, clock=time.monotonic, hwmon: str = SYS_HWMON) -> None:
        self.clock = clock
        self.cpus = sorted(glob.glob(os.path.join(cpu_root, "cpu[0-9]*")))
        self.cooling: list[tuple[str, str]] = []
        for dev in sorted(glob.glob(os.path.join(thermal_root, "cooling_device*"))):
            kind = _text(os.path.join(dev, "type")) or ""
            for key, wanted in (("processor", "Processor"), ("powerclamp", "intel_powerclamp"),
                                ("tcc", "TCC Offset")):
                if kind == wanted:
                    self.cooling.append((key, os.path.join(dev, "cur_state")))
        zone = os.path.join(powercap, "intel-rapl:0")
        self.pl_files = [os.path.join(zone, f"constraint_{i}_power_limit_uw") for i in (0, 1)]
        self.tj_max: float | None = None  # coretemp's critical temperature (Tjmax), in C
        for hw in glob.glob(os.path.join(hwmon, "hwmon*")):
            if _text(os.path.join(hw, "name")) == "coretemp":
                crit = _int(os.path.join(hw, "temp1_crit"))
                self.tj_max = crit / 1000 if crit else None
                break
        self._prev: tuple[int, int] | None = None
        self._thermal_since: float | None = None
        self._reset_window()
        self.last: dict = {}

    # --------------------------------------------------------------- reading
    def _counters(self) -> tuple[int, int]:
        """(events, milliseconds) summed over the package and all core throttle counters."""
        events = ms = 0
        for cpu in self.cpus:
            base = os.path.join(cpu, "thermal_throttle")
            for name in ("core_throttle_count", "package_throttle_count"):
                events += _int(os.path.join(base, name)) or 0
            for name in ("core_throttle_total_time_ms", "package_throttle_total_time_ms"):
                ms += _int(os.path.join(base, name)) or 0
        return events, ms

    def _frequencies(self) -> tuple[list[int], int, bool]:
        """-> (current kHz per core, hardware max kHz, any core capped below its maximum)."""
        cur, fmax, capped = [], 0, False
        for cpu in self.cpus:
            base = os.path.join(cpu, "cpufreq")
            f, hw, cap = (_int(os.path.join(base, n)) for n in
                          ("scaling_cur_freq", "cpuinfo_max_freq", "scaling_max_freq"))
            if f is not None:
                cur.append(f)
            if hw:
                fmax = max(fmax, hw)
                if cap is not None and cap < hw:
                    capped = True
        return cur, fmax, capped

    def _cooling_states(self) -> dict[str, int]:
        out = {"processor": 0, "powerclamp": 0, "tcc": 0}
        for key, path in self.cooling:
            v = _int(path)
            if v is not None:
                out[key] = max(out[key], v)
        return out

    def power_limits(self) -> list[float]:
        """Long- and short-term package power limits in watts (0 / unreadable are left out)."""
        out = []
        for path in self.pl_files:
            v = _int(path)
            if v and v > 0:
                out.append(v / 1e6)
        return out

    # ---------------------------------------------------------------- update
    def update(self, pkg_watts: float | None = None) -> dict:
        now = self.clock()
        events, ms = self._counters()
        freqs, fmax, capped = self._frequencies()
        cool = self._cooling_states()
        prev, self._prev = self._prev, (events, ms)
        hw_event = prev is not None and (events > prev[0] or ms > prev[1])
        managed = cool["processor"] > 0 or cool["powerclamp"] > 0
        thermal = hw_event or managed
        limits = self.power_limits()
        power_limited = bool(pkg_watts is not None and limits
                             and any(pkg_watts >= POWER_LIMIT_MARGIN * lim for lim in limits))
        if thermal:
            self._thermal_since = self._thermal_since if self._thermal_since is not None else now
        else:
            self._thermal_since = None
        mhz = round(sum(freqs) / len(freqs) / 1000) if freqs else None
        reasons = []
        if hw_event:
            reasons.append("Calor: o processador reduziu a frequência (proteção do hardware).")
        if managed:
            reasons.append("Gestão térmica do sistema está limitando o processador.")
        if power_limited:
            reasons.append(f"Limite de potência atingido ({pkg_watts:.0f} W).")
        if capped:
            reasons.append("Frequência máxima reduzida pelo sistema (plano de energia ou térmica).")
        self.last = {
            "mhz": mhz, "mhz_peak": round(max(freqs) / 1000) if freqs else None,
            "mhz_max": round(fmax / 1000) if fmax else None,
            "thermal": thermal, "power_limited": power_limited, "freq_capped": capped,
            "thermal_for_s": round(now - self._thermal_since, 1) if self._thermal_since is not None else 0,
            "events": events, "cooling": cool,
            # the hardware starts throttling at Tjmax minus the TCC offset
            "tcc_offset": cool["tcc"] or None,
            "limit_c": round(self.tj_max - cool["tcc"]) if self.tj_max and cool["tcc"] else None,
            "reasons": reasons,
        }
        w = self._win
        w["n"] += 1
        w["thermal"] += thermal
        w["power"] += power_limited
        if mhz is not None:
            w["mhz"] += mhz
            w["mhz_n"] += 1
        return self.last

    # --------------------------------------------------------------- window
    def _reset_window(self) -> None:
        self._win = {"n": 0, "thermal": 0, "power": 0, "mhz": 0.0, "mhz_n": 0}

    def window(self) -> dict:
        """Averages since the previous call, for the history: share of time limited, mean MHz."""
        w, self._win = self._win, {"n": 0, "thermal": 0, "power": 0, "mhz": 0.0, "mhz_n": 0}
        if not w["n"]:
            return {}
        return {"thr": round(100 * w["thermal"] / w["n"], 1), "pl": round(100 * w["power"] / w["n"], 1),
                "fq": round(w["mhz"] / w["mhz_n"]) if w["mhz_n"] else None}
