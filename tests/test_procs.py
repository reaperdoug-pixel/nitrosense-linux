import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nitrosense import procs  # noqa: E402

PAGE = procs.PAGE


def make_proc(root, pid, comm, ticks=0, resident=0, shared=0, cmdline=(), fds=()):
    d = os.path.join(root, str(pid))
    os.makedirs(os.path.join(d, "fd"))
    # fields after "(comm)": state ppid ... utime(idx 11) stime(idx 12) ...
    fields = ["S", "1"] + ["0"] * 9 + [str(ticks), "0"] + ["0"] * 20
    with open(os.path.join(d, "stat"), "w") as f:
        f.write(f"{pid} ({comm}) " + " ".join(fields) + "\n")
    with open(os.path.join(d, "statm"), "w") as f:
        f.write(f"1000 {resident} {shared} 0 0 0 0\n")
    with open(os.path.join(d, "cmdline"), "wb") as f:
        f.write(b"\0".join(a.encode() for a in cmdline) + b"\0")
    for i, target in enumerate(fds):
        os.symlink(target, os.path.join(d, "fd", str(i)))


def set_ticks(root, pid, comm, ticks):
    path = os.path.join(root, str(pid), "stat")
    fields = ["S", "1"] + ["0"] * 9 + [str(ticks), "0"] + ["0"] * 20
    with open(path, "w") as f:
        f.write(f"{pid} ({comm}) " + " ".join(fields) + "\n")


class Clock:
    t = 10.0

    def __call__(self):
        return self.t


class SamplerTests(unittest.TestCase):
    def test_cpu_groups_by_program_and_machine_share(self):
        root, clock = tempfile.mkdtemp(), Clock()
        make_proc(root, 10, "brave", ticks=0, resident=500, shared=100)
        make_proc(root, 11, "brave", ticks=0, resident=300, shared=100)
        make_proc(root, 12, "idle", ticks=0, resident=10, shared=10)
        s = procs.ProcessSampler(root, clock, ncpu=4)
        first = s.sample()
        self.assertFalse(first["ready"])
        self.assertEqual(first["cpu"], [])  # no baseline yet
        clock.t += 2.0
        set_ticks(root, 10, "brave", 100)  # 1 s of CPU in 2 s
        set_ticks(root, 11, "brave", 50)   # 0.5 s
        r = s.sample()
        self.assertTrue(r["ready"])
        name, pct, count = r["cpu"][0]
        self.assertEqual((name, count), ("brave", 2))
        self.assertAlmostEqual(pct, (1.5 / 2 / 4) * 100, places=1)  # 18.75 % of 4 CPUs
        self.assertNotIn("idle", [n for n, _v, _c in r["cpu"]])

    def test_memory_is_private_resident_pages(self):
        root = tempfile.mkdtemp()
        make_proc(root, 10, "app", resident=500, shared=100)
        make_proc(root, 11, "app", resident=300, shared=100)
        make_proc(root, 12, "shared-only", resident=10, shared=10)
        r = procs.ProcessSampler(root, Clock()).sample()
        self.assertEqual(r["mem"], [("app", (400 + 200) * PAGE, 2)])

    def test_wrapper_names_and_odd_comm(self):
        self.assertEqual(procs.app_name("python3", ["python3", "-I", "/opt/x/bin/nitrosense"]), "nitrosense")
        self.assertEqual(procs.app_name("python3", ["python3", "-c", "import os; ..."]), "python3 -c")
        self.assertEqual(procs.app_name("python3", ["python3", "-m", "http.server"]), "http.server")
        self.assertEqual(procs.app_name("node", ["node", "/usr/lib/app/server.js"]), "server.js")
        self.assertEqual(procs.app_name("firefox", ["firefox", "-new-tab"]), "firefox")
        root = tempfile.mkdtemp()
        d = os.path.join(root, "7")
        os.makedirs(d)
        with open(os.path.join(d, "stat"), "w") as f:  # comm with spaces and a parenthesis
            f.write("7 (Web (Content) x) S 1 " + " ".join(["0"] * 30) + "\n")
        self.assertEqual(procs.ProcessSampler(root, Clock())._stat("7")[0], "Web (Content) x")

    def test_vanished_and_garbage_entries(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "99"))  # no stat file: the process ended
        os.makedirs(os.path.join(root, "notapid"))
        self.assertEqual(procs.ProcessSampler(root, Clock()).sample()["mem"], [])


class GpuTests(unittest.TestCase):
    PMON = """# gpu         pid   type     sm    mem    enc    dec    jpg    ofa     fb   ccpm    command
# Idx           #    C/G      %      %      %      %      %      %     MB     MB    name
    0       1137     G      -      -      -      -      -      -      4      0    Xorg
    0      12343     G     35     12      -      -      -      -    210      0    web apps
    0       4000     C      -      -      -      -      -      -    900      0    python3
"""

    def test_parse_pmon(self):
        rows = procs.parse_pmon(self.PMON)
        self.assertEqual([r["name"] for r in rows], ["web apps", "python3", "Xorg"])
        self.assertEqual((rows[0]["sm"], rows[0]["mem_mb"], rows[0]["type"]), (35, 210, "G"))
        self.assertEqual(procs.parse_pmon("No devices were found\n"), [])

    def test_holders_of_nvidia_devices(self):
        root = tempfile.mkdtemp()
        make_proc(root, 20, "webapps", fds=["/dev/nvidiactl", "/dev/nvidia0", "/tmp/x"])
        make_proc(root, 21, "Xorg", fds=["/dev/nvidiactl"])
        make_proc(root, 22, "quiet", fds=["/dev/null"])
        found = procs.nvidia_holders(root)
        self.assertEqual([(h["pid"], h["name"]) for h in found], [(20, "webapps"), (21, "Xorg")])
        self.assertIn("/dev/nvidia0", found[0]["devices"])


if __name__ == "__main__":
    unittest.main()
