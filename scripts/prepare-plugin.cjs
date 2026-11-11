"use strict";
const fs = require("node:fs"),
  path = require("node:path"),
  os = require("node:os");
const { execFileSync } = require("node:child_process");
async function main() {
  if (
    process.platform !== "linux" ||
    Number(process.versions.node.split(".")[0]) < 24
  )
    throw new Error("Linux and Node.js 24+ are required.");
  const home = path.resolve(
    process.env.PASEO_HOME || path.join(os.homedir(), ".paseo"),
  );
  const codex = path.resolve(
    process.env.CODEX_HOME || path.join(os.homedir(), ".codex"),
  );
  execFileSync(
    "python3",
    ["-c", "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"],
    { stdio: "pipe", timeout: 5000 },
  );
  execFileSync("patch", ["--version"], { stdio: "pipe", timeout: 5000 });
  if (
    !fs
      .statSync(path.join(codex, "app-server-control/app-server-control.sock"))
      .isSocket()
  )
    throw new Error("The managed Codex socket is missing.");
  const version = execFileSync(
    path.join(codex, "packages/app-server-daemon/current/bin/codex"),
    ["--version"],
    { encoding: "utf8", timeout: 5000 },
  );
  if (!/(?<!\d)0\.167\.1\b/.test(version))
    throw new Error("Codex managed daemon 0.167.1 is required.");
  const config = JSON.parse(
    fs.readFileSync(path.join(home, "config.json"), "utf8"),
  );
  if (config.pluginsEnabled !== true) {
    // The build worker has no stable argv path (Paseo sets process.title).
    // Use the official SDK and instance-owned local credential only for this home.
    const { createHostClient } = await import("@getpaseo/client/node");
    const instance = JSON.parse(
      fs.readFileSync(path.join(home, "paseo.pid"), "utf8"),
    );
    const client = createHostClient(instance.listen, {
      clientId: "codex-session-bridge-setup",
      clientType: "cli",
      appVersion: "0.15.3",
      localCredential: () =>
        fs.readFileSync(path.join(home, "local-credential"), "utf8").trim(),
      reconnect: { enabled: false },
      connectTimeoutMs: 10000,
    });
    try {
      await client.connect();
      await client.patchDaemonConfig({ pluginsEnabled: true });
    } finally {
      await client.close();
    }
  }
  console.log(
    "Prerequisites checked; plugin runtime enabled. Automatic setup starts after registration.",
  );
}
main().catch((error) => {
  console.error(
    "Bridge preparation failed: " +
      (error.message?.startsWith("Codex managed") ||
      error.message?.startsWith("The managed") ||
      error.message?.startsWith("Linux")
        ? error.message
        : "Check Python 3.11+, patch, the existing daemon and local access."),
  );
  process.exitCode = 1;
});
