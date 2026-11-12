import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fake_hw import make_daemon  # noqa: E402

from nitrosense import daemon as dmod  # noqa: E402
from nitrosense import encoders as enc  # noqa: E402
from nitrosense import fancurve as fc  # noqa: E402

P = fc.DEFAULT_POINTS  # 40:30 50:40 60:50 70:70 80:90 90:100


class CurveMathTests(unittest.TestCase):
    def test_interpolation_and_rounding_up(self):
        self.assertEqual(fc.target_percent(P, 20), 30)    # below the first point: its value
        self.assertEqual(fc.target_percent(P, 45), 40)    # 35 % -> up to the next 10 %
        self.assertEqual(fc.target_percent(P, 60), 50)
        self.assertEqual(fc.target_percent(P, 75), 80)
        self.assertEqual(fc.target_percent(P, 99), 100)
        low = [[40, 20], [60, 20], [90, 100]]
        self.assertEqual(fc.target_percent(low, 30), 20)  # never below the floor

    def test_validation(self):
        self.assertEqual(fc.validate(P), P)
        for bad in (None, "x", P[:2], [[40, 30], [40, 50], [90, 100]],      # not increasing
                    [[40, 50], [60, 30], [90, 100]],                         # decreasing speed
                    [[40, 10], [60, 50], [90, 100]],                         # below the floor
                    [[40, 30], [60, 50], [90, 90]],                          # does not reach 100 %
                    [[40, 30], [60, 50], [95, 100]],                         # reaches it too late
                    [[40, 30], [60, 50], [90, 100], "x"], [[True, 30], [60, 50], [90, 100]]):
            with self.assertRaises(ValueError, msg=bad):
                fc.validate(bad)

    def test_presets_are_valid(self):
        for values in fc.PRESETS.values():
            fc.validate([[t, p] for t, p in zip(fc.TEMPS, values)])


class StateMachineTests(unittest.TestCase):
    def test_first_step_enters_then_rises_at_once_and_falls_slowly(self):
        c = fc.FanCurve(hold_s=8)
        self.assertEqual(c.step(P, 45, None, 2), fc.Decision(40, True, False))
        self.assertEqual(c.step(P, 45, None, 2), fc.Decision(None, False, False))  # unchanged
        self.assertEqual(c.step(P, 65, None, 2), fc.Decision(60, False, False))   # up: immediately
        for _ in range(3):                                                         # cooling: wait
            self.assertEqual(c.step(P, 45, None, 2).percent, None)
        self.assertEqual(c.step(P, 45, None, 2).percent, 40)                       # after 8 s
        self.assertEqual(c.applied, 40)

    def test_a_short_dip_does_not_slow_the_fans(self):
        c = fc.FanCurve(hold_s=8)
        c.step(P, 65, None, 2)
        c.step(P, 45, None, 2)
        c.step(P, 45, None, 2)
        self.assertEqual(c.step(P, 65, None, 2).percent, None)  # back to the old target
        self.assertEqual(c.down_for, 0.0)                        # the timer starts over
        c.step(P, 45, None, 2)
        self.assertIsNone(c.step(P, 45, None, 2).percent)        # only 4 s below again

    def test_safety_overrides_the_curve(self):
        flat = [[40, 20], [60, 20], [90, 100]]
        c = fc.FanCurve()
        c.step(flat, 50, None, 2)
        self.assertEqual(c.step(flat, 88, None, 2).percent, 100)  # CPU at the limit
        c2 = fc.FanCurve()
        c2.step(flat, 50, 50, 2)
        self.assertEqual(c2.step(flat, 50, 82, 2).percent, 100)   # GPU at its limit
        self.assertTrue(c2.info["safety"])

    def test_hottest_sensor_wins(self):
        c = fc.FanCurve()
        self.assertEqual(c.step(P, 45, 75, 2).percent, 80)

    def test_failsafe_releases_and_recovers(self):
        c = fc.FanCurve(fail_limit=3)
        c.step(P, 50, None, 2)
        self.assertEqual(c.step(P, None, None, 2), fc.Decision(None, False, False))
        self.assertEqual(c.step(P, None, None, 2), fc.Decision(None, False, False))
        self.assertEqual(c.step(P, None, None, 2), fc.Decision(None, False, True))   # give back
        self.assertEqual(c.step(P, None, None, 2), fc.Decision(None, False, False))  # only once
        self.assertEqual(c.step(P, 55, None, 2), fc.Decision(50, True, False))       # sensors back


