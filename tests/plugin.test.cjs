"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { allIdle } = require("../server/controller.cjs");
const { stageRuntime } = require("../server/entry.cjs");
const { findPackage, enabled } = require("../server/environment.cjs");
test("automatic restart refuses running, waiting and unknown states", () => {
  assert.equal(allIdle([{ status: "running" }]), false);
  assert.equal(allIdle([{ status: "waiting_permission" }]), false);
  assert.equal(allIdle([{ status: "future-status" }]), false);
  assert.equal(allIdle({}), false);
  assert.equal(allIdle([{ status: "idle" }, { status: "error" }]), true);
  assert.equal(allIdle([]), true);
});
test("runtime staging leaves private state intact and refuses edited runtime assets", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bridge-plugin-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const runtime = path.join(root, "runtime");
  const options = { root: path.resolve(__dirname, ".."), runtime };
  stageRuntime(options);
  const state = path.join(runtime, ".bridge-state");
  fs.mkdirSync(state, { mode: 0o700 });
  fs.writeFileSync(path.join(state, "private.json"), "preserve me");
  stageRuntime(options);
  assert.equal(
    fs.readFileSync(path.join(state, "private.json"), "utf8"),
    "preserve me",
  );
  assert.equal(
    fs.statSync(path.join(runtime, "bin/bridge.cjs")).mode & 0o777,
    0o600,
  );
  fs.appendFileSync(path.join(runtime, "bin/bridge.cjs"), "// local change");
  assert.throws(() => stageRuntime(options), /edited/);
});
test("package discovery identifies the actual ancestor rather than an arbitrary global installation", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bridge-package-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.writeFileSync(
    path.join(root, "package.json"),
    JSON.stringify({ name: "@getpaseo/server" }),
  );
  const child = path.join(root, "dist/server/plugin-process.js");
  assert.equal(findPackage(child, "@getpaseo/server"), root);
  assert.equal(findPackage(child, "@other/server"), null);
});
test("removal and both plugin disable switches are recognized", (t) => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "bridge-disable-test-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const write = (c) =>
    fs.writeFileSync(path.join(root, "config.json"), JSON.stringify(c));
  write({
    pluginsEnabled: true,
    plugins: { "codex-session-bridge": { enabled: true } },
  });
  assert.equal(Boolean(enabled(root)), true);
  write({
    pluginsEnabled: false,
    plugins: { "codex-session-bridge": { enabled: true } },
  });
  assert.equal(Boolean(enabled(root)), false);
  write({
    pluginsEnabled: true,
    plugins: { "codex-session-bridge": { enabled: false } },
  });
  assert.equal(Boolean(enabled(root)), false);
  write({ pluginsEnabled: true, plugins: {} });
  assert.equal(Boolean(enabled(root)), false);
});
