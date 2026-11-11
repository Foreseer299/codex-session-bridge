#!/usr/bin/env python3
"""Private lifecycle installer used by the native Paseo plugin.

Unlike the manual installer, configuration ownership is tracked per field: Paseo
can add, remove, or update plugins without invalidating this plugin's rollback.
"""
import argparse
import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("_bridge_install_helpers", _ROOT / "scripts/install.py")
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
ROOT = _ROOT
InstallError = _helpers.InstallError
atomic_write = _helpers.atomic_write
digest = _helpers.digest
encoded = _helpers.encoded
snapshot = _helpers.snapshot
safe_child = _helpers.safe_child
patched_bytes = _helpers.patched_bytes
run_version = _helpers.run_version
executable = _helpers.executable


def field(config, parts):
    value = config
    for key in parts:
        if not isinstance(value, dict):
            raise InstallError("Configuration parent is not an object; no fields were overwritten.")
        if key not in value:
            return {"exists": False}
        value = value[key]
    return {"exists": True, "value": copy.deepcopy(value)}


def set_field(config, parts, value):
    parent = config
    for key in parts[:-1]:
        if key not in parent:
            if not value["exists"]:
                return
            parent[key] = {}
        if not isinstance(parent[key], dict):
            raise InstallError("Configuration parent is not an object.")
        parent = parent[key]
    if value["exists"]:
        parent[parts[-1]] = copy.deepcopy(value["value"])
    else:
        parent.pop(parts[-1], None)


def read_config(path):
    raw, mode = snapshot(path)
    value = json.loads(raw) if raw is not None else {}
    if not isinstance(value, dict):
        raise InstallError("Paseo configuration must be an object.")
    return raw, mode, value


def validate_environment(args):
    if sys.platform != "linux" or sys.version_info < (3, 11):
        raise InstallError("Linux and Python 3.11 or newer are required.")
    if not shutil.which("patch"):
        raise InstallError("The system patch utility is required.")
    for name in ("paseo_home", "paseo_package", "codex_home", "paseo_cli", "node"):
        if not getattr(args, name, None):
            raise InstallError("The plugin did not supply a required runtime path.")
    node = executable(args.node, "node")
    python = executable(args.python or sys.executable, "python3")
    cli = executable(args.paseo_cli, "paseo")
    if run_version([node, "--version"], "Node.js") < (24, 0, 0):
        raise InstallError("Node.js 24 or newer is required.")
    if run_version([python, "--version"], "Python") < (3, 11, 0):
        raise InstallError("Python 3.11 or newer is required.")
    home = Path(args.paseo_home).expanduser().resolve()
    codex = Path(args.codex_home).expanduser().resolve()
    package = Path(args.paseo_package).expanduser().resolve()
    if not home.is_dir():
        raise InstallError("Paseo home must already exist.")
    if not (codex / "app-server-control/app-server-control.sock").is_socket():
        raise InstallError("Managed Codex daemon socket is missing; connect Desktop first.")
    daemon = codex / "packages/app-server-daemon/current/bin/codex"
    if run_version([str(daemon), "--version"], "Codex managed daemon") != (0, 167, 1):
        raise InstallError("This release requires Codex managed daemon 0.167.1.")
    manifest = json.loads((ROOT / "patches/manifest.json").read_bytes())
    if json.loads((package / "package.json").read_bytes()).get("version") != manifest["version"]:
        raise InstallError("This release requires the supported Paseo package version.")
    if not (ROOT / "bin/bridge.cjs").is_file():
        raise InstallError("Plugin runtime files are missing.")
    probe = subprocess.run([node, "-e", "require.resolve('ws')"], cwd=ROOT, capture_output=True, timeout=15)
    if probe.returncode:
        raise InstallError("Plugin runtime dependencies are missing.")
    runtime = {"paseoHome": str(home), "codexHome": str(codex), "paseoCli": cli,
               "node": node, "python": python}
    return home, package, manifest, runtime


