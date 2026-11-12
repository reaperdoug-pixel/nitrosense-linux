"""Disk health for NVMe drives: temperature, wear, SMART counters and plain-language advice.

Three layers:
  * basic()      unprivileged: model, size, temperature and its limits (hwmon), filesystem use
  * read_smart() root only (the service): NVMe "SMART / Health Information" log page 0x02
  * assess()     pure function turning both into a level (0 ok, 1 attention, 2 critical)
                 with reasons and advice in Portuguese

Only NVMe is covered; SATA drives would need smartmontools.
"""

from __future__ import annotations

import ctypes
import fcntl
import glob
import os
import struct

SYS_NVME = "/sys/class/nvme"
NVME_IOCTL_ADMIN_CMD = 0xC0484E41  # _IOWR('N', 0x41, struct nvme_admin_cmd), 72 bytes
_ADMIN_FMT = "<BBHIIIQQ" + "I" * 10
OP_GET_LOG_PAGE = 0x02
LOG_SMART = 0x02
UNIT_BYTES = 512_000  # an NVMe "data unit" is 1000 x 512 bytes

OK, WARN, CRIT = 0, 1, 2
LABELS = {OK: "Saudável", WARN: "Atenção", CRIT: "Crítico"}


# ------------------------------------------------------------------ SMART (root)
def _u128(buf: bytes, off: int) -> int:
    return int.from_bytes(buf[off:off + 16], "little")


def parse_smart_log(buf: bytes) -> dict:
    """Decode the 512-byte SMART / Health Information log (NVMe base spec, figure 'Log Page 02h')."""
    if len(buf) < 200:
        raise ValueError("SMART log too short")
    kelvin = int.from_bytes(buf[1:3], "little")
    sensors = []
    for i in range(8):
        k = int.from_bytes(buf[200 + 2 * i:202 + 2 * i], "little")
        if k:
            sensors.append(k - 273)
    return {
        "critical_warning": buf[0],
        "temperature_c": kelvin - 273 if kelvin else None,
        "available_spare": buf[3],
        "spare_threshold": buf[4],
        "percentage_used": buf[5],
        "bytes_read": _u128(buf, 32) * UNIT_BYTES,
        "bytes_written": _u128(buf, 48) * UNIT_BYTES,
        "power_cycles": _u128(buf, 112),
        "power_on_hours": _u128(buf, 128),
        "unsafe_shutdowns": _u128(buf, 144),
        "media_errors": _u128(buf, 160),
        "error_log_entries": _u128(buf, 176),
        "warning_temp_minutes": int.from_bytes(buf[192:196], "little"),
        "critical_temp_minutes": int.from_bytes(buf[196:200], "little"),
        "sensors_c": sensors,
    }


def read_smart_log(dev: str = "/dev/nvme0") -> bytes:
    """Issue Get Log Page (SMART) through the admin ioctl. Needs root."""
    data = ctypes.create_string_buffer(512)
    numd = 512 // 4 - 1
    cmd = bytearray(struct.pack(_ADMIN_FMT, OP_GET_LOG_PAGE, 0, 0, 0xFFFFFFFF, 0, 0, 0,
                                ctypes.addressof(data), 0, 512,
                                (numd << 16) | LOG_SMART, 0, 0, 0, 0, 0, 10_000, 0))
    fd = os.open(dev, os.O_RDONLY)
    try:
        status = fcntl.ioctl(fd, NVME_IOCTL_ADMIN_CMD, cmd, True)
    finally:
        os.close(fd)
    if status:  # >0 is an NVMe completion status, <0 raises OSError above
        raise OSError(f"NVMe Get Log Page failed (status {status:#x})")
    return data.raw


def read_smart() -> dict[str, dict]:
    """SMART data for every NVMe controller, keyed by controller name (nvme0...)."""
    out: dict[str, dict] = {}
    for path in sorted(glob.glob(os.path.join(SYS_NVME, "nvme[0-9]*"))):
        name = os.path.basename(path)
        try:
            out[name] = parse_smart_log(read_smart_log("/dev/" + name))
        except (OSError, ValueError) as e:
            out[name] = {"error": str(e)}
    return out


# ------------------------------------------------------------- unprivileged data
def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _milli(path: str) -> float | None:
    v = _read(path)
    try:
        return int(v) / 1000 if v is not None else None
    except ValueError:
        return None


def _mounts(ctrl: str) -> list[dict]:
    """Filesystems living on this controller's partitions, with their usage."""
    out = []
    try:
        with open("/proc/mounts") as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    for line in lines:
        parts = line.split()
        if len(parts) < 2 or not parts[0].startswith(f"/dev/{ctrl}n"):
            continue
        try:
            st = os.statvfs(parts[1])
        except OSError:
            continue
        total = st.f_blocks * st.f_frsize
        if total <= 0:
            continue
        free = st.f_bavail * st.f_frsize
        out.append({"device": parts[0], "mount": parts[1], "fs": parts[2] if len(parts) > 2 else "",
                    "total": total, "used": total - free})
    return out


