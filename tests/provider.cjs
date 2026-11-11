// Integration tests against the actual supported, patched Paseo provider.
// Set PASEO_TEST_PACKAGE to an isolated @getpaseo/server installation.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
(async () => {
  if (!process.env.PASEO_TEST_PACKAGE) { console.log('SKIP provider integration: set PASEO_TEST_PACKAGE'); return; }
  const {CodexAppServerAgentSession} = await import(pathToFileURL((process.env.PASEO_TEST_PROVIDER_FILE || path.join(process.env.PASEO_TEST_PACKAGE, 'dist/server/server/agent/providers/codex-app-server-agent.js'))));
  const logger = { child() {return this}, trace(){}, debug(){}, info(){}, warn(){}, error(){} };
  const session = new CodexAppServerAgentSession({cwd:'/example'}, null, logger, () => {throw Error('No model processes allowed')});
  session.currentThreadId = 'root'; session.sharedDaemon = true;
  const states = {done:'completed',broken:'failed',stopped:'interrupted',busy:'inProgress',nested:'completed'};
  const activity = id => ({type:'subAgentActivity',id:'launch-'+id,kind:'started',agentThreadId:id,agentPath:'/root/'+id});
  const client = { async request(method,p) {
    if (method === 'thread/turns/list') return {data:[{id:'turn-'+p.threadId,status:states[p.threadId]}]};
    assert.equal(method,'thread/read');
    const items = p.threadId === 'root' ? ['done','broken','stopped','busy'].map(activity) : p.threadId === 'done' ? [activity('nested')] : [];
    return {thread:{turns:[{id:'turn-'+p.threadId,items}]}};
  }};
  const history = await session.readThreadHistory(client);
  const latest = new Map(history.providerSubagentEvents.filter(e=>e.event.type==='upsert').map(e=>[e.event.id,e.event.status]));
  assert.deepEqual(Object.fromEntries(latest),{done:'completed',nested:'completed',broken:'failed',stopped:'canceled',busy:'running'});
  // A late parent announcement must recover a child that already completed.
  session.client = client;
  session.registerSubAgentToolCall({timelineItem:{type:'tool_call',callId:'late',name:'spawn_agent',status:'running',error:null,detail:{type:'sub_agent',subAgentType:'Late'}},rawItem:{agentThreadId:'late-child'},parentCallId:null,parentSubagentId:null});
  states['late-child'] = 'completed';
  await session.syncSharedSubAgentStatus(client,'late-child','late');
  assert.equal(session.subAgentCallsByCallId.get('late').toolCall.status,'completed');
  const events=[]; session.subscribers.add(e=>events.push(e));
  await session.handleNotification('turn/started',{threadId:'done',turn:{id:'followup',status:'inProgress',items:[],error:null}});
  assert.equal(events.filter(e=>e.type==='provider_subagent').at(-1).event.status,'running');
  await session.handleNotification('turn/completed',{threadId:'done',turn:{id:'followup',status:'completed',items:[],error:null}});
  assert.equal(events.filter(e=>e.type==='provider_subagent').at(-1).event.status,'completed');
  let resolve;
  const delayed={request(){return new Promise(r=>{resolve=r})}};
  const before=events.length;
  const restore=session.syncSharedSubAgentStatus(delayed,'done',session.subAgentCallIdByChildThreadId.get('done'));
  await session.handleNotification('turn/started',{threadId:'done',turn:{id:'newer',status:'inProgress',items:[],error:null}});
  resolve({data:[{status:'completed'}]});await restore;
  assert.equal(events.slice(before).filter(e=>e.type==='provider_subagent').at(-1).event.status,'running','A stale read must not overwrite a newer live turn');
  const reconnect = new CodexAppServerAgentSession({}, null, logger, () => {});
  reconnect.sharedDaemon = true;
  reconnect.connectionState = 'disconnected';
  let attempts = 0;
  reconnect.connect = async () => { if (++attempts === 1) throw Error('temporary socket outage'); reconnect.connectionState = 'connected'; };
  const recovered = new Promise((resolve,reject) => {
    const timeout = setTimeout(() => reject(Error('Reconnect did not recover')), 6000);
    reconnect.subscribers.add(e => { if(e.type === 'shared_history_refresh') {clearTimeout(timeout); resolve();} });
  });
  reconnect.scheduleSharedReconnect(); reconnect.scheduleSharedReconnect();
  await recovered;
  assert.equal(attempts,2,'One timer, then retry after a transient failure');
  reconnect.closed = true; reconnect.scheduleSharedReconnect();
  assert.equal(reconnect.sharedReconnectTimer,null,'Closed sessions must not reconnect');
  console.log('PASS provider: reconnect retries and closed-session cleanup');
  console.log('PASS provider: cold completion/failure/cancellation/running/nesting, live follow-up, stale-response race');
})().catch(e=>{console.error(e);process.exitCode=1});
