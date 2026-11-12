import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fake_hw import make_daemon  # noqa: E402

from nitrosense import history  # noqa: E402
from nitrosense.rapl import Rapl  # noqa: E402


def make_root(zones):
    root = tempfile.mkdtemp()
    for i, (name, energy, span) in enumerate(zones):
        d = os.path.join(root, f"intel-rapl:{i}")
        os.makedirs(d)
        for fname, val in (("name", name), ("energy_uj", energy), ("max_energy_range_uj", span)):
            with open(os.path.join(d, fname), "w") as f:
                f.write(f"{val}\n")
    return root


def set_energy(root, index, value):
    with open(os.path.join(root, f"intel-rapl:{index}", "energy_uj"), "w") as f:
        f.write(f"{value}\n")


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class RaplTests(unittest.TestCase):
    def test_watts_from_energy_delta(self):
        root, clock = make_root([("package-0", 0, 10**9), ("psys", 0, 10**9),
                                 ("core", 0, 10**9), ("other", 5, 10**9)]), Clock()
        r = Rapl(root, clock)
        self.assertEqual(sorted(r.zones), ["core", "cpu", "sys"])  # unknown zones are ignored
        self.assertEqual(r.sample(), {})  # first call only sets the baseline
        clock.t += 2.0
        set_energy(root, 0, 30_000_000)  # 30 J in 2 s
        set_energy(root, 1, 50_000_000)
        set_energy(root, 2, 10_000_000)
        self.assertEqual(r.sample(), {"cpu": 15.0, "sys": 25.0, "core": 5.0})

    def test_counter_wraparound(self):
        root, clock = make_root([("package-0", 990_000_000, 1_000_000_000)]), Clock()
        r = Rapl(root, clock)
        r.sample()
        clock.t += 1.0
        set_energy(root, 0, 20_000_000)  # wrapped: 10 J before the end + 20 J after
        self.assertEqual(r.sample(), {"cpu": 30.0})

    def test_back_to_back_calls_repeat_the_last_value(self):
        root, clock = make_root([("package-0", 0, 10**9)]), Clock()
        r = Rapl(root, clock)
        r.sample()
        clock.t += 1.0
        set_energy(root, 0, 8_000_000)
        first = r.sample()
        clock.t += 0.01
        set_energy(root, 0, 8_100_000)
        self.assertEqual(r.sample(), first)
        clock.t += 1.0  # the skipped energy is still counted against the next full interval
        set_energy(root, 0, 16_000_000)
        self.assertAlmostEqual(r.sample()["cpu"], 8.0 / 1.01, places=1)

    def test_unreadable_or_missing(self):
        self.assertEqual(Rapl(tempfile.mkdtemp()).sample(), {})
        root = make_root([("package-0", 0, 10**9)])
        os.unlink(os.path.join(root, "intel-rapl:0", "energy_uj"))
        r = Rapl(root, Clock())
        self.assertEqual((r.sample(), r.sample()), ({}, {}))


class IntegrationTests(unittest.TestCase):
    def test_sensors_and_history_carry_watts(self):
        d = make_daemon()
        root, clock = make_root([("package-0", 0, 10**9), ("psys", 0, 10**9)]), Clock()
        d._rapl, d._rapl_rec = Rapl(root, clock), Rapl(root, clock)
        d.sensors()                       # baselines
        clock.t += 1.0
        set_energy(root, 0, 12_000_000)
        set_energy(root, 1, 30_000_000)
        d._sensor_cache = (0.0, {})       # force a refresh
        s = d.sensors()
        self.assertEqual((s["cpu_power"], s["sys_power"], s["igpu_power"]), (12.0, 30.0, None))
        d.recorder = history.Recorder(tempfile.mkdtemp())
        d._rapl_rec.sample()              # baseline for the recorder's own counter
        clock.t += 30.0
        set_energy(root, 0, 12_000_000 + 600_000_000)  # 600 J over 30 s = 20 W
        d.record_sample()
        q = d.recorder.query("1h")
        self.assertEqual(q["summary"]["cpw"]["max"], 20.0)
        self.assertEqual(q["summary"]["cpw"]["n"], 1)


if __name__ == "__main__":
    unittest.main()