class NoGpu:
    def awake(self):
        return False


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.d = make_daemon()
        self.d._gpu_probe = NoGpu()
        self.wmi = self.d.ctl.wmi

    def set_temp(self, cpu):
        self.d._sensor_cache = (1e12, {"cpu_temp": cpu, "gpu_temp": None, "cpu_fan": 2000,
                                       "gpu_fan": 2000, "cpu_power": None, "igpu_power": None,
                                       "sys_power": None})

    def test_curve_mode_drives_the_fans(self):
        self.set_temp(65)
        self.d.handle({"cmd": "set_fan", "mode": "curve"})
        self.assertEqual(self.d.state["fan"]["mode"], "curve")
        self.assertEqual(self.wmi.calls[-3:], [
            ("SetGamingFanBehavior", enc.fan_custom_behavior(False, False)),
            ("SetGamingFanSpeed", enc.fan_speed("cpu", 60)),
            ("SetGamingFanSpeed", enc.fan_speed("gpu", 60))])
        self.set_temp(78)
        self.d.fan_curve_step(2)
        self.assertEqual(self.wmi.fan_speed, {"cpu": 90, "gpu": 90})
        st = self.d.handle({"cmd": "status"})["fan_curve"]
        self.assertEqual((st["percent"], st["temp"]), (90, 78))

    def test_leaving_curve_mode_stops_the_thread_logic(self):
        self.set_temp(65)
        self.d.handle({"cmd": "set_fan", "mode": "curve"})
        self.d.handle({"cmd": "set_fan", "mode": "auto"})
        self.assertEqual(self.wmi.calls[-1], ("SetGamingFanBehavior", enc.fan_mode_all("auto")))
        before = len(self.wmi.calls)
        self.set_temp(90)
        self.d.fan_curve_step(2)
        self.assertEqual(len(self.wmi.calls), before)  # no more fan writes outside curve mode

    def test_set_curve_validates_and_persists(self):
        with self.assertRaises(dmod.ValidationError):
            self.d.handle({"cmd": "set_fan_curve", "points": [[40, 30], [50, 20], [90, 100]]})
        new = [[40, 20], [60, 40], [80, 80], [90, 100]]
        self.d.handle({"cmd": "set_fan_curve", "points": new})
        self.assertEqual(self.d.state["fan_curve"]["points"], new)
        d2 = make_daemon(dmod.STATE_DIR)
        self.assertEqual(d2.state["fan_curve"]["points"], new)

    def test_reapply_after_reboot_restores_curve_mode(self):
        self.set_temp(65)
        self.d.handle({"cmd": "set_fan", "mode": "curve"})
        d2 = make_daemon(dmod.STATE_DIR)
        d2._gpu_probe = NoGpu()
        d2._sensor_cache = self.d._sensor_cache
        d2.reapply("test")
        self.assertEqual(d2.ctl.wmi.fan_speed["cpu"], 60)
        self.assertEqual(d2.ctl.wmi.fan_behavior["cpu"], 3)  # custom

    def test_release_on_shutdown_and_sensor_failure(self):
        self.set_temp(65)
        self.d.handle({"cmd": "set_fan", "mode": "curve"})
        self.d.release_fans()
        self.assertEqual(self.wmi.calls[-1], ("SetGamingFanBehavior", enc.fan_mode_all("auto")))
        self.d.curve.reset()
        self.d.handle({"cmd": "set_fan", "mode": "curve"})
        self.set_temp(None)
        for _ in range(3):
            self.d.fan_curve_step(2)
        self.assertEqual(self.wmi.calls[-1], ("SetGamingFanBehavior", enc.fan_mode_all("auto")))

    def test_wmi_error_retries_from_scratch(self):
        self.set_temp(65)
        self.d.handle({"cmd": "set_fan", "mode": "curve"})
        real = self.wmi.call
        self.wmi.call = lambda *a: (_ for _ in ()).throw(dmod.WmiError("boom"))
        self.set_temp(80)
        self.d.fan_curve_step(2)  # fails: must not raise
        self.wmi.call = real
        self.assertIsNone(self.d.curve.applied)
        self.d.fan_curve_step(2)  # next step enters again
        self.assertEqual(self.wmi.fan_speed["cpu"], 90)


if __name__ == "__main__":
    unittest.main()
