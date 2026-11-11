"use strict";
const fs = require("node:fs");
const path = require("node:path");
const { execFile, spawn } = require("node:child_process");
const { promisify } = require("node:util");
const run = promisify(execFile);
const { enabled, environment, readJSON } = require("./environment.cjs");
const { privateWrite } = require("./entry.cjs");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const IDLE = new Set(["idle", "error", "closed", "archived"]);
function allIdle(rows) {
  return (
    Array.isArray(rows) &&
    rows.every((row) => typeof row.status === "string" && IDLE.has(row.status))
  );
}
async function daemonAvailable(socketPath) {
  return await new Promise(resolve => {
    const socket = require("node:net").createConnection(socketPath);
    let settled = false;
    const finish = value => { if (settled) return; settled = true; socket.destroy(); resolve(value); };
    socket.setTimeout(1500, () => finish(false));
    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
  });
}
async function main(options) {
  const env = environment(options),
    root = options.runtime;
  const stateDir = path.join(root, ".bridge-state");
  fs.mkdirSync(stateDir, { recursive: true, mode: 0o700 });
  const lease = path.join(stateDir, "controller.pid");
  const marker = path.join(stateDir, "restart.json");
  const statusFile = path.join(stateDir, "status.json");
  let stopping = false,
    removing = false,
    watcher = null,
    lastStatus = "",
    restartRequested = false;
  process.stdout.on("error", () => {});
  process.stderr.on("error", () => {});
  const report = (phase, detail = "") => {
    privateWrite(
      statusFile,
      JSON.stringify({ phase, detail, at: new Date().toISOString() }),
    );
    if (phase !== lastStatus) {
      console.log(
        "Codex Session Bridge: " + phase + (detail ? " — " + detail : ""),
      );
      lastStatus = phase;
    }
  };
  const stopWatch = () => {
    if (watcher) {
      watcher.kill("SIGTERM");
      watcher = null;
    }
  };
  process.on("SIGTERM", () => {
    stopping = true;
    stopWatch();
  });
  process.on("SIGINT", () => {
    stopping = true;
    stopWatch();
  });
  process.on("message", (m) => {
    if (m?.type === "remove") {
      removing = true;
      stopWatch();
    }
  });
  process.on("disconnect", () => {
    try {
      if (!enabled(options.paseoHome)) removing = true;
      else stopping = true;
    } catch {
      stopping = true;
    }
    stopWatch();
  });
  for (let tries = 0; ; tries++) {
    try {
      fs.writeFileSync(lease, String(process.pid), { flag: "wx", mode: 0o600 });
      break;
    } catch (error) {
      if (error.code !== "EEXIST") throw error;
      const pid = Number(fs.readFileSync(lease, "utf8"));
      let alive = false;
      try {
        process.kill(pid, 0);
        alive = true;
      } catch {}
      if (!alive) {
        fs.unlinkSync(lease);
        continue;
      }
      if (tries >= 30)
        throw new Error(
          "Another bridge controller is still active. Reload this plugin after it stops.",
        );
      await sleep(500);
    }
  }
  const cli = async (...args) => {
    const r = await run(
      options.node,
      [options.paseoCli, ...args, "--home", options.paseoHome, "--json"],
      { env, timeout: 30000, maxBuffer: 32 * 1024 * 1024 },
    );
    return JSON.parse(r.stdout);
  };
  const managed = async (uninstall = false, check = false) => {
    const args = [
      path.join(root, "scripts/managed.py"),
      "--paseo-home",
      options.paseoHome,
      "--paseo-package",
      options.paseoPackage,
      "--codex-home",
      options.codexHome,
      "--paseo-cli",
      options.paseoCli,
      "--node",
      options.node,
      "--python",
      options.python,
    ];
    if (uninstall) args.push("--uninstall");
    if (check) args.push("--check");
    try {
      return JSON.parse(
        (
          await run(options.python, args, {
            env,
            timeout: 45000,
            maxBuffer: 1024 * 1024,
          })
        ).stdout,
      );
    } catch (e) {
      let reason;
      try {
        reason = JSON.parse(e.stderr).error;
      } catch {}
      throw new Error(
        "Error: " +
          (typeof reason === "string"
            ? reason
            : "Compatibility installation failed; inspect supported versions and local file changes."),
      );
    }
  };
  const restart = () => {
    report(removing ? "restored_restart_pending" : "installed_restart_pending");
    privateWrite(
      marker,
      JSON.stringify({
        daemonPid: options.daemonPid,
        at: Date.now(),
        removing,
      }),
    );
    const child = spawn(
      options.node,
      [
        options.paseoCli,
        "daemon",
        "restart",
        "--home",
        options.paseoHome,
        "--timeout",
        "60",
      ],
      { env, detached: true, stdio: "ignore" },
    );
    child.on("error", () =>
      report("restart_failed", "Paseo could not start its restart command."),
    );
    child.unref();
    restartRequested = true;
  };
  try {
    await sleep(1500); // Let plugin installation/registration finish before lifecycle work.
    if (fs.existsSync(marker)) {
      const previous = readJSON(marker);
      if (previous.daemonPid !== options.daemonPid) fs.unlinkSync(marker);
      else restartRequested = true;
    }
    while (!stopping) {
      if (!enabled(options.paseoHome)) removing = true;
      if (removing) stopWatch();
      if (restartRequested && !removing) {
        const previous = readJSON(marker);
        if (Date.now() - previous.at > 65000) {
          report(
            "restart_failed",
            "Run paseo daemon restart once; no automatic restart loop.",
          );
          break;
        }
        await sleep(1000);
        continue;
      }
      if (!removing && watcher) {
        await sleep(1000);
        continue;
      }
      if (!removing && !await daemonAvailable(path.join(options.codexHome, "app-server-control/app-server-control.sock"))) {
        report("waiting_for_codex", "The private Codex daemon is not ready; retrying automatically.");
        await sleep(3000);
        continue;
      }
      let rows;
      try {
        rows = await cli("ls", "--all");
      } catch {
        report("waiting_for_paseo");
        await sleep(3000);
        continue;
      }
      if (!allIdle(rows)) {
        report(removing ? "waiting_to_restore" : "waiting_for_idle");
        await sleep(3000);
        continue;
      }
      // A second fresh check reduces the chance of restarting over newly started work.
      await sleep(750);
      if (stopping) break;
      if (!allIdle(await cli("ls", "--all"))) continue;
      const journal = path.join(stateDir, "managed.json");
      if (fs.existsSync(journal) && readJSON(journal).phase !== "installed")
        await managed(true);
      const actionWasRemoval = removing;
      let result;
      try { result = await managed(actionWasRemoval); }
      catch (error) {
        if (!actionWasRemoval && error.message?.includes("daemon socket is missing")) {
          report("waiting_for_codex");
          await sleep(3000);
          continue;
        }
        throw error;
      }
      if (removing && !actionWasRemoval) result = await managed(true);
      if (result.changed) {
        restart();
        if (removing) break;
        continue;
      }
      if (removing) {
        report("removed");
        break;
      }
      // Probe RPC without logging or saving private session metadata.
      try {
        await run(
          options.node,
          [path.join(root, "bin/bridge.cjs"), "--snapshot"],
          { env, timeout: 15000, maxBuffer: 32 * 1024 * 1024 },
        );
      } catch {
        report("waiting_for_codex", "Codex RPC is unavailable; retrying automatically.");
        await sleep(3000);
        continue;
      }
      watcher = spawn(options.node, [path.join(root, "bin/watch.cjs")], {
        env,
        stdio: ["ignore", "inherit", "inherit"],
      });
      watcher.on("error", () => report("watcher_failed"));
      watcher.on("close", () => {
        watcher = null;
      });
      report("ready");
      await sleep(1000);
    }
  } catch (error) {
    report(
      "error",
      error.message?.startsWith("Error:")
        ? error.message
        : "Automatic setup failed; check versions, daemon availability and local modifications.",
    );
  } finally {
    stopWatch();
    try {
      if (fs.readFileSync(lease, "utf8") === String(process.pid))
        fs.unlinkSync(lease);
    } catch {}
    if (process.connected) process.disconnect();
  }
}
if (require.main === module) {
  main(readJSON(process.argv[2])).catch(() => {
    console.error("Bridge controller could not start.");
    process.exitCode = 1;
  });
}
module.exports = { allIdle, daemonAvailable };
