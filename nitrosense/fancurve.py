"""Automatic fan curve: fan speed as a function of the hottest temperature.

FanCurve is the pure decision logic (no hardware access); the service feeds it the sensors
every couple of seconds and applies what it decides through the custom fan mode.

Safety rules that the curve cannot override:
  * speeds are never below MIN_PERCENT and the curve must end at 100 %
  * at or above SAFETY_CPU / SAFETY_GPU degrees the fans go to 100 % whatever the curve says
  * if every temperature sensor fails for a few samples the fans go back to the firmware's
    automatic mode (FanCurve.step reports release=True) until the sensors return
  * speed is raised at once but lowered only after the lower target has held for HOLD_S
    seconds, so the fans do not hunt up and down
"""

from __future__ import annotations

import math
from typing import NamedTuple

MIN_PERCENT = 20
SAFETY_CPU = 88          # degrees C: 100 % above this CPU temperature
SAFETY_GPU = 82          # degrees C: 100 % above this GPU temperature (when the dGPU is awake)
HOLD_S = 8.0             # seconds a lower target must persist before the fans slow down
FAIL_LIMIT = 3           # sensor-less samples before handing the fans back to the firmware
STEP = 10                # the firmware takes speeds in steps of 10 %

TEMPS = (40, 50, 60, 70, 80, 90)
PRESETS = {
    "quiet": (20, 25, 35, 50, 75, 100),
    "balanced": (30, 40, 50, 70, 90, 100),
    "performance": (40, 55, 70, 85, 100, 100),
}
DEFAULT_POINTS = [[t, p] for t, p in zip(TEMPS, PRESETS["balanced"])]


def validate(points) -> list[list[int]]:
    """Return the points as [[temp, percent], ...] or raise ValueError."""
    if not isinstance(points, (list, tuple)) or not 3 <= len(points) <= 8:
        raise ValueError("a fan curve needs 3 to 8 points")
    out = []
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) != 2 or not all(
                isinstance(v, (int, float)) and not isinstance(v, bool) for v in p):
            raise ValueError("each point is [temperature, percent]")
        t, pct = int(p[0]), int(p[1])
        if not 20 <= t <= 100 or not MIN_PERCENT <= pct <= 100:
            raise ValueError(f"point {t} C / {pct} % out of range (20-100 C, {MIN_PERCENT}-100 %)")
        out.append([t, pct])
    if any(b[0] <= a[0] for a, b in zip(out, out[1:])):
        raise ValueError("temperatures must be strictly increasing")
    if any(b[1] < a[1] for a, b in zip(out, out[1:])):
        raise ValueError("fan speed cannot decrease as the temperature rises")
    if out[-1][1] != 100 or out[-1][0] > 90:
        raise ValueError("the curve must reach 100 % at 90 C or below")
    return out


def interpolate(points: list[list[int]], temp: float) -> float:
    if temp <= points[0][0]:
        return points[0][1]
    for (t0, p0), (t1, p1) in zip(points, points[1:]):
        if temp <= t1:
            return p0 + (p1 - p0) * (temp - t0) / (t1 - t0)
    return points[-1][1]


def target_percent(points: list[list[int]], temp: float) -> int:
    """Curve value rounded up to the firmware's 10 % step (erring towards more cooling)."""
    pct = math.ceil(round(interpolate(points, temp), 6) / STEP) * STEP
    return max(MIN_PERCENT, min(100, pct))


class Decision(NamedTuple):
    percent: int | None   # set the fans to this now (None: leave them as they are)
    enter: bool           # first speed after (re)start: switch the firmware to custom mode too
    release: bool         # give the fans back to the firmware's automatic mode


class FanCurve:
    def __init__(self, hold_s: float = HOLD_S, fail_limit: int = FAIL_LIMIT) -> None:
        self.hold_s, self.fail_limit = hold_s, fail_limit
        self.reset()

    def reset(self) -> None:
        """Forget what was applied: the next step sets the speed from scratch."""
        self.applied: int | None = None
        self.down_for = 0.0
        self.bad = 0
        self.failsafe = False
        self.info: dict = {}

    def step(self, points, cpu_temp, gpu_temp, dt: float) -> Decision:
        temps = [t for t in (cpu_temp, gpu_temp) if t is not None]
        if not temps:
            self.bad += 1
            if self.bad >= self.fail_limit and not self.failsafe:
                self.failsafe, self.applied = True, None
                self.info = {"failsafe": True, "temp": None, "percent": None, "safety": False}
                return Decision(None, False, True)
            return Decision(None, False, False)
        self.bad = 0
        if self.failsafe:  # sensors are back: take control again
            self.failsafe, self.applied = False, None
        hottest = max(temps)
        safety = ((cpu_temp is not None and cpu_temp >= SAFETY_CPU)
                  or (gpu_temp is not None and gpu_temp >= SAFETY_GPU))
        target = 100 if safety else target_percent(points, hottest)
        decision = Decision(None, False, False)
        if self.applied is None:
            self.applied, self.down_for = target, 0.0
            decision = Decision(target, True, False)
        elif target > self.applied:
            self.applied, self.down_for = target, 0.0
            decision = Decision(target, False, False)
        elif target < self.applied:
            self.down_for += dt
            if self.down_for >= self.hold_s:
                self.applied, self.down_for = target, 0.0
                decision = Decision(target, False, False)
        else:
            self.down_for = 0.0
        self.info = {"failsafe": False, "temp": hottest, "percent": self.applied, "safety": safety,
                     "target": target}
        return decision
