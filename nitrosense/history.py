"""Long-term history: the service samples temperatures, fans and load all the time.

Samples are appended to one JSON-lines file per day (/var/lib/nitrosense/history/) and
kept for RETENTION_DAYS; a second small log keeps SSD wear counters (never pruned).
query() condenses any range into at most `points` buckets so the GUI draws it cheaply.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import threading
import time

log = logging.getLogger("nitrosense.history")

INTERVAL = 30            # seconds between samples
RETENTION_DAYS = 30
SMART_EVERY = 6 * 3600   # SSD counters are logged every 6 hours
RANGES = {"1h": 3600, "6h": 6 * 3600, "24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400}
# metric -> is a temperature (averaged, with max kept); the rest are plain averages
# bat: charge %, pw: W drawn from the battery, cpw/gpw/sys: CPU package / GPU / platform watts,
# fq: mean CPU MHz, thr/pl: % of the interval the CPU was thermally / power limited
FIELDS = ("cpu", "gpu", "ssd", "cf", "gf", "load", "bat", "pw", "cpw", "gpw", "sys", "fq", "thr", "pl")
HOT = {"cpu": 90, "gpu": 85}  # same "attention" limits as alerts.py


class Recorder:
    def __init__(self, directory: str, interval: int = INTERVAL,
                 retention_days: int = RETENTION_DAYS) -> None:
        self.dir = directory
        self.interval = interval
        self.retention = retention_days * 86400
        self.lock = threading.Lock()
        self._last_smart = 0.0
        self._last_battery = 0.0
        self._cache: dict[str, tuple[float, dict]] = {}

    # ------------------------------------------------------------- writing
    def _day_file(self, t: float) -> str:
        return os.path.join(self.dir, time.strftime("history-%Y%m%d.jsonl", time.localtime(t)))

    @property
    def _smart_file(self) -> str:
        return os.path.join(self.dir, "smart.jsonl")

    def _append(self, path: str, obj: dict) -> None:
        os.makedirs(self.dir, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(obj, separators=(",", ":")) + "\n")

    def record(self, sample: dict, t: float | None = None) -> None:
        """Append one sample; None values (sensor missing, GPU asleep) are left out."""
        t = time.time() if t is None else t
        row = {"t": int(t)}
        for k in FIELDS:
            v = sample.get(k)
            if v is not None:
                row[k] = round(float(v), 1)
        if len(row) == 1:
            return
        with self.lock:
            self._append(self._day_file(t), row)

    def record_smart(self, smart: dict, t: float | None = None) -> bool:
        """Log SSD wear counters at most every SMART_EVERY seconds. -> True when written."""
        t = time.time() if t is None else t
        if t - self._last_smart < SMART_EVERY:
            return False
        row = {"t": int(t)}
        for name, s in smart.items():
            keys = ("percentage_used", "bytes_written", "bytes_read", "power_on_hours",
                    "unsafe_shutdowns", "media_errors", "available_spare")
            # only NVMe drives report all of these (ATA ones have their own, different counters)
            if isinstance(s, dict) and "error" not in s and not s.get("ata") and all(k in s for k in keys):
                row[name] = {k: s[k] for k in keys}
        if len(row) == 1:
            return False
        self._last_smart = t
        with self.lock:
            self._append(self._smart_file, row)
        return True

    @property
    def _battery_file(self) -> str:
        return os.path.join(self.dir, "battery.jsonl")

    def record_battery(self, batteries: list[dict], t: float | None = None) -> bool:
        """Log battery health at most every SMART_EVERY seconds. -> True when written."""
        t = time.time() if t is None else t
        if t - self._last_battery < SMART_EVERY:
            return False
        row = {"t": int(t)}
        for b in batteries:
            if b.get("health") is not None:
                row[b["name"]] = {"health": round(b["health"], 2), "full": round(b["energy_full"], 2),
                                  "design": round(b["energy_design"], 2), "cycles": b.get("cycles")}
        if len(row) == 1:
            return False
        self._last_battery = t
        with self.lock:
            self._append(self._battery_file, row)
        return True

    def prune(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        cutoff = time.strftime("history-%Y%m%d.jsonl", time.localtime(now - self.retention))
        removed = 0
        for path in glob.glob(os.path.join(self.dir, "history-*.jsonl")):
            if os.path.basename(path) < cutoff:
                try:
                    os.unlink(path)
                    removed += 1
                except OSError:
                    pass
        return removed

    # ------------------------------------------------------------- reading
    def _rows(self, since: float, until: float):
        day = since - since % 86400 - 86400  # start a day early: file names use local time
        paths = set()
        while day <= until + 86400:
            paths.add(self._day_file(day))
            day += 86400
        for path in sorted(paths):
            try:
                with open(path) as f:
                    for line in f:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue  # a half-written last line after a crash
                        if since <= row.get("t", 0) <= until:
                            yield row
            except OSError:
                continue

    def _smart_rows(self, since: float, path: str | None = None) -> list[dict]:
        out = []
        try:
            with open(path or self._smart_file) as f:
                for line in f:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get("t", 0) >= since:
                        out.append(row)
        except OSError:
            pass
        return out

    def query(self, range_key: str, points: int = 240, now: float | None = None) -> dict:
        span = RANGES[range_key]
        now = time.time() if now is None else now
        cached = self._cache.get(range_key)
        if cached and now - cached[0] < 15:
            return cached[1]
        since = now - span
        step = max(self.interval, span / points)
        n = int(span / step) + 1
        sums = {k: [0.0] * n for k in FIELDS}
        counts = {k: [0] * n for k in FIELDS}
        peaks = {k: [None] * n for k in FIELDS}
        stats = {k: [None, None, 0.0, 0] for k in FIELDS}  # min, max, sum, count
        hot_samples = {k: 0 for k in HOT}
        total = 0
        for row in self._rows(since, now):
            total += 1
            i = min(n - 1, int((row["t"] - since) / step))
            for k in FIELDS:
                v = row.get(k)
                if v is None:
                    continue
                sums[k][i] += v
                counts[k][i] += 1
                if peaks[k][i] is None or v > peaks[k][i]:
                    peaks[k][i] = v
                s = stats[k]
                s[0] = v if s[0] is None or v < s[0] else s[0]
                s[1] = v if s[1] is None or v > s[1] else s[1]
                s[2] += v
                s[3] += 1
            for k, limit in HOT.items():
                if (row.get(k) or 0) >= limit:
                    hot_samples[k] += 1
        series = []
        for i in range(n):
            point = {"t": int(since + i * step)}
            for k in FIELDS:
                if counts[k][i]:
                    point[k] = round(sums[k][i] / counts[k][i], 1)
                    if k in ("cpu", "gpu", "ssd", "pw", "cpw", "gpw", "sys"):
                        point[k + "_max"] = peaks[k][i]
            if len(point) > 1:
                series.append(point)
        summary = {k: {"min": s[0], "max": s[1], "avg": round(s[2] / s[3], 1), "n": s[3]}
                   for k, s in stats.items() if s[3]}
        smart = self._smart_rows(since)
        result = {
            "range": range_key, "span": span, "step": step, "interval": self.interval,
            "samples": total, "coverage_s": total * self.interval,
            "series": series, "summary": summary,
            "hot_minutes": {k: round(v * self.interval / 60) for k, v in hot_samples.items()},
            "smart": self._smart_trend(smart),
            "battery": self._battery_trend(self._smart_rows(since, self._battery_file)),
        }
        self._cache[range_key] = (now, result)
        return result

    @staticmethod
    def _smart_trend(rows: list[dict]) -> dict:
        """Change in SSD counters between the first and last log entry of the range."""
        trend: dict = {}
        if len(rows) < 2:
            return trend
        first, last = rows[0], rows[-1]
        for name in last:
            if name == "t" or name not in first:
                continue
            a, b = first[name], last[name]
            trend[name] = {
                "days": round((last["t"] - first["t"]) / 86400, 1),
                "written": b["bytes_written"] - a["bytes_written"],
                "read": b["bytes_read"] - a["bytes_read"],
                "wear": b["percentage_used"] - a["percentage_used"],
                "unsafe": b["unsafe_shutdowns"] - a["unsafe_shutdowns"],
                "media_errors": b["media_errors"] - a["media_errors"],
            }
        return trend

    @staticmethod
    def _battery_trend(rows: list[dict]) -> dict:
        """Health and cycle change between the first and last battery log entry of the range."""
        trend: dict = {}
        if len(rows) < 2:
            return trend
        first, last = rows[0], rows[-1]
        for name in last:
            if name == "t" or name not in first:
                continue
            a, b = first[name], last[name]
            trend[name] = {"days": round((last["t"] - first["t"]) / 86400, 1),
                           "health": round(b["health"] - a["health"], 2),
                           "cycles": (b["cycles"] or 0) - (a["cycles"] or 0)}
        return trend
