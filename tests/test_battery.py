import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nitrosense import alerts, battery, disks, history  # noqa: E402


def fake_supply(root, name="BAT1", **files):
    d = os.path.join(root, name)
    os.makedirs(d)
    base = {"type": "Battery", "present": "1", "status": "Discharging"}
    base.update({k: str(v) for k, v in files.items()})
    for k, v in base.items():
        with open(os.path.join(d, k), "w") as f:
            f.write(v + "\n")


def charge_based(**kw):  # like the Nitro: µAh and µV
    return dict(charge_full=3114000, charge_full_design=3733000, charge_now=1557000,
                voltage_now=16000000, voltage_min_design=15400000, current_now=2000000,
                cycle_count=54, capacity=50, technology="Li-ion", manufacturer="LGC",
                model_name="AP21D8M", **kw)


class ReadTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_charge_based_battery(self):
        fake_supply(self.root, **charge_based())
        fake_supply(self.root, "ACAD", type="Mains")
        (b,) = battery.read(self.root)
        self.assertAlmostEqual(b["health"], 83.4, delta=0.1)
        self.assertAlmostEqual(b["energy_design"], 3.733 * 15.4, delta=0.01)
        self.assertAlmostEqual(b["power"], 32.0, delta=0.01)  # 2 A x 16 V
        self.assertEqual((b["cycles"], b["capacity"]), (54, 50))
        hours = battery.time_left(b) / 3600
        self.assertAlmostEqual(hours, b["energy_now"] / 32, delta=0.01)

    def test_energy_based_battery_and_charging_eta(self):
        fake_supply(self.root, status="Charging", energy_full=45_000_000, energy_full_design=50_000_000,
                    energy_now=20_000_000, power_now=25_000_000, voltage_now=15_000_000)
        (b,) = battery.read(self.root)
        self.assertAlmostEqual(b["health"], 90.0)
        self.assertAlmostEqual(battery.time_left(b) / 3600, 1.0)  # 25 Wh missing at 25 W

    def test_idle_battery_has_no_eta_and_devices_are_skipped(self):
        fake_supply(self.root, **charge_based(), scope="System")
        fake_supply(self.root, "hid-mouse", scope="Device", capacity=40)
        fake_supply(self.root, "BAT2", present=0)
        batts = battery.read(self.root)
        self.assertEqual([b["name"] for b in batts], ["BAT1"])
        batts[0]["status"] = "Full"
        self.assertIsNone(battery.time_left(batts[0]))
        self.assertEqual(battery.human_duration(None), "--")
        self.assertEqual(battery.human_duration(5400), "1 h 30 min")


def bat(health=90.0, cycles=100, temp=None):
    return {"name": "BAT1", "health": health, "cycles": cycles, "temp": temp}


class AssessTests(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(battery.assess(bat(95))["level"], disks.OK)
        self.assertEqual(battery.assess(bat(79))["level"], disks.WARN)
        self.assertEqual(battery.assess(bat(59))["level"], disks.CRIT)
        self.assertEqual(battery.assess(bat(90, cycles=1200))["level"], disks.WARN)
        self.assertEqual(battery.assess(bat(90, temp=61))["level"], disks.CRIT)

    def test_unknown_capacity_is_not_an_alarm(self):
        a = battery.assess(bat(None, None))
        self.assertEqual(a["level"], disks.OK)
        self.assertIn("não informa", a["advice"])

    def test_note_for_fast_loss(self):
        self.assertIn("grande", battery.assess(bat(83.4, 54))["note"])
        self.assertEqual(battery.assess(bat(83.4, 400))["note"], "")


class AlertAndHistoryTests(unittest.TestCase):
    def test_only_critical_battery_interrupts(self):
        warn = (bat(75), battery.assess(bat(75)))
        crit = (bat(50), battery.assess(bat(50)))
        self.assertEqual(alerts.evaluate(40, 40, 2000, 2000, [], [warn]), [])
        got = alerts.evaluate(40, 40, 2000, 2000, [], [crit])
        self.assertEqual(got[0][1], "battery:BAT1")

    def test_battery_log_trend_and_fields(self):
        rec = history.Recorder(tempfile.mkdtemp())
        now = 1_800_000_000.0
        b1 = {"name": "BAT1", "health": 84.0, "energy_full": 48.0, "energy_design": 57.0, "cycles": 50}
        b2 = dict(b1, health=83.0, cycles=58)
        self.assertTrue(rec.record_battery([b1], now - 10 * 86400))
        self.assertFalse(rec.record_battery([b1], now - 10 * 86400 + 5))
        self.assertTrue(rec.record_battery([b2], now - 60))
        rec.record({"cpu": 50, "bat": 80, "pw": 22.5}, now - 120)
        q = rec.query("30d", now=now)
        self.assertEqual(q["battery"]["BAT1"]["cycles"], 8)
        self.assertAlmostEqual(q["battery"]["BAT1"]["health"], -1.0)
        self.assertEqual(q["summary"]["pw"]["max"], 22.5)
        self.assertIn("pw_max", q["series"][0])


if __name__ == "__main__":
    unittest.main()
