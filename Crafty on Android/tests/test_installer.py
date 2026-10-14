"""Offline regression tests. No ADB devices, downloads, or server changes."""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer", ROOT / "crafty_android_installer.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
helper = {"__name__": "guest_helper"}
exec(compile(installer.CONFIG_HELPER, "config-helper.py", "exec"), helper)
runtime = {"__name__": "android_runtime"}
exec(compile(installer.ANDROID_RUNTIME, "android-runtime.py", "exec"), runtime)


class AndroidCompatibilityTests(unittest.TestCase):
    def test_normal_disk_discovery_is_preserved(self):
        expected = ["real partitions"]
        original = Mock(return_value=expected)
        psutil = SimpleNamespace(disk_partitions=original)
        runtime["install_compat"](psutil)
        self.assertIs(psutil.disk_partitions(all=True), expected)
        original.assert_called_once_with(all=True)

    def test_restricted_disk_discovery_falls_back_to_app_storage(self):
        psutil = SimpleNamespace(disk_partitions=Mock(side_effect=PermissionError("Android")))
        runtime["install_compat"](psutil, Path("/example/storage"))
        partitions = psutil.disk_partitions()
        self.assertEqual(len(partitions), 1)
        self.assertEqual(partitions[0].mountpoint, str(Path("/example/storage")))
        self.assertEqual(partitions[0].fstype, "unknown")

    def test_unrelated_errors_are_not_hidden(self):
        psutil = SimpleNamespace(disk_partitions=Mock(side_effect=OSError("I/O error")))
        runtime["install_compat"](psutil)
        with self.assertRaises(OSError):
            psutil.disk_partitions()


class GuestConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "app"
        self.config = self.root / "app/config/config.json"
        self.config.parent.mkdir(parents=True)

    def make_db(self, schema="auto_start INTEGER, type TEXT"):
        path = self.root / "app/config/db/crafty.sqlite"
        path.parent.mkdir()
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.execute(f"CREATE TABLE servers ({schema})")
            db.commit()
        return path

    def read_rows(self, path):
        with contextlib.closing(sqlite3.connect(path)) as db:
            return db.execute("SELECT auto_start, type FROM servers ORDER BY rowid").fetchall()

    def test_preserve_existing_config_and_first_backup(self):
        original = {"https_port": 8443, "custom": "preserve", "show_errors": True}
        self.config.write_text(json.dumps(original))
        helper["configure"](self.root, "9443")
        result = json.loads(self.config.read_text())
        self.assertEqual(result["https_port"], 9443)
        self.assertEqual(result["custom"], "preserve")
        self.assertFalse(result["show_errors"])
        helper["configure"](self.root, "10443")
        backup = self.config.with_name("config.json.before-android")
        self.assertEqual(json.loads(backup.read_text()), original)

    def test_defaults_are_read_without_executing_upstream(self):
        source = self.root / "app/classes/helpers/helpers.py"
        source.parent.mkdir(parents=True)
        source.write_text('raise RuntimeError("must not execute")\nMASTER_CONFIG = {"https_port": 8443, "other": [1, 2]}\n')
        helper["configure"](self.root, 8443)
        self.assertEqual(json.loads(self.config.read_text())["other"], [1, 2])

    def test_unknown_defaults_fail_without_partial_config(self):
        source = self.root / "app/classes/helpers/helpers.py"
        source.parent.mkdir(parents=True)
        source.write_text("renamed_config = {}")
        with self.assertRaises(RuntimeError):
            helper["configure"](self.root, 8443)
        self.assertFalse(self.config.exists())

    def test_policy_changes_only_java_and_backs_up_original(self):
        path = self.make_db()
        original = [(0, "minecraft-java"), (1, "minecraft-java"), (0, "minecraft-bedrock")]
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.executemany("INSERT INTO servers VALUES (?, ?)", original)
            db.commit()
        helper["server_policy"](self.root, "all")
        self.assertEqual(self.read_rows(path), [(1, "minecraft-java"), (1, "minecraft-java"), (0, "minecraft-bedrock")])
        backups = list(path.parent.glob("crafty.before-autostart-*.sqlite"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(self.read_rows(backups[0]), original)
        helper["server_policy"](self.root, "all")
        self.assertEqual(len(list(path.parent.glob("crafty.before-autostart-*.sqlite"))), 1)
        helper["server_policy"](self.root, "none")
        self.assertEqual(self.read_rows(path), [(0, "minecraft-java"), (0, "minecraft-java"), (0, "minecraft-bedrock")])

    def test_keep_and_fresh_install_do_not_create_database(self):
        helper["server_policy"](self.root, "all")
        helper["server_policy"](self.root, "keep")
        self.assertFalse((self.root / "app/config/db").exists())

    def test_unknown_schema_is_not_changed(self):
        path = self.make_db("renamed TEXT")
        with self.assertRaises(RuntimeError):
            helper["server_policy"](self.root, "all")
        self.assertFalse(list(path.parent.glob("crafty.before-autostart-*.sqlite")))

    def test_invalid_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            helper["server_policy"](self.root, "all; rm -rf /")

    def test_stop_does_not_signal_without_pidfile(self):
        with patch.object(helper["os"], "kill") as kill:
            self.assertFalse(helper["stop"](self.root))
        kill.assert_not_called()

    def test_hardware_budget_reserves_android_headroom(self):
        meminfo = "MemTotal: 4194304 kB\nMemAvailable: 262144 kB\nMemFree: 131072 kB\n"
        with patch.object(helper["Path"], "read_text", return_value=meminfo), \
             patch.object(helper["os"], "cpu_count", return_value=8):
            measured = helper["hardware"]()
        self.assertEqual(measured["total_mb"], 4096)
        self.assertEqual(measured["available_mb"], 256)
        self.assertEqual(measured["combined_heap_budget_mb"], 2560)

    def test_max_performance_shares_budget_and_preserves_jar_arguments(self):
        path = self.make_db("server_id TEXT PRIMARY KEY, type TEXT, execution_command TEXT")
        command = "java -Xms2G -Xmx2G -XX:ActiveProcessorCount=2 -jar 'my server.jar' nogui"
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.executemany("INSERT INTO servers VALUES (?, ?, ?)", [
                ("one", "minecraft-java", command), ("two", "minecraft-java", command),
                ("other", "minecraft-bedrock", "bedrock_server")])
            db.commit()
        measured = {"cores": 8, "combined_heap_budget_mb": 3072}
        helper["performance"](self.root, "max", measured)
        with contextlib.closing(sqlite3.connect(path)) as db:
            rows = db.execute("SELECT execution_command FROM servers ORDER BY rowid").fetchall()
        for row in rows[:2]:
            tokens = shlex.split(row[0])
            self.assertIn("-Xms256M", tokens)
            self.assertIn("-Xmx1536M", tokens)
            self.assertIn("-XX:ActiveProcessorCount=8", tokens)
            self.assertEqual(tokens[-3:], ["-jar", "my server.jar", "nogui"])
            self.assertNotIn("-Xmx2G", tokens)
        self.assertEqual(rows[2][0], "bedrock_server")
        self.assertEqual(len(list(path.parent.glob("crafty.before-performance-*.sqlite"))), 1)
        helper["performance"](self.root, "max", measured)
        self.assertEqual(len(list(path.parent.glob("crafty.before-performance-*.sqlite"))), 1)

    def test_max_profile_rejects_custom_commands_without_partial_changes(self):
        path = self.make_db("server_id TEXT PRIMARY KEY, type TEXT, execution_command TEXT")
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.executemany("INSERT INTO servers VALUES (?, ?, ?)", [
                ("one", "minecraft-java", "java -jar server.jar"),
                ("two", "minecraft-java", "bash custom-server.sh")])
            db.commit()
        with self.assertRaises(RuntimeError):
            helper["performance"](self.root, "max", {"cores": 8, "combined_heap_budget_mb": 2048})
        with contextlib.closing(sqlite3.connect(path)) as db:
            command = db.execute("SELECT execution_command FROM servers WHERE server_id='one'").fetchone()[0]
        self.assertEqual(command, "java -jar server.jar")
        self.assertFalse(list(path.parent.glob("crafty.before-performance-*.sqlite")))

    def test_low_ram_profile_preserves_configuration(self):
        path = self.make_db("server_id TEXT PRIMARY KEY, type TEXT, execution_command TEXT")
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.execute("INSERT INTO servers VALUES (?, ?, ?)", ("one", "minecraft-java", "java -jar server.jar"))
            db.commit()
        with self.assertRaises(RuntimeError):
            helper["performance"](self.root, "max", {"cores": 8, "combined_heap_budget_mb": 256})
        self.assertFalse(list(path.parent.glob("crafty.before-performance-*.sqlite")))


class LauncherTests(unittest.TestCase):
    def test_adb_shell_quotes_every_remote_argument(self):
        argv = ("sh", "-c", "echo 'hello'; $(touch BAD)", "/path with spaces")
        with patch.object(installer, "run") as run:
            installer.adb_shell("adb", "serial", *argv)
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["adb", "-s", "serial", "shell"])
        self.assertEqual(shlex.split(command[4]), list(argv))

    def test_export_is_identical_and_does_not_need_adb(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "installer.sh"
            with patch.object(installer, "deploy") as deploy:
                self.assertEqual(installer.main(["--export-shell", str(path)]), 0)
            deploy.assert_not_called()
            self.assertEqual(path.read_bytes(), installer.render_installer().encode())

    def test_committed_shell_matches_python_source(self):
        self.assertEqual((ROOT / "crafty_android_termux.sh").read_bytes(), installer.render_installer().encode())

    def test_invalid_port_fails_before_device_operations(self):
        for port in ("0", "1023", "65536"):
            with self.subTest(port=port), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    installer.main(["--port", port])
                self.assertEqual(error.exception.code, 2)

    def test_no_device_does_not_claim_success(self):
        args = ["--boot", "no", "--server-autostart", "keep", "--start-now", "no", "--performance", "manual"]
        with patch.dict(os.environ, {"PREFIX": "", "devices": ""}), \
             patch.object(installer.shutil, "which", return_value="adb"), \
             patch.object(installer, "run", return_value=subprocess.CompletedProcess([], 0, "List of devices attached\n")), \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                installer.main(args)
        self.assertEqual(error.exception.code, 2)

    def test_failed_device_returns_failure_and_next_device_runs(self):
        args = ["--device", "first", "--device", "second", "--boot", "no", "--server-autostart", "keep", "--start-now", "no", "--performance", "manual"]
        with patch.dict(os.environ, {"PREFIX": ""}), \
             patch.object(installer.shutil, "which", return_value="adb"), \
             patch.object(installer, "deploy", side_effect=[RuntimeError("failure"), None]) as deploy, \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(installer.main(args), 1)
        self.assertEqual(deploy.call_count, 2)

    def test_untrusted_serial_rejected_before_adb(self):
        args = argparse_args()
        with patch.object(installer, "adb_shell") as adb:
            with self.assertRaises(ValueError):
                installer.deploy(args, "serial;touch BAD", [], Path("."))
        adb.assert_not_called()

    def test_apk_integrity_and_source(self):
        data = b"fake-apk-for-offline-test"
        asset = {"name": "termux-app_apt-android-7-arm64-v8a.apk",
                 "browser_download_url": "https://github.com/termux/termux-app/releases/download/test/app.apk",
                 "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
        for mutation, expected_error in [({}, False), ({"digest": None}, True),
                                          ({"digest": "sha256:BAD"}, True),
                                          ({"browser_download_url": "https://evil.example/app.apk"}, True)]:
            release = {"assets": [dict(asset, **mutation)]}
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                responses = [io.BytesIO(json.dumps(release).encode()), io.BytesIO(data)]
                with patch.object(installer.urllib.request, "urlopen", side_effect=responses):
                    if expected_error:
                        with self.assertRaises(RuntimeError):
                            installer.latest_termux_apk("arm64-v8a", Path(temp))
                    else:
                        path = installer.latest_termux_apk("arm64-v8a", Path(temp))
                        self.assertEqual(path.read_bytes(), data)


def argparse_args():
    from argparse import Namespace
    return Namespace(adb="adb", port=8443)


class SyntaxTests(unittest.TestCase):
    def test_embedded_python_is_valid(self):
        ast.parse(installer.CONFIG_HELPER)
        ast.parse(installer.ANDROID_RUNTIME)

    def test_all_shell_payloads_parse(self):
        bash = os.environ.get("BASH_TEST_BIN") or shutil.which("bash")
        if not bash:
            self.skipTest("Bash is not available")
        scripts = {name: getattr(installer, name) for name in
                   ("GUEST_SETUP", "GUEST_RUN", "SERVICE_RUN", "LOG_RUN", "CONTROL", "BOOT")}
        scripts["full_installer"] = installer.render_installer()
        for name, script in scripts.items():
            with self.subTest(name=name):
                result = subprocess.run([bash, "-n"], input=script, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)


class ShellControlTests(unittest.TestCase):
    def setUp(self):
        self.bash = os.environ.get("BASH_TEST_BIN") or shutil.which("bash")
        if not self.bash:
            self.skipTest("Bash is not available")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.base = self.home / "cellhasher-crafty"
        self.base.mkdir()
        self.env = dict(os.environ, HOME=self.home.as_posix(), PREFIX=(self.home / "prefix").as_posix())
        self.env["MSYS_NO_PATHCONV"] = "1"

    def control(self, *args):
        return subprocess.run([self.bash, "-s", "--", *args], input=installer.CONTROL,
                              env=self.env, capture_output=True, text=True, timeout=15)

    def test_boot_toggle_preserves_other_hooks(self):
        boot = self.home / ".termux/boot"
        boot.mkdir(parents=True)
        unrelated = boot / "10-unrelated"
        unrelated.write_text("preserve me")
        (self.base / "boot-template.sh").write_text(installer.BOOT)
        self.assertEqual(self.control("boot", "on").returncode, 0)
        installed = boot / "30-cellhasher-crafty"
        self.assertEqual(installed.read_text(), installer.BOOT)
        self.assertEqual(self.control("boot", "off").returncode, 0)
        self.assertFalse(installed.exists())
        self.assertEqual(unrelated.read_text(), "preserve me")

    def test_policy_validation_does_not_overwrite_previous_setting(self):
        policy = self.base / "server-autostart"
        policy.write_text("keep\n")
        self.assertNotEqual(self.control("server-autostart", "all; touch BAD").returncode, 0)
        self.assertEqual(policy.read_text(), "keep\n")
        self.assertEqual(self.control("server-autostart", "all").returncode, 0)
        self.assertEqual(policy.read_text(), "all\n")

    def test_performance_profile_is_validated(self):
        self.assertNotEqual(self.control("performance", "unsafe").returncode, 0)
        self.assertFalse((self.base / "performance").exists())
        self.assertEqual(self.control("performance", "max").returncode, 0)
        self.assertEqual((self.base / "performance").read_text(), "max\n")


if __name__ == "__main__":
    unittest.main()
