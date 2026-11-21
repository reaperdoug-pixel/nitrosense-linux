import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nitrosense import power  # noqa: E402

# tests/fake_hw.py replaces power.apply_plan for the daemon tests; keep the real one
apply_plan = power.apply_plan


class ApplyPlanTests(unittest.TestCase):
    def setUp(self):
        self.writes, self.ppd_calls = [], []
        self.real = (power._write, power._available_governors, power._ppd_profiles,
                     power._scaling_driver, power.glob.glob, power.subprocess.run)
        power._write = lambda path, value: self.writes.append((path, value)) or True
        power.glob.glob = lambda pat: ["/cpu/policy0"] if "policy" in pat else []
        power.subprocess.run = lambda cmd, **kw: self.ppd_calls.append(cmd)

    def tearDown(self):
        (power._write, power._available_governors, power._ppd_profiles,
         power._scaling_driver, power.glob.glob, power.subprocess.run) = self.real

    def _setup(self, driver, govs, profiles):
        power._scaling_driver = lambda: driver
        power._available_governors = lambda: set(govs)
        power._ppd_profiles = lambda: set(profiles)

    def governor(self):
        return [v for p, v in self.writes if p.endswith("scaling_governor")]

    def test_intel_pstate_with_ppd_keeps_powersave(self):
        # the performance governor would lock EPP and make ppd abort the profile switch
        self._setup("intel_pstate", ("performance", "powersave"),
                    ("performance", "balanced", "power-saver"))
        apply_plan(power.PLAN_PERFORMANCE)
        self.assertEqual(self.governor(), ["powersave"])
        self.assertEqual(self.ppd_calls, [["powerprofilesctl", "set", "performance"]])

    def test_acpi_cpufreq_uses_performance_governor(self):
        self._setup("acpi-cpufreq", ("performance", "schedutil"), ("performance", "balanced"))
        apply_plan(power.PLAN_PERFORMANCE)
        self.assertEqual(self.governor(), ["performance"])

    def test_intel_pstate_without_ppd_uses_performance_governor(self):
        self._setup("intel_pstate", ("performance", "powersave"), ())
        apply_plan(power.PLAN_PERFORMANCE)
        self.assertEqual(self.governor(), ["performance"])
        self.assertEqual(self.ppd_calls, [])


if __name__ == "__main__":
    unittest.main()
