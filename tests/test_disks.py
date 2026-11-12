import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nitrosense import alerts, disks  # noqa: E402


def smart_log(critical=0, kelvin=307, spare=100, threshold=10, used=0, hours=1000,
              media_errors=0, written_units=2_000_000, sensors=(307, 310)) -> bytes:
    b = bytearray(512)
    b[0] = critical
    b[1:3] = kelvin.to_bytes(2, "little")
    b[3], b[4], b[5] = spare, threshold, used
    b[48:64] = written_units.to_bytes(16, "little")
    b[128:144] = hours.to_bytes(16, "little")
    b[160:176] = media_errors.to_bytes(16, "little")
    for i, k in enumerate(sensors):
        b[200 + 2 * i:202 + 2 * i] = k.to_bytes(2, "little")
    return bytes(b)


def disk(temp=34.0, warn=85.85, mounts=()):
    return {"name": "nvme0", "model": "TestDisk", "temp": temp, "temp_warn": warn,
            "temp_crit": 92.85, "mounts": list(mounts)}


class ParseTests(unittest.TestCase):
    def test_fields(self):
        s = disks.parse_smart_log(smart_log(used=7, hours=1234, media_errors=2))
        self.assertEqual(s["temperature_c"], 34)
        self.assertEqual(s["percentage_used"], 7)
        self.assertEqual(s["power_on_hours"], 1234)
        self.assertEqual(s["media_errors"], 2)
        self.assertEqual(s["bytes_written"], 2_000_000 * 512_000)
        self.assertEqual(s["sensors_c"], [34, 37])

    def test_short_buffer(self):
        with self.assertRaises(ValueError):
            disks.parse_smart_log(b"\x00" * 10)


class AssessTests(unittest.TestCase):
    def level(self, d, **kw):
        return disks.assess(d, disks.parse_smart_log(smart_log(**kw)))["level"]

    def test_healthy(self):
        a = disks.assess(disk(), disks.parse_smart_log(smart_log()))
        self.assertEqual(a["level"], disks.OK)
        self.assertEqual(a["reasons"], [])

    def test_wear_levels(self):
        self.assertEqual(self.level(disk(), used=79), disks.OK)
        self.assertEqual(self.level(disk(), used=80), disks.WARN)
        self.assertEqual(self.level(disk(), used=100), disks.CRIT)

    def test_spare_and_critical_warning(self):
        self.assertEqual(self.level(disk(), spare=40), disks.WARN)
        self.assertEqual(self.level(disk(), spare=10, threshold=10), disks.CRIT)
        self.assertEqual(self.level(disk(), critical=0x01), disks.CRIT)
        self.assertEqual(self.level(disk(), critical=0x08), disks.CRIT)

    def test_media_errors(self):
        self.assertEqual(self.level(disk(), media_errors=1), disks.WARN)
        self.assertEqual(self.level(disk(), media_errors=10), disks.CRIT)

    def test_temperature(self):
        self.assertEqual(self.level(disk(temp=70)), disks.OK)
        self.assertEqual(self.level(disk(temp=76)), disks.WARN)
        self.assertEqual(self.level(disk(temp=86)), disks.CRIT)

    def test_unset_temperature_limit_falls_back(self):
        self.assertEqual(self.level(disk(temp=65, warn=65261.85)), disks.WARN)

    def test_filesystem_full(self):
        m = {"mount": "/", "total": 100, "used": 91}
        self.assertEqual(self.level(disk(mounts=[m])), disks.WARN)
        m = {"mount": "/", "total": 100, "used": 96}
        self.assertEqual(self.level(disk(mounts=[m])), disks.CRIT)

    def test_without_smart_uses_temperature_only(self):
        self.assertEqual(disks.assess(disk(temp=90), None)["level"], disks.CRIT)
        self.assertEqual(disks.assess(disk(), {"error": "x"})["level"], disks.OK)

    def test_life_estimate(self):
        self.assertIn("Sem desgaste", disks.life_estimate({"percentage_used": 0, "power_on_hours": 5000}))
        self.assertIn("ano", disks.life_estimate({"percentage_used": 10, "power_on_hours": 8760}))
        self.assertIn("esgotada", disks.life_estimate({"percentage_used": 100, "power_on_hours": 5}))

    def test_human_bytes(self):
        self.assertEqual(disks.human_bytes(512), "512 B")
        self.assertEqual(disks.human_bytes(1_500_000_000), "1,5 GB")


class AlertTests(unittest.TestCase):
    def test_quiet_system(self):
        self.assertEqual(alerts.evaluate(50, 40, 2000, 2000, []), [])

    def test_temperatures(self):
        got = alerts.evaluate(91, 93, 2000, 2000, [])
        self.assertEqual([a[0] for a in got], [disks.CRIT, disks.WARN])
        self.assertEqual(got[0][1], "temp:GPU")

    def test_missing_values_are_ignored(self):
        self.assertEqual(alerts.evaluate(None, None, None, None, []), [])

    def test_stopped_fan_only_when_hot(self):
        self.assertEqual(alerts.evaluate(50, None, 0, None, []), [])
        got = alerts.evaluate(80, None, 0, None, [])
        self.assertEqual(got[0][1], "fan:CPU")

    def test_disk_alert(self):
        d = disk(temp=90)
        a = disks.assess(d, None)
        got = alerts.evaluate(40, 40, 2000, 2000, [(d, a)])
        self.assertEqual(got[0][1], "disk:nvme0")
        self.assertIn("TestDisk", got[0][2])


if __name__ == "__main__":
    unittest.main()
