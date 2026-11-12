import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nitrosense import disks, tray, watcher  # noqa: E402

STATUS = {"sensors": {"cpu_temp": 48, "gpu_temp": 0, "cpu_fan": 2300, "gpu_fan": 2100, "cpu_power": 9.4},
          "state": {"fan": {"mode": "curve"}}, "hw": {"battery_limit_supported": True, "battery_limit": True}}
BAT = {"capacity": 100, "status": "Not charging", "health": 83.4}


class SummaryTests(unittest.TestCase):
    def test_lines(self):
        lines = tray.summary(STATUS, [BAT])
        self.assertEqual(lines["cpu"], "CPU 48 °C · 2300 RPM · 9 W")
        self.assertEqual(lines["gpu"], "GPU suspensa")                  # 0 means asleep, not 0 degrees
        self.assertEqual(lines["battery"], "Bateria 100% (conectada, sem carregar) · saúde 83%")

    def test_awake_gpu_and_fahrenheit(self):
        status = {"sensors": {"cpu_temp": 50, "gpu_temp": 70, "cpu_fan": 0, "gpu_fan": 2500}}
        lines = tray.summary(status, [], "F")
        self.assertEqual(lines["cpu"], "CPU 122 °F")                     # no RPM when the fan reads 0
        self.assertEqual(lines["gpu"], "GPU 158 °F · 2500 RPM")
        self.assertEqual(lines["battery"], "")

    def test_service_down(self):
        lines = tray.summary(None, [])
        self.assertIn("indisponível", lines["cpu"])
        self.assertEqual(tray.icon_for([], reachable=False), "nitrosense-tray-warning")

    def test_icon_follows_the_worst_alert(self):
        self.assertEqual(tray.icon_for([]), "nitrosense-tray")
        self.assertEqual(tray.icon_for([(disks.WARN, "a", "x")]), "nitrosense-tray-warning")
        self.assertEqual(tray.icon_for([(disks.CRIT, "b", "y"), (disks.WARN, "a", "x")]),
                         "nitrosense-tray-critical")

    def test_tooltip_shows_the_first_alert(self):
        lines = tray.summary(STATUS, [BAT])
        text = tray.tooltip(lines, [(disks.CRIT, "temp:CPU", "CPU: temperatura crítica (98 °C).")])
        self.assertTrue(text.startswith("NitroSense\nCPU 48"))
        self.assertTrue(text.endswith("⚠ CPU: temperatura crítica (98 °C)."))
        self.assertNotIn("⚠", tray.tooltip(lines, []))

    def test_unit_preference(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "gui.json")
        self.assertEqual(tray.unit_preference(path), "C")                # no file
        with open(path, "w") as f:
            json.dump({"unit": "F"}, f)
        self.assertEqual(tray.unit_preference(path), "F")
        with open(path, "w") as f:
            f.write("{broken")
        self.assertEqual(tray.unit_preference(path), "C")

    def test_icon_files_exist_for_every_state(self):
        base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "icons")
        for name in tray.ICONS.values():
            self.assertTrue(os.path.exists(os.path.join(base, name + ".svg")), name)

    def test_create_survives_a_missing_toolkit(self):
        real = tray.Tray
        tray.Tray = lambda actions: (_ for _ in ()).throw(ImportError("no XApp"))
        try:
            self.assertIsNone(tray.create({}))
        finally:
            tray.Tray = real


class PollTests(unittest.TestCase):
    def test_poll_returns_alerts_and_status_and_check_stays_compatible(self):
        class Client:
            def request(self, cmd, **kw):
                if cmd == "status":
                    return dict(STATUS, sensors=dict(STATUS["sensors"], cpu_temp=98))
                return {"smart": {}}
        found, status = watcher.poll(Client(), {}, False)
        self.assertIn("temp:CPU", [a[1] for a in found])
        self.assertEqual(status["sensors"]["cpu_temp"], 98)
        self.assertEqual([a[1] for a in watcher.check(Client(), {}, False)], [a[1] for a in found])

    def test_unreachable_service(self):
        class Down:
            def request(self, cmd, **kw):
                raise watcher.DaemonError("down")
        self.assertEqual(watcher.poll(Down(), {}, False), (None, None))
        self.assertIsNone(watcher.check(Down(), {}, False))


if __name__ == "__main__":
    unittest.main()
