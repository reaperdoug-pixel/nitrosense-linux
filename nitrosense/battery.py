"""Battery health: capacity against the original design, cycles, power draw and time left.

Everything comes from /sys/class/power_supply (no privileges needed). assess() is a pure
function that turns a reading into a level (0 ok, 1 attention, 2 critical) with reasons and
advice in Portuguese, using the same levels as disks.py.
"""

from __future__ import annotations

import glob
import os

from .disks import CRIT, LABELS, OK, WARN

SYS_POWER = "/sys/class/power_supply"
HEALTH_WARN, HEALTH_CRIT = 80.0, 60.0   # % of the original capacity
CYCLES_WARN = 1000
TEMP_WARN, TEMP_CRIT = 50.0, 60.0       # battery cell temperature, when the firmware reports it

STATUS_PT = {"Charging": "Carregando", "Discharging": "Descarregando", "Full": "Cheia",
             "Not charging": "Conectada, sem carregar", "Unknown": "Desconhecido"}


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _num(path: str) -> float | None:
    v = _read(path)
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def read(root: str = SYS_POWER) -> list[dict]:
    """One dict per internal battery (energies in Wh, power in W, time in seconds)."""
    out = []
    for path in sorted(glob.glob(os.path.join(root, "*"))):
        if _read(os.path.join(path, "type")) != "Battery" or _read(os.path.join(path, "present")) == "0":
            continue
        if _read(os.path.join(path, "scope")) == "Device":  # a mouse/headset, not the laptop
            continue
        n = lambda name: _num(os.path.join(path, name))  # noqa: E731
        volts = (n("voltage_now") or 0) / 1e6
        nominal = (n("voltage_min_design") or n("voltage_now") or 0) / 1e6
        if n("energy_full_design"):
            full, design, now = n("energy_full") / 1e6, n("energy_full_design") / 1e6, (n("energy_now") or 0) / 1e6
        elif n("charge_full_design") and nominal:  # µAh -> Wh at the nominal voltage
            full = (n("charge_full") or 0) / 1e6 * nominal
            design = n("charge_full_design") / 1e6 * nominal
            now = (n("charge_now") or 0) / 1e6 * nominal
        else:
            full = design = now = None
        status = _read(os.path.join(path, "status")) or "Unknown"
        power = None
        if n("power_now") is not None:
            power = abs(n("power_now")) / 1e6
        elif n("current_now") is not None and volts:
            power = abs(n("current_now")) / 1e6 * volts
        capacity = n("capacity")
        if capacity is None and now is not None and full:
            capacity = 100 * now / full
        temp = n("temp")
        out.append({
            "name": os.path.basename(path), "status": status,
            "manufacturer": _read(os.path.join(path, "manufacturer")) or "",
            "model": _read(os.path.join(path, "model_name")) or "",
            "technology": _read(os.path.join(path, "technology")) or "",
            "cycles": int(n("cycle_count")) if n("cycle_count") is not None else None,
            "capacity": capacity,
            "energy_full": full, "energy_design": design, "energy_now": now,
            "health": 100 * full / design if full and design else None,
            "voltage": volts or None, "power": power,
            "temp": temp / 10 if temp is not None else None,
        })
    return out


def time_left(b: dict, power: float | None = None) -> float | None:
    """Seconds until empty (discharging) or full (charging); `power` may be a smoothed value."""
    p = power if power is not None else b["power"]
    if not p or p < 0.5 or b["energy_now"] is None or not b["energy_full"]:
        return None
    if b["status"] == "Discharging":
        return b["energy_now"] / p * 3600
    if b["status"] == "Charging":
        return max(0.0, b["energy_full"] - b["energy_now"]) / p * 3600
    return None


def human_duration(seconds: float | None) -> str:
    if seconds is None:
        return "--"
    minutes = int(seconds // 60)
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def assess(b: dict) -> dict:
    """-> {'level', 'label', 'reasons': [(level, text)], 'advice', 'note'}."""
    reasons: list[tuple[int, str]] = []
    health, cycles, temp = b.get("health"), b.get("cycles"), b.get("temp")
    if health is not None:
        if health < HEALTH_CRIT:
            reasons.append((CRIT, f"Capacidade em {health:.0f}% do original: troque a bateria."))
        elif health < HEALTH_WARN:
            reasons.append((WARN, f"Capacidade em {health:.0f}% do original: a autonomia já caiu bastante."))
    if cycles is not None and cycles >= CYCLES_WARN:
        reasons.append((WARN, f"{cycles} ciclos de carga: perto do fim da vida típica."))
    if temp is not None:
        if temp >= TEMP_CRIT:
            reasons.append((CRIT, f"Bateria muito quente: {temp:.0f} °C."))
        elif temp >= TEMP_WARN:
            reasons.append((WARN, f"Bateria quente: {temp:.0f} °C."))
    level = max((lv for lv, _ in reasons), default=OK)
    if health is None:
        advice = "O notebook não informa a capacidade original da bateria."
    elif level == CRIT:
        advice = "Faça backup do que importa e planeje a troca da bateria."
    elif level == WARN:
        advice = "Funciona, mas dura menos. Evite deixar a carga em 100% na tomada por semanas."
    note = ""
    if health is not None and cycles is not None and 0 < cycles < 150 and health < 90:
        note = (f"A perda ({100 - health:.0f}%) é grande para só {cycles} ciclos. Costuma vir de "
                "envelhecimento por calor e por ficar muito tempo em 100% na tomada, ou de uma "
                "estimativa desajustada da bateria (uma descarga e carga completas pode recalibrar).")
    if level == OK and health is not None:
        if health >= 90:
            advice = "Excelente: quase toda a capacidade original."
        elif note:
            advice = "Ainda acima de 80% da capacidade original, mas com perda acima do esperado."
        else:
            advice = "Boa: desgaste normal para o tempo de uso."
    return {"level": level, "label": LABELS[level], "reasons": reasons, "advice": advice,
            "note": note}
