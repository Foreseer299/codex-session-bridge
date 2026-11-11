#!/usr/bin/env python3
"""Install version-pinned local compatibility patches; dry-run unless --apply."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
CODEX_VERSION = "0.167.1"


class InstallError(Exception):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def regular(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise InstallError(f"Expected a regular file: {path.name}")


def snapshot(path):
    regular(path)
    if not path.exists():
        return None, 0o600
    return path.read_bytes(), stat.S_IMODE(path.stat().st_mode)


def atomic_write(path, data, mode):
    """Replace one file without exposing partial contents or permissive modes."""
    fd, temporary = tempfile.mkstemp(prefix=".bridge-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_version(command, label):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallError(f"Cannot run {label}; check its installation.") from error
    found = re.search(r"(?<!\d)(\d+)\.(\d+)\.(\d+)\b", result.stdout)
    if not found:
        raise InstallError(f"Cannot recognize {label} version.")
    return tuple(int(part) for part in found.groups())


def executable(value, name):
    result = shutil.which(value or name)
    if not result:
        raise InstallError(f"{name} is missing from PATH; install it first.")
    return str(Path(result).absolute())


def safe_child(root, name):
    candidate = root / name
    if Path(name).is_absolute() or ".." in Path(name).parts:
        raise InstallError("Unsafe patch manifest path.")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise InstallError("Patch target escapes its package directory.")
    return candidate


def patched_bytes(original, patch_file):
    with tempfile.TemporaryDirectory(prefix="codex-bridge-patch-") as temporary:
        target = Path(temporary) / "target"
        target.write_bytes(original)
        result = subprocess.run(
            ["patch", "--batch", "--forward", "--fuzz=0", "--silent", str(target), str(patch_file)],
            capture_output=True, timeout=30,
        )
        if result.returncode:
            raise InstallError(f"Compatibility patch failed: {patch_file.name}")
        return target.read_bytes()


def build_plan(args):
    if not args.paseo_package:
        raise InstallError("--paseo-package is required for installation.")
    if sys.platform != "linux":
        raise InstallError("This release supports Linux only.")
    if not shutil.which("patch"):
        raise InstallError("Install the system 'patch' utility first.")
    node = executable(None, "node")
    if run_version([node, "--version"], "Node.js") < (24, 0, 0):
        raise InstallError("Node.js 24 or newer is required.")
    paseo_cli = executable(args.paseo_cli, "paseo")
    paseo_home = Path(args.paseo_home).expanduser().resolve()
    codex_home = Path(args.codex_home).expanduser().resolve()
    if not paseo_home.is_dir():
        raise InstallError("Paseo home must already exist; configure Paseo first.")
    socket_path = codex_home / "app-server-control/app-server-control.sock"
    if not socket_path.is_socket():
        raise InstallError("The managed Codex daemon socket is missing; connect Desktop to this host first.")
    daemon = codex_home / "packages/app-server-daemon/current/bin/codex"
    if run_version([str(daemon), "--version"], "Codex managed daemon") != tuple(map(int, CODEX_VERSION.split("."))):
        raise InstallError(f"This release requires Codex managed daemon {CODEX_VERSION}.")
    if not (ROOT / "bin/bridge.cjs").is_file():
        raise InstallError("Bridge files are missing; unpack the complete release.")
    dependency = subprocess.run(
        [node, "-e", "require.resolve('ws')"], cwd=ROOT, capture_output=True, timeout=15,
    )
    if dependency.returncode:
        raise InstallError("Node dependencies are missing; run npm ci in the bridge directory.")
    package = Path(args.paseo_package).expanduser().resolve()
    manifest = json.loads((ROOT / "patches/manifest.json").read_bytes())
    version = json.loads((package / "package.json").read_bytes()).get("version")
    if version != manifest["version"]:
        raise InstallError(f"This release requires Paseo {manifest['version']}; detected {version}.")
    plan = []
    for entry in manifest["files"]:
        target = safe_child(package, entry["path"])
        before, mode = snapshot(target)
        if before is None or digest(before) != entry["before_sha256"]:
            raise InstallError(f"Paseo file differs from the supported original: {entry['path']}")
        patch_file = safe_child(ROOT / "patches", entry["patch"])
        after = patched_bytes(before, patch_file)
        if digest(after) != entry["after_sha256"]:
            raise InstallError(f"Patched content checksum mismatch: {entry['path']}")
        plan.append((target, before, mode, after, mode))
    config_path = paseo_home / "config.json"
    before, mode = snapshot(config_path)
    config = json.loads(before) if before is not None else {"version": 1}
    providers = config.setdefault("agents", {}).setdefault("providers", {})
    command = [node, str(ROOT / "bin/bridge.cjs")]
    providers.setdefault("codex", {}).update({"command": command})
    providers["codex"].setdefault("enabled", True)
    shared = providers.setdefault("codex-desktop-shared", {})
    shared.update({"extends": "codex", "command": command})
    shared.setdefault("enabled", True)
    shared.setdefault("label", "Codex Shared")
    plan.append((config_path, before, mode, encoded(config), mode))
    runtime = ROOT / ".bridge-state/runtime.json"
    runtime_config = {"paseoHome": str(paseo_home), "codexHome": str(codex_home),
                      "paseoCli": paseo_cli, "node": node, "python": sys.executable}
    old_runtime, old_mode = snapshot(runtime)
    if old_runtime is not None:
        raise InstallError("Untracked runtime configuration exists; move it aside before installing.")
    plan.append((runtime, None, old_mode, encoded(runtime_config), 0o600))
    if len({str(row[0]) for row in plan}) != len(plan):
        raise InstallError("Duplicate installation targets.")
    return plan


def current_hash(path):
    data, _ = snapshot(path)
    return digest(data) if data is not None else None


def check_installed(state, allow_original=False):
    for entry in state["files"]:
        accepted = {entry["after_sha256"]}
        if allow_original:
            accepted.add(entry["before_sha256"])
        if current_hash(Path(entry["path"])) not in accepted:
            raise InstallError(f"File changed after installation; refusing to overwrite: {Path(entry['path']).name}")


def restore_entry(entry, state_dir):
    target = Path(entry["path"])
    if entry["before_sha256"] is None:
        target.unlink(missing_ok=True)
    else:
        backup = state_dir / "backups" / entry["backup"]
        data = backup.read_bytes()
        if digest(data) != entry["before_sha256"]:
            raise InstallError("Installation backup checksum mismatch; original was not overwritten.")
        atomic_write(target, data, entry["before_mode"])


def validate_backups(state, state_dir):
    for entry in state["files"]:
        if entry["before_sha256"] is not None:
            backup = state_dir / "backups" / entry["backup"]
            if not backup.is_file() or digest(backup.read_bytes()) != entry["before_sha256"]:
                raise InstallError("Installation backup is missing or damaged; no files were changed.")


def install(args, state_dir):
    state_file = state_dir / "install.json"
    if state_file.exists():
        state = json.loads(state_file.read_bytes())
        if state.get("phase") != "installed":
            raise InstallError("An interrupted installation exists; run --uninstall --apply to restore it first.")
        check_installed(state)
        print("Already installed; all installed checksums match. No changes.")
        return
    plan = build_plan(args)
    print(f"Validated {len(plan) - 2} compatibility patches, Paseo config, and local runtime config.")
    if not args.apply:
        print("Dry run only. Add --apply after stopping Paseo and any bridge watcher.")
        return
    backup_dir = state_dir / "backups"
    backup_dir.mkdir(mode=0o700, exist_ok=False)
    entries = []
    for index, (path, before, mode, after, after_mode) in enumerate(plan):
        backup_name = f"{index:03d}.bin"
        if before is not None:
            atomic_write(backup_dir / backup_name, before, 0o600)
        entries.append({"path": str(path), "backup": backup_name,
                        "before_sha256": digest(before) if before is not None else None,
                        "before_mode": mode, "after_sha256": digest(after), "after_mode": after_mode})
    state = {"schema": 1, "phase": "prepared", "files": entries}
    atomic_write(state_file, encoded(state), 0o600)
    written = []
    try:
        for entry, (path, before, _, after, after_mode) in zip(entries, plan):
            if current_hash(path) != entry["before_sha256"]:
                raise InstallError("A target changed during installation. Stop Paseo and retry.")
            written.append(entry)
            atomic_write(path, after, after_mode)
        state["phase"] = "installed"
        atomic_write(state_file, encoded(state), 0o600)
    except BaseException:
        # Keep the journal if rollback cannot finish; --uninstall can retry.
        for entry in reversed(written):
            actual = current_hash(Path(entry["path"]))
            if actual == entry["before_sha256"]:
                continue
            if actual != entry["after_sha256"]:
                raise InstallError("A target changed during rollback; local recovery journal was retained.")
            restore_entry(entry, state_dir)
        state_file.unlink(missing_ok=True)
        shutil.rmtree(backup_dir)
        raise
    print("Installed. Restart Paseo when idle, then run npm run watch from this directory.")
    print("Existing approval, sandbox, model, and provider options were preserved.")


def uninstall(args, state_dir):
    state_file = state_dir / "install.json"
    if not state_file.exists():
        print("No installation record found; nothing to uninstall.")
        return
    state = json.loads(state_file.read_bytes())
    check_installed(state, allow_original=state.get("phase") != "installed")
    validate_backups(state, state_dir)
    if not args.apply:
        print("Uninstall dry run passed. Stop Paseo and the watcher, then add --apply.")
        return
    # Record recovery intent first so an interrupted uninstall is resumable.
    state["phase"] = "restoring"
    atomic_write(state_file, encoded(state), 0o600)
    for entry in reversed(state["files"]):
        if current_hash(Path(entry["path"])) not in {entry["after_sha256"], entry["before_sha256"]}:
            raise InstallError("A file changed during uninstall; recovery journal was retained.")
        restore_entry(entry, state_dir)
    state_file.unlink()
    shutil.rmtree(state_dir / "backups")
    print("Uninstalled; original files and permissions restored. Restart Paseo when idle.")
    print("Conversation data and sync metadata were retained.")


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--paseo-home", default="~/.paseo")
    result.add_argument("--paseo-package", help="Installed @getpaseo/server package directory")
    result.add_argument("--paseo-cli", help="Path to the Paseo CLI (default: find in PATH)")
    result.add_argument("--codex-home", default="~/.codex")
    result.add_argument("--apply", action="store_true", help="Write changes; otherwise only validate")
    result.add_argument("--uninstall", action="store_true", help="Restore original installation files")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    state_dir = ROOT / ".bridge-state"
    try:
        if sys.version_info < (3, 11):
            raise InstallError("Python 3.11 or newer is required.")
        if state_dir.is_symlink():
            raise InstallError("Refusing symlinked installation state directory.")
        if args.apply:
            state_dir.mkdir(mode=0o700, exist_ok=True)
            os.chmod(state_dir, 0o700)
        # Dry runs never create a state directory. Apply uses an exclusive lock.
        if args.apply or state_dir.exists():
            lock_path = state_dir / ".install.lock"
            if lock_path.is_symlink():
                raise InstallError("Refusing symlinked installation lock.")
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            with os.fdopen(fd, "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                (uninstall if args.uninstall else install)(args, state_dir)
        else:
            (uninstall if args.uninstall else install)(args, state_dir)
        return 0
    except (InstallError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # Never print command stdout/stderr or configuration contents.
        print(f"Error: {error if isinstance(error, InstallError) else type(error).__name__ + '; check paths, permissions and valid JSON.'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
