import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fake_hw import make_daemon  # noqa: E402

from nitrosense import alerts, disks, history, sata  # noqa: E402


def attr(i, name, value, raw, worst=100, thresh=0, when_failed=""):
    return {"id": i, "name": name, "value": value, "worst": worst, "thresh": thresh,
            "when_failed": when_failed, "raw": {"value": raw, "string": str(raw)}}


def smartctl_json(rpm=5400, passed=True, hours=1730, temp=32, attrs=(), tests=None, **extra):
    """Shaped like `smartctl -j -a` output (see the structure of real smartctl captures)."""
    base = [attr(1, "Raw_Read_Error_Rate", 100, 0, thresh=1), attr(5, "Reallocated_Sector_Ct", 100, 0, thresh=1),
            attr(197, "Current_Pending_Sector", 100, 0), attr(198, "Offline_Uncorrectable", 100, 0),
            attr(199, "UDMA_CRC_Error_Count", 100, 0)]
    table = [a for a in base if a["id"] not in {x["id"] for x in attrs}] + list(attrs)
    data = {"json_format_version": [1, 0], "smartctl": {"exit_status": 0},
            "model_name": "WDC WD10SPZX", "rotation_rate": rpm, "smart_status": {"passed": passed},
            "ata_smart_attributes": {"revision": 16, "table": table},
            "power_on_time": {"hours": hours}, "power_cycle_count": 9,
            "temperature": {"current": temp},
            "ata_smart_error_log": {"summary": {"revision": 1, "count": 0}},
            "ata_smart_self_test_log": {"standard": {"table": tests if tests is not None else [
                {"type": {"value": 1, "string": "Short offline"},
                 "status": {"value": 0, "string": "Completed without error", "passed": True},
                 "lifetime_hours": hours - 20}]}}}
    data.update(extra)
    return data


HDD = {"name": "sda", "model": "WDC WD10SPZX", "rotational": True, "transport": "sata", "mounts": [],
       "temp": 32.0, "temp_warn": 60.0}
SSD = {"name": "sdb", "model": "Samsung SSD 860", "rotational": False, "transport": "sata", "mounts": [],
       "temp": 35.0, "temp_warn": None}


def put(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f"{value}\n")


class ListDevicesTests(unittest.TestCase):
    def test_internal_disks_only(self):
        root = tempfile.mkdtemp()
        for name, size, removable, rot, model in (("sda", 1_953_525_168, 0, 1, "WDC WD10SPZX-21Z"),
                                                  ("sdb", 500_118_192, 0, 0, "Samsung SSD 860"),
                                                  ("sdc", 62_000_000, 1, 0, "USB Flash"),
                                                  ("sdd", 0, 0, 0, "Empty reader")):
            put(f"{root}/{name}/size", size)
            put(f"{root}/{name}/removable", removable)
            put(f"{root}/{name}/queue/rotational", rot)
            put(f"{root}/{name}/device/model", model)
            put(f"{root}/{name}/device/vendor", "ATA     ")
            put(f"{root}/{name}/device/rev", "1A01")
        os.makedirs(f"{root}/nvme0n1")
        os.makedirs(f"{root}/loop0")
        found = sata.list_devices(root)
        self.assertEqual([d["name"] for d in found], ["sda", "sdb"])
        self.assertEqual((found[0]["model"], found[0]["rotational"], found[0]["size"]),
                         ("WDC WD10SPZX-21Z", True, 1_953_525_168 * 512))
        self.assertEqual(found[1]["rotational"], False)

    def test_drivetemp_lookup(self):
        root = tempfile.mkdtemp()
        scsi = os.path.join(root, "devices", "target0", "0:0:0:0")
        os.makedirs(os.path.join(scsi, "block", "sda"))
        hw = os.path.join(root, "hwmon", "hwmon3")
        os.makedirs(hw)
        put(os.path.join(hw, "name"), "drivetemp")
        put(os.path.join(hw, "temp1_input"), 38000)
        os.symlink(scsi, os.path.join(hw, "device"))
        self.assertEqual(sata.drivetemp("sda", os.path.join(root, "hwmon")), 38.0)
        self.assertIsNone(sata.drivetemp("sdb", os.path.join(root, "hwmon")))