def build_plan(args):
    home, package, manifest, runtime = validate_environment(args)
    plans = []
    for item in manifest["files"]:
        target = safe_child(package, item["path"])
        before, mode = snapshot(target)
        if before is None or digest(before) != item["before_sha256"]:
            raise InstallError("Paseo files are not pristine supported originals; uninstall earlier manual patches first.")
        after = patched_bytes(before, safe_child(ROOT / "patches", item["patch"]))
        if digest(after) != item["after_sha256"]:
            raise InstallError("Compatibility patch checksum mismatch.")
        plans.append((target, before, mode, after, mode))
    runtime_path = ROOT / ".bridge-state/runtime.json"
    if runtime_path.exists() or runtime_path.is_symlink():
        raise InstallError("Untracked runtime configuration exists; earlier installation needs recovery.")
    plans.append((runtime_path, None, 0o600, encoded(runtime), 0o600))
    config_path = home / "config.json"
    before, mode, config = read_config(config_path)
    result = copy.deepcopy(config)
    owned = []
    created = []

    def own(parts, value, only_missing=False):
        previous = field(config, parts)
        if only_missing and previous["exists"]:
            return
        for depth in range(1, len(parts)):
            parent = parts[:depth]
            if not field(config, parent)["exists"] and parent not in created:
                created.append(parent)
        after = {"exists": True, "value": value}
        owned.append({"parts": parts, "before": previous, "after": after})
        set_field(result, parts, after)

    if before is None:
        own(["version"], 1)
    command = [runtime["node"], str(ROOT / "bin/bridge.cjs")]
    for provider in ("codex", "codex-desktop-shared"):
        prefix = ["agents", "providers", provider]
        own(prefix + ["command"], command)
        own(prefix + ["enabled"], True, only_missing=True)
    own(["agents", "providers", "codex-desktop-shared", "extends"], "codex")
    own(["agents", "providers", "codex-desktop-shared", "label"], "Codex Shared", only_missing=True)
    validator = "import {pathToFileURL} from 'node:url'; import fs from 'node:fs'; const {PersistedConfigSchema}=await import(pathToFileURL(process.argv[1]).href); PersistedConfigSchema.parse(JSON.parse(fs.readFileSync(0,'utf8')));"
    checked = subprocess.run([runtime["node"], "--input-type=module", "-e", validator, str(package / "dist/server/server/persisted-config.js")], input=encoded(result), capture_output=True, timeout=15)
    if checked.returncode:
        raise InstallError("Paseo rejected the proposed configuration; no changes were applied.")
    config_state = {"path": str(config_path), "before_mode": mode,
                    "before_sha256": digest(before) if before is not None else None,
                    "backup": "config.bin", "owned": owned, "created": created}
    return plans, config_state, before, encoded(result), runtime, str(package)


def state_file(state_dir):
    return state_dir / "managed.json"


def file_hash(path):
    content, _ = snapshot(path)
    return digest(content) if content is not None else None


def validate_current(state, allow_original=False):
    for item in state["files"]:
        allowed = {item["after_sha256"]}
        if allow_original:
            allowed.add(item["before_sha256"])
        if file_hash(Path(item["path"])) not in allowed:
            raise InstallError("A managed file changed after installation; refusing to overwrite it.")
    _, _, config = read_config(Path(state["config"]["path"]))
    for item in state["config"]["owned"]:
        actual = field(config, item["parts"])
        if actual != item["after"] and not (allow_original and actual == item["before"]):
            raise InstallError("A managed provider setting changed after installation; refusing to overwrite it.")


def backup_bytes(item, state_dir):
    if item["before_sha256"] is None:
        return None
    path = safe_child(state_dir / "managed-backups", item["backup"])
    raw, _ = snapshot(path)
    if raw is None or digest(raw) != item["before_sha256"]:
        raise InstallError("An installation backup is missing or damaged; recovery stopped.")
    return raw


def restore_config(state, state_dir):
    item = state["config"]
    path = Path(item["path"])
    old, mode, current = read_config(path)
    for setting in item["owned"]:
        actual = field(current, setting["parts"])
        if actual not in (setting["after"], setting["before"]):
            raise InstallError("A managed provider setting changed during recovery.")
        set_field(current, setting["parts"], setting["before"])
    for parts in sorted(item["created"], key=len, reverse=True):
        if field(current, parts) == {"exists": True, "value": {}}:
            set_field(current, parts, {"exists": False})
    original = backup_bytes(item, state_dir)
    if file_hash(path) != (digest(old) if old is not None else None):
        raise InstallError("Configuration changed during recovery; retry when Paseo is idle.")
    if original is None and current == {}:
        path.unlink(missing_ok=True)
    elif original is not None and json.loads(original) == current:
        atomic_write(path, original, item["before_mode"])
    else:
        atomic_write(path, encoded(current), mode)


