#!/usr/bin/env node
"use strict";
const fs = require("node:fs"),
  { spawn } = require("node:child_process");
const WS = require("ws");
const config = require("./runtime.cjs");
const root = config.paseoHome,
  statePath = root + "/codex-shared-native-events.json";
let state = {};
try {
  state = JSON.parse(fs.readFileSync(statePath, "utf8"));
} catch (e) {
  if (e.code !== "ENOENT") throw e;
}
let socket,
  stopping = false,
  worker = null,
  dirty = false,
  debounce = null,
  retry = null,
  serial = 0;
function save() {
  const tmp = statePath + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(state), { mode: 0o600 });
  fs.renameSync(tmp, statePath);
}
function schedule() {
  dirty = true;
  if (worker || debounce || stopping) return;
  debounce = setTimeout(run, 250);
}
function run() {
  debounce = null;
  if (stopping || worker) return;
  dirty = false;
  worker = spawn(
    config.python || "python3",
    [require("node:path").join(__dirname, "../scripts/sync.py")],
    { stdio: ["ignore", "inherit", "inherit"] },
  );
  worker.on("error", () => {});
  worker.on("close", (code) => {
    worker = null;
    if (code) dirty = true;
    if (dirty && !stopping) {
      debounce = setTimeout(run, code ? 3000 : 250);
    }
  });
}
function connect() {
  if (stopping) return;
  socket = new WS(
    "ws+unix://" +
      config.codexHome +
      "/app-server-control/app-server-control.sock:/",
    { maxPayload: 8 * 1024 * 1024, handshakeTimeout: 5000 },
  );
  socket.on("open", () =>
    socket.send(
      JSON.stringify({
        id: 1,
        method: "initialize",
        params: {
          clientInfo: {
            name: "codex_app_server_daemon",
            title: "Codex metadata synchronization",
            version: "2",
          },
          capabilities: { experimentalApi: true },
        },
      }),
    ),
  );
  socket.on("message", (raw) => {
    let m;
    try {
      m = JSON.parse(raw);
    } catch {
      return;
    }
    if (m.id === 1 && m.result) {
      socket.send(JSON.stringify({ method: "initialized" }));
      schedule();
      return;
    }
    const id = m.params?.threadId ?? m.params?.thread?.id;
    if (!id) return;
    const at = Date.now(),
      version = at + ":" + ++serial;
    if (m.method === "thread/archived" || m.method === "thread/unarchived") {
      state[id] = {
        ...state[id],
        archive: { value: m.method === "thread/archived", at, version },
      };
      save();
      schedule();
    } else if (m.method === "thread/name/updated") {
      state[id] = {
        ...state[id],
        title: {
          value: m.params.threadName ?? m.params.name ?? "",
          at,
          version,
        },
      };
      save();
      schedule();
    } else if (m.method === "thread/started") schedule();
  });
  socket.on("error", () => {});
  socket.on("close", () => {
    if (!stopping) retry = setTimeout(connect, 1500);
  });
}
const poll = setInterval(schedule, 5000);
connect();
function stop() {
  stopping = true;
  clearInterval(poll);
  clearTimeout(retry);
  clearTimeout(debounce);
  socket?.close();
  if (!worker) setTimeout(() => process.exit(0), 100).unref();
}
process.on("SIGTERM", stop);
process.on("SIGINT", stop);
