"""Battery calibration: follow the firmware's charge / discharge / recharge cycle.

Acer's calibration mode (the `acer-wmi-battery` "calibration_mode") charges the battery to
100 %, discharges it and recharges it once so the fuel gauge relearns the real capacity. The
firmware offers no progress report, and the Linux driver does not even handle the completion
event, so the service follows the cycle itself from the charge level and status.

Tracker.update() is a pure state machine (no I/O); the service feeds it every few seconds.
"""

from __future__ import annotations

FULL = 99.0          # % that counts as "charged to 100 %"
DEEP = 30.0          # the discharge must reach this level (or lower) before a recharge counts
MAX_HOURS = 16       # safety net: stop a calibration that never finishes

PHASES = ("charging", "waiting", "discharging", "recharging")
PHASE_TEXT = {
    "charging": "Carregando até 100%",
    "waiting": "Bateria cheia: aguardando o firmware começar a descarregar",
    "discharging": "Descarregando",
    "recharging": "Recarregando até 100%",
}


class Tracker:
    def __init__(self, started: float, phase: str = "charging", min_seen: float = 100.0) -> None:
        self.started, self.phase, self.min_seen = started, phase, min_seen

    def to_dict(self) -> dict:
        return {"started": self.started, "phase": self.phase, "min_seen": self.min_seen}

    @classmethod
    def from_dict(cls, d: dict) -> "Tracker":
        return cls(d.get("started") or 0.0, d.get("phase", "charging"), d.get("min_seen", 100.0))

    def update(self, capacity: float | None, status: str, now: float, hw_active: bool | None):
        """Advance the phase. -> None while running, or "done" / "aborted" / "timeout"."""
        if capacity is not None:
            self.min_seen = min(self.min_seen, capacity)
        if now - self.started > MAX_HOURS * 3600:
            return "timeout"
        cap = capacity if capacity is not None else 0.0
        if hw_active is False:  # the firmware ended it: finished only if we saw the whole cycle
            return "done" if self.phase == "recharging" and cap >= 95 else "aborted"
        if self.phase == "charging" and cap >= FULL:
            self.phase = "waiting"
        if self.phase == "waiting" and (status == "Discharging" or cap < FULL - 1):
            self.phase = "discharging"
        if (self.phase == "discharging" and self.min_seen <= DEEP and status == "Charging"
                and cap > self.min_seen + 2):
            self.phase = "recharging"
        if self.phase == "recharging" and cap >= FULL:
            return "done"
        return None

    @property
    def text(self) -> str:
        if self.phase == "discharging":
            return f"Descarregando (mínimo até agora: {self.min_seen:.0f}%)"
        return PHASE_TEXT[self.phase]