class ParseTests(unittest.TestCase):
    def test_healthy_hdd(self):
        p = sata.parse(smartctl_json())
        self.assertEqual((p["ata"], p["passed"], p["temperature_c"], p["power_on_hours"], p["rotation_rpm"]),
                         (True, True, 32, 1730, 5400))
        self.assertEqual((p["reallocated"], p["pending"], p["crc_errors"]), (0, 0, 0))
        self.assertIsNone(p["percentage_used"])
        self.assertTrue(p["last_self_test"]["passed"])

    def test_ssd_wear_from_the_remaining_life_attribute(self):
        p = sata.parse(smartctl_json(rpm=0, attrs=[attr(177, "Wear_Leveling_Count", 92, 120)]))
        self.assertEqual((p["rotation_rpm"], p["percentage_used"]), (None, 8))
        p = sata.parse(smartctl_json(rpm=0, attrs=[attr(202, "Percent_Lifetime_Remain", 12, 88)]))
        self.assertEqual(p["percentage_used"], 88)

    def test_failing_attributes_and_temperature_fallback(self):
        data = smartctl_json(attrs=[attr(5, "Reallocated_Sector_Ct", 1, 900, thresh=36, when_failed="FAILING_NOW"),
                                    attr(194, "Temperature_Celsius", 30, 0x1F0029)])
        del data["temperature"]
        p = sata.parse(data)
        self.assertEqual((p["failing"], p["reallocated"], p["temperature_c"]),
                         (["Reallocated_Sector_Ct"], 900, 0x29))  # low byte of the raw value

    def test_missing_pieces_do_not_crash(self):
        p = sata.parse({})
        self.assertIsNone(p["passed"])
        self.assertEqual(p["failing"], [])


class AssessTests(unittest.TestCase):
    def level(self, disk, **kw):
        return disks.assess(disk, sata.parse(smartctl_json(**kw)))["level"]

    def test_healthy(self):
        a = disks.assess(HDD, sata.parse(smartctl_json()))
        self.assertEqual((a["level"], a["reasons"]), (disks.OK, []))
        self.assertIn("1.7", a["life"].replace(",", "."))  # about 0.2 years
        self.assertIn("4 a 6 anos", a["life"])

    def test_failed_smart_status_is_critical(self):
        self.assertEqual(self.level(HDD, passed=False), disks.CRIT)

    def test_bad_sectors(self):
        self.assertEqual(self.level(HDD, attrs=[attr(5, "Reallocated_Sector_Ct", 99, 3)]), disks.WARN)
        self.assertEqual(self.level(HDD, attrs=[attr(5, "Reallocated_Sector_Ct", 50, 120)]), disks.CRIT)
        self.assertEqual(self.level(HDD, attrs=[attr(197, "Current_Pending_Sector", 99, 2)]), disks.WARN)
        self.assertEqual(self.level(HDD, attrs=[attr(197, "Current_Pending_Sector", 80, 12)]), disks.CRIT)
        self.assertEqual(self.level(HDD, attrs=[attr(199, "UDMA_CRC_Error_Count", 99, 4)]), disks.WARN)

    def test_old_hdd_and_failed_self_test(self):
        self.assertEqual(self.level(HDD, hours=44000), disks.WARN)
        self.assertEqual(self.level(SSD, hours=44000), disks.OK)             # age only matters for spinning disks
        bad = [{"type": {"string": "Extended offline"},
                "status": {"string": "Completed: read failure", "passed": False}, "lifetime_hours": 1}]
        a = disks.assess(HDD, sata.parse(smartctl_json(tests=bad)))
        self.assertEqual(a["level"], disks.WARN)
        self.assertIn("Extended offline", a["reasons"][0][1])

    def test_ssd_wear(self):
        self.assertEqual(self.level(SSD, rpm=0, attrs=[attr(177, "Wear_Leveling_Count", 15, 1)]), disks.WARN)
        self.assertEqual(self.level(SSD, rpm=0, attrs=[attr(177, "Wear_Leveling_Count", 0, 1)]), disks.CRIT)

    def test_temperature_limits_differ_for_hdd_and_ssd(self):
        hot = dict(HDD, temp=55.0)
        self.assertEqual(disks.assess(hot, sata.parse(smartctl_json()))["level"], disks.WARN)  # HDD: 50 C
        self.assertEqual(disks.assess(dict(SSD, temp=55.0), sata.parse(smartctl_json(rpm=0)))["level"], disks.OK)
        self.assertEqual(disks.assess(dict(HDD, temp=61.0), None)["level"], disks.CRIT)

    def test_alert_text_names_the_disk(self):
        a = disks.assess(HDD, sata.parse(smartctl_json(passed=False)))
        found = alerts.evaluate(40, 40, 2000, 2000, [(HDD, a)])
        self.assertEqual(found[0][1], "disk:sda")
        self.assertIn("WDC WD10SPZX", found[0][2])


