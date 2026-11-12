"""nitrosensed - root service that owns the Acer WMI interface.

Mirrors the Windows NitroSense service + agent: executes hardware requests
from the GUI, remembers the settings and re-applies them at boot, after
resume from suspend, and (power plans) whenever the AC adapter changes.
"""

from __future__ import annotations

import copy
import glob
import json
import logging
import os
import pwd
import re
import socket
import socketserver
import struct
import sys
import threading
import time

from . import battery
from . import calibration
from . import disks
from . import fancurve
from . import history
from . import encoders as enc
from . import model as model_cfg
from . import set_process_name
from . import power
from . import procs
from . import throttle
from .rapl import Rapl
from .sysmon import CpuLoad, GpuMonitor, gpu_throttle
from .controller import Controller, wait_for_acpi_call
from .protocol import (ALLOWED_USERS_FILE, MAX_REQUEST, SOCKET_DIR, SOCKET_PATH,
                       HISTORY_DIR, STATE_DIR, STATE_FILE, default_state)
from .wmi import WmiError

log = logging.getLogger("nitrosense.daemon")

GPU_GATE_C = 78  # below this the dGPU is never asked about slowdowns (see gpu_slowdown_step)

HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class ValidationError(ValueError):
    pass


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    raise ValidationError("expected boolean")


