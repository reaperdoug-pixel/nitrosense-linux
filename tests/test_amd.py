import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nitrosense import rapl, sysmon, throttle  # noqa: E402


def put(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(f"{value}\n")


def pci(root, name, vendor, boot_vga=None, status="active"):
    d = os.path.join(root, name)
    put(os.path.join(d, "vendor"), vendor)
    put(os.path.join(d, "class"), "0x030000")
    put(os.path.join(d, "power", "runtime_status"), status)
    if boot_vga is not None:
        put(os.path.join(d, "boot_vga"), boot_vga)
    return d


def amdgpu(dev, busy=37, temp=61000, power=18_500_000, freq=1_800_000_000):
    put(os.path.join(dev, "gpu_busy_percent"), busy)
    hw = os.path.join(dev, "hwmon", "hwmon3")
    put(os.path.join(hw, "temp1_input"), temp)
    put(os.path.join(hw, "power1_average"), power)
    put(os.path.join(hw, "freq1_input"), freq)
    put(os.path.join(dev, "pp_dpm_sclk"), "0: 400Mhz\n1: 1200Mhz\n2: 2400Mhz *\n")


class AmdGpu(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_amd_dgpu_is_read_from_sysfs(self):
        pci(self.root, "0000:00:08.1", "0x1002", boot_vga="1")          # APU graphics
        dgpu = pci(self.root, "0000:03:00.0", "0x1002", boot_vga="0")   # discrete card
        amdgpu(dgpu)
        mon = sysmon.GpuMonitor(self.root)
        self.assertTrue(mon.present)
        self.assertEqual(mon.vendor, "amd")
        self.assertEqual(mon.pci, [dgpu])
        self.assertEqual(mon.sample(), (False, 37.0, 61))
        self.assertEqual((mon.power, mon.clock, mon.clock_max, mon.reasons), (18.5, 1800, 2400, None))

    def test_apu_only_machine_uses_the_integrated_gpu(self):
        igpu = pci(self.root, "0000:05:00.0", "0x1002", boot_vga="1")
        amdgpu(igpu, busy=5)
        mon = sysmon.GpuMonitor(self.root)
        self.assertEqual(mon.pci, [igpu])
        self.assertEqual(mon.sample()[1], 5.0)

    def test_sleeping_amd_gpu_is_idle_and_not_read(self):
        dgpu = pci(self.root, "0000:03:00.0", "0x1002", boot_vga="0", status="suspended")
        amdgpu(dgpu)
        mon = sysmon.GpuMonitor(self.root)
        self.assertFalse(mon.awake())
        self.assertEqual(mon.sample(), (True, None, None))

    def test_nvidia_wins_when_both_are_present(self):
        pci(self.root, "0000:00:08.1", "0x1002", boot_vga="1")
        nv = pci(self.root, "0000:01:00.0", "0x10de", boot_vga="0")
        mon = sysmon.GpuMonitor(self.root)
        self.assertEqual((mon.vendor, mon.pci), ("nvidia", [nv]))

    def test_no_gpu_at_all(self):
        mon = sysmon.GpuMonitor(self.root)
        self.assertFalse(mon.present)
        self.assertEqual(mon.sample(), (True, None, None))

    def test_missing_files_give_none_not_errors(self):
        dgpu = pci(self.root, "0000:03:00.0", "0x1002", boot_vga="0")
        mon = sysmon.GpuMonitor(self.root)
        self.assertEqual(mon.sample(), (False, None, None))
        self.assertIsNone(mon.power)
        self.assertTrue(dgpu)


class AmdCpu(unittest.TestCase):
    def test_k10temp_gives_tjmax(self):
        root = tempfile.mkdtemp()
        put(os.path.join(root, "hwmon0", "name"), "k10temp")
        put(os.path.join(root, "hwmon0", "temp1_crit"), 100000)
        thr = throttle.CpuThrottle(cpu_root=root, thermal_root=root, powercap=root, hwmon=root)
        self.assertEqual(thr.tj_max, 100.0)

    def test_amd_uses_the_same_rapl_powercap_zone(self):
        root = tempfile.mkdtemp()
        zone = os.path.join(root, "intel-rapl:0")   # the kernel keeps this name on Zen
        put(os.path.join(zone, "name"), "package-0")
        put(os.path.join(zone, "energy_uj"), 1_000_000)
        put(os.path.join(zone, "max_energy_range_uj"), 65_532_610_987)
        t = [0.0]
        r = rapl.Rapl(root, clock=lambda: t[0])
        self.assertEqual(r.sample(), {})
        put(os.path.join(zone, "energy_uj"), 16_000_000)
        t[0] = 1.0
        self.assertEqual(r.sample(), {"cpu": 15.0})


if __name__ == "__main__":
    unittest.main()
