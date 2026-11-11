#!/usr/bin/python3
"""Link shared Codex Desktop history through Paseo's native import command."""

import json
import fcntl
from datetime import datetime
import os
import tempfile
import subprocess
from pathlib import Path


CONFIG_PATH = Path(os.environ.get("CODEX_SESSION_BRIDGE_CONFIG", Path(__file__).resolve().parents[1] / ".bridge-state/runtime.json"))
CONFIG = json.loads(CONFIG_PATH.read_bytes())
PASEO = Path(CONFIG["paseoHome"])
CLI = Path(CONFIG["paseoCli"])
BRIDGE = Path(__file__).resolve().parents[1] / "bin/bridge.cjs"
NODE = CONFIG["node"]
PROVIDER = "codex-desktop-shared"
METADATA = PASEO / "codex-shared-metadata.json"
CODEX_PROVIDERS = {"codex", PROVIDER}


def paired_agents():
    pairs = {}
    for path in (PASEO / "agents").rglob("*.json"):
        try:
            record = json.loads(path.read_bytes())
        except FileNotFoundError:
            continue
        handle = record.get("persistence") or {}
        native_id = handle.get("nativeHandle") or handle.get("sessionId")
        if record.get("provider") in CODEX_PROVIDERS and isinstance(native_id, str):
            previous = pairs.get(native_id)
            if previous is None or (previous.get("archivedAt") and not record.get("archivedAt")):
                pairs[native_id] = record
    return pairs


def is_root_codex_thread(thread):
    # Migrated paginated history is in Codex's database; its old JSONL path can
    # be absent while all messages remain available through the native API.
    return (
        bool(thread.get("cwd"))
        and Path(thread["cwd"]).is_dir()
        and not thread.get("ephemeral")
        and not thread.get("parentThreadId")
        and thread.get("source") in ("vscode", "cli", "appServer")
    )


def paseo(*args):
    return subprocess.run(
        [CLI, "--home", PASEO, *args, "--json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=120,
    )


def codex_metadata(method, thread_id, **params):
    request = {"method": method, "params": {"threadId": thread_id, **params}}
    return subprocess.run([NODE, BRIDGE, "--metadata"], input=json.dumps(request).encode(), timeout=15).returncode == 0


def reconcile_metadata(thread, agent, previous, created_in_paseo, events):
    thread_id = thread["id"]
    agent_id = agent["id"]
    native_archived = thread["archived"]
    paseo_archived = bool(agent.get("archivedAt"))
    native_title = thread.get("name") or ""
    paseo_title = agent.get("title") or ""
    native_event = events.get("archive") or {}
    new_native_event = native_event.get("version") and native_event.get("version") != (previous or {}).get("archiveEventVersion")
    local_archive_changed = previous and paseo_archived != previous["paseoArchived"]
    local_archive_time = agent.get("archivedAt") if paseo_archived else agent.get("updatedAt")
    try:
        local_archive_ms = datetime.fromisoformat(local_archive_time.replace("Z", "+00:00")).timestamp() * 1000
    except (AttributeError, ValueError):
        local_archive_ms = 0
    prefer_native_archive = new_native_event and not (local_archive_changed and local_archive_ms > native_event.get("at", 0))
    if (previous or new_native_event) and native_archived != paseo_archived:
        if prefer_native_archive or (previous and native_archived != previous["nativeArchived"]):
            if native_archived:
                result = paseo("archive", agent_id)
            else:
                result = paseo("agent", "import", thread_id, "--provider", agent["provider"], "--cwd", agent["cwd"])
            if result.returncode:
                return None
            paseo_archived = native_archived
        elif previous and paseo_archived != previous["paseoArchived"]:
            method = "thread/archive" if paseo_archived else "thread/unarchive"
            if not codex_metadata(method, thread_id):
                return None
            native_archived = paseo_archived

    if not native_archived and not paseo_archived and native_title != paseo_title:
        if previous:
            # If both changed during one interval, prefer the desktop's native title.
            take_native = native_title and native_title != previous["nativeTitle"]
            take_paseo = paseo_title and paseo_title != previous["paseoTitle"]
        else:
            take_native = native_title and (not created_in_paseo or not paseo_title)
            take_paseo = paseo_title and not take_native
        if take_native:
            if paseo("agent", "update", agent_id, "--name=" + native_title).returncode:
                return None
            paseo_title = native_title
        elif take_paseo:
            if not codex_metadata("thread/name/set", thread_id, name=paseo_title):
                return None
            native_title = paseo_title

    return {
        "archiveEventVersion": native_event.get("version"),
        "nativeTitle": native_title,
        "paseoTitle": paseo_title,
        "nativeArchived": native_archived,
        "paseoArchived": paseo_archived,
    }


def save_metadata(state):
    fd, tmp = tempfile.mkstemp(dir=PASEO, prefix=".codex-shared-metadata-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream, ensure_ascii=False)
        os.replace(tmp, METADATA)
    finally:
        Path(tmp).unlink(missing_ok=True)


def main():
    try:
        events = json.loads((PASEO / "codex-shared-native-events.json").read_bytes())
    except FileNotFoundError:
        events = {}
    snapshot = subprocess.check_output([NODE, BRIDGE, "--snapshot-all"], timeout=15)
    threads = {thread["id"]: thread for thread in json.loads(snapshot)}
    created = {path.name for path in (PASEO / "codex-shared-created").glob("*")}
    linked = set(paired_agents()) | created
    failed = False
    for thread in sorted(threads.values(), key=lambda item: item["createdAt"], reverse=True):
        thread_id = thread["id"]
        if thread["archived"] or thread_id in linked or not is_root_codex_thread(thread):
            continue
        # Native import serializes simultaneous requests for the same provider.
        if thread_id in paired_agents():
            continue
        try:
            result = paseo("agent", "import", thread_id, "--provider", PROVIDER, "--cwd", thread["cwd"])
            if result.returncode:
                print("Thread import failed; retry pending.", flush=True)
                failed = True
                continue
            agent_id = json.loads(result.stdout)["agentId"]
            linked.add(thread_id)
            print("Linked a Codex thread in Paseo.", flush=True)
            if thread.get("name") and paseo("agent", "update", agent_id, "--name=" + thread["name"]).returncode:
                print("Title update pending.", flush=True)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
            print("Import or title update pending.", flush=True)
            failed = True
    try:
        previous = json.loads(METADATA.read_bytes())
    except FileNotFoundError:
        previous = {}
    state = previous.copy()
    for thread_id, agent in paired_agents().items():
        thread = threads.get(thread_id)
        if thread is None:
            continue
        try:
            result = reconcile_metadata(
                thread, agent, previous.get(thread_id),
                thread_id in created or agent["provider"] == "codex", events.get(thread_id, {}),
            )
        except (subprocess.TimeoutExpired, KeyError):
            result = None
        if result is None:
            print("Metadata update pending.", flush=True)
            failed = True
        else:
            state[thread_id] = result
    if state != previous:
        save_metadata(state)
    return int(failed)


if __name__ == "__main__":
    with (PASEO / ".codex-sync.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit(0)
        raise SystemExit(main())
