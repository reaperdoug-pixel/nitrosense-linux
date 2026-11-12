import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fake_hw import make_daemon  # noqa: E402

from nitrosense import alerts, disks, history, sysmon, throttle  # noqa: E402


def put(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f"{value}\n")


class Tree:
    """A fake /sys with two CPUs, cooling devices and package power limits."""

    def __init__(self):
        self.root = tempfile.mkdtemp()
        self.cpu = os.path.join(self.root, "cpu")
        self.thermal = os.path.join(self.root, "thermal")
        self.powercap = os.path.join(self.root, "powercap")
        for i in (0, 1):
            self.set_cpu(i, freq=3_000_000, max=4_600_000, cap=4_600_000, events=0, ms=0)
        for n, (kind, cur) in enumerate((("Processor", 0), ("intel_powerclamp", 0), ("TCC Offset", 8),
                                         ("PCIe_Port_Link_Speed_0", 2))):
            put(os.path.join(self.thermal, f"cooling_device{n}", "type"), kind)
            put(os.path.join(self.thermal, f"cooling_device{n}", "cur_state"), cur)
        put(os.path.join(self.powercap, "intel-rapl:0", "constraint_0_power_limit_uw"), 45_000_000)
        put(os.path.join(self.powercap, "intel-rapl:0", "constraint_1_power_limit_uw"), 115_000_000)
        self.t = 100.0

    def set_cpu(self, i, freq=None, max=None, cap=None, events=None, ms=None):
        base = os.path.join(self.cpu, f"cpu{i}")
        for name, v in (("cpufreq/scaling_cur_freq", freq), ("cpufreq/cpuinfo_max_freq", max),
                        ("cpufreq/scaling_max_freq", cap),
                        ("thermal_throttle/package_throttle_count", events),
                        ("thermal_throttle/core_throttle_count", 0),
                        ("thermal_throttle/package_throttle_total_time_ms", ms),
                        ("thermal_throttle/core_throttle_total_time_ms", 0)):
            if v is not None:
                put(os.path.join(base, name), v)

    def cooling(self, n, value):
        put(os.path.join(self.thermal, f"cooling_device{n}", "cur_state"), value)

    def monitor(self):
        return throttle.CpuThrottle(self.cpu, self.thermal, self.powercap, clock=lambda: self.t)


class CpuThrottleTests(unittest.TestCase):
    def test_quiet_system(self):
        tree = Tree()
        m = tree.monitor()
        s = m.update(10.0)
        self.assertEqual((s["thermal"], s["power_limited"], s["freq_capped"], s["reasons"]),
                         (False, False, False, []))
        self.assertEqual((s["mhz"], s["mhz_max"], s["tcc_offset"]), (3000, 4600, 8))
        put(os.path.join(tree.root, "hwmon", "hwmon0", "name"), "coretemp")
        put(os.path.join(tree.root, "hwmon", "hwmon0", "temp1_crit"), 100000)
        m = throttle.CpuThrottle(tree.cpu, tree.thermal, tree.powercap, hwmon=os.path.join(tree.root, "hwmon"))
        self.assertEqual(m.update()["limit_c"], 92)  # Tjmax 100 - TCC offset 8

    def test_hardware_thermal_event_is_flagged_once(self):
        tree = Tree()
        m = tree.monitor()
        m.update()  # baseline
        tree.set_cpu(0, events=1, ms=0)
        self.assertTrue(m.update()["thermal"])
        tree.t += 2
        self.assertFalse(m.update()["thermal"])  # the counter did not move again

    def test_thermal_time_counter_alone_counts(self):
        tree = Tree()
        m = tree.monitor()
        m.update()
        tree.set_cpu(1, ms=350)
        self.assertTrue(m.update()["thermal"])

    def test_cooling_device_and_duration(self):
        tree = Tree()
        m = tree.monitor()
        tree.cooling(0, 2)  # a Processor cooling device is holding the CPU back
        self.assertEqual(m.update()["thermal_for_s"], 0)
        tree.t += 12
        s = m.update()
        self.assertTrue(s["thermal"])
        self.assertEqual(s["thermal_for_s"], 12)
        self.assertTrue(alerts.evaluate(50, 40, 2000, 2000, [], throttle=s))
        tree.cooling(0, 0)
        tree.t += 2
        s = m.update()
        self.assertEqual((s["thermal"], s["thermal_for_s"]), (False, 0))
        self.assertEqual(alerts.evaluate(50, 40, 2000, 2000, [], throttle=s), [])

    def test_alert_needs_ten_seconds(self):
        self.assertEqual(alerts.evaluate(50, 40, 2000, 2000, [], throttle={"thermal_for_s": 4}), [])
        got = alerts.evaluate(50, 40, 2000, 2000, [], throttle={"thermal_for_s": 10})
        self.assertEqual((got[0][0], got[0][1]), (disks.WARN, "throttle:CPU"))
        got = alerts.evaluate(50, 40, 2000, 2000, [], gpu_thermal=True)
        self.assertEqual(got[0][1], "throttle:GPU")

    def test_power_limit_and_cap(self):
        tree = Tree()
        m = tree.monitor()
        self.assertFalse(m.update(30.0)["power_limited"])
        self.assertTrue(m.update(44.0)["power_limited"])    # 44 W >= 97 % of PL1 = 45 W
        tree.set_cpu(0, cap=3_000_000)
        s = m.update(10.0)
        self.assertTrue(s["freq_capped"])
        self.assertFalse(s["thermal"])  # a frequency cap alone is information, not throttling

    def test_missing_interfaces(self):
        m = throttle.CpuThrottle(tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp())
        s = m.update()
        self.assertEqual((s["mhz"], s["thermal"], s["reasons"]), (None, False, []))

    def test_history_window(self):
        tree = Tree()
        m = tree.monitor()
        m.update()
        tree.cooling(0, 1)
        m.update()
        m.update()
        tree.cooling(0, 0)
        m.update()
        w = m.window()
        self.assertEqual((w["thr"], w["pl"], w["fq"]), (50.0, 0.0, 3000))
        self.assertEqual(m.window(), {})  # nothing new since


class GpuAndIntegrationTests(unittest.TestCase):
    def test_gpu_reason_classes(self):
        self.assertEqual(sysmon.gpu_throttle(0x4), {"thermal": False, "power": True, "hw": False})
        self.assertTrue(sysmon.gpu_throttle(0x60)["thermal"])
        self.assertEqual(sysmon.gpu_throttle(0x1), {"thermal": False, "power": False, "hw": False})
        self.assertEqual(sysmon.gpu_throttle(None), {"thermal": False, "power": False, "hw": False})

    def test_status_and_history(self):
        d = make_daemon()
        tree = Tree()
        tree.cooling(0, 1)
        d.throttle = tree.monitor()
        d.throttle.update()
        self.assertTrue(d.handle({"cmd": "status"})["throttle"]["thermal"])
        d.recorder = history.Recorder(tempfile.mkdtemp())
        d.record_sample()
        q = d.recorder.query("1h")
        self.assertEqual(q["summary"]["thr"]["max"], 100.0)
        self.assertEqual(q["summary"]["fq"]["max"], 3000.0)


if __name__ == "__main__":
    unittest.main()
