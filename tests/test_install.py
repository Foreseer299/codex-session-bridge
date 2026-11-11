"""Installer tests use synthetic files and a local socket, never real profiles."""

import contextlib
import difflib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location("bridge_installer", Path(__file__).resolve().parents[1] / "scripts/install.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cbi-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "bridge"
        self.root.mkdir()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(installer, "ROOT", self.root).start()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.executable(self.bin / "node", '#!/bin/sh\nif [ "$1" = "--version" ]; then echo v24.0.0; fi\n')
        self.executable(self.bin / "paseo", "#!/bin/sh\nexit 0\n")
        mock.patch.dict(os.environ, {"PATH": str(self.bin) + os.pathsep + os.environ["PATH"]}).start()
        self.paseo = self.base / "paseo"
        self.paseo.mkdir()
        self.codex = self.base / "codex"
        self.codex.mkdir()
        daemon = self.codex / "packages/app-server-daemon/current/bin/codex"
        daemon.parent.mkdir(parents=True)
        self.executable(daemon, "#!/bin/sh\necho codex-cli 0.167.1\n")
        control = self.codex / "app-server-control"
        control.mkdir()
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(str(control / "app-server-control.sock"))
        self.addCleanup(self.sock.close)
        (self.root / "bin").mkdir()
        (self.root / "bin/bridge.cjs").write_text("// synthetic bridge\n")
        self.package = self.base / "package"
        self.package.mkdir()
        self.package_json = self.package / "package.json"
        self.package_json.write_text(json.dumps({"version": "0.15.3"}))
        self.original = b"const value = 'original';\n"
        self.updated = b"const value = 'patched';\n"
        self.target = self.package / "example.js"
        self.target.write_bytes(self.original)
        self.target.chmod(0o640)
        self.patches = self.root / "patches"
        self.patches.mkdir()
        patch = "".join(difflib.unified_diff(self.original.decode().splitlines(True), self.updated.decode().splitlines(True), fromfile="a/example.js", tofile="b/example.js"))
        (self.patches / "example.patch").write_text(patch)
        self.manifest = {"version": "0.15.3", "files": [{"path": "example.js", "patch": "example.patch", "before_sha256": installer.digest(self.original), "after_sha256": installer.digest(self.updated)}]}
        (self.patches / "manifest.json").write_text(json.dumps(self.manifest))
        self.config_path = self.paseo / "config.json"
        self.config = {"version": 1, "unrelated": {"keep": True}, "agents": {"providers": {"codex": {"options": {"approval_policy": "on-request", "sandbox_mode": "workspace-write"}, "enabled": True}, "other": {"enabled": False}}}}
        self.config_bytes = (json.dumps(self.config) + "\n").encode()
        self.config_path.write_bytes(self.config_bytes)
        self.config_path.chmod(0o600)
        self.args = ["--paseo-home", str(self.paseo), "--codex-home", str(self.codex), "--paseo-package", str(self.package)]
        self.state = self.root / ".bridge-state"

    def executable(self, path, text):
        path.write_text(text)
        path.chmod(0o700)

    def invoke(self, *extra, uninstall=False):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = installer.main((["--uninstall"] if uninstall else self.args) + list(extra))
        return code, output.getvalue()

    def assert_success(self, *extra, **kwargs):
        code, output = self.invoke(*extra, **kwargs)
        self.assertEqual(code, 0, output)
        return output

    def test_dry_run_has_no_persistent_changes(self):
        self.assertIn("Dry run", self.assert_success())
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(self.config_path.read_bytes(), self.config_bytes)
        self.assertFalse(self.state.exists())

    def test_install_preserves_options_and_uninstall_exact_bytes_modes(self):
        self.assert_success("--apply")
        self.assertEqual(self.target.read_bytes(), self.updated)
        config = json.loads(self.config_path.read_bytes())
        providers = config["agents"]["providers"]
        self.assertEqual(providers["codex"]["options"], self.config["agents"]["providers"]["codex"]["options"])
        self.assertEqual(config["unrelated"], self.config["unrelated"])
        self.assertEqual(providers["other"], {"enabled": False})
        self.assertEqual(providers["codex-desktop-shared"]["extends"], "codex")
        self.assertEqual(len(providers["codex"]["command"]), 2)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.state / "runtime.json").stat().st_mode), 0o600)
        self.assertEqual(json.loads((self.state / "runtime.json").read_bytes())["python"], sys.executable)
        self.assertIn("Already installed", self.assert_success("--apply"))
        self.assert_success(uninstall=True)
        self.assertEqual(self.target.read_bytes(), self.updated)
        self.assert_success("--apply", uninstall=True)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(self.config_path.read_bytes(), self.config_bytes)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(self.config_path.stat().st_mode), 0o600)
        self.assertFalse((self.state / "runtime.json").exists())
        self.assertFalse((self.state / "install.json").exists())

    def test_uninstall_refuses_later_edits_before_any_restore(self):
        self.assert_success("--apply")
        changed = self.config_path.read_bytes() + b"\n"
        self.config_path.write_bytes(changed)
        code, output = self.invoke("--apply", uninstall=True)
        self.assertEqual(code, 1)
        self.assertIn("File changed", output)
        self.assertEqual(self.target.read_bytes(), self.updated)
        self.assertEqual(self.config_path.read_bytes(), changed)

    def test_rejects_unknown_paseo_version(self):
        self.package_json.write_text('{"version":"99.0.0"}')
        code, output = self.invoke("--apply")
        self.assertEqual(code, 1)
        self.assertIn("requires Paseo", output)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertFalse((self.state / "backups").exists())

    def test_rejects_modified_paseo_original(self):
        self.target.write_bytes(b"local edit\n")
        code, output = self.invoke("--apply")
        self.assertEqual(code, 1)
        self.assertIn("supported original", output)
        self.assertEqual(self.config_path.read_bytes(), self.config_bytes)

    def test_rejects_wrong_patch_result_hash(self):
        self.manifest["files"][0]["after_sha256"] = "0" * 64
        (self.patches / "manifest.json").write_text(json.dumps(self.manifest))
        code, output = self.invoke("--apply")
        self.assertEqual(code, 1)
        self.assertIn("checksum mismatch", output)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_rejects_old_node(self):
        self.executable(self.bin / "node", "#!/bin/sh\necho v22.0.0\n")
        code, output = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn("Node.js 24", output)

    def test_rejects_wrong_managed_daemon_version(self):
        self.executable(self.codex / "packages/app-server-daemon/current/bin/codex", "#!/bin/sh\necho codex-cli 1.0.0\n")
        code, output = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn("managed daemon 0.167.1", output)

    def test_missing_socket_requires_managed_daemon(self):
        (self.codex / "app-server-control/app-server-control.sock").unlink()
        code, output = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn("socket is missing", output)

    def test_install_write_failure_rolls_back_prior_writes(self):
        real_write = installer.atomic_write

        def write(path, data, mode):
            if path == self.config_path and b"codex-desktop-shared" in data:
                raise OSError("simulated write failure")
            return real_write(path, data, mode)

        with mock.patch.object(installer, "atomic_write", side_effect=write):
            code, _ = self.invoke("--apply")
        self.assertEqual(code, 1)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(self.config_path.read_bytes(), self.config_bytes)
        self.assertFalse((self.state / "install.json").exists())

    def test_damaged_backup_stops_uninstall_before_any_write(self):
        self.assert_success("--apply")
        (self.state / "backups/000.bin").write_bytes(b"damaged\n")
        code, output = self.invoke("--apply", uninstall=True)
        self.assertEqual(code, 1)
        self.assertIn("backup is missing or damaged", output)
        self.assertEqual(self.target.read_bytes(), self.updated)
        self.assertTrue((self.state / "runtime.json").exists())

    def test_interrupted_uninstall_can_resume(self):
        self.assert_success("--apply")
        real_restore = installer.restore_entry
        count = 0

        def restore(entry, state_dir):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("simulated interruption")
            return real_restore(entry, state_dir)

        with mock.patch.object(installer, "restore_entry", side_effect=restore):
            code, _ = self.invoke("--apply", uninstall=True)
        self.assertEqual(code, 1)
        self.assert_success("--apply", uninstall=True)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(self.config_path.read_bytes(), self.config_bytes)

    def test_install_and_uninstall_new_config(self):
        self.config_path.unlink()
        self.assert_success("--apply")
        self.assertTrue(self.config_path.exists())
        self.assert_success("--apply", uninstall=True)
        self.assertFalse(self.config_path.exists())

    def test_rejects_symlinked_patch_target(self):
        elsewhere = self.base / "elsewhere.js"
        elsewhere.write_bytes(self.original)
        self.target.unlink()
        self.target.symlink_to(elsewhere)
        code, _ = self.invoke("--apply")
        self.assertEqual(code, 1)
        self.assertEqual(elsewhere.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
