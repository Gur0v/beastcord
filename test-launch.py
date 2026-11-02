import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from importlib.machinery import SourceFileLoader
spec = importlib.util.spec_from_loader("supervisor", SourceFileLoader("supervisor", str(Path(__file__).with_name("beastcord"))))
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)


class LaunchTests(unittest.TestCase):
    def test_standalone_has_no_comments(self):
        import io, tokenize
        source = Path(__file__).with_name("beastcord").read_text()
        comments = [token.string for token in tokenize.generate_tokens(io.StringIO(source).readline) if token.type == tokenize.COMMENT]
        self.assertEqual(comments, ["#!/usr/bin/env -S python3 -I"])

    def test_graphics_compatibility_is_source_contained(self):
        self.assertIn("drmGetNodeTypeFromFd", s.DRM_COMPAT_SOURCE)
        self.assertIn("drmGetDevices2", s.DRM_COMPAT_SOURCE)
        self.assertNotIn("/tmp/", s.DRM_COMPAT_SOURCE)
        with patch.dict(os.environ, {"BEASTCORD_SOFTWARE_RENDERING": "1"}):
            self.assertIsNone(s.drm_compatibility(Path("/unused")))

    @unittest.skipUnless(sys.platform.startswith("freebsd") and Path("/compat/linux/usr/bin/gcc").is_file(), "Linux compiler required")
    def test_native_graphics_compile_cache_and_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            library = s.drm_compatibility(Path(temporary))
            if library is None:
                self.skipTest("render sysfs is complete")
            self.assertEqual(s.drm_compatibility(Path(temporary)), library)
            probe = "import ctypes as c,os;d=c.CDLL(None);l=c.CDLL('libdrm.so.2');fd=os.open('/dev/dri/renderD128',os.O_RDWR);assert d.drmGetNodeTypeFromFd(fd)==2;" + "\nfor i in range(100):\n p=c.c_void_p();assert d.drmGetDevice2(fd,0,c.byref(p))==0;l.drmFreeDevice(c.byref(p))"
            environment = dict(os.environ, LD_PRELOAD=library)
            subprocess.run(["/compat/linux/usr/bin/python3", "-I", "-c", probe], env=environment, check=True, timeout=10)

    def test_native_ps(self):
        rows = s.processes()
        self.assertIn(os.getpid(), rows)
        self.assertEqual(rows[os.getpid()][0], os.getppid())

    def test_kernel_paths_replace_thread_names(self):
        uid = os.getuid()
        row = f"{uid} 99881 1 Mon Nov 2 20:00:00 2026 VizCompositorTh /managed/versions/v-x/Discord --type=gpu-process\n"
        query = subprocess.CompletedProcess([], 1, "  PID COMM OSREL PATH\n99881 VizCompositorTh 197120 /managed/versions/v-x/Discord\n", "")
        with patch.object(s, "command", return_value=row), patch.object(s.subprocess, "run", return_value=query):
            rows = s.processes()
        self.assertEqual(rows[99881][2], "/managed/versions/v-x/Discord")
        self.assertEqual(set(s.clients(rows, "/managed")), {99881})

    def test_process_selection(self):
        rows = {11: (1, "birth", "/path/Discord", "/path/Discord"),
                12: (11, "birth", "truncated-helper", "helper"),
                13: (1, "birth", "editor", "editor Discord beastcord"),
                14: (1, "birth", "chrome_crashpad_handler", "/managed/versions/v-x/handler")}
        self.assertEqual(set(s.clients(rows, "/managed")), {11, 12, 14})

    def test_pid_reuse_and_window_race(self):
        snapshot = {99999: (1, "old", "Discord", "Discord")}
        with patch.object(s, "processes", return_value={99999: (1, "new", "Discord", "Discord")}), patch.object(s, "windows", return_value=None), patch.object(s.time, "sleep"), patch.object(s.os, "kill") as kill:
            s.terminate(snapshot)
            kill.assert_not_called()
        with patch.object(s, "processes", return_value=snapshot), patch.object(s, "windows", return_value="0x1"), patch.object(s.os, "kill") as kill:
            with self.assertRaises(s.LaunchError):
                s.terminate(snapshot)
            kill.assert_not_called()

    def test_term_then_kill(self):
        snapshot = {99999: (1, "old", "Discord", "Discord")}
        with patch.object(s, "processes", return_value=snapshot), patch.object(s, "windows", return_value=None), patch.object(s.time, "sleep"), patch.object(s.os, "kill") as kill:
            s.terminate(snapshot)
            self.assertEqual(kill.call_args_list[0].args, (99999, signal.SIGTERM))
            self.assertEqual(kill.call_args_list[1].args, (99999, signal.SIGKILL))

    def test_window_query_fail_closed(self):
        with patch.object(s, "command", return_value="missing property"):
            with self.assertRaises(s.LaunchError):
                s.windows(set())
        with patch.object(s, "command", side_effect=["_NET_CLIENT_LIST(WINDOW): 0x123", "WM_CLASS(STRING) = \"discord\""]):
            self.assertEqual(s.windows(set()), "0x123")

    def test_non_ewmh_window_tree_fallback(self):
        tree = "xwininfo: Window id: 0x1 (the root window)\n     1 child:\n     0x123 \"Discord\": (\"discord\" \"discord\")\n"
        with patch.object(s, "command", side_effect=["no such atom", tree, "WM_CLASS(STRING) = \"discord\""]):
            self.assertEqual(s.windows(set()), "0x123")
        with patch.object(s, "command", side_effect=["no such atom", "xwininfo: Window id: 0x1\n 0 children."]):
            self.assertIsNone(s.windows(set()))

    def test_window_enumeration_has_total_budget(self):
        with patch.object(s.time, "monotonic", side_effect=[0, 6]), patch.object(s, "command", return_value="_NET_CLIENT_LIST(WINDOW): 0x123"):
            with self.assertRaisesRegex(s.LaunchError, "budget"):
                s.windows(set())

    def test_monitor_failure_stops_disposable_client(self):
        # Native fixture regression: monitor failure must not turn into an
        # unbounded wait. Only the disposable child session receives signals.
        with tempfile.TemporaryDirectory() as root:
            script = Path(__file__).with_name("beastcord")
            code = "import runpy,sys; m=runpy.run_path(sys.argv[1],run_name=\"fixture\"); g=m[\"run\"].__globals__; g[\"processes\"]=lambda: {}; exec(\"def broken(pids):\\n raise g[\\\"LaunchError\\\"](\\\"missing window enumeration\\\")\"); g[\"windows\"]=broken; sys.exit(m[\"run\"](sys.argv[2],sys.argv[3],sys.executable,[\"-I\",\"-c\",\"import time; time.sleep(60)\"]))"
            child = subprocess.run([sys.executable, "-I", "-c", code, str(script), root, str(Path(root, "log"))], env={**os.environ, "DISPLAY": ":fixture", "BEASTCORD_OZONE_PLATFORM": "x11"}, timeout=10, capture_output=True)
            self.assertEqual(child.returncode, 143, child.stderr)
            self.assertIn(b"stopping this launch", child.stderr)

    def test_native_lockf_compatibility(self):
        with tempfile.TemporaryDirectory() as root:
            lock = str(Path(root, "lock"))
            child = subprocess.Popen(["lockf", "-k", "-t", "0", lock, sys.executable, "-I", "-c", "import sys; print(\"ready\", flush=True); sys.stdin.read()"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            try:
                self.assertEqual(child.stdout.readline(), b"ready\n")
                fd = s.lockfile(lock)
                try:
                    with self.assertRaises(s.LaunchError):
                        s.acquire(fd)
                finally:
                    os.close(fd)
            finally:
                child.stdin.close()
                child.wait(timeout=5)
                child.stdout.close()
            fd = s.lockfile(lock)
            s.acquire(fd)
            os.close(fd)

    def test_native_supervisor_exit_and_rotation(self):
        # Run a disposable Python fixture, never Discord or a real account.
        with tempfile.TemporaryDirectory() as root:
            script = Path(__file__).with_name("beastcord")
            code = "import runpy,sys; m=runpy.run_path(sys.argv[1],run_name=\"fixture\"); m[\"run\"].__globals__[\"processes\"]=lambda: {}; sys.exit(m[\"run\"](sys.argv[2],sys.argv[3],sys.executable,[\"-I\",\"-c\",\"import sys; sys.stdout.write(\\\"x\\\" * 1200000); sys.exit(7)\"]))"
            child = subprocess.run([sys.executable, "-I", "-c", code, str(script), root, str(Path(root, "log"))], env={**os.environ, "BEASTCORD_OZONE_PLATFORM": "wayland"}, timeout=15, capture_output=True)
            self.assertEqual(child.returncode, 7, child.stderr)
            self.assertLessEqual(Path(root, "log").stat().st_size, 512 * 1024)
            self.assertLessEqual(Path(root, "log.1").stat().st_size, 512 * 1024)

    def test_existing_window_and_unsafe_recovery(self):
        snapshot = {99999: (1, "old", "Discord", "Discord")}
        with tempfile.TemporaryDirectory() as root, patch.object(s, "processes", return_value=snapshot), patch.object(s, "windows", return_value="0x123"), patch.object(s.subprocess, "run"), patch.object(s.subprocess, "Popen") as popen, patch.dict(os.environ, {"DISPLAY": ":0", "BEASTCORD_OZONE_PLATFORM": "x11"}):
            self.assertEqual(s.run(root, str(Path(root, "log")), "/unused", []), 0)
            popen.assert_not_called()
        with tempfile.TemporaryDirectory() as root, patch.object(s, "processes", return_value=snapshot), patch.object(s.subprocess, "Popen") as popen, patch.dict(os.environ, {"BEASTCORD_OZONE_PLATFORM": "wayland"}):
            with self.assertRaises(s.LaunchError):
                s.run(root, str(Path(root, "log")), "/unused", [])
            popen.assert_not_called()

    def test_birth_identity_ignores_reparenting(self):
        self.assertEqual(s.identity((1, "birth", "Discord", "args")), s.identity((2, "birth", "Discord", "args")))

    def test_malformed_ps_rejected(self):
        with patch.object(s, "command", return_value="1001 garbage"):
            with self.assertRaises(s.LaunchError):
                s.processes()

    def test_nonregular_locks_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, "lock")
            path.symlink_to(Path(root, "target"))
            with self.assertRaises(OSError):
                s.lockfile(str(path))


if __name__ == "__main__":
    unittest.main()