def _int(v, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValidationError(f"expected integer {lo}..{hi}")
    return v


def _choice(v, options) -> str:
    if v not in options:
        raise ValidationError(f"expected one of {', '.join(options)}")
    return v


def validate_keyboard(kb) -> dict:
    if not isinstance(kb, dict):
        raise ValidationError("keyboard must be an object")
    out = {
        "mode": _choice(kb.get("mode"), ("static", "dynamic")),
        "brightness": _int(kb.get("brightness"), 1, 5),
        "effect": _choice(kb.get("effect"), enc.EFFECTS),
        "speed": _int(kb.get("speed"), 1, 9),
        "direction": _int(kb.get("direction"), 1, 2),
    }
    zones_on = kb.get("zones_on")
    colors = kb.get("zone_colors")
    if not (isinstance(zones_on, list) and len(zones_on) == 4):
        raise ValidationError("zones_on must have 4 entries")
    if not (isinstance(colors, list) and len(colors) == 4):
        raise ValidationError("zone_colors must have 4 entries")
    out["zones_on"] = [_bool(z) for z in zones_on]
    for c in colors + [kb.get("effect_color")]:
        if not isinstance(c, str) or not HEX_COLOR.match(c):
            raise ValidationError("colors must be #RRGGBB")
    out["zone_colors"] = [c.upper() for c in colors]
    out["effect_color"] = kb["effect_color"].upper()
    return out


class Daemon:
    def __init__(self) -> None:
        self.model = model_cfg.load()
        self.ctl = Controller(adjust=enc.ColorAdjust(*self.model.zone_adjust))
        self.lock = threading.RLock()
        self.state = self._load_state()
        self.ready = False
        self.error = ""
        self._sensor_cache: tuple[float, dict] = (0.0, {})
        self._smart_cache: tuple[float, dict] = (-1e9, {})
        self._holders_cache: tuple[float, list] = (-1e9, [])
        self.recorder: history.Recorder | None = None
        self._stop = threading.Event()
        self._cpu_load = None
        self._gpu_mon = None
        self._rapl = Rapl()      # live readings (the window polls every second)
        self._rapl_rec = Rapl()  # its own baseline: the history gets the average over each interval
        self._rapl_thr = Rapl()  # and one more for the throttling monitor
        self.throttle = throttle.CpuThrottle()
        self.curve = fancurve.FanCurves()
        self.fan_lock = threading.RLock()  # serialises fan commands and the curve thread
        self._gpu_probe = GpuMonitor()     # only to know whether the dGPU is awake
        self._gpu_slow = GpuMonitor()      # NVML slowdown reasons, used by the throttle thread only
        self.gpu_throttle: dict = {}
        self._gpu_thermal_for = 0.0
        self._ac = power.ac_online()
        self.gpu_mode_supported = False
        self.gpu_mode = 0
        self.hw_lcd_overdrive = None
        self.hw_coolboost = None
        self.hw_backlight_timeout = None
        self.hw_battery_limit = None  # None = not supported
        self.hw_battery_calibration = None  # None = not supported
        self.cal_lock = threading.RLock()
        self._battery_read = battery.read   # replaceable in tests

    @property
    def overdrive_supported(self) -> bool:
        # Windows shows LCD Overdrive only with the factory flag LCD_Overdrive_support.
        # On the AN515-44 panel the setting is accepted but never takes effect, so it is
        # offered only when the firmware reports Overdrive as active.
        return self.hw_lcd_overdrive is True

    @property
    def battery_limit_supported(self) -> bool:
        return self.hw_battery_limit is not None

    @property
    def backlight_timeout_supported(self) -> bool:
        return self.hw_backlight_timeout is not None

    # ------------------------------------------------------------ state
    def _load_state(self) -> dict:
        state = default_state(self.model.zone_default_colors)
        try:
            with open(STATE_FILE) as f:
                saved = json.load(f)
            for key, value in saved.items():
                if key in state:
                    if isinstance(state[key], dict) and isinstance(value, dict):
                        state[key].update(value)
                    else:
                        state[key] = value
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as e:
            log.warning("state file unreadable, using defaults: %s", e)
        return state

    def _save_state(self) -> None:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE_FILE)

    # ------------------------------------------------------------ apply
    def startup(self) -> None:
        if not wait_for_acpi_call():
            self.error = "acpi_call kernel module is not loaded"
            log.error(self.error)
        ok, why = self.ctl.wmi.available()
        if not ok:
            self.error = why
            log.error("hardware interface unavailable: %s", why)
        else:
            self.ready = True
            self.gpu_mode_supported = self.ctl.gpu_mode_supported()
            if self.gpu_mode_supported:
                self.gpu_mode = self.ctl.get_gpu_mode()
            self.hw_lcd_overdrive = self.ctl.get_lcd_overdrive()
            self.hw_coolboost = self.ctl.get_coolboost()
            self.hw_battery_limit = self.ctl.get_battery_limit()
            self.hw_battery_calibration = self.ctl.get_battery_calibration()
            bl = self.ctl.get_backlight()
            self.hw_backlight_timeout = bl[1] if bl else None
        self.reapply("startup")

    def reapply(self, reason: str) -> None:
        """Restore persisted settings (Windows: NitroSense agent at logon/resume)."""
        log.info("re-applying settings (%s)", reason)
        with self.lock:
            st = copy.deepcopy(self.state)
        if self.ready:
            steps = [
                ("fan", lambda: self._reapply_fan(st)),
                ("coolboost", lambda: st["coolboost"] is not None and st["fan"]["mode"] == "auto"
                 and self.ctl.set_coolboost(st["coolboost"])),
                ("keyboard", lambda: st["keyboard_applied"] and self.ctl.apply_keyboard(st["keyboard"])),
                ("lcd_overdrive", lambda: st["lcd_overdrive"] is not None
                 and self.overdrive_supported and self.ctl.set_lcd_overdrive(st["lcd_overdrive"])),
                ("win_key", lambda: st["win_key"] is not None and self.ctl.set_win_key(st["win_key"])),
                # while a calibration runs the firmware keeps the charge limit off on purpose
                ("battery_limit", lambda: st["battery_limit"] is not None
                 and not st["battery_calibration"]["active"]
                 and self.battery_limit_supported and self.ctl.set_battery_limit(st["battery_limit"])),
                ("backlight_timeout", lambda: st["backlight_timeout"] is not None
                 and self.backlight_timeout_supported
                 and self.ctl.set_backlight_timeout(st["backlight_timeout"])),
            ]
            for name, fn in steps:
                try:
                    fn()
                except (WmiError, KeyError, ValueError) as e:
                    log.warning("re-apply %s failed: %s", name, e)
        if st["power_applied"]:
            self.apply_power(force=True)

    def _reapply_fan(self, st: dict) -> None:
        if st["fan"]["mode"] == "curve":
            self.curve.reset()          # the curve thread sets the speed on its next step
            self.fan_curve_step(0.0)
        else:
            self.ctl.set_fan_mode(**st["fan"])

    # ------------------------------------------------------- fan curve
    def start_fan_curve(self, interval: float = 2.0) -> None:
        def loop() -> None:
            while not self._stop.wait(interval):
                try:
                    self.fan_curve_step(interval)
                except Exception as e:  # never let the curve thread die silently
                    log.warning("fan curve step failed: %s", e)
        threading.Thread(target=loop, name="fancurve", daemon=True).start()

    def fan_curve_step(self, dt: float) -> None:
        with self.fan_lock:
            with self.lock:
                mode = self.state["fan"]["mode"]
                cfg = copy.deepcopy(self.state["fan_curve"])
            if mode != "curve":
                if self.curve.applied is not None or self.curve.failsafe:
                    self.curve.reset()
                return
            if not self.ready:
                return
            s = self.sensors()
            gpu = s["gpu_temp"] if self._gpu_probe.awake() else None  # asleep: value is not real
            plan = self.curve.step(cfg, s["cpu_temp"], gpu, dt)
            try:
                if plan.release:
                    log.warning("no temperature readings: fans back to automatic")
                    self.ctl.set_fan_mode("auto")
                elif plan.enter:
                    self.ctl.set_fan_mode("custom", False, False, plan.cpu, plan.gpu)
                else:
                    if plan.cpu is not None:
                        self.ctl.set_fan_speed("cpu", plan.cpu)
                    if plan.gpu is not None:
                        self.ctl.set_fan_speed("gpu", plan.gpu)
            except WmiError as e:
                log.warning("fan curve could not set the fans: %s", e)
                self.curve.reset()  # try again from scratch next time

    def release_fans(self) -> None:
        """On shutdown give the fans back to the firmware (a custom speed would stay otherwise)."""
        with self.fan_lock:
            if self.ready and self.state["fan"]["mode"] == "curve" and self.curve.applied is not None:
                try:
                    self.ctl.set_fan_mode("auto")
                except WmiError as e:
                    log.warning("could not release the fans: %s", e)

    def apply_power(self, force: bool = False) -> None:
        ac = power.ac_online()
        if not force and ac == self._ac:
            return
        self._ac = ac
        with self.lock:
            plan = self.state["power"]["ac" if ac else "battery"]
            applied = self.state["power_applied"]
        if applied:
            power.apply_plan(plan)

    # ---------------------------------------------------------- sensors
    def sensors(self) -> dict:
        now = time.monotonic()
        ts, cached = self._sensor_cache
        if now - ts < 0.7:
            return cached
        data = {"cpu_temp": None, "gpu_temp": None, "cpu_fan": None, "gpu_fan": None,
                "cpu_power": None, "igpu_power": None, "sys_power": None}
        if self.ready:
            data["cpu_temp"] = self.ctl.read_sensor(enc.SENSOR_CPU_TEMP)
            data["gpu_temp"] = self.ctl.read_sensor(enc.SENSOR_GPU_TEMP)
            data["cpu_fan"] = self.ctl.read_sensor(enc.SENSOR_CPU_FAN)
            data["gpu_fan"] = self.ctl.read_sensor(enc.SENSOR_GPU_FAN)
        if not data["cpu_temp"]:
            data["cpu_temp"] = _hwmon_temp(("k10temp", "coretemp", "zenpower"))
        watts = self._rapl.sample()
        data["cpu_power"], data["igpu_power"], data["sys_power"] = (
            watts.get("cpu"), watts.get("igpu"), watts.get("sys"))
        self._sensor_cache = (now, data)
        return data

    def smart(self) -> dict:
        """NVMe SMART data (needs root, so only the service can read it); cached for 10 s."""
        now = time.monotonic()
        ts, cached = self._smart_cache
        if now - ts < 10:
            return cached
        try:
            data = disks.read_smart()
        except Exception as e:  # never let a disk problem break the hardware service
            log.warning("disk SMART read failed: %s", e)
            data = {}
        self._smart_cache = (now, data)
        return data

    def holders(self) -> list:
        """Programs holding /dev/nvidia* open (root sees every user's); cached for 3 s."""
        now = time.monotonic()
        ts, cached = self._holders_cache
        if now - ts < 3:
            return cached
        try:
            data = procs.nvidia_holders()
        except Exception as e:  # a weird /proc entry must not break the service
            log.warning("gpu holders scan failed: %s", e)
            data = []
        self._holders_cache = (now, data)
        return data

    # ------------------------------------------------------- throttling
    def start_throttle_monitor(self, interval: float = 2.0) -> None:
        """Watch for CPU throttling every couple of seconds (short events would be missed by
        the 30 s history samples, so those get the share of time spent throttled instead)."""
        def loop() -> None:
            while not self._stop.wait(interval):
                try:
                    self.throttle.update(self._rapl_thr.sample().get("cpu"))
                    self.gpu_slowdown_step(interval)
                except Exception as e:
                    log.warning("throttle sample failed: %s", e)
        threading.Thread(target=loop, name="throttle", daemon=True).start()

    def gpu_slowdown_step(self, dt: float) -> None:
        """Is the dGPU being slowed down by heat? Uses NVML's clocks-event reasons.

        NVML is touched only when the GPU is already awake AND hot (GPU_GATE_C or more, read
        from the firmware sensor, which does not involve the GPU): a hot GPU is busy, so these
        reads can never keep an idle GPU from suspending.
        """
        temp = self.sensors()["gpu_temp"]
        sampled = bool(temp is not None and temp >= GPU_GATE_C and self._gpu_probe.awake())
        flags = {"thermal": False, "power": False, "hw": False}
        clocks: dict = {}
        if sampled:
            self._gpu_slow.sample()
            flags = gpu_throttle(self._gpu_slow.reasons)
            clocks = {"clock": self._gpu_slow.clock, "clock_max": self._gpu_slow.clock_max}
        self._gpu_thermal_for = self._gpu_thermal_for + dt if flags["thermal"] else 0.0
        self.gpu_throttle = dict(flags, sampled=sampled, thermal_for_s=round(self._gpu_thermal_for, 1),
                                 **clocks)

    # ---------------------------------------------------------- history
    def start_recorder(self, directory: str = HISTORY_DIR, interval: int = history.INTERVAL) -> None:
        """Sample sensors in the background so the history has no gaps while the GUI is closed."""
        self.recorder = history.Recorder(directory, interval)
        self._cpu_load = CpuLoad()
        self._gpu_mon = GpuMonitor()
        threading.Thread(target=self._record_loop, name="history", daemon=True).start()

    def _record_loop(self) -> None:
        last_prune = 0.0
        self._stop.wait(5)
        while not self._stop.is_set():
            try:
                self.record_sample()
                if time.time() - last_prune > 6 * 3600:
                    last_prune = time.time()
                    self.recorder.prune()
            except Exception as e:  # a full disk or odd sensor must never stop the service
                log.warning("history sample failed: %s", e)
            self._stop.wait(self.recorder.interval)

    def record_sample(self) -> None:
        s = self.sensors()
        gpu, gpu_watts = s["gpu_temp"], None
        if self._gpu_mon is not None and self._gpu_mon.present:
            if not self._gpu_mon.awake():
                gpu = None  # dGPU powered down: the firmware value is not a real reading
            else:
                self._gpu_mon.sample()  # also refreshes .power (NVML; never wakes the GPU)
                gpu_watts = self._gpu_mon.power
        watts = self._rapl_rec.sample()
        limits = self.throttle.window()
        bats = battery.read()
        main = bats[0] if bats else None
        self.recorder.record({"cpu": s["cpu_temp"], "gpu": gpu, "cf": s["cpu_fan"],
                              "gf": s["gpu_fan"], "ssd": disks.hottest_temp(),
                              "load": self._cpu_load.sample() if self._cpu_load else None,
                              "fq": limits.get("fq"), "thr": limits.get("thr"), "pl": limits.get("pl"),
                              "cpw": watts.get("cpu"), "gpw": gpu_watts, "sys": watts.get("sys"),
                              "bat": main["capacity"] if main else None,
                              "pw": main["power"] if main and main["status"] == "Discharging" else None})
        self.recorder.record_battery(bats)
        self.recorder.record_smart(self.smart())

    # ---------------------------------------------------------- requests
    def handle(self, req: dict) -> dict:
        cmd = req.get("cmd")
        if cmd == "status":
            with self.lock:
                st = copy.deepcopy(self.state)
            return {"ok": True, "ready": self.ready, "error": self.error,
                    "sensors": self.sensors(), "throttle": self.throttle.last,
                    "gpu_throttle": self.gpu_throttle, "state": st,
                    "fan_curve": dict(self.curve.info, **st["fan_curve"]), "ac": power.ac_online(),
                    "hw": {"lcd_overdrive": self.hw_lcd_overdrive, "coolboost": self.hw_coolboost,
                           "lcd_overdrive_supported": self.overdrive_supported,
                           "battery_limit": self.hw_battery_limit,
                           "battery_calibration": self.calibration_status(),
                           "battery_limit_supported": self.battery_limit_supported,
                           "backlight_timeout": self.hw_backlight_timeout,
                           "backlight_timeout_supported": self.backlight_timeout_supported,
                           "gpu_mode_supported": self.gpu_mode_supported,
                           "gpu_mode": self.gpu_mode}}
        if cmd == "disks":
            return {"ok": True, "smart": self.smart()}
        if cmd == "gpu_holders":
            return {"ok": True, "holders": self.holders()}
        if cmd == "history":
            key = _choice(req.get("range", "24h"), tuple(history.RANGES))
            if self.recorder is None:
                return {"ok": True, "history": None}
            return {"ok": True, "history": self.recorder.query(key)}
        if cmd == "set_power_plan":
            source = _choice(req.get("source"), ("ac", "battery"))
            plan = _choice(req.get("plan"), power.PLANS)
            with self.lock:
                self.state["power"][source] = plan
                self.state["power_applied"] = True
                self._save_state()
            if (source == "ac") == power.ac_online():
                power.apply_plan(plan)
            return {"ok": True}
        if not self.ready:
            return {"ok": False, "error": self.error or "hardware interface unavailable"}
        handler = getattr(self, "cmd_" + str(cmd), None)
        if handler is None:
            return {"ok": False, "error": f"unknown command {cmd!r}"}
        handler(req)
        return {"ok": True}

    def cmd_set_fan(self, req: dict) -> None:
        with self.fan_lock:
            with self.lock:
                fan = dict(self.state["fan"])
            fan["mode"] = _choice(req.get("mode", fan["mode"]), ("auto", "max", "custom", "curve"))
            for k in ("cpu_auto", "gpu_auto"):
                if k in req:
                    fan[k] = _bool(req[k])
            for k in ("cpu_percent", "gpu_percent"):
                if k in req:
                    fan[k] = _int(req[k], 0, 100) // 10 * 10
            if fan["mode"] != "curve":
                self.ctl.set_fan_mode(**fan)
            with self.lock:
                self.state["fan"] = fan
                self._save_state()
            self.curve.reset()
            if fan["mode"] == "curve":
                self.fan_curve_step(0.0)  # start right away instead of waiting for the thread

    def cmd_set_fan_curve(self, req: dict) -> None:
        with self.lock:
            current = copy.deepcopy(self.state["fan_curve"])
        try:
            cfg = fancurve.normalize(
                req.get("points", current["points"]),
                req.get("gpu_points", current.get("gpu_points")),
                _bool(req["split"]) if "split" in req else current.get("split", False))
        except ValueError as e:
            raise ValidationError(str(e)) from e
        with self.fan_lock:
            with self.lock:
                self.state["fan_curve"] = cfg
                self._save_state()
            if self.state["fan"]["mode"] == "curve":
                self.fan_curve_step(0.0)

    def cmd_set_fan_speed(self, req: dict) -> None:
        fan = _choice(req.get("fan"), ("cpu", "gpu"))
        pct = _int(req.get("percent"), 0, 100) // 10 * 10
        with self.fan_lock:
            with self.lock:
                if self.state["fan"]["mode"] != "custom":
                    raise ValidationError("fan speed can only be set in Custom mode")
            self.ctl.set_fan_speed(fan, pct)
            with self.lock:
                self.state["fan"][fan + "_percent"] = pct
                self._save_state()

    def cmd_set_coolboost(self, req: dict) -> None:
        on = _bool(req.get("on"))
        self.ctl.set_coolboost(on)
        self.hw_coolboost = on
        with self.lock:
            self.state["coolboost"] = on
            self._save_state()

    def cmd_set_keyboard(self, req: dict) -> None:
        kb = validate_keyboard(req.get("keyboard"))
        self.ctl.apply_keyboard(kb)
        with self.lock:
            self.state["keyboard"] = kb
            self.state["keyboard_applied"] = True
            self._save_state()

    def cmd_set_lcd_overdrive(self, req: dict) -> None:
        on = _bool(req.get("on"))
        if not self.overdrive_supported:
            raise ValidationError("LCD Overdrive is not supported by this panel")
        self.ctl.set_lcd_overdrive(on)
        self.hw_lcd_overdrive = on
        with self.lock:
            self.state["lcd_overdrive"] = on
            self._save_state()

    # --------------------------------------------------- battery calibration
    def _cal_state(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.state["battery_calibration"])

    def calibration_status(self) -> dict:
        st = self._cal_state()
        out = {"supported": self.hw_battery_calibration is not None, "active": st["active"],
               "external": bool(self.hw_battery_calibration) and not st["active"],
               "last": st["last"]}
        if st["active"]:
            tracker = calibration.Tracker.from_dict(st)
            out.update(phase=tracker.phase, text=tracker.text, started=st["started"],
                       elapsed_s=round(time.time() - st["started"]), min_seen=tracker.min_seen,
                       restore_limit=st["restore_limit"])
        return out

    def cmd_start_battery_calibration(self, req: dict) -> None:
        with self.cal_lock:
            if self.hw_battery_calibration is None:
                raise ValidationError("this firmware has no battery calibration")
            if self._cal_state()["active"] or self.hw_battery_calibration:
                raise ValidationError("a calibration is already running")
            if not power.ac_online():
                raise ValidationError("connect the charger before calibrating")
            restore = bool(self.hw_battery_limit)  # the firmware turns the charge limit off
            self.ctl.set_battery_calibration(True)
            self.hw_battery_calibration = True
            self.hw_battery_limit = self.ctl.get_battery_limit()
            with self.lock:
                self.state["battery_calibration"] = {
                    "active": True, "restore_limit": restore, "started": time.time(),
                    "phase": "charging", "min_seen": 100.0,
                    "last": self.state["battery_calibration"]["last"]}
                self._save_state()
            log.info("battery calibration started (restore charge limit: %s)", restore)

    def cmd_stop_battery_calibration(self, req: dict) -> None:
        with self.cal_lock:
            if self.hw_battery_calibration is None:
                raise ValidationError("this firmware has no battery calibration")
            if not self._finish_calibration("cancelled"):
                raise WmiError("could not stop the calibration")

    def _finish_calibration(self, result: str) -> bool:
        """Turn the firmware's calibration off, restore the charge limit and record the result."""
        st = self._cal_state()
        try:
            self.ctl.set_battery_calibration(False)
        except WmiError as e:
            log.warning("could not stop the battery calibration: %s", e)
            return False
        self.hw_battery_calibration = False
        if st["restore_limit"]:
            try:
                self.ctl.set_battery_limit(True)
                self.hw_battery_limit = True
            except WmiError as e:
                log.warning("could not restore the battery charge limit: %s", e)
        with self.lock:
            self.state["battery_calibration"] = {
                "active": False, "restore_limit": False, "started": None, "phase": "charging",
                "min_seen": 100.0,
                "last": {"result": result, "finished": time.time(), "started": st["started"],
                         "min_seen": st["min_seen"]}}
            self._save_state()
        log.info("battery calibration finished: %s", result)
        return True

    def battery_calibration_step(self) -> None:
        """Follow a running calibration; also notices a calibration changed outside the service."""
        if not self.ready:
            return
        with self.cal_lock:
            hw = self.ctl.get_battery_calibration()
            if hw is not None:
                self.hw_battery_calibration = hw
            st = self._cal_state()
            if not st["active"]:
                return
            bats = self._battery_read()
            b = bats[0] if bats else None
            tracker = calibration.Tracker.from_dict(st)
            result = tracker.update(b["capacity"] if b else None, b["status"] if b else "",
                                    time.time(), hw)
            if result:
                self._finish_calibration(result)
            elif (tracker.phase, tracker.min_seen) != (st["phase"], st["min_seen"]):
                with self.lock:
                    self.state["battery_calibration"].update(phase=tracker.phase,
                                                             min_seen=tracker.min_seen)
                    self._save_state()

    def start_calibration_monitor(self, interval: float = 15.0) -> None:
        def loop() -> None:
            while not self._stop.wait(interval):
                try:
                    self.battery_calibration_step()
                except Exception as e:
                    log.warning("calibration step failed: %s", e)
        threading.Thread(target=loop, name="calibration", daemon=True).start()

    def cmd_set_battery_limit(self, req: dict) -> None:
        on = _bool(req.get("on"))
        if not self.battery_limit_supported:
            raise ValidationError("this firmware has no battery charge limit")
        if self._cal_state()["active"]:
            raise ValidationError("the charge limit cannot be changed during a calibration")
        self.ctl.set_battery_limit(on)
        self.hw_battery_limit = on
        with self.lock:
            self.state["battery_limit"] = on
            self._save_state()

    def cmd_set_win_key(self, req: dict) -> None:
        on = _bool(req.get("on"))
        self.ctl.set_win_key(on)
        with self.lock:
            self.state["win_key"] = on
            self._save_state()

    def cmd_set_backlight_timeout(self, req: dict) -> None:
        on = _bool(req.get("on"))
        if not self.backlight_timeout_supported:
            raise ValidationError("the keyboard backlight timeout is not supported by this BIOS")
        self.ctl.set_backlight_timeout(on)
        self.hw_backlight_timeout = on
        with self.lock:
            self.state["backlight_timeout"] = on
            self._save_state()

    def cmd_set_gpu_mode(self, req: dict) -> None:
        if not self.gpu_mode_supported:
            raise ValidationError("this model has no discrete-GPU switch")
        on = _bool(req.get("discrete_only"))
        self.ctl.set_gpu_mode(on)
        self.gpu_mode = 1 if on else 2


