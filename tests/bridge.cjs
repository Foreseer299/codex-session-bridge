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
const child = '22222222-2222-4222-8222-222222222222';
reply({ method: 'item/completed', params: { threadId: tid, item: { type: 'subAgentActivity', kind: 'started', agentThreadId: child } } });
reply({ method: 'turn/completed', params: { threadId: child, turn: { status: 'completed' } } });
assert.equal(output.at(-1).params.threadId, child, 'Child completion must reach Paseo');
count = output.length;
reply({ id: 102, method: 'item/tool/call', params: { threadId: child } });
assert.equal(output.length, count, 'Child Desktop tools must remain isolated');
const grandchild = '33333333-3333-4333-8333-333333333333';
reply({ method: 'item/completed', params: { threadId: child, item: { type: 'collabAgentToolCall', tool: 'spawnAgent', receiverThreadIds: [grandchild] } } });
reply({ method: 'turn/completed', params: { threadId: grandchild, turn: { status: 'failed' } } });
assert.equal(output.at(-1).params.threadId, grandchild, 'Nested descendants must receive lifecycle updates');
const restored = '44444444-4444-4444-8444-444444444444';
request({ id: 3, method: 'thread/items/list', params: { threadId: tid } });
reply({ id: 3, error: { message: 'thread/items/list is not supported' } });
reply({ id: 3, result: { thread: { turns: [{ items: [{ type: 'subAgentActivity', kind: 'started', agentThreadId: restored }] }] } } });
reply({ method: 'turn/started', params: { threadId: restored, turn: { status: 'inProgress' } } });
assert.equal(output.at(-1).params.threadId, restored, 'Cold history must rebuild descendant routes');
request({ id: 4, method: 'thread/read', params: { threadId: 'unrelated' } });
reply({ id: 4, result: { thread: { turns: [{ items: [{ type: 'subAgentActivity', kind: 'started', agentThreadId: 'unrelated-child' }] }] } } });
count = output.length;
reply({ method: 'turn/completed', params: { threadId: 'unrelated-child', turn: { status: 'completed' } } });
assert.equal(output.length, count, 'Reading another history must not subscribe to unrelated descendants');
console.log('PASS: live/cold/nested child lifecycle, unrelated descendant isolation');
reply({ method: 'codex/event/item_completed', params: { msg: { thread_id: tid, item: {type:'subAgentActivity',kind:'started',agentThreadId:'legacy-child'} } } });
reply({ method: 'codex/event/task_complete', params: { msg: { thread_id:'legacy-child' } } });
assert.equal(output.at(-1).params.msg.thread_id,'legacy-child','Legacy descendant lifecycle remains scoped and delivered');
reply({ method:'item/completed',params:{threadId:tid,item:{type:'collabAgentToolCall',tool:'sendInput',receiverThreadIds:['unrelated-target']}} });
count=output.length;
reply({method:'turn/completed',params:{threadId:'unrelated-target',turn:{status:'completed'}}});
assert.equal(output.length,count,'Sending to another agent must not claim it as a descendant');
console.log('PASS: legacy lifecycle routing and non-spawn isolation');
