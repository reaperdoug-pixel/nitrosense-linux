import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nitrosense import hwmonfan  # noqa: E402
from nitrosense.wmi import WmiError  # noqa: E402


def make_hwmon(root, idx, name, pwm=True):
    d = os.path.join(root, f"hwmon{idx}")
    os.makedirs(d)
    files = {"name": name, "fan1_input": 2500, "fan2_input": 2400}
    if pwm:
        files.update(pwm1=0, pwm2=0, pwm1_enable=2, pwm2_enable=2)
    for fname, value in files.items():
        with open(os.path.join(d, fname), "w") as f:
            f.write(f"{value}\n")
    return d


def read(d, name):
    with open(os.path.join(d, name)) as f:
        return int(f.read())


class HwmonFanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_finds_only_acer_with_pwm(self):
        make_hwmon(self.root, 0, "coretemp", pwm=False)
        make_hwmon(self.root, 1, "acer", pwm=False)
        self.assertIsNone(hwmonfan.find_pwm_hwmon(self.root))
        d = make_hwmon(self.root, 2, "acer")
        self.assertEqual(hwmonfan.find_pwm_hwmon(self.root), d)

    def test_modes(self):
        d = make_hwmon(self.root, 0, "acer")
        fans = hwmonfan.HwmonFans(d)
        fans.set_fan_mode("max")
        self.assertEqual((read(d, "pwm1_enable"), read(d, "pwm2_enable")), (0, 0))
        fans.set_fan_mode("auto")
        self.assertEqual((read(d, "pwm1_enable"), read(d, "pwm2_enable")), (2, 2))

    def test_custom_mode_mixes_auto_and_manual(self):
        d = make_hwmon(self.root, 0, "acer")
        hwmonfan.HwmonFans(d).set_fan_mode("custom", cpu_auto=False, gpu_auto=True,
                                           cpu_percent=60, gpu_percent=30)
        self.assertEqual(read(d, "pwm1_enable"), 1)
        self.assertEqual(read(d, "pwm1"), 153)   # 60 % of 255
        self.assertEqual(read(d, "pwm2_enable"), 2)

    def test_set_speed_switches_to_manual(self):
        d = make_hwmon(self.root, 0, "acer")
        hwmonfan.HwmonFans(d).set_fan_speed("gpu", 100)
        self.assertEqual((read(d, "pwm2_enable"), read(d, "pwm2")), (1, 255))

    def test_write_failure_is_a_wmi_error(self):
        fans = hwmonfan.HwmonFans(os.path.join(self.root, "gone"))
        real = hwmonfan.find_pwm_hwmon
        hwmonfan.find_pwm_hwmon = lambda root="/sys/class/hwmon": None
        try:
            with self.assertRaises(WmiError):
                fans.set_fan_mode("auto")
        finally:
            hwmonfan.find_pwm_hwmon = real

    def test_follows_renumbered_hwmon(self):
        d = make_hwmon(self.root, 5, "acer")
        fans = hwmonfan.HwmonFans(os.path.join(self.root, "hwmon4"))  # stale path
        real = hwmonfan.find_pwm_hwmon
        hwmonfan.find_pwm_hwmon = lambda root="/sys/class/hwmon": real(self.root)
        try:
            fans.set_fan_mode("max")
        finally:
            hwmonfan.find_pwm_hwmon = real
        self.assertEqual(fans.path, d)
        self.assertEqual(read(d, "pwm1_enable"), 0)


class DaemonWithoutWmiTests(unittest.TestCase):
    """acpi_call missing (kernel lockdown): fans still work through acer_wmi's pwm."""

    def setUp(self):
        from fake_hw import make_daemon
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = make_hwmon(self.tmp.name, 0, "acer")
        self.d = make_daemon()
        self.d.ready = False
        self.d.fan_control = True
        self.d.fans = hwmonfan.HwmonFans(self.dir)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fan_commands_go_to_hwmon(self):
        self.assertTrue(self.d.handle({"cmd": "set_fan", "mode": "max"})["ok"])
        self.assertEqual(read(self.dir, "pwm1_enable"), 0)
        self.assertTrue(self.d.handle({"cmd": "set_fan", "mode": "custom", "cpu_auto": False,
                                       "cpu_percent": 40})["ok"])
        self.assertEqual((read(self.dir, "pwm1_enable"), read(self.dir, "pwm1")), (1, 102))
        self.assertTrue(self.d.handle({"cmd": "set_fan", "mode": "auto"})["ok"])
        self.assertEqual(read(self.dir, "pwm2_enable"), 2)
        self.assertEqual(self.d.ctl.wmi.calls, [])  # nothing went to WMI

    def test_other_hardware_commands_still_refused(self):
        self.assertFalse(self.d.handle({"cmd": "set_coolboost", "on": True})["ok"])

    def test_status_reports_fan_control(self):
        self.assertTrue(self.d.handle({"cmd": "status"})["hw"]["fan_control"])


if __name__ == "__main__":
    unittest.main()