def _hwmon_temp(names) -> int | None:
    for hw in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            with open(os.path.join(hw, "name")) as f:
                if f.read().strip() not in names:
                    continue
            with open(os.path.join(hw, "temp1_input")) as f:
                return round(int(f.read()) / 1000)
        except (OSError, ValueError):
            continue
    return None


def _allowed_uids() -> set[int]:
    uids = {0}
    try:
        with open(ALLOWED_USERS_FILE) as f:
            for line in f:
                name = line.strip()
                if name and not name.startswith("#"):
                    try:
                        uids.add(pwd.getpwnam(name).pw_uid)
                    except KeyError:
                        pass
    except OSError:
        pass
    return uids


class _Handler(socketserver.StreamRequestHandler):
    daemon_ref: Daemon

    def handle(self) -> None:
        creds = self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                           struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", creds)
        if uid not in _allowed_uids():
            self._send({"ok": False, "error": "permission denied"})
            return
        while True:
            line = self.rfile.readline(MAX_REQUEST)
            if not line:
                return
            try:
                req = json.loads(line)
                if not isinstance(req, dict):
                    raise ValidationError("request must be an object")
                resp = self.daemon_ref.handle(req)
            except (ValidationError, ValueError) as e:
                resp = {"ok": False, "error": str(e)}
            except WmiError as e:
                log.warning("hardware error: %s", e)
                resp = {"ok": False, "error": f"hardware error: {e}"}
            except Exception as e:  # keep the service alive
                log.exception("request failed")
                resp = {"ok": False, "error": f"internal error: {e}"}
            self._send(resp)

    def _send(self, obj: dict) -> None:
        self.wfile.write(json.dumps(obj).encode() + b"\n")
        self.wfile.flush()


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def start_server(d: Daemon, path: str) -> _Server:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    if directory == SOCKET_DIR:
        os.chmod(directory, 0o755)
    if os.path.exists(path):
        os.unlink(path)
    _Handler.daemon_ref = d
    server = _Server(path, _Handler)
    os.chmod(path, 0o666)  # access is checked per connection with SO_PEERCRED
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> int:
    logging.basicConfig(level=os.environ.get("NITROSENSE_LOG", "INFO"),
                        format="%(levelname)s %(name)s: %(message)s")
    if os.geteuid() != 0:
        print("nitrosensed must run as root", file=sys.stderr)
        return 1
    set_process_name("nitrosensed")

    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib

    d = Daemon()
    d.startup()
    d.start_throttle_monitor()
    d.start_calibration_monitor()
    d.start_fan_curve()
    d.start_recorder()

    server = start_server(d, SOCKET_PATH)

    loop = GLib.MainLoop()

    def on_sleep(_conn, _sender, _path, _iface, _signal, params, *_a):
        going_down = params.unpack()[0]
        if not going_down:
            GLib.timeout_add_seconds(2, lambda: (d.reapply("resume"), False)[1])

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager",
                             "PrepareForSleep", "/org/freedesktop/login1", None,
                             Gio.DBusSignalFlags.NONE, on_sleep)
    except GLib.Error as e:
        log.warning("cannot watch suspend/resume: %s", e)

    GLib.timeout_add_seconds(2, lambda: (d.apply_power(), True)[1])
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 15, lambda: (loop.quit(), False)[1])
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 2, lambda: (loop.quit(), False)[1])
    log.info("nitrosensed ready (hardware %s)", "OK" if d.ready else "UNAVAILABLE: " + d.error)
    loop.run()
    d._stop.set()
    d.release_fans()
    server.shutdown()
    try:
        os.unlink(SOCKET_PATH)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
