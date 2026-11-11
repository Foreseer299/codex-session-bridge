#!/usr/bin/env node
"use strict";
const fs = require("node:fs"),
  path = require("node:path"),
  os = require("node:os");
const { version } = require("../package.json");
const ID = "codex-session-bridge";
async function main() {
  const args = process.argv.slice(2),
    option = (key, fallback) => {
      const i = args.indexOf(key);
      return i >= 0 ? args[i + 1] : fallback;
    };
  const home = path.resolve(
    option(
      "--home",
      process.env.PASEO_HOME || path.join(os.homedir(), ".paseo"),
    ),
  );
  const source = option(
    "--source",
    "https://github.com/Foreseer299/codex-session-bridge.git",
  );
  const ref = option("--ref", "v" + version);
  const { createHostClient } = await import("@getpaseo/client/node");
  async function connect() {
    const instance = JSON.parse(
      fs.readFileSync(path.join(home, "paseo.pid"), "utf8"),
    );
    const c = createHostClient(instance.listen, {
      clientId: "codex-session-bridge-installer",
      clientType: "cli",
      appVersion: "0.15.3",
      localCredential: () =>
        fs.readFileSync(path.join(home, "local-credential"), "utf8").trim(),
      reconnect: { enabled: false },
      connectTimeoutMs: 10000,
    });
    await c.connect();
    return c;
  }
  let client = await connect();
  try {
    // Enable outside the plugin-install queue so the native add result is accurate.
    const config = JSON.parse(
      fs.readFileSync(path.join(home, "config.json"), "utf8"),
    );
    if (config.pluginsEnabled !== true)
      await client.patchDaemonConfig({ pluginsEnabled: true });
    await new Promise((r) => setTimeout(r, 300));
    const exists = (await client.listPlugins()).find((x) => x.id === ID);
    if (!exists) await client.installPluginSource({ source, ref });
    else {
      if (exists.enabled === false) await client.enablePlugin(ID);
      console.log("Plugin is already registered; checking its current state.");
    }
  } finally {
    await client.close();
  }
  console.log("Native Paseo plugin registered. Waiting for automatic setup…");
  let last = "";
  for (let i = 0; i < 90; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    try {
      client = await connect();
      const logs = await client.getPluginLogs(ID);
      const line =
        logs.filter((x) => x.message.includes("Codex Session Bridge:")).at(-1)
          ?.message || "";
      if (line && line !== last) {
        console.log(line);
        last = line;
      }
      if (line.includes("Codex Session Bridge: ready")) return;
      if (line.includes("Codex Session Bridge: error"))
        throw new Error("SETUP_ERROR");
      if (line.includes("waiting_for_idle")) {
        console.log(
          "Setup will continue automatically when Paseo tasks are idle.",
        );
        return;
      }
    } catch (error) {
      if (error.message === "SETUP_ERROR") throw error;
    } finally {
      await client?.close().catch(() => {});
    }
  }
  console.log(
    "Still pending. Inspect progress with: paseo plugin logs codex-session-bridge",
  );
}
main().catch(() => {
  console.error(
    "Installation did not complete. Check that Paseo is running and inspect: paseo plugin logs codex-session-bridge",
  );
  process.exitCode = 1;
});
