#!/usr/bin/env node
"use strict";

const { execFileSync } = require("node:child_process");
const { closeSync, openSync, readFileSync } = require("node:fs");
const readline = require("node:readline");
const WebSocket = require("ws");

const config = require("./runtime.cjs");
const codexHome = config.codexHome;
const socketPath = codexHome + "/app-server-control/app-server-control.sock";
const paseoThreadMarkers = require("node:path").join(
  config.paseoHome,
  "codex-shared-created",
);
const operation = process.argv[2];
const snapshot = operation === "--snapshot" || operation === "--snapshot-all";
const metadata = operation === "--metadata";

if (process.argv[2] === "--version" || process.argv[2] === "-V") {
  process.stdout.write(
    execFileSync(codexHome + "/packages/app-server-daemon/current/bin/codex", [
      "--version",
    ]),
  );
  process.exit(0);
}
if (!snapshot && !metadata && operation !== "app-server") process.exit(2);

const setupMethods = new Set([
  "initialize",
  "initialized",
  "model/list",
  "config/read",
  "getUserSavedConfig",
  "collaborationMode/list",
  "skills/list",
  "thread/list",
  "thread/archive",
  "thread/unarchive",
]);
// Shared daemon server requests are multicast. Paseo must never answer Desktop-only
// tools: its transport returns an empty result for unknown methods, winning the race.
const paseoServerRequests = new Set([
  "item/commandExecution/requestApproval",
  "item/fileChange/requestApproval",
  "item/tool/requestUserInput",
  "tool/requestUserInput",
  "mcpServer/elicitation/request",
]);
const historyMethods = new Set([
  "thread/read",
  "thread/items/list",
  "thread/turns/list",
]);
const sessionMethods = new Set([
  "thread/backgroundTerminals/list",
  "thread/goal/get",
  "thread/goal/set",
  "thread/goal/clear",
  "thread/compact/start",
  "thread/rollback",
  "turn/start",
  "turn/steer",
  "turn/interrupt",
]);
const socket = new WebSocket("ws+unix://" + socketPath + ":/", {
  maxPayload: 128 * 1024 * 1024,
  handshakeTimeout: 5000,
});
let pendingThread;
let threadId;
let initializationId;
let freshThreadId;
const itemReads = new Map();
const historyReads = new Map();
const childThreads = new Set();
const forwardedServerRequests = new Set();
let waitingForDrain = false;

function write(message) {
  if (
    !process.stdout.write(JSON.stringify(message) + "\n") &&
    !waitingForDrain
  ) {
    waitingForDrain = true;
    socket.pause();
    process.stdout.once("drain", () => {
      waitingForDrain = false;
      socket.resume();
    });
  }
}

function startBridge() {
  const lines = readline.createInterface({
    input: process.stdin,
    crlfDelay: Infinity,
  });
  lines.on("line", (line) => {
    const request = JSON.parse(line);
    const { id, method, params } = request;
    if (method === "initialize") initializationId = id;
    if (historyMethods.has(method) && id !== undefined)
      historyReads.set(id, params?.threadId);
    if (
      method === "thread/items/list" &&
      freshThreadId &&
      params?.threadId === freshThreadId
    ) {
      // Codex does not expose item pagination before this connection starts a first turn.
      write({ id, result: { data: [], nextCursor: null } });
    } else if (method === "thread/items/list" && !params?.cursor) {
      itemReads.set(id, { params });
      socket.send(line);
    } else if (
      !method ||
      setupMethods.has(method) ||
      historyMethods.has(method) ||
      (threadId && sessionMethods.has(method) && params?.threadId === threadId)
    ) {
      if (method === "turn/start") freshThreadId = undefined;
      socket.send(line);
    } else if (method === "thread/loaded/list") {
      // A thread can be loaded by Desktop before this connection subscribes.
      write({ id, result: { data: threadId ? [threadId] : [] } });
    } else if (
      !pendingThread &&
      ((method === "thread/start" && !threadId) ||
        (method === "thread/fork" && threadId && params?.threadId === threadId))
    ) {
      pendingThread = { id, fresh: method === "thread/start" };
      socket.send(line);
    } else if (
      method === "thread/resume" &&
      typeof params?.threadId === "string" &&
      !pendingThread &&
      (!threadId || threadId === params.threadId)
    ) {
      pendingThread = { id, threadId: params.threadId };
      socket.send(
        JSON.stringify({
          id,
          method,
          params: { threadId: params.threadId, excludeTurns: true },
        }),
      );
    } else if (id !== undefined) {
      write({
        id,
        error: {
          code: -32602,
          message:
            "This Codex connection can operate on one conversation at a time.",
        },
      });
    }
  });
  lines.on("close", () => socket.close());
}

