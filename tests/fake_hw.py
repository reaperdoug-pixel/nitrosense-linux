"""Simulated Acer WMI firmware + mock daemon for tests and GUI development."""

from __future__ import annotations

import math
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nitrosense import daemon as dmod  # noqa: E402
from nitrosense import disks as disks_mod  # noqa: E402
from nitrosense import encoders as enc  # noqa: E402
from nitrosense import power  # noqa: E402
from nitrosense.wmi import METHODS, WmiError  # noqa: E402


class FakeWmi:
    """Behaves like the AN515-44 firmware for the methods NitroSense uses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.fan_behavior = {"cpu": 1, "gpu": 1}
        self.fan_speed = {"cpu": 0, "gpu": 0}
        self.coolboost = False
        self.overdrive = False
        self.battery_limit = False
        self.reject_battery_limit = False
        self.backlight = (100, False)
        self.t0 = time.monotonic()

    def available(self):
        return True, ""

    def call(self, name: str, value: int) -> int:
        _guid, _mid, size = METHODS[name]
        if value >= 1 << (8 * size):
            raise WmiError("input too large")
        self.calls.append((name, value))
        if name == "SetGamingFanBehavior":
            if value & 1:
                self.fan_behavior["cpu"] = (value >> 16) & 3
            if value & 8:
                self.fan_behavior["gpu"] = (value >> 22) & 3
            return 0
        if name == "SetGamingFanSpeed":
            fan = {1: "cpu", 4: "gpu"}[value & 0xFF]
            self.fan_speed[fan] = (value >> 8) & 0xFF
            return 0
        if name == "GetGamingSysInfo":
            idx = (value >> 8) & 0xFF
            t = time.monotonic() - self.t0
            vals = {enc.SENSOR_CPU_TEMP: 55 + int(8 * math.sin(t / 7)),
                    enc.SENSOR_GPU_TEMP: 48 + int(5 * math.sin(t / 9)),
                    enc.SENSOR_CPU_FAN: self._rpm("cpu"),
                    enc.SENSOR_GPU_FAN: self._rpm("gpu")}
            if idx not in vals:
                return 1
            return vals[idx] << 8
        if name == "SetFunction":
            if value & 0xFF == 7:
                self.coolboost = bool((value >> 16) & 1)
            elif value & 0xFF == 2:
                self.backlight = ((value >> 32) & 0xFF, ((value >> 40) & 0xFF) == 30)
            return 0
        if name == "GetFunction":
            if value == enc.COOLBOOST_GET:
                return int(self.coolboost) << 8
            if value & 0xFF == 1:
                return (self.backlight[0] << 32) | ((30 if self.backlight[1] else 0) << 40)
            return 1
        if name == "GetGamingProfile":
            return (1 if self.overdrive else 0) << 48
        if name == "SetGamingProfile":
            if value & 0xFF == 0x10:
                self.overdrive = bool((value >> 48) & 1)
            return 0
        if name == "GetBatteryHealth":
            return 3 | (int(self.battery_limit) << 24)
        if name == "SetBatteryHealth":
            if value & 0xFF == 1 and (value >> 8) & 0xFF == 1 and not self.reject_battery_limit:
                self.battery_limit = bool((value >> 16) & 0xFF)
            return 0
        if name == "GetGamingMiscSetting":
            return 0  # no discrete GPU switch on AN515-44
        return 0

    def _rpm(self, fan: str) -> int:
        b = self.fan_behavior[fan]
        if b == 2:
            return 5200
        if b == 3:
            return int(self.fan_speed[fan] * 55)
        return 2300 if fan == "cpu" else 2100


class FakeRapl:
    """CPU power that wobbles like a real laptop (the real counters need root)."""

    def sample(self):
        t = time.monotonic()
        cpu = 18 + 9 * math.sin(t / 5)
        return {"cpu": round(cpu, 1), "igpu": 1.2, "sys": round(cpu + 14, 1)}


def make_daemon(state_dir: str | None = None):
    state_dir = state_dir or tempfile.mkdtemp(prefix="nitrosense-test-")
    dmod.STATE_DIR = state_dir
    dmod.STATE_FILE = os.path.join(state_dir, "state.json")
    dmod._allowed_uids = lambda: {0, os.getuid()}
    applied = []
    power.apply_plan = lambda plan: applied.append(plan)
    dmod.power.apply_plan = power.apply_plan
    d = dmod.Daemon()
    d.ctl.wmi = FakeWmi()
    d.ready = True
    d._rapl = d._rapl_rec = FakeRapl()
    d.hw_battery_limit = d.ctl.get_battery_limit()
    d.ctl.wmi.calls.clear()  # tests assert on the calls they trigger themselves
    d.power_applied_log = applied
    # synthetic NVMe SMART data (the real log needs root); wear is configurable for GUI demos
    wear = int(os.environ.get("NITROSENSE_FAKE_WEAR", "3"))
    log = bytearray(512)
    log[1:3] = (307).to_bytes(2, "little")
    log[3], log[4], log[5] = 100, 10, wear
    log[48:64] = (2_600_000).to_bytes(16, "little")
    log[32:48] = (4_100_000).to_bytes(16, "little")
    log[112:128] = (410).to_bytes(16, "little")
    log[128:144] = (1250).to_bytes(16, "little")
    log[144:160] = (9).to_bytes(16, "little")
    d._smart_cache = (1e12, {"nvme0": disks_mod.parse_smart_log(bytes(log))})
    return d


def seed_history(d, days: int = 7) -> None:
    """Fill the daemon's recorder with synthetic history (GUI demos)."""
    import random
    from nitrosense import history
    d.recorder = history.Recorder(tempfile.mkdtemp(prefix="ns-hist-"))
    now = time.time()
    rnd = random.Random(7)
    t = now - days * 86400
    while t < now:
        hour = (t % 86400) / 3600
        busy = 1 if 9 <= hour <= 18 or 20 <= hour <= 23 else 0.15
        asleep = 2 <= hour < 7.5 and int(t // 86400) % 2 == 0  # laptop suspended some nights
        if not asleep:
            load = max(2, min(100, 25 * busy + rnd.gauss(0, 12) + (40 if rnd.random() < 0.04 else 0)))
            cpu = 38 + load * 0.55 + rnd.gauss(0, 2)
            gpu = None if rnd.random() < 0.6 else 45 + load * 0.3
            on_battery = int(t // 86400) % 3 == 0 and 9 <= hour <= 15
            d.recorder.record({"cpu": cpu, "gpu": gpu, "ssd": 30 + load * 0.08 + rnd.gauss(0, 0.6),
                               "cf": 2300, "gf": 2100, "load": load,
                               "fq": 4600 - cpu * 22 + rnd.gauss(0, 80),
                               "thr": 100.0 if cpu > 80 else (35.0 if cpu > 74 else 0.0),
                               "pl": 0.0,
                               "cpw": 6 + load * 0.55 + rnd.gauss(0, 1.2),
                               "gpw": None if gpu is None else 9 + load * 0.4,
                               "bat": (100 - (hour - 9) * 9) if on_battery else 100,
                               "pw": (14 + load * 0.35) if on_battery else None}, t)
        t += 30
    _seed_battery(d, now)
    d.recorder._last_smart = 0
    d.recorder.record_smart({"nvme0": {"percentage_used": 9, "bytes_written": 33_000_000_000_000,
        "bytes_read": 70_000_000_000_000, "power_on_hours": 4600, "unsafe_shutdowns": 41,
        "media_errors": 0, "available_spare": 100}}, now - 5 * 86400)
    d.recorder._last_smart = 0
    d.recorder.record_smart({"nvme0": {"percentage_used": 10, "bytes_written": 34_200_000_000_000,
        "bytes_read": 72_500_000_000_000, "power_on_hours": 4738, "unsafe_shutdowns": 42,
        "media_errors": 0, "available_spare": 100}}, now - 60)


def _seed_battery(d, now) -> None:
    for days, health, cycles in ((6, 83.9, 50), (0.01, 83.4, 54)):
        d.recorder._last_battery = 0
        d.recorder.record_battery([{"name": "BAT1", "health": health, "energy_full": 48.0,
                                    "energy_design": 57.5, "cycles": cycles}], now - days * 86400)


def main() -> None:
    sock = sys.argv[1] if len(sys.argv) > 1 else os.path.join(tempfile.gettempdir(), "ns-test.sock")
    d = make_daemon()
    if os.environ.get("NITROSENSE_FAKE_HISTORY"):
        seed_history(d)
    if os.environ.get("NITROSENSE_FAKE_THROTTLE"):  # pretend thermald is holding the CPU back
        d.throttle._cooling_states = lambda: {"processor": 2, "powerclamp": 0, "tcc": 8}
    d.start_throttle_monitor(1.0)
    d.start_fan_curve(1.0)
    dmod.start_server(d, sock)
    print("mock nitrosensed on", sock, flush=True)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