class FakeRun:
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        out = self.results.pop(0)
        return types.SimpleNamespace(stdout=out[0], stderr=out[1] if len(out) > 1 else "", returncode=0)


class ReadTests(unittest.TestCase):
    def test_reads_with_standby_flag(self):
        run = FakeRun((json.dumps(smartctl_json()),))
        out = sata.read(HDD, run=run, smartctl="/usr/sbin/smartctl")
        self.assertTrue(out["ata"])
        self.assertEqual(run.calls[0], ["/usr/sbin/smartctl", "-j", "-a", "-n", "standby", "/dev/sda"])

    def test_sleeping_disk_is_not_woken_or_misread(self):
        run = FakeRun(("", "Device is in STANDBY mode, exit(2)\n"))
        self.assertEqual(sata.read(HDD, run=run, smartctl="x"), {"ata": True, "standby": True})

    def test_missing_tool_and_errors(self):
        real = sata.shutil.which
        sata.shutil.which = lambda _n: None
        try:
            self.assertTrue(sata.read(HDD)["missing_tool"])
        finally:
            sata.shutil.which = real
        self.assertIn("error", sata.read(HDD, run=FakeRun(("not json", "Smartctl open device: failed")), smartctl="x"))
        nodata = json.dumps({"smartctl": {"messages": [{"string": "SMART support is: Unavailable"}]}})
        self.assertIn("Unavailable", sata.read(HDD, run=FakeRun((nodata,)), smartctl="x")["error"])

    def test_usb_bridge_gets_a_sat_retry(self):
        usb = dict(HDD, transport="usb")
        run = FakeRun((json.dumps({"smartctl": {"messages": []}}),), (json.dumps(smartctl_json()),))
        out = sata.read(usb, run=run, smartctl="x")
        self.assertTrue(out["ata"])
        self.assertIn("sat", run.calls[1])


class DaemonTests(unittest.TestCase):
    def setUp(self):
        self.d = make_daemon()
        self.real = sata.read_all

    def tearDown(self):
        sata.read_all = self.real

    def test_sata_results_join_the_disks_command_and_standby_keeps_the_last_data(self):
        sata.read_all = lambda: {"sda": sata.parse(smartctl_json(temp=33))}
        self.d.sata_refresh()
        smart = self.d.handle({"cmd": "disks"})["smart"]
        self.assertEqual((smart["sda"]["temperature_c"], "nvme0" in smart), (33, True))
        sata.read_all = lambda: {"sda": {"ata": True, "standby": True}}
        self.d.sata_refresh()
        sda = self.d.handle({"cmd": "disks"})["smart"]["sda"]
        self.assertEqual((sda["temperature_c"], sda["standby"]), (33, True))   # last data, flagged

    def test_a_failing_scan_keeps_the_previous_data(self):
        sata.read_all = lambda: {"sda": sata.parse(smartctl_json())}
        self.d.sata_refresh()

        def boom():
            raise OSError("no /sys/block")
        sata.read_all = boom
        self.d.sata_refresh()
        self.assertIn("sda", self.d.smart())

    def test_history_ignores_ata_disks(self):
        rec = history.Recorder(tempfile.mkdtemp())
        smart = {"sda": sata.parse(smartctl_json(rpm=0, attrs=[attr(177, "Wear_Leveling_Count", 90, 1)]))}
        self.assertFalse(rec.record_smart(smart))   # nothing NVMe to log, and no KeyError

    def test_basic_lists_sata_disks_with_their_limits(self):
        real = disks.sata.list_devices
        disks.sata.list_devices = lambda: [{"name": "sda", "model": "WDC", "firmware": "1", "size": 10,
                                            "rotational": True, "transport": "sata"}]
        try:
            found = [d for d in disks.basic() if d["kind"] == "sata"]
        finally:
            disks.sata.list_devices = real
        self.assertEqual((found[0]["name"], found[0]["temp_warn"], found[0]["rotational"]), ("sda", 60.0, True))


if __name__ == "__main__":
    unittest.main()