// Only discover descendants through an already-owned parent. Never forward the
// shared daemon's unrelated conversations or Desktop-only server requests.
function learnChildren(parentId, items) {
  if (!parentId || (parentId !== threadId && parentId !== pendingThread?.threadId && !childThreads.has(parentId))) return;
  for (const item of items) {
    if (!item || !["subAgentActivity", "sub_agent_activity", "collabAgentToolCall", "collab_agent_tool_call"].includes(item.type)) continue;
    if (["collabAgentToolCall", "collab_agent_tool_call"].includes(item.type) && item.tool !== "spawnAgent") continue;
    if (["subAgentActivity", "sub_agent_activity"].includes(item.type) && item.kind !== "started") continue;
    for (const child of [item.agentThreadId, ...(item.receiverThreadIds ?? [])]) {
      if (typeof child === "string" && child !== threadId) childThreads.add(child);
    }
  }
}

function forwardMessage(data) {
  const message = JSON.parse(data);
  if (!message.method) {
    if (message.id === initializationId && message.result)
      message.result.paseoSharedDaemon = true;
    const itemRead = itemReads.get(message.id);
    if (itemRead) {
      if (
        !itemRead.fallback &&
        message.error?.message?.includes("thread/items/list is not supported")
      ) {
        itemRead.fallback = true;
        socket.send(
          JSON.stringify({
            id: message.id,
            method: "thread/read",
            params: { threadId: itemRead.params.threadId, includeTurns: true },
          }),
        );
        return;
      }
      itemReads.delete(message.id);
      if (itemRead.fallback && Array.isArray(message.result?.thread?.turns)) {
        // Paseo's forward history scan can consume a legacy full read as its last page.
        message.result = {
          data: message.result.thread.turns.flatMap((turn) =>
            (turn.items ?? []).map((item) => ({
              turnId: turn.id,
              item,
              startedAtMs:
                typeof turn.startedAt === "number"
                  ? turn.startedAt * 1000
                  : null,
              completedAtMs:
                typeof turn.completedAt === "number"
                  ? turn.completedAt * 1000
                  : null,
            })),
          ),
          nextCursor: null,
        };
      }
    }
    if (pendingThread && message.id === pendingThread.id) {
      const nativeId = message.result?.thread?.id;
      if (pendingThread.threadId) {
        if (nativeId === pendingThread.threadId) threadId = nativeId;
      } else if (
        typeof nativeId === "string" &&
        /^[0-9a-f-]{36}$/i.test(nativeId)
      ) {
        threadId = nativeId;
        if (pendingThread.fresh) freshThreadId = nativeId;
        if (!message.result.thread.ephemeral) {
          // Mark ownership before Paseo can send the first turn and persist the rollout.
          try {
            closeSync(
              openSync(paseoThreadMarkers + "/" + nativeId, "a", 0o600),
            );
          } catch {
            process.stderr.write(
              "Unable to mark the new shared Codex conversation as Paseo-owned.\n",
            );
          }
        }
      }
      pendingThread = undefined;
    }
    const historyParent = historyReads.get(message.id);
    historyReads.delete(message.id);
    if (historyParent) {
      learnChildren(historyParent, [
        ...(message.result?.thread?.turns ?? []).flatMap(turn => turn.items ?? []),
        ...(message.result?.data ?? []).flatMap(row => row.item ? [row.item] : (row.items ?? [])),
      ]);
    }
    write(message);
    return;
  }
  if (
    message.method === "serverRequest/resolved" &&
    forwardedServerRequests.delete(message.params?.requestId)
  ) {
    write(message);
    return;
  }
  if (message.id !== undefined && !paseoServerRequests.has(message.method))
    return;
  const eventThreadId = message.params?.threadId ?? message.params?.thread?.id ?? message.params?.thread_id ?? message.params?.msg?.threadId ?? message.params?.msg?.thread_id;
  if (
    eventThreadId &&
    (eventThreadId === threadId || eventThreadId === pendingThread?.threadId || childThreads.has(eventThreadId))
  ) {
    learnChildren(eventThreadId, [message.params?.item ?? message.params?.msg?.item]);
    if (message.id !== undefined) forwardedServerRequests.add(message.id);
    write(message);
  }
}

