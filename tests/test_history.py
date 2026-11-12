import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fake_hw import make_daemon  # noqa: E402

from nitrosense import disks, history, watcher  # noqa: E402
from nitrosense.daemon import ValidationError  # noqa: E402

NOW = 1_800_000_000.0


def smart(used=5, written=1000, unsafe=3):
    return {"nvme0": {"percentage_used": used, "bytes_written": written, "bytes_read": 2 * written,
                      "power_on_hours": 100, "unsafe_shutdowns": unsafe, "media_errors": 0,
                      "available_spare": 100}}


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.rec = history.Recorder(self.dir, interval=30)

    def test_query_buckets_and_summary(self):
        for i in range(120):  # one hour of samples, CPU ramps 50 -> 69.5
            self.rec.record({"cpu": 50 + i / 6, "gpu": None, "load": 10}, NOW - 3600 + i * 30)
        r = self.rec.query("1h", points=12, now=NOW)
        self.assertEqual(r["samples"], 120)
        self.assertLessEqual(len(r["series"]), 13)
        self.assertNotIn("gpu", r["summary"])
        self.assertAlmostEqual(r["summary"]["cpu"]["min"], 50, delta=0.1)
        self.assertAlmostEqual(r["summary"]["cpu"]["max"], 69.8, delta=0.2)
        self.assertEqual(r["hot_minutes"], {"cpu": 0, "gpu": 0})
        first = r["series"][0]
        self.assertLessEqual(first["cpu"], first["cpu_max"])

    def test_hot_minutes(self):
        for i in range(10):
            self.rec.record({"cpu": 92, "gpu": 60}, NOW - 600 + i * 30)
        self.assertEqual(self.rec.query("1h", now=NOW)["hot_minutes"]["cpu"], 5)

    def test_range_excludes_old_samples_and_survives_garbage(self):
        self.rec.record({"cpu": 99}, NOW - 2 * 86400)
        self.rec.record({"cpu": 40}, NOW - 60)
        with open(self.rec._day_file(NOW - 60), "a") as f:
            f.write('{"t": 1\n')  # half-written line
        r = self.rec.query("24h", now=NOW)
        self.assertEqual(r["summary"]["cpu"]["max"], 40)

    def test_empty_sample_is_skipped(self):
        self.rec.record({"cpu": None}, NOW)
        self.assertEqual(os.listdir(self.dir), [])

    def test_prune_keeps_recent_days(self):
        self.rec.record({"cpu": 1}, NOW - 40 * 86400)
        self.rec.record({"cpu": 2}, NOW - 5 * 86400)
        self.assertEqual(self.rec.prune(NOW), 1)
        self.assertEqual(len(os.listdir(self.dir)), 1)

    def test_smart_log_and_trend(self):
        self.assertTrue(self.rec.record_smart(smart(5, 1000, 3), NOW - 3 * 86400))
        self.assertFalse(self.rec.record_smart(smart(5, 1500, 3), NOW - 3 * 86400 + 60))  # too soon
        self.assertTrue(self.rec.record_smart(smart(6, 4000, 5), NOW - 60))
        t = self.rec.query("7d", now=NOW)["smart"]["nvme0"]
        self.assertEqual((t["written"], t["wear"], t["unsafe"]), (3000, 1, 2))
        self.assertAlmostEqual(t["days"], 3, delta=0.1)

    def test_smart_errors_are_ignored(self):
        self.assertFalse(self.rec.record_smart({"nvme0": {"error": "x"}}, NOW))


class DaemonHistoryTests(unittest.TestCase):
    def test_command(self):
        d = make_daemon()
        self.assertEqual(d.handle({"cmd": "history"}), {"ok": True, "history": None})
        d.recorder = history.Recorder(tempfile.mkdtemp())
        d.record_sample()
        r = d.handle({"cmd": "history", "range": "1h"})
        self.assertTrue(r["ok"])
        self.assertGreaterEqual(r["history"]["samples"], 1)
        self.assertIn("cpu", r["history"]["summary"])
        with self.assertRaises(ValidationError):
            d.handle({"cmd": "history", "range": "forever"})


class ThrottleTests(unittest.TestCase):
    def test_new_worse_and_reminders(self):
        t = watcher.Throttle(remind=100)
        warn = [(disks.WARN, "temp:CPU", "hot")]
        crit = [(disks.CRIT, "temp:CPU", "very hot")]
        self.assertEqual(t.filter(warn, 0), warn)       # new
        self.assertEqual(t.filter(warn, 10), [])        # unchanged
        self.assertEqual(t.filter(crit, 20), crit)      # worse
        self.assertEqual(t.filter(crit, 60), [])        # reminder not due
        self.assertEqual(t.filter(crit, 130), crit)     # critical reminder
        self.assertEqual(t.filter([], 140), [])         # cleared
        self.assertEqual(t.filter(warn, 150), warn)     # recurrence notifies again

    def test_warning_is_never_repeated(self):
        t = watcher.Throttle(remind=1)
        warn = [(disks.WARN, "disk:nvme0", "wear")]
        t.filter(warn, 0)
        self.assertEqual(t.filter(warn, 10_000), [])


class LockTests(unittest.TestCase):
    def test_single_instance(self):
        old = watcher.LOCK_PATH
        watcher.LOCK_PATH = os.path.join(tempfile.mkdtemp(), "w.lock")
        try:
            self.assertFalse(watcher.running())
            held = watcher.acquire_lock()
            self.assertIsNotNone(held)
            self.assertTrue(watcher.running())
            self.assertIsNone(watcher.acquire_lock())
            held.close()
            self.assertFalse(watcher.running())
        finally:
            watcher.LOCK_PATH = old


if __name__ == "__main__":
    unittest.main()
