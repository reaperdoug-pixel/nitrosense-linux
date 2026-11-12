"""Which programs weigh the most: CPU and memory per application, GPU users, GPU holders.

CPU and memory come from /proc and need no privileges. Processes are grouped by program
(a browser or an Electron app is dozens of processes). Memory counts the private resident
part (resident minus shared pages), so shared libraries are not counted once per process.
The list of processes that keep /dev/nvidia* open needs root to see other users' file
descriptors, so the service provides it (see daemon "gpu_holders").
"""

from __future__ import annotations

import os
import re
import subprocess
import time

PROC = "/proc"
CLK_TCK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")
# programs whose own name says nothing: show the script / app they run instead
WRAPPERS = {"python", "python3", "node", "java", "bash", "sh", "perl", "ruby", "electron", "dotnet"}
_PYTHON = re.compile(r"^python[\d.]*$")


def app_name(comm: str, cmdline: list[str]) -> str:
    """Friendly program name: comm, or the script a wrapper (python, node, ...) is running."""
    if comm in WRAPPERS or _PYTHON.match(comm):
        args = [a for a in cmdline[1:] if a]
        for i, arg in enumerate(args):
            if arg in ("-c", "-e", "-p", "--eval"):  # inline code: do not show the code itself
                return f"{comm} {arg}"
            if arg == "-m" and i + 1 < len(args):
                return args[i + 1]
            if not arg.startswith("-"):
                return (os.path.basename(arg.rstrip("/")) or comm)[:40]
    return comm


def _read(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return None


def _pids(proc: str) -> list[str]:
    try:
        return [e for e in os.listdir(proc) if e.isdigit()]
    except OSError:
        return []


class ProcessSampler:
    """sample() -> top programs by CPU and by memory, with CPU as % of the whole machine."""

    def __init__(self, proc: str = PROC, clock=time.monotonic, top: int = 8,
                 ncpu: int | None = None) -> None:
        self.proc, self.clock, self.top = proc, clock, top
        self.ncpu = ncpu or os.cpu_count() or 1
        self._prev: dict[str, int] = {}
        self._prev_t: float | None = None

    def _stat(self, pid: str):
        raw = _read(os.path.join(self.proc, pid, "stat"))
        if not raw:
            return None
        # "pid (comm) S ppid ...": comm may contain spaces and parentheses
        left, right = raw.find("("), raw.rfind(")")
        if left < 0 or right < left:
            return None
        fields = raw[right + 2:].split()
        if len(fields) < 13:
            return None
        return raw[left + 1:right], int(fields[11]) + int(fields[12])  # utime + stime, in ticks

    def _private_bytes(self, pid: str) -> int:
        raw = _read(os.path.join(self.proc, pid, "statm"))
        try:
            _size, resident, shared = (int(x) for x in raw.split()[:3])
        except (AttributeError, ValueError):
            return 0
        return max(0, resident - shared) * PAGE

    def sample(self) -> dict:
        now = self.clock()
        dt = (now - self._prev_t) if self._prev_t is not None else None
        ticks: dict[str, int] = {}
        cpu: dict[str, list[float]] = {}   # name -> [percent, processes]
        mem: dict[str, list[float]] = {}   # name -> [bytes, processes]
        for pid in _pids(self.proc):
            stat = self._stat(pid)
            if stat is None:
                continue  # the process ended while we looked
            comm, used = stat
            cmd = None
            name = comm
            if comm in WRAPPERS or _PYTHON.match(comm):
                cmd = (_read(os.path.join(self.proc, pid, "cmdline")) or "").split("\0")
                name = app_name(comm, cmd)
            ticks[pid] = used
            if dt and dt > 0.05 and pid in self._prev:
                pct = max(0, used - self._prev[pid]) / CLK_TCK / dt / self.ncpu * 100
                row = cpu.setdefault(name, [0.0, 0])
                row[0] += pct
                row[1] += 1
            private = self._private_bytes(pid)
            if private:
                row = mem.setdefault(name, [0.0, 0])
                row[0] += private
                row[1] += 1
        self._prev, self._prev_t = ticks, now
        pick = lambda d, minimum: sorted(((n, v, c) for n, (v, c) in d.items() if v > minimum),  # noqa: E731
                                         key=lambda r: -r[1])[:self.top]
        return {"cpu": pick(cpu, 0.05), "mem": pick(mem, 1), "ready": dt is not None}


# --------------------------------------------------------------- GPU
def parse_pmon(text: str) -> list[dict]:
    """Parse `nvidia-smi pmon -c 1 -s um` -> [{pid, type, sm, mem_mb, name}] sorted by use."""
    rows = []
    for line in text.splitlines():
        if line.lstrip().startswith("#") or not line.strip():
            continue
        parts = line.split()
        if len(parts) < 12 or not parts[1].isdigit():
            continue
        num = lambda s: int(s) if s.isdigit() else 0  # noqa: E731  ("-" means no data)
        rows.append({"pid": int(parts[1]), "type": parts[2], "sm": num(parts[3]),
                     "mem_mb": num(parts[9]), "name": " ".join(parts[11:])})
    return sorted(rows, key=lambda r: (-r["sm"], -r["mem_mb"]))


def gpu_processes(timeout: float = 4.0) -> list[dict]:
    """Per-process GPU use. Run it only while the dGPU is awake: nvidia-smi would wake it."""
    try:
        out = subprocess.run(["nvidia-smi", "pmon", "-c", "1", "-s", "um"], capture_output=True,
                             text=True, timeout=timeout, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_pmon(out)


def nvidia_holders(proc: str = PROC) -> list[dict]:
    """Processes with /dev/nvidia* open: they are what keeps the dGPU from suspending.

    -> [{pid, name, devices}] (other users' processes need root to be visible).
    """
    out = []
    for pid in _pids(proc):
        fd_dir = os.path.join(proc, pid, "fd")
        try:
            entries = os.listdir(fd_dir)
        except OSError:
            continue
        devices = set()
        for fd in entries:
            try:
                target = os.readlink(os.path.join(fd_dir, fd))
            except OSError:
                continue
            if target.startswith("/dev/nvidia"):
                devices.add(target)
        if devices:
            stat = _read(os.path.join(proc, pid, "stat")) or ""
            left, right = stat.find("("), stat.rfind(")")
            comm = stat[left + 1:right] if 0 <= left < right else pid
            cmd = (_read(os.path.join(proc, pid, "cmdline")) or "").split("\0")
            out.append({"pid": int(pid), "name": app_name(comm, cmd), "devices": sorted(devices)})
    return sorted(out, key=lambda r: (("/dev/nvidia0" not in r["devices"]), r["name"]))
