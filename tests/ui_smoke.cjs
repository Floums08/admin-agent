/* DOM + real API integration tests. This is NOT a browser or visual-layout test. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const {spawn} = require('node:child_process');
const {webcrypto} = require('node:crypto');
const {parseHTML} = require('linkedom');
const root = path.resolve(__dirname, '..');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'admin-agent-ui-'));
const nativeFetch = global.fetch;
const nativeSetTimeout = global.setTimeout;
const child = spawn(process.env.PYTHON || 'python3', ['-m','admin_agent','--port','0','--db',path.join(temp,'test.sqlite3')], {
  cwd:root, env:{...process.env, ADMIN_AGENT_AI_ENABLED:'0'}, stdio:['ignore','pipe','pipe']
});
let count = 0;
function passed(label) { count++; console.log(`PASS ${count}: ${label}`); }

(async()=>{
  const origin = await new Promise((resolve,reject)=>{
    const timer = nativeSetTimeout(()=>reject(new Error('Local test server startup timeout')),10000);
    let output='';
    child.stdout.on('data',chunk=>{output+=chunk;const match=output.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});
    child.on('error',reject);child.on('exit',code=>{if(!output)reject(new Error(`Server exited ${code}`));});
    child.stderr.on('data',chunk=>process.stderr.write(chunk));
  });
  const request = async (route, body) => {
    const response=await nativeFetch(origin+route,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json();assert.ok(response.ok,JSON.stringify(data));return data;
  };
  const {window,document}=parseHTML(fs.readFileSync(path.join(root,'web/index.html'),'utf8'));
  class DOMFormData {
    constructor(form){this.values=new Map();for(const element of form.querySelectorAll('[name]')){
      if(element.hasAttribute('disabled'))continue;
      if(['checkbox','radio'].includes(element.type)&&!element.checked)continue;
      this.values.set(element.name,element.type==='checkbox'?(element.getAttribute('value')||'on'):element.value);
    }}
    get(name){return this.values.has(name)?this.values.get(name):null;}
  }
  Object.defineProperty(window.HTMLInputElement.prototype,'checked',{configurable:true,get(){return this.hasAttribute('checked');},set(value){value?this.setAttribute('checked',''):this.removeAttribute('checked');}});
  Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){const selected=this.querySelector('option[selected]')||this.querySelector('option');return selected?.getAttribute('value')||'';},set(value){for(const option of this.querySelectorAll('option'))option.getAttribute('value')===String(value)?option.setAttribute('selected',''):option.removeAttribute('selected');}});
  for(const dialog of document.querySelectorAll('dialog')){
    Object.defineProperty(dialog,'open',{get(){return this.hasAttribute('open');}});
    dialog.showModal=function(){this.setAttribute('open','');};dialog.close=function(){this.removeAttribute('open');this.dispatchEvent(new window.Event('close'));};
  }
  const context=vm.createContext({window,document,console,FormData:DOMFormData,crypto:webcrypto,AbortController,Blob,URL,
    location:{hash:'',origin}, navigator:{clipboard:{writeText:async()=>{}}},
    fetch:(url,options)=>nativeFetch(new URL(url,origin),options),
    setTimeout:(fn,ms)=>{const timer=nativeSetTimeout(fn,ms);timer.unref();return timer;},clearTimeout});
  const run=source=>vm.runInContext(source,context);
  await run(fs.readFileSync(path.join(root,'web/app.js'),'utf8'));
  assert.match(document.querySelector('h1').textContent,/administratif/);
  assert.equal(document.querySelectorAll('.metric-card').length,4);passed('Dashboard empty state renders from API');

  await request('/api/demo/seed',{});await run('loadData()');
  assert.equal(run('state.tasks.length'),4);assert.equal(document.querySelectorAll('.task-title-button').length,4);
  assert.equal((await request('/api/demo/seed',{})).created,0);passed('Demo loading and idempotency');

  run("state.query='1250.00';updateTaskList()");
  assert.equal(document.querySelectorAll('.task-title-button').length,1);
  run("state.query='';state.page='skills';renderPage()");
  assert.equal(document.querySelectorAll('.skill-card').length,12);
  run("state.skillStatus='guided';updateSkillsList()");
  assert.equal(document.querySelectorAll('.skill-card').length,7);passed('Payload search and 12-skill maturity filters');

  run("openCreate('invoice-check');prefill()");
  document.querySelector('#task-title').value='<img src=x onerror=alert(1)> QA facture';
  await run("saveTask(document.querySelector('#task-form'))");
  assert.equal(run('state.detail.status'),'needs_review');
  assert.equal(document.querySelectorAll('#detail-dialog img').length,0);
  assert.match(document.querySelector('#detail-dialog-title').textContent,/<img/);passed('Create/analyze and escaped untrusted title');

  const goodId=run('state.detail.id');
  document.querySelector('#review-note').value='Contrôle synthétique';
  await run("reviewTask('approve',document.querySelector('[data-decision=approve]'))");
  assert.equal((await request(`/api/tasks/${goodId}`)).task.status,'ready');passed('UI approval is version-bound and persisted');

  run("document.querySelector('#detail-dialog').close();openCreate(null,state.detail)");
  document.querySelector('#field-total_amount').value='1300.00';
  await run("saveTask(document.querySelector('#task-form'))");
  assert.equal(run('state.detail.status'),'blocked');
  assert.equal(document.querySelectorAll('[data-decision=approve]').length,0);passed('Editing invalidates approval and mismatch blocks review');

  const base=(await request('/api/tasks')).tasks.find(task=>task.skill_id==='receivables-followup');
  const partial=await request('/api/tasks',{title:'Partiel à conserver',description:'Dossier synthétique',country:'FR',skill_id:'receivables-followup',payload:{...base.payload,paid_amount:'200.00'}});
  await request(`/api/tasks/${partial.task.id}/analyze`,{use_ai:false});
  await run(`openTask(${JSON.stringify(partial.task.id)})`);
  run("document.querySelector('#detail-dialog').close();openCreate(null,state.detail)");
  document.querySelector('#task-title').value='Titre corrigé seulement';
  await run("saveTask(document.querySelector('#task-form'))");
  assert.equal(run('state.detail.payload.paid_amount'),'200.00');
  assert.equal(run('state.detail.status'),'blocked');passed('Editing preserves unrendered payment evidence and blockers');

  run("document.querySelector('#detail-dialog').close();openCreate('receivables-followup')");
  const emptyPayload=run("collectPayload(document.querySelector('#task-form'),'receivables-followup')");
  assert.equal(Object.hasOwn(emptyPayload,'paid'),false);
  assert.equal(Object.hasOwn(emptyPayload,'disputed'),false);passed('Unknown paid/disputed states are not silently false');
  document.querySelector('#create-dialog').close();

  await run(`openTask(${JSON.stringify(base.id)})`);
  const staleVersion=run('state.detail.version');
  const current=(await request(`/api/tasks/${base.id}/update`,{version:staleVersion,title:'Autre onglet'})).task;
  await request(`/api/tasks/${base.id}/analyze`,{use_ai:false});
  document.querySelector('#review-note').value='Ancienne lecture';
  await run("reviewTask('approve',document.querySelector('[data-decision=approve]'))");
  assert.equal((await request(`/api/tasks/${base.id}`)).task.status,'needs_review');
  assert.ok(run('state.detail.version')>staleVersion);passed('Stale approval refreshes the dossier without approving it');

  run("state.health.mode='offline';renderTaskDetail()");assert.equal(document.querySelector('#ai-consent'),null);
  run("state.health.mode='ai_available';renderTaskDetail()");
  assert.equal(document.querySelector('#analyze-ai-button').disabled,true);
  assert.match(document.querySelector('#detail-dialog').textContent,/transmis au fournisseur/);passed('Optional AI is disclosed and requires explicit per-case choice');

  run("document.querySelector('#detail-dialog').close();openCreate('invoice-check');prefill()");
  document.querySelector('#task-title').value='Retry after lost response';
  let loseResponse=true;
  context.fetch=async(url,options)=>{
    const response=await nativeFetch(new URL(url,origin),options);
    if(url==='/api/tasks'&&options.method==='POST'&&loseResponse){loseResponse=false;throw new Error('Simulated lost response');}
    return response;
  };
  await run("saveTask(document.querySelector('#task-form'))");
  assert.match(document.querySelector('#task-form-error').textContent,/Simulated lost response/);
  await run("saveTask(document.querySelector('#task-form'))");
  assert.equal((await request('/api/tasks')).tasks.filter(task=>task.title==='Retry after lost response').length,1);
  assert.equal(run('state.detail.status'),'needs_review');passed('Lost-response retry keeps idempotency key and creates one dossier');

  const exported=await request('/api/export');assert.ok(exported.tasks.length>=6);assert.ok(exported.events.length>0);passed('JSON export includes actual dossiers and audit trail');
  console.log(`${count} DOM/API scenarios passed. Layout, focus and browser rendering were not tested.`);
})().catch(error=>{console.error(error.stack);process.exitCode=1;}).finally(()=>{
  child.kill('SIGTERM');
  child.once('exit',()=>{fs.rmSync(temp,{recursive:true,force:true});});
});
