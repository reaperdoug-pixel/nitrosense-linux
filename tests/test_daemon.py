"""Daemon request handling against the simulated firmware (no root needed)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_hw import make_daemon  # noqa: E402

from nitrosense import encoders as enc  # noqa: E402
from nitrosense.client import Client, DaemonError  # noqa: E402
from nitrosense import daemon as dmod  # noqa: E402

KB = {"mode": "static", "brightness": 4, "zones_on": [True, False, True, True],
      "zone_colors": ["#FF0000", "#00ff00", "#0000FF", "#FFFFFF"], "effect": "wave",
      "speed": 5, "direction": 1, "effect_color": "#FF0000"}


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.d = make_daemon()
        self.wmi = self.d.ctl.wmi

    def test_status(self):
        r = self.d.handle({"cmd": "status"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["sensors"]["cpu_fan"], 2300)
        self.assertIsNotNone(r["sensors"]["cpu_temp"])

    def test_fan_modes(self):
        self.d.handle({"cmd": "set_fan", "mode": "max"})
        self.assertEqual(self.wmi.calls[-1], ("SetGamingFanBehavior", enc.fan_mode_all("max")))
        self.d.handle({"cmd": "set_fan", "mode": "custom", "cpu_percent": 73, "gpu_auto": True})
        self.assertEqual(self.wmi.calls[-3:], [
            ("SetGamingFanBehavior", enc.fan_custom_behavior(False, True)),
            ("SetGamingFanSpeed", enc.fan_speed("cpu", 70)),
            ("SetGamingFanSpeed", enc.fan_speed("gpu", 50))])
        self.d.handle({"cmd": "set_fan_speed", "fan": "gpu", "percent": 100})
        self.assertEqual(self.wmi.calls[-1], ("SetGamingFanSpeed", enc.fan_speed("gpu", 100)))

    def test_fan_speed_requires_custom(self):
        with self.assertRaises(dmod.ValidationError):
            self.d.handle({"cmd": "set_fan_speed", "fan": "cpu", "percent": 50})

    def test_keyboard_static_sequence(self):
        self.d.handle({"cmd": "set_keyboard", "keyboard": KB})
        names = [c[0] for c in self.wmi.calls]
        self.assertEqual(names, ["SetGamingKBBacklight"] + ["SetGamingRgbKb"] * 4)
        self.assertEqual(self.wmi.calls[0][1], enc.kb_static_backlight(4))
        # zone 2 is switched off -> written black; zone 3 keeps its colour
        self.assertEqual(self.wmi.calls[2][1], enc.kb_zone_color(2, (0, 0, 0)))
        self.assertEqual(self.wmi.calls[3][1], enc.kb_zone_color(3, (0, 0, 255)))

    def test_keyboard_validation(self):
        bad = dict(KB, brightness=9)
        with self.assertRaises(dmod.ValidationError):
            self.d.handle({"cmd": "set_keyboard", "keyboard": bad})
        bad = dict(KB, zone_colors=["red"] * 4)
        with self.assertRaises(dmod.ValidationError):
            self.d.handle({"cmd": "set_keyboard", "keyboard": bad})
        self.assertEqual(self.wmi.calls, [])

    def test_persist_and_reapply(self):
        self.d.handle({"cmd": "set_fan", "mode": "custom", "cpu_percent": 30})
        self.d.handle({"cmd": "set_keyboard", "keyboard": dict(KB, mode="dynamic")})
        self.d.handle({"cmd": "set_coolboost", "on": True})
        state_dir = dmod.STATE_DIR
        d2 = make_daemon(state_dir)
        d2.reapply("test")
        names = [c[0] for c in d2.ctl.wmi.calls]
        self.assertIn("SetGamingKBBacklight", names)
        self.assertEqual(d2.ctl.wmi.calls[0], ("SetGamingFanBehavior",
                                                enc.fan_custom_behavior(False, False)))
        # CoolBoost is only re-applied in Auto mode (NitroSense disables it otherwise)
        self.assertNotIn(("SetFunction", enc.coolboost_set(True)), d2.ctl.wmi.calls)

    def test_unsupported_features_rejected(self):
        # fresh daemon: firmware reported neither Overdrive active nor a readable timeout
        with self.assertRaises(dmod.ValidationError):
            self.d.handle({"cmd": "set_lcd_overdrive", "on": True})
        with self.assertRaises(dmod.ValidationError):
            self.d.handle({"cmd": "set_backlight_timeout", "on": True})
        self.assertEqual(self.wmi.calls, [])

    def test_power_plan(self):
        r = self.d.handle({"cmd": "set_power_plan", "source": "ac", "plan": "performance"})
        self.assertTrue(r["ok"])
        self.assertEqual(self.d.state["power"]["ac"], "performance")

    def test_disks_command_is_cached_and_survives_errors(self):
        calls = []
        real = dmod.disks.read_smart
        self.d._smart_cache = (-1e9, {})  # make_daemon() pre-fills it with fake data
        try:
            dmod.disks.read_smart = lambda: calls.append(1) or {"nvme0": {"percentage_used": 3}}
            r = self.d.handle({"cmd": "disks"})
            self.assertTrue(r["ok"])
            self.assertEqual(r["smart"]["nvme0"]["percentage_used"], 3)
            self.d.handle({"cmd": "disks"})
            self.assertEqual(len(calls), 1)  # second call served from the cache
            self.d._smart_cache = (-1e9, {})

            def boom():
                raise OSError("no device")
            dmod.disks.read_smart = boom
            r = self.d.handle({"cmd": "disks"})
            self.assertEqual((r["ok"], r["smart"]), (True, {}))
        finally:
            dmod.disks.read_smart = real

    def test_battery_limit(self):
        self.assertIs(self.d.hw_battery_limit, False)  # supported, currently off
        self.d.handle({"cmd": "set_battery_limit", "on": True})
        self.assertIs(self.wmi.battery_limit, True)
        self.assertIs(self.d.handle({"cmd": "status"})["hw"]["battery_limit"], True)
        self.assertEqual(self.d.state["battery_limit"], True)
        d2 = make_daemon(dmod.STATE_DIR)
        d2.reapply("test")  # persisted setting is restored after a reboot
        self.assertIs(d2.ctl.wmi.battery_limit, True)

    def test_battery_limit_rejected_by_firmware_or_unsupported(self):
        self.wmi.reject_battery_limit = True
        with self.assertRaises(Exception):
            self.d.handle({"cmd": "set_battery_limit", "on": True})
        self.assertIsNone(self.d.state["battery_limit"])  # nothing persisted
        self.d.hw_battery_limit = None
        with self.assertRaises(dmod.ValidationError):
            self.d.handle({"cmd": "set_battery_limit", "on": True})

    def test_gpu_holders_command_is_cached_and_survives_errors(self):
        calls = []
        real = dmod.procs.nvidia_holders
        self.d._holders_cache = (-1e9, [])
        try:
            dmod.procs.nvidia_holders = lambda: calls.append(1) or [{"pid": 7, "name": "webapps",
                                                                       "devices": ["/dev/nvidia0"]}]
            r = self.d.handle({"cmd": "gpu_holders"})
            self.assertEqual(r["holders"][0]["name"], "webapps")
            self.d.handle({"cmd": "gpu_holders"})
            self.assertEqual(len(calls), 1)  # served from the cache the second time
            self.d._holders_cache = (-1e9, [])

            def boom():
                raise OSError("proc vanished")
            dmod.procs.nvidia_holders = boom
            self.assertEqual(self.d.handle({"cmd": "gpu_holders"}), {"ok": True, "holders": []})
        finally:
            dmod.procs.nvidia_holders = real

    def test_unknown_and_bad_types(self):
        self.assertFalse(self.d.handle({"cmd": "rm -rf"})["ok"])
        with self.assertRaises(dmod.ValidationError):
            self.d.handle({"cmd": "set_coolboost", "on": 1})


class SocketTests(unittest.TestCase):
    def test_roundtrip(self):
        d = make_daemon()
        path = os.path.join(tempfile.mkdtemp(), "s.sock")
        server = dmod.start_server(d, path)
        try:
            c = Client(path)
            self.assertTrue(c.request("status")["ok"])
            c.request("set_fan", mode="max")
            with self.assertRaises(DaemonError):
                c.request("set_fan", mode="turbo")
            self.assertTrue(c.request("status")["ok"])  # connection still usable
        finally:
            server.shutdown()


if __name__ == "__main__":
    unittest.main()