function listSessions() {
  const sessions = [];
  const send = (id, method, params) =>
    socket.send(JSON.stringify({ id, method, params }));
  const timeout = setTimeout(() => socket.terminate(), 10000);
  let complete = false;
  let archived = false;
  const list = (cursor) =>
    send(2, "thread/list", {
      cursor,
      limit: 100,
      archived,
      useStateDbOnly: true,
      modelProviders: [],
      sourceKinds: ["vscode", "cli", "appServer"],
      sortKey: "created_at",
    });
  socket.on("close", () => {
    clearTimeout(timeout);
    if (!complete) process.exitCode = 1;
  });
  socket.on("message", (data) => {
    const { id, result, error } = JSON.parse(data);
    if (error && id) {
      socket.close();
    } else if (id === 1) {
      send(undefined, "initialized", {});
      list();
    } else if (id === 2) {
      for (const {
        id,
        cwd,
        path,
        name,
        createdAt,
        source,
        originator,
        parentThreadId,
        ephemeral,
      } of result.data) {
        sessions.push({
          id,
          cwd,
          path,
          name,
          createdAt,
          archived,
          source,
          originator,
          parentThreadId,
          ephemeral,
        });
      }
      if (result.nextCursor) {
        list(result.nextCursor);
      } else if (!archived && operation === "--snapshot-all") {
        archived = true;
        list();
      } else {
        write(sessions);
        complete = true;
        socket.close();
      }
    }
  });
  send(1, "initialize", {
    clientInfo: {
      name: "codex_app_server_daemon",
      title: "Paseo Codex history sync",
      version: "1.0.0",
    },
    capabilities: { experimentalApi: true },
  });
}

function updateMetadata() {
  const { method, params } = JSON.parse(readFileSync(0, "utf8"));
  if (
    !["thread/name/set", "thread/archive", "thread/unarchive"].includes(method)
  ) {
    process.exitCode = 2;
    socket.close();
    return;
  }
  const send = (id, method, params) =>
    socket.send(JSON.stringify({ id, method, params }));
  const timeout = setTimeout(() => {
    process.exitCode = 1;
    socket.terminate();
  }, 10000);
  socket.on("close", () => clearTimeout(timeout));
  socket.on("message", (data) => {
    const message = JSON.parse(data);
    if (message.id === 1 && message.result) {
      send(undefined, "initialized", {});
      send(2, method, params);
    } else if (message.id === 1 || message.id === 2) {
      if (message.error) process.exitCode = 1;
      socket.close();
    }
  });
  send(1, "initialize", {
    clientInfo: {
      name: "codex_app_server_daemon",
      title: "Paseo Codex history sync",
      version: "1.0.0",
    },
    capabilities: { experimentalApi: true },
  });
}

socket.on(
  "open",
  snapshot ? listSessions : metadata ? updateMetadata : startBridge,
);
if (!snapshot && !metadata) socket.on("message", forwardMessage);

socket.on("error", () => {
  process.stderr.write(
    "Unable to connect to the private Codex Desktop socket.\n",
  );
  process.exitCode = 1;
});
socket.on("close", () => process.stdin.destroy());
