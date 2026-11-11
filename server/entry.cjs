"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { createHash } = require("node:crypto");
const { spawn } = require("node:child_process");
const {
  discover,
  enabled,
  readJSON,
  environment,
} = require("./environment.cjs");
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
function privateWrite(file, bytes) {
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  if (fs.existsSync(file) && fs.lstatSync(file).isSymbolicLink())
    throw new Error("Refusing symlinked runtime file.");
  const tmp = file + ".new";
  fs.writeFileSync(tmp, bytes, { mode: 0o600 });
  fs.renameSync(tmp, file);
}
function stageRuntime(options) {
  const root = options.root,
    destination = options.runtime;
  fs.mkdirSync(destination, { recursive: true, mode: 0o700 });
  if (fs.lstatSync(destination).isSymbolicLink())
    throw new Error("Refusing symlinked runtime directory.");
  const inventoryPath = path.join(destination, ".asset-hashes.json");
  const old = fs.existsSync(inventoryPath) ? readJSON(inventoryPath) : {};
  const assets = {};
  for (const [dir, suffixes] of [
    ["bin", [".cjs"]],
    ["scripts", [".py", ".cjs"]],
    ["server", [".cjs"]],
    ["patches", [".patch", ".json"]],
  ]) {
    for (const name of fs.readdirSync(path.join(root, dir))) {
      if (suffixes.some((x) => name.endsWith(x)))
        assets[dir + "/" + name] = fs.readFileSync(path.join(root, dir, name));
    }
  }
  assets["package.json"] = fs.readFileSync(path.join(root, "package.json"));
  const wsRoot = path.join(root, "node_modules/ws");
  for (const file of [
    "package.json",
    "index.js",
    "wrapper.mjs",
    "LICENSE",
    ...fs.readdirSync(path.join(wsRoot, "lib")).map((x) => "lib/" + x),
  ]) {
    assets["node_modules/ws/" + file] = fs.readFileSync(
      path.join(wsRoot, file),
    );
  }
  for (const [name, digest] of Object.entries(old)) {
    const file = path.join(destination, name);
    if (!fs.existsSync(file) || hash(fs.readFileSync(file)) !== digest)
      throw new Error(
        "Runtime files were edited; restore them before updating the plugin.",
      );
  }
  const state = path.join(destination, ".bridge-state/managed.json");
  if (
    fs.existsSync(state) &&
    old["patches/manifest.json"] !== hash(assets["patches/manifest.json"])
  )
    throw new Error(
      "Compatibility patches changed; remove the previous plugin version before upgrading.",
    );
  for (const [name, bytes] of Object.entries(assets))
    privateWrite(path.join(destination, name), bytes);
  privateWrite(
    inventoryPath,
    JSON.stringify(
      Object.fromEntries(Object.entries(assets).map(([n, b]) => [n, hash(b)])),
    ),
  );
}
function activate() {
  const options = discover();
  stageRuntime(options);
  const boot = path.join(options.runtime, ".controller.json");
  privateWrite(boot, JSON.stringify(options));
  const child = spawn(
    options.node,
    [path.join(options.runtime, "server/controller.cjs"), boot],
    {
      env: environment(options),
      detached: true,
      stdio: ["ignore", "pipe", "pipe", "ipc"],
    },
  );
  child.stdout.on("data", (chunk) => process.stdout.write(chunk));
  child.stderr.on("data", (chunk) => process.stderr.write(chunk));
  child.on("error", () =>
    console.error("Codex Session Bridge controller could not start."),
  );
  return () => {
    // A normal daemon restart/reload keeps the integration installed. Disable/remove
    // hands rollback to the short-lived detached controller after this plugin stops.
    let active = true;
    try {
      active = Boolean(enabled(options.paseoHome));
    } catch {}
    if (active) child.kill("SIGTERM");
    else if (child.connected) child.send({ type: "remove" });
    child.stdout.destroy();
    child.stderr.destroy();
    if (child.connected) child.disconnect();
    child.unref();
  };
}
module.exports = { activate, stageRuntime, privateWrite };
