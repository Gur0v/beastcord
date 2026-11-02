import importlib.util
from importlib.machinery import SourceFileLoader
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

source = Path(__file__).with_name("beastcord")
spec = importlib.util.spec_from_loader("manager", SourceFileLoader("manager", str(source)))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"HOME": str(self.root / "home"), "XDG_DATA_HOME": str(self.root / "data"), "XDG_STATE_HOME": str(self.root / "state")})
        self.env.start()
        self.manager = m.Manager()
        self.manager.prepare()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def archive(self, entries=None):
        path = self.root / (str(len(list(self.root.iterdir()))) + ".tgz")
        if entries is None:
            entries = [("Discord/Discord", b"\x7fELF\x02fixture", "file"), ("Discord/resources/app.asar", b"fixture", "file")]
        with tarfile.open(path, "w:gz") as archive:
            for name, data, kind in entries:
                item = tarfile.TarInfo(name)
                item.mode = 0o755
                if kind == "link":
                    item.type = tarfile.SYMTYPE
                    item.linkname = "/tmp/escape"
                    archive.addfile(item)
                else:
                    item.size = len(data)
                    archive.addfile(item, io.BytesIO(data))
        return path

    def test_archive_validation(self):
        self.assertTrue(m.validate_archive(self.archive(), self.root / "good"))
        cases = [[("Discord/../../escape", b"x", "file")], [("Discord/link", b"", "link")], [("Discord/a", b"x", "file")] * 2, [("Discord/Discord", b"script", "file"), ("Discord/resources/app.asar", b"x", "file")]]
        for i, entries in enumerate(cases):
            with self.assertRaises(m.LaunchError):
                m.validate_archive(self.archive(entries), self.root / f"bad{i}")
        self.assertFalse(m.validate_archive(self.archive([("Discord/updater_bootstrap", b"fixture", "file")]), self.root / "bootstrap"))

    def test_native_install_update_rollback(self):
        archive = self.archive()
        def run(*args, ok=True):
            result = subprocess.run([sys.executable, "-I", str(source), *map(str, args)], capture_output=True)
            self.assertEqual(result.returncode == 0, ok, result.stderr.decode())
            return result
        run("--install", "--archive", archive, "--vanilla")
        first, _ = self.manager.version()
        installed = self.manager.bin / "beastcord"
        self.assertEqual(installed.read_bytes(), source.read_bytes())
        run("--update", "--archive", archive)
        second, _ = self.manager.version()
        self.assertNotEqual(first, second)
        self.assertEqual(os.readlink(self.manager.base / "previous"), first)
        run("--rollback")
        self.assertEqual(self.manager.version()[0], first)
        (self.manager.base / "previous").unlink()
        (self.manager.base / "previous").symlink_to("../../outside")
        run("--rollback", ok=False)
        with m.held_lock(self.manager.base / ".lock"):
            run("--update", "--archive", archive, ok=False)
        run("--update", "--archive", archive)
        self.assertTrue(subprocess.run([str(installed), "--help"], capture_output=True).returncode == 0)

    def test_bootstrap_install_retains_metadata(self):
        archive = self.archive([("Discord/updater_bootstrap", b"fixture", "file")])
        def checked(args, **kwargs):
            self.assertNotEqual(Path(kwargs.get("cwd", self.root)).name, "extract")
            if str(args[0]).endswith("updater_bootstrap"):
                profile = Path(args[2])
                app = profile / "app-1.2.3"
                (app / "resources").mkdir(parents=True)
                (app / "resources/app.asar").write_bytes(b"fixture")
                (app / "Discord").write_bytes(b"fixture")
                (app / "Discord").chmod(0o700)
                (app / "modules").mkdir()
                (profile / "installer.db").write_bytes(b"metadata")
                return subprocess.CompletedProcess(args, 0, "app-1.2.3\n")
            self.fail("unexpected external command")
        with patch.object(m, "checked_run", side_effect=checked):
            self.manager.maintain("install", archive, False)
        target, hostdir = self.manager.version()
        self.assertEqual(hostdir, "bootstrap-profile/app-1.2.3")
        self.assertEqual((self.manager.base / target / "bootstrap-profile/installer.db").read_bytes(), b"metadata")

    def test_cli(self):
        self.assertEqual(m.parse_cli([]), ("launch", None, None, []))
        self.assertEqual(m.parse_cli(["--launch", "--disable-gpu"])[3], ["--disable-gpu"])
        self.assertEqual(m.parse_cli(["--install", "--vanilla"])[2], False)
        with self.assertRaises(SystemExit):
            m.parse_cli(["--update", "--archive"])
        with self.assertRaises(m.LaunchError):
            m.parse_cli(["--bogus"])
        with self.assertRaises(m.LaunchError):
            m.parse_cli(["--doctor", "unexpected"])

    def test_bootstrap_layout_and_repair(self):
        version = self.manager.base / "versions/v-fixture"
        app = version / "bootstrap-profile/app-1.2.3"
        (app / "resources").mkdir(parents=True)
        (app / "resources/app.asar").write_bytes(b"fixture")
        (app / "Discord").write_bytes(b"fixture")
        (app / "Discord").chmod(0o700)
        (app / "modules").mkdir()
        (app / "modules/fixture").write_text("retained")
        (version / "bootstrap-profile/installer.db").write_bytes(b"metadata")
        (version / "host-path").write_text("bootstrap-profile/app-1.2.3\n")
        (version / ".managed-by-beastcord").touch()
        (version / "equicord").touch()
        self.manager.activate("versions/v-fixture")
        self.assertEqual(self.manager.version()[1], "bootstrap-profile/app-1.2.3")
        def checked(args, **kwargs):
            if str(args[0]) == "fetch":
                Path(args[4]).write_bytes(b"fixture")
        with patch.object(m, "checked_run", side_effect=checked):
            self.manager.maintain("repair-equicord")
        target, hostdir = self.manager.version()
        repaired = self.manager.base / target
        self.assertEqual((repaired / "bootstrap-profile/installer.db").read_bytes(), b"metadata")
        self.assertEqual((repaired / hostdir / "modules/fixture").read_text(), "retained")
        for bad in ("../outside", "Discord", "bootstrap-profile/app-1.2.3/../../escape"):
            (repaired / "host-path").write_text(bad)
            with self.assertRaises(m.LaunchError):
                m.read_host_path(repaired)

    def test_legacy_installed_upgrade_and_unmanaged_refusal(self):
        self.manager.bin.mkdir(parents=True)
        installed = self.manager.bin / "beastcord"
        installed.write_text("#!/bin/sh\n# Managed by beastcord\n")
        self.manager.install_manager("versions/v-fixture", "Discord")
        self.assertEqual(installed.read_bytes(), source.read_bytes())
        installed.write_text("do not overwrite")
        with self.assertRaises(m.LaunchError):
            self.manager.install_manager("versions/v-fixture", "Discord")
        self.assertEqual(installed.read_text(), "do not overwrite")

    def test_launch_flags_and_environment(self):
        archive = self.archive()
        self.manager.maintain("install", archive, False)
        with patch.object(m, "run", return_value=0) as run, patch.dict(os.environ, {"BEASTCORD_OZONE_PLATFORM": "x11", "BEASTCORD_SOFTWARE_RENDERING": "0", "NODE_OPTIONS": "bad"}):
            self.assertEqual(self.manager.launch(["discord://fixture"]), 0)
            args = run.call_args.args[3]
            for flag in ("--use-gl=angle", "--use-angle=gl", "--disable-features=Vulkan", "discord://fixture"):
                self.assertIn(flag, args)
            self.assertNotIn("--disable-gpu", args)
            self.assertNotIn("NODE_OPTIONS", os.environ)

    def test_failed_update_keeps_current_and_cleans_stage(self):
        self.manager.maintain("install", self.archive(), False)
        old = self.manager.version()[0]
        before = set((self.manager.base / "versions").iterdir())
        with self.assertRaises(m.LaunchError):
            self.manager.maintain("update", self.archive([("../evil", b"x", "file")]), False)
        self.assertEqual(self.manager.version()[0], old)
        self.assertEqual(set((self.manager.base / "versions").iterdir()), before)


if __name__ == "__main__":
    unittest.main()
