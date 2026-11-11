const assert = require("node:assert/strict"),
  fs = require("node:fs"),
  vm = require("node:vm"),
  { EventEmitter } = require("node:events");
const lines = new EventEmitter(),
  output = [],
  sent = [];
let socket;
class WS extends EventEmitter {
  constructor() {
    super();
    socket = this;
  }
  send(x) {
    sent.push(JSON.parse(x));
  }
  pause() {}
  resume() {}
  close() {}
  terminate() {}
}
const proc = {
  argv: ["node", "bridge", "app-server"],
  stdin: { destroy() {} },
  stdout: {
    write(x) {
      output.push(JSON.parse(x));
      return true;
    },
    once() {},
  },
  stderr: { write() {} },
  exit() {
    throw Error("Unexpected exit");
  },
};
vm.runInNewContext(
  fs.readFileSync(
    require("node:path").join(__dirname, "../bin/bridge.cjs"),
    "utf8",
  ),
  {
    process: proc,
    require: (n) =>
      n === "./runtime.cjs"
        ? { codexHome: "/example/codex", paseoHome: "/example/paseo" }
        : n === "ws"
          ? WS
          : n === "node:readline"
            ? { createInterface: () => lines }
            : require(n),
    setTimeout,
    clearTimeout,
  },
);
socket.emit("open");
const request = (m) => lines.emit("line", JSON.stringify(m)),
  reply = (m) => socket.emit("message", JSON.stringify(m));
request({ id: 1, method: "initialize", params: {} });
reply({ id: 1, result: { userAgent: "codex/0.167.1" } });
assert.equal(output.at(-1).result.paseoSharedDaemon, true);
const tid = "11111111-1111-4111-8111-111111111111";
request({
  id: 2,
  method: "thread/resume",
  params: { threadId: tid, config: { unrelated: "do not mutate" } },
});
assert.deepEqual(sent.at(-1).params, { threadId: tid, excludeTurns: true });
reply({ id: 2, result: { thread: { id: tid } } });
let count = output.length;
reply({
  id: 100,
  method: "item/tool/call",
  params: { threadId: tid, tool: "codex_app" },
});
assert.equal(
  output.length,
  count,
  "Desktop-only request must remain unanswered by Paseo",
);
reply({
  id: 101,
  method: "item/tool/requestUserInput",
  params: { threadId: tid },
});
assert.equal(output.at(-1).id, 101);
reply({ method: "serverRequest/resolved", params: { requestId: 101 } });
assert.equal(output.at(-1).method, "serverRequest/resolved");
count = output.length;
reply({ method: "item/started", params: { threadId: "other" } });
assert.equal(output.length, count, "Unrelated conversation must not leak");
reply({
  method: "item/started",
  params: { threadId: tid, item: { id: "live" } },
});
assert.equal(output.at(-1).params.item.id, "live");
console.log(
  "PASS: shared capability, scoped resume, Desktop request isolation, supported question forwarding, cross-client resolution, unrelated-thread isolation, live delivery",
);
