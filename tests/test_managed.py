"""Native-plugin installer tests; all profiles and binaries are synthetic."""
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

SPEC = importlib.util.spec_from_file_location("bridge_managed", Path(__file__).resolve().parents[1] / "scripts/managed.py")
managed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(managed)


class ManagedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cbm-")
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / "runtime"
        self.root.mkdir()
        patcher = mock.patch.object(managed, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.home = base / "paseo"
        self.home.mkdir()
        self.package = base / "package"
        self.package.mkdir()
        (self.package / "package.json").write_text('{"version":"0.15.3"}')
        self.codex = base / "codex"
        socket_path = self.codex / "app-server-control/app-server-control.sock"
        socket_path.parent.mkdir(parents=True)
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(socket_path))
        self.addCleanup(sock.close)
        daemon = self.codex / "packages/app-server-daemon/current/bin/codex"
        daemon.parent.mkdir(parents=True)
        self.executable(daemon, '#!/bin/sh\necho codex-cli 0.167.1\n')
        self.node = base / "node"
        self.executable(self.node, '#!/bin/sh\nif [ "$1" = "--version" ]; then echo v24.0.0; fi\n')
        self.cli = base / "paseo-cli"
        self.executable(self.cli, '#!/bin/sh\nexit 0\n')
        (self.root / "bin").mkdir()
        (self.root / "bin/bridge.cjs").write_text('// test bridge\n')
        self.before = b'export const state = "before";\n'
        self.after = b'export const state = "after";\n'
        self.target = self.package / "provider.js"
        self.target.write_bytes(self.before)
        self.target.chmod(0o640)
        patches = self.root / "patches"
        patches.mkdir()
        (patches / "provider.patch").write_text(''.join(difflib.unified_diff(self.before.decode().splitlines(True), self.after.decode().splitlines(True), fromfile="a/provider.js", tofile="b/provider.js")))
        self.manifest = {"version": "0.15.3", "files": [{"path": "provider.js", "patch": "provider.patch", "before_sha256": managed.digest(self.before), "after_sha256": managed.digest(self.after)}]}
        (patches / "manifest.json").write_text(json.dumps(self.manifest))
        self.config_path = self.home / "config.json"
        self.config = {"version": 1, "plugins": {"codex-session-bridge": {"enabled": True}}, "agents": {"providers": {"codex": {"enabled": False, "options": {"approval_policy": "on-request"}}, "other": {"enabled": True}}}}
        self.config_bytes = (json.dumps(self.config) + '\n').encode()
        self.config_path.write_bytes(self.config_bytes)
        self.config_path.chmod(0o600)
        self.state = self.root / ".bridge-state"
        self.args = ["--paseo-home", str(self.home), "--paseo-package", str(self.package), "--codex-home", str(self.codex), "--paseo-cli", str(self.cli), "--node", str(self.node)]

    def executable(self, path, content):
        path.write_text(content)
        path.chmod(0o700)

    def invoke(self, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = managed.main(self.args + list(extra))
        return result, json.loads(stdout.getvalue() or stderr.getvalue())

    def success(self, *extra):
        code, data = self.invoke(*extra)
        self.assertEqual(code, 0, data)
        return data

    def read(self):
        return json.loads(self.config_path.read_bytes())

    def write(self, data):
        self.config_path.write_text(json.dumps(data))

    def test_check_has_no_state_or_profile_changes(self):
        self.assertEqual(self.success('--check'), {"changed": False, "installed": False, "check": True})
        self.assertFalse(self.state.exists())
        self.assertEqual(self.config_path.read_bytes(), self.config_bytes)
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_native_schema_rejection_leaves_files_untouched(self):
        real_run = managed.subprocess.run
        def reject_schema(command, *args, **kwargs):
            if "--input-type=module" in command:
                return type("Rejected", (), {"returncode": 1})()
            return real_run(command, *args, **kwargs)
        with mock.patch.object(managed.subprocess, "run", side_effect=reject_schema):
            code, result = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn("rejected", result["error"])
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual(self.config_path.read_bytes(), self.config_bytes)

    def test_install_idempotent_restore_exact_original(self):
        self.assertTrue(self.success()['changed'])
        self.assertEqual(self.read()["agents"]["providers"]["codex-desktop-shared"]["label"], "Codex Shared")
        self.assertEqual(self.target.read_bytes(), self.after)
        provider = self.read()['agents']['providers']['codex']
        self.assertFalse(provider['enabled'])
        self.assertEqual(provider['options'], self.config['agents']['providers']['codex']['options'])
        self.assertFalse(self.success()['changed'])
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        for p in (self.state/'managed-backups').iterdir():
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(json.loads((self.state/'runtime.json').read_bytes())['python'], sys.executable)
        self.assertTrue(self.success('--uninstall')['changed'])
        self.assertEqual(self.config_path.read_bytes(), self.config_bytes)
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o640)
        self.assertFalse(self.success('--uninstall')['changed'])

    def test_plugin_registry_changes_survive_idempotency_and_uninstall(self):
        self.success()
        config = self.read()
        config['plugins'] = {'other-plugin': {'enabled': True, 'path': '/example/plugin'}}
        config['agents']['providers']['codex']['options']['approval_policy'] = 'never'
        self.write(config)
        self.assertFalse(self.success()['changed'])
        self.success('--uninstall')
        restored = self.read()
        self.assertEqual(restored['plugins'], config['plugins'])
        self.assertEqual(restored['agents']['providers']['codex']['options']['approval_policy'], 'never')
        self.assertNotIn('command', restored['agents']['providers']['codex'])
        self.assertNotIn('codex-desktop-shared', restored['agents']['providers'])

    def test_new_provider_settings_keep_container(self):
        self.success()
        config = self.read()
        config['agents']['providers']['codex-desktop-shared']['custom'] = {'keep': True}
        self.write(config)
        self.success('--uninstall')
        self.assertEqual(self.read()['agents']['providers']['codex-desktop-shared'], {'custom': {'keep': True}})

    def test_existing_shared_values_are_restored(self):
        config = self.read()
        config['agents']['providers']['codex-desktop-shared'] = {'command': ['old'], 'extends': 'old-provider', 'enabled': False}
        self.write(config)
        self.success()
        self.success('--uninstall')
        self.assertEqual(self.read(), config)

    def test_owned_setting_edit_is_not_overwritten(self):
        self.success()
        config = self.read()
        config['agents']['providers']['codex']['command'] = ['changed-by-user']
        self.write(config)
        code, output = self.invoke('--uninstall')
        self.assertEqual(code, 1)
        self.assertIn('provider setting changed', output['error'])
        self.assertEqual(self.read(), config)
        self.assertEqual(self.target.read_bytes(), self.after)

    def test_unknown_version_or_hash_stops_before_config_change(self):
        (self.package/'package.json').write_text('{"version":"0.99.0"}')
        self.assertEqual(self.invoke()[0], 1)
        (self.package/'package.json').write_text('{"version":"0.15.3"}')
        self.target.write_bytes(self.after)
        code, output = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn('manual patches', output['error'])
        self.assertEqual(self.config_path.read_bytes(), self.config_bytes)

    def test_write_failure_rolls_back_and_clears_journal(self):
        real = managed.atomic_write
        def failing(path, data, mode):
            if path == self.config_path and b'codex-desktop-shared' in data:
                raise OSError('synthetic write failure')
            return real(path, data, mode)
        with mock.patch.object(managed, 'atomic_write', side_effect=failing):
            self.assertEqual(self.invoke()[0], 1)
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertEqual(self.config_path.read_bytes(), self.config_bytes)
        self.assertFalse((self.state/'managed.json').exists())
        self.assertFalse((self.state/'runtime.json').exists())

    def test_damaged_backup_prevents_any_uninstall_write(self):
        self.success()
        (self.state/'managed-backups/000.bin').write_bytes(b'damaged')
        before = self.config_path.read_bytes()
        self.assertEqual(self.invoke('--uninstall')[0], 1)
        self.assertEqual(self.config_path.read_bytes(), before)
        self.assertEqual(self.target.read_bytes(), self.after)

    def test_interrupted_restore_can_continue(self):
        self.success()
        real = managed.atomic_write
        def failing(path, data, mode):
            if path == self.target and data == self.before:
                raise OSError('synthetic interruption')
            return real(path, data, mode)
        with mock.patch.object(managed, 'atomic_write', side_effect=failing):
            self.assertEqual(self.invoke('--uninstall')[0], 1)
        self.assertEqual(json.loads((self.state/'managed.json').read_bytes())['phase'], 'restoring')
        self.success('--uninstall')
        self.assertEqual(self.config_path.read_bytes(), self.config_bytes)
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_missing_config_is_removed_after_restore(self):
        self.config_path.unlink()
        self.success()
        self.success('--uninstall')
        self.assertFalse(self.config_path.exists())

    def test_missing_socket_rejects_install(self):
        (self.codex/'app-server-control/app-server-control.sock').unlink()
        code, output = self.invoke()
        self.assertEqual(code, 1)
        self.assertIn('socket is missing', output['error'])
