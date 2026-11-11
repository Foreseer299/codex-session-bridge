"use strict";
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { createRequire } = require("node:module");
const { execFileSync } = require("node:child_process");
const ID = "codex-session-bridge";
function readJSON(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}
function findPackage(file, name) {
  let at = path.dirname(path.resolve(file));
  for (;;) {
    try {
      if (readJSON(path.join(at, "package.json")).name === name) return at;
    } catch {}
    const parent = path.dirname(at);
    if (parent === at) return null;
    at = parent;
  }
}
function hostPackage() {
  const direct = findPackage(process.argv[1], "@getpaseo/server");
  if (direct) return direct;
  let pid = process.ppid;
  for (let depth = 0; pid > 1 && depth < 8; depth++) {
    const args = fs.readFileSync(`/proc/${pid}/cmdline`, "utf8").split("\0");
    for (const arg of args) {
      if (!path.isAbsolute(arg)) continue;
      const found = findPackage(arg, "@getpaseo/server");
      if (found) return found;
    }
    const status = fs.readFileSync(`/proc/${pid}/status`, "utf8");
    pid = Number(/^PPid:\s*(\d+)/m.exec(status)?.[1]);
  }
  throw new Error(
    "Run installation through the Paseo daemon: paseo plugin add <Git URL>.",
  );
}
function discover(root) {
  if (process.platform !== "linux")
    throw new Error("This plugin currently supports Linux hosts.");
  const paseoPackage = hostPackage();
  if (readJSON(path.join(paseoPackage, "package.json")).version !== "0.15.3")
    throw new Error("Paseo 0.15.3 is required.");
  const paseoHome = path.resolve(
    process.env.PASEO_HOME || path.join(os.homedir(), ".paseo"),
  );
  const config = readJSON(path.join(paseoHome, "config.json"));
  root ||= config.plugins?.[ID]?.path;
  if (!root || readJSON(path.join(root, "paseo-plugin.json")).id !== ID)
    throw new Error(
      "Plugin installation record is missing. Custom --id is not supported.",
    );
  const resolver = createRequire(path.join(paseoPackage, "package.json"));
  const cliPackage = resolver.resolve("@getpaseo/cli/package.json");
  const cli = path.join(
    path.dirname(cliPackage),
    readJSON(cliPackage).bin.paseo,
  );
  const python = execFileSync(
    "python3",
    ["-c", "import sys; print(sys.executable)"],
    { encoding: "utf8", timeout: 5000 },
  ).trim();
  return {
    root: path.resolve(root),
    paseoHome,
    paseoPackage,
    paseoCli: cli,
    codexHome: path.resolve(
      process.env.CODEX_HOME || path.join(os.homedir(), ".codex"),
    ),
    node: process.execPath,
    python,
    daemonPid: process.ppid,
    runtime: path.join(paseoHome, "plugin-state", ID, "runtime"),
  };
}
function enabled(home) {
  const c = readJSON(path.join(home, "config.json"));
  return (
    c.pluginsEnabled === true &&
    c.plugins?.[ID] &&
    c.plugins[ID].enabled !== false
  );
}
function environment(options) {
  const env = {
    ...process.env,
    PATH:
      path.dirname(options.node) + path.delimiter + (process.env.PATH || ""),
    PASEO_HOME: options.paseoHome,
  };
  delete env.PASEO_HOST;
  env.CODEX_SESSION_BRIDGE_CONFIG = path.join(
    options.runtime,
    ".bridge-state/runtime.json",
  );
  return env;
}
module.exports = { ID, readJSON, findPackage, discover, enabled, environment };