def hottest_temp() -> float | None:
    """Highest NVMe temperature (hwmon); cheap enough to call every few seconds."""
    best = None
    for path in glob.glob(os.path.join(SYS_NVME, "nvme[0-9]*")):
        hw = (glob.glob(os.path.join(path, "hwmon*")) or [None])[0]
        t = _milli(os.path.join(hw, "temp1_input")) if hw else None
        if t is not None and (best is None or t > best):
            best = t
    return best


def basic() -> list[dict]:
    """Model, size, live temperature (+limits) and filesystem use; no privileges needed."""
    disks = []
    for path in sorted(glob.glob(os.path.join(SYS_NVME, "nvme[0-9]*"))):
        name = os.path.basename(path)
        hw = (glob.glob(os.path.join(path, "hwmon*")) or [None])[0]
        size = None
        ns = glob.glob(os.path.join(path, f"{name}n*", "size"))
        if ns:
            try:
                size = int(_read(ns[0]) or 0) * 512
            except ValueError:
                size = None
        disks.append({
            "name": name,
            "model": _read(os.path.join(path, "model")) or name,
            "firmware": _read(os.path.join(path, "firmware_rev")) or "",
            "size": size,
            "temp": _milli(os.path.join(hw, "temp1_input")) if hw else None,
            "temp_warn": _milli(os.path.join(hw, "temp1_max")) if hw else None,
            "temp_crit": _milli(os.path.join(hw, "temp1_crit")) if hw else None,
            "mounts": _mounts(name),
        })
    return disks


# ------------------------------------------------------------------ assessment
def life_estimate(smart: dict) -> str:
    used, hours = smart.get("percentage_used", 0), smart.get("power_on_hours", 0)
    if used >= 100:
        return "Vida útil nominal esgotada."
    if used <= 0 or hours < 24:
        return "Sem desgaste mensurável até agora."
    years = hours * (100 - used) / used / (24 * 365)
    return f"Estimativa: cerca de {years:.0f} ano(s) de uso no ritmo atual (aproximação)."


def assess(disk: dict, smart: dict | None) -> dict:
    """-> {'level', 'label', 'reasons': [(level, text)], 'advice', 'life'}."""
    reasons: list[tuple[int, str]] = []
    temp = disk.get("temp")
    if temp is None and smart and smart.get("temperature_c") is not None:
        temp = smart["temperature_c"]
    warn = disk.get("temp_warn") or 70.0
    if warn > 150:  # some drives report an unset (huge) limit
        warn = 70.0
    if temp is not None:
        if temp >= warn:
            reasons.append((CRIT, f"Temperatura muito alta: {temp:.0f} °C (limite de aviso do disco {warn:.0f} °C)."))
        elif temp >= warn - 10:
            reasons.append((WARN, f"Temperatura elevada: {temp:.0f} °C."))
    if smart and "error" not in smart:
        cw = smart["critical_warning"]
        if cw & 0x01:
            reasons.append((CRIT, "O disco avisa que a reserva de células está abaixo do limite."))
        if cw & 0x04:
            reasons.append((CRIT, "O disco avisa que a confiabilidade está degradada."))
        if cw & 0x08:
            reasons.append((CRIT, "O disco entrou em modo somente leitura."))
        if cw & 0x10:
            reasons.append((WARN, "Falha no backup de memória volátil do disco."))
        if smart["available_spare"] <= smart["spare_threshold"]:
            reasons.append((CRIT, f"Reserva de células em {smart['available_spare']}% "
                                  f"(mínimo do fabricante {smart['spare_threshold']}%)."))
        elif smart["available_spare"] < 50:
            reasons.append((WARN, f"Reserva de células baixa: {smart['available_spare']}%."))
        used = smart["percentage_used"]
        if used >= 100:
            reasons.append((CRIT, f"Desgaste em {used}%: vida útil nominal esgotada."))
        elif used >= 80:
            reasons.append((WARN, f"Desgaste em {used}%: planeje a troca."))
        if smart["media_errors"] > 0:
            reasons.append((WARN if smart["media_errors"] < 10 else CRIT,
                            f"{smart['media_errors']} erro(s) de integridade de dados registrados."))
        if smart["critical_temp_minutes"] > 0:
            reasons.append((WARN, f"O disco já passou {smart['critical_temp_minutes']} min em temperatura crítica."))
    for m in disk.get("mounts", []):
        pct = 100 * m["used"] / m["total"]
        if pct >= 95:
            reasons.append((CRIT, f"{m['mount']} está {pct:.0f}% cheio."))
        elif pct >= 90:
            reasons.append((WARN, f"{m['mount']} está {pct:.0f}% cheio."))
    level = max((lv for lv, _ in reasons), default=OK)
    advice = {OK: "Tudo certo. Nada a fazer.",
              WARN: "Fique de olho e mantenha backup em dia.",
              CRIT: "Faça backup agora e considere trocar o disco."}[level]
    life = life_estimate(smart) if smart and "error" not in smart else ""
    return {"level": level, "label": LABELS[level], "reasons": reasons, "advice": advice,
            "life": life}


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1000 or unit == "PB":
            return (f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}").replace(".", ",")
        n /= 1000
    return str(n)