def restore(state, state_dir):
    validate_current(state, allow_original=True)
    for item in state["files"] + [state["config"]]:
        backup_bytes(item, state_dir)
    state["phase"] = "restoring"
    atomic_write(state_file(state_dir), encoded(state), 0o600)
    restore_config(state, state_dir)
    for item in reversed(state["files"]):
        path = Path(item["path"])
        if file_hash(path) not in {item["before_sha256"], item["after_sha256"]}:
            raise InstallError("A managed file changed during recovery.")
        before = backup_bytes(item, state_dir)
        if before is None:
            path.unlink(missing_ok=True)
        else:
            atomic_write(path, before, item["before_mode"])
    state_file(state_dir).unlink()
    shutil.rmtree(state_dir / "managed-backups")


def install(args, state_dir):
    record = state_file(state_dir)
    if record.exists():
        state = json.loads(record.read_bytes())
        if state.get("phase") != "installed":
            raise InstallError("An interrupted operation needs --uninstall recovery before installation.")
        _, package, _, runtime = validate_environment(args)
        if state["runtime"] != runtime or state["package"] != str(package):
            raise InstallError("Runtime paths changed; restore this installation before moving it.")
        validate_current(state)
        return {"changed": False, "installed": True, "check": args.check}
    plans, config, config_before, config_after, runtime, package = build_plan(args)
    if args.check:
        return {"changed": False, "installed": False, "check": True}
    backups = state_dir / "managed-backups"
    backups.mkdir(mode=0o700)
    files = []
    try:
        for index, (path, before, mode, after, after_mode) in enumerate(plans):
            name = f"{index:03d}.bin"
            if before is not None:
                atomic_write(backups / name, before, 0o600)
            files.append({"path": str(path), "backup": name,
                          "before_sha256": digest(before) if before is not None else None,
                          "before_mode": mode, "after_sha256": digest(after), "after_mode": after_mode})
        if config_before is not None:
            atomic_write(backups / config["backup"], config_before, 0o600)
        state = {"schema": 1, "phase": "prepared", "runtime": runtime,
                 "package": package, "files": files, "config": config}
        atomic_write(record, encoded(state), 0o600)
    except BaseException:
        if not record.exists():
            shutil.rmtree(backups)
        raise
    try:
        for item, (path, before, _, after, mode) in zip(files, plans):
            if file_hash(path) != item["before_sha256"]:
                raise InstallError("A target changed during installation.")
            atomic_write(path, after, mode)
        config_path = Path(config["path"])
        if file_hash(config_path) != config["before_sha256"]:
            raise InstallError("Paseo configuration changed during installation; retry when idle.")
        atomic_write(config_path, config_after, config["before_mode"])
        state["phase"] = "installed"
        atomic_write(record, encoded(state), 0o600)
    except BaseException:
        restore(state, state_dir)
        raise
    return {"changed": True, "installed": True, "check": False}


def uninstall(args, state_dir):
    if not state_file(state_dir).exists():
        return {"changed": False, "installed": False, "check": args.check}
    state = json.loads(state_file(state_dir).read_bytes())
    validate_current(state, allow_original=state.get("phase") != "installed")
    for item in state["files"] + [state["config"]]:
        backup_bytes(item, state_dir)
    if args.check:
        return {"changed": False, "installed": True, "check": True}
    restore(state, state_dir)
    return {"changed": True, "installed": False, "check": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("paseo-home", "paseo-package", "codex-home", "paseo-cli", "node", "python"):
        parser.add_argument("--" + name)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    state_dir = ROOT / ".bridge-state"
    try:
        if state_dir.is_symlink():
            raise InstallError("Refusing a symlinked state directory.")
        if not args.check:
            state_dir.mkdir(mode=0o700, exist_ok=True)
            os.chmod(state_dir, 0o700)
        action = uninstall if args.uninstall else install
        if state_dir.exists():
            lock_path = state_dir / ".managed.lock"
            if lock_path.is_symlink():
                raise InstallError("Refusing a symlinked installation lock.")
            with os.fdopen(os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600), "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = action(args, state_dir)
        else:
            result = action(args, state_dir)
        print(json.dumps(result))
        return 0
    except (InstallError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, InstallError) else "Operation failed; check runtime files and permissions."
        print(json.dumps({"error": message}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
