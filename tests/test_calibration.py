import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fake_hw import make_daemon  # noqa: E402

from nitrosense import calibration as cal  # noqa: E402
from nitrosense import daemon as dmod  # noqa: E402
from nitrosense import encoders as enc  # noqa: E402

H = 3600


class TrackerTests(unittest.TestCase):
    def run_cycle(self, steps, tracker=None):
        t = tracker or cal.Tracker(0.0)
        result, now = None, 0.0
        for cap, status in steps:
            now += 60
            result = t.update(cap, status, now, True)
            if result:
                break
        return t, result

    def test_full_cycle(self):
        steps = ([(70, "Charging"), (99, "Charging"), (100, "Full"), (100, "Full")]
                 + [(c, "Discharging") for c in (90, 60, 30, 10, 4)]
                 + [(8, "Charging"), (40, "Charging"), (80, "Charging"), (99, "Charging")])
        t = cal.Tracker(0.0)
        phases = []
        now = 0.0
        for cap, status in steps:
            now += 60
            result = t.update(cap, status, now, True)
            phases.append(t.phase)
        self.assertEqual(result, "done")
        self.assertEqual([p for i, p in enumerate(phases) if i == 0 or p != phases[i - 1]],
                         ["charging", "waiting", "discharging", "recharging"])
        self.assertEqual(t.min_seen, 4)

    def test_a_shallow_dip_is_not_a_calibration(self):
        steps = [(100, "Full"), (95, "Discharging"), (85, "Discharging"), (90, "Charging"),
                 (100, "Full")]
        t, result = self.run_cycle(steps)
        self.assertIsNone(result)  # never went deep, so the recharge does not count
        self.assertEqual(t.phase, "discharging")

    def test_firmware_ends_it_early_is_an_abort(self):
        t = cal.Tracker(0.0, "discharging", 50.0)
        self.assertEqual(t.update(60, "Discharging", 100, False), "aborted")

    def test_firmware_ends_it_after_the_recharge_is_done(self):
        t = cal.Tracker(0.0, "recharging", 3.0)
        self.assertEqual(t.update(97, "Charging", 100, False), "done")
        t2 = cal.Tracker(0.0, "recharging", 3.0)
        self.assertEqual(t2.update(40, "Charging", 100, False), "aborted")

    def test_timeout_and_persistence(self):
        t = cal.Tracker(0.0)
        self.assertEqual(t.update(50, "Charging", cal.MAX_HOURS * H + 1, True), "timeout")
        again = cal.Tracker.from_dict(cal.Tracker(5.0, "discharging", 22.0).to_dict())
        self.assertEqual((again.started, again.phase, again.min_seen), (5.0, "discharging", 22.0))
        self.assertIn("22%", again.text)


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.d = make_daemon()
        self.wmi = self.d.ctl.wmi
        self.real_ac = dmod.power.ac_online
        dmod.power.ac_online = lambda: self.ac
        self.ac = True
        self.cap = {"capacity": 100, "status": "Full"}
        self.d._battery_read = lambda: [dict(self.cap)]

    def tearDown(self):
        dmod.power.ac_online = self.real_ac

    def start(self):
        self.d.handle({"cmd": "start_battery_calibration"})

    def test_encoders(self):
        self.assertEqual(enc.battery_calibration_set(True), 0x010201)
        self.assertEqual(enc.battery_calibration_set(False), 0x000201)
        self.assertIs(enc.battery_calibration_decode(3 | (1 << 32)), True)
        self.assertIs(enc.battery_calibration_decode(3 | (1 << 24)), False)  # only health mode on
        self.assertIsNone(enc.battery_calibration_decode(1))                 # not supported

    def test_start_needs_the_charger_and_a_free_firmware(self):
        self.ac = False
        with self.assertRaises(dmod.ValidationError):
            self.start()
        self.assertFalse(self.wmi.battery_calibration)
        self.ac = True
        self.start()
        self.assertTrue(self.wmi.battery_calibration)
        with self.assertRaises(dmod.ValidationError):
            self.start()  # already running
        self.d.hw_battery_calibration = None
        self.d.state["battery_calibration"]["active"] = False
        with self.assertRaises(dmod.ValidationError):
            self.start()  # unsupported

    def test_limit_is_suspended_during_and_restored_after(self):
        self.d.handle({"cmd": "set_battery_limit", "on": True})
        self.start()
        self.assertFalse(self.wmi.battery_limit)  # the firmware turned it off
        st = self.d.handle({"cmd": "status"})["hw"]["battery_calibration"]
        self.assertEqual((st["active"], st["restore_limit"], st["phase"]), (True, True, "charging"))
        with self.assertRaises(dmod.ValidationError):
            self.d.handle({"cmd": "set_battery_limit", "on": True})  # not while calibrating
        self.d.handle({"cmd": "stop_battery_calibration"})
        self.assertFalse(self.wmi.battery_calibration)
        self.assertTrue(self.wmi.battery_limit)                       # restored
        self.assertTrue(self.d.hw_battery_limit)
        last = self.d.handle({"cmd": "status"})["hw"]["battery_calibration"]["last"]
        self.assertEqual(last["result"], "cancelled")

    def test_limit_stays_off_if_it_was_off(self):
        self.start()
        self.d.handle({"cmd": "stop_battery_calibration"})
        self.assertFalse(self.wmi.battery_limit)

    def test_supervisor_follows_the_cycle_and_finishes(self):
        self.d.handle({"cmd": "set_battery_limit", "on": True})
        self.start()
        seen = []
        for cap, status in [(100, "Full"), (100, "Full"), (60, "Discharging"), (5, "Discharging"),
                            (20, "Charging"), (70, "Charging"), (100, "Charging")]:
            self.cap = {"capacity": cap, "status": status}
            self.d.battery_calibration_step()
            seen.append(self.d.calibration_status().get("phase"))
        self.assertEqual(seen[0], "waiting")
        self.assertIn("discharging", seen)
        self.assertIn("recharging", seen)
        self.assertFalse(self.d.state["battery_calibration"]["active"])      # finished
        self.assertEqual(self.d.state["battery_calibration"]["last"]["result"], "done")
        self.assertFalse(self.wmi.battery_calibration)
        self.assertTrue(self.wmi.battery_limit)                              # charge limit back

    def test_unplugging_aborts_and_restores(self):
        self.d.handle({"cmd": "set_battery_limit", "on": True})
        self.start()
        self.wmi.battery_calibration = False  # the firmware gave up (charger removed)
        self.d.battery_calibration_step()
        self.assertEqual(self.d.state["battery_calibration"]["last"]["result"], "aborted")
        self.assertTrue(self.wmi.battery_limit)

    def test_state_survives_a_restart_and_reapply_keeps_the_limit_off(self):
        self.d.handle({"cmd": "set_battery_limit", "on": True})
        self.start()
        d2 = make_daemon(dmod.STATE_DIR)
        d2.ctl.wmi.battery_calibration = True
        d2.hw_battery_calibration = True
        d2.reapply("test")
        self.assertTrue(d2.state["battery_calibration"]["active"])
        self.assertFalse(d2.ctl.wmi.battery_limit)  # not re-enabled mid-calibration

    def test_calibration_started_outside_is_reported_not_touched(self):
        self.wmi.battery_calibration = True
        self.d.battery_calibration_step()
        st = self.d.calibration_status()
        self.assertEqual((st["active"], st["external"]), (False, True))
        self.assertTrue(self.wmi.battery_calibration)  # we did not stop it
        self.d.handle({"cmd": "stop_battery_calibration"})  # but the user may
        self.assertFalse(self.wmi.battery_calibration)


if __name__ == "__main__":
    unittest.main()
