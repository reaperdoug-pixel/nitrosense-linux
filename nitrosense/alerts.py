"""System alerts: temperatures, stopped fans and disk health, with plain-language messages.

evaluate() is a pure function. The GUI shows its result in a banner and sends a desktop
notification when an alert appears or gets worse.
"""

from __future__ import annotations

from .disks import CRIT, OK, WARN

CPU_WARN, CPU_CRIT = 90, 97   # coretemp reports 100 C as the hardware limit
GPU_WARN, GPU_CRIT = 85, 92
THERMAL_ALERT_S = 10         # continuous CPU thermal throttling before the alert appears
FAN_STOPPED_TEMP = 75         # a fan reading 0 RPM above this temperature is a problem


def _temp_alert(name: str, temp, warn: int, crit: int):
    if temp is None:
        return None
    if temp >= crit:
        return CRIT, f"temp:{name}", f"{name}: temperatura crítica ({temp:.0f} °C). Reduza a carga."
    if temp >= warn:
        return WARN, f"temp:{name}", f"{name}: temperatura muito alta ({temp:.0f} °C)."
    return None


def evaluate(cpu_temp, gpu_temp, cpu_rpm, gpu_rpm, disks: list[tuple[dict, dict]],
             batteries: list[tuple[dict, dict]] = (), throttle: dict | None = None,
             gpu_thermal: bool = False) -> list[tuple[int, str, str]]:
    """-> [(level, key, text)] sorted most severe first.

    disks / batteries: [(info, assessment)] from disks.assess() / battery.assess().
    """
    out = []
    for a in (_temp_alert("CPU", cpu_temp, CPU_WARN, CPU_CRIT),
              _temp_alert("GPU", gpu_temp, GPU_WARN, GPU_CRIT)):
        if a:
            out.append(a)
    for name, rpm, temp in (("CPU", cpu_rpm, cpu_temp), ("GPU", gpu_rpm, gpu_temp)):
        if rpm == 0 and temp is not None and temp >= FAN_STOPPED_TEMP:
            out.append((CRIT, f"fan:{name}", f"Ventoinha da {name} parada com o sistema a {temp:.0f} °C."))
    if throttle and throttle.get("thermal_for_s", 0) >= THERMAL_ALERT_S:
        out.append((WARN, "throttle:CPU", "CPU: o notebook está reduzindo o desempenho por calor."))
    if gpu_thermal:
        out.append((WARN, "throttle:GPU", "GPU: reduzindo o desempenho por calor."))
    for info, assessment in disks:
        if assessment["level"] > OK:
            worst = max(assessment["reasons"], key=lambda r: r[0])
            out.append((assessment["level"], f"disk:{info['name']}",
                        f"Disco {info['model']}: {worst[1]}"))
    for info, assessment in batteries:
        # only critical battery problems interrupt; "attention" stays visible in the Battery tab
        if assessment["level"] >= CRIT:
            worst = max(assessment["reasons"], key=lambda r: r[0])
            out.append((CRIT, f"battery:{info['name']}", f"Bateria: {worst[1]}"))
    out.sort(key=lambda a: -a[0])
    return out
