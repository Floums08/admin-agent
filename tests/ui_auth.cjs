/* Security-sensitive UI regression cases with a simulated auth/API transport.
   Backend authorization is tested separately; this is not a browser-layout test. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const {parseHTML} = require('linkedom');
const root = path.resolve(__dirname,'..');
const source = fs.readFileSync(path.join(root,'web/app.js'),'utf8');
let count = 0;
function passed(label){count++;console.log(`PASS auth ${count}: ${label}`);}
const task={id:'synthetic-1',title:'Confidentiel synthétique',description:'Informations de test seulement',skill_id:'invoice-check',country:'FR',status:'needs_review',version:2,payload:{invoice_number:'SYNTH-042'},updated_at:'2026-10-02T12:00:00Z',result:{summary:'Contrôles synthétiques',findings:[],checks:[],draft:'Brouillon confidentiel synthétique'}};
const skill={id:'invoice-check',name:'Facture',status:'implemented',agent:'Contrôle',priority:'P0',description:'Contrôle synthétique',inputs:[],outputs:[],body:'Instructions synthétiques'};
async function makeUI(role=null,BroadcastChannel=undefined){
  const {window,document}=parseHTML(fs.readFileSync(path.join(root,'web/index.html'),'utf8'));
  for(const dialog of document.querySelectorAll('dialog')){
    Object.defineProperty(dialog,'open',{get(){return this.hasAttribute('open');}});
    dialog.showModal=function(){this.setAttribute('open','');};dialog.close=function(){this.removeAttribute('open');};
  }
  Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){const o=this.querySelector('option[selected]')||this.querySelector('option');return o?.getAttribute('value')||'';},set(value){for(const o of this.querySelectorAll('option'))o.getAttribute('value')===String(value)?o.setAttribute('selected',''):o.removeAttribute('selected');}});
  let serverRole=role;
  let csrf='pre-csrf';
  let handler=null;
  const requests=[];
  const session=()=>({authenticated:Boolean(serverRole),user:serverRole?{username:'test-user',role:serverRole}:null,csrf_token:csrf,scope:'production_single_client',mode:'offline',expires_at:Math.floor(Date.now()/1000)+28800,idle_timeout_seconds:1800,client:{id:'synthetic-client',name:'Atelier <img src=x onerror=alert(1)>'},capabilities:{create:['operator','admin'].includes(serverRole),update:['operator','admin'].includes(serverRole),analyze:['operator','admin'].includes(serverRole),review:['operator','admin'].includes(serverRole),export:serverRole==='admin',demo:false}});
  const reply=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
  const transport=async(url,options={})=>{
    requests.push({url,options,body:options.body?JSON.parse(options.body):undefined});
    assert.equal(options.credentials,'same-origin');assert.equal(options.cache,'no-store');
    if(handler){const response=await handler(url,options);if(response)return response;}
    if(url==='/api/session')return reply(session());
    if(options.method==='POST'){
      if(options.headers['X-CSRF-Token']!==csrf)return reply({error:{code:'csrf_invalid',message:'CSRF invalide'}},403);
      if(url==='/api/login'){
        const body=JSON.parse(options.body);
        if(body.password!=='synthetic-passphrase' || body.otp!=='123456')return reply({error:{code:'invalid_credentials',message:'Identifiants invalides'}},401);
        serverRole=body.username==='reader'?'reader':body.username==='admin'?'admin':'operator';csrf='authenticated-csrf';return reply(session());
      }
      if(url==='/api/logout'){serverRole=null;csrf='rotated-pre-csrf';return reply(session());}
    }
    if(!serverRole)return reply({error:{code:'auth_required',message:'Connexion requise'}},401);
    if(url==='/api/dashboard'){const {payload,result,...summary}=task;return reply({tasks:[summary],metrics:{total:1,needs_review:1}});}
    if(url==='/api/skills')return reply({skills:[skill]});
    if(url==='/api/health')return reply({scope:'production_single_client',mode:'offline',expires_at:Math.floor(Date.now()/1000)+28800,idle_timeout_seconds:1800});
    if(url==='/api/tasks/synthetic-1')return reply({task,events:[]});
    throw new Error(`Unexpected UI request: ${url}`);
  };
  const context=vm.createContext({window,document,console,BroadcastChannel,FormData:class{},crypto:webcrypto,AbortController,Blob,URL,
    location:{hash:'',origin:'https://client.example.test'},navigator:{clipboard:{writeText:async()=>{}}},fetch:transport,
    setTimeout:(fn,ms)=>{const timer=setTimeout(fn,ms);timer.unref();return timer;},clearTimeout});
  const run=code=>vm.runInContext(code,context);
  await run(source);
  const login=async(user='operator',password='synthetic-passphrase',otp='123456')=>{
    document.querySelector('#login-username').value=user;document.querySelector('#login-password').value=password;document.querySelector('#login-otp').value=otp;
    await run("login(document.querySelector('#login-form'))");
  };
  return {run,document,requests,login,reply,setHandler:fn=>{handler=fn;},setRole:r=>{serverRole=r;},context};
}
(async()=>{
  const anonymous=await makeUI();
  assert.equal(anonymous.requests.length,1);assert.equal(anonymous.requests[0].url,'/api/session');
  assert.ok(anonymous.document.querySelector('#login-form'));assert.equal(anonymous.document.querySelectorAll('img').length,0);
  assert.equal(anonymous.document.querySelector('#login-otp').getAttribute('autocomplete'),'one-time-code');
  assert.equal(anonymous.document.querySelector('#login-otp').getAttribute('inputmode'),'numeric');
  assert.equal(anonymous.document.querySelectorAll('.task-title-button').length,0);
  passed('Anonymous page requests no dossier data, labels TOTP and escapes client identity');

  await anonymous.login('operator','wrong-password','000000');
  assert.match(anonymous.document.querySelector('#login-error').textContent,/Identifiant, mot de passe ou code incorrect/);
  assert.equal(anonymous.document.querySelector('#login-password').value,'');assert.equal(anonymous.document.querySelector('#login-otp').value,'');
  assert.equal(anonymous.run('state.sessionPhase'),'anonymous');
  passed('Failed login clears password and OTP and gives no credential-specific clue');

  await anonymous.login();
  assert.equal(anonymous.run('state.sessionPhase'),'authenticated');assert.equal(anonymous.run('state.csrfToken'),'authenticated-csrf');
  assert.ok(anonymous.document.querySelector('[data-action=create]'));assert.equal(anonymous.document.querySelector('[data-action=export]'),null);
  assert.equal(anonymous.document.querySelector('[data-action=seed]'),null);
  assert.equal(anonymous.document.querySelector('#logout-button').hidden,false);
  await anonymous.run("openTask('synthetic-1')");
  assert.ok(anonymous.document.querySelector('[data-action=review]'));assert.ok(anonymous.document.querySelector('[data-action=edit-task]'));
  anonymous.run("state.health.mode='ai_available';renderTaskDetail()");
  assert.equal(anonymous.document.querySelector('#ai-consent'),null);
  passed('Operator uses rotated CSRF, can work and review, cannot export/demo or activate production AI');

  const reader=await makeUI('reader');
  await reader.run("openTask('synthetic-1')");
  for(const action of ['create','edit-task','analyze','review','export','seed'])assert.equal(reader.document.querySelector(`[data-action=${action}]`),null);
  const before=reader.requests.length;
  await reader.run("openCreate('invoice-check');exportData({});seedDemo({});reviewTask('approve',{});analyzeTask(false,{})");
  assert.equal(reader.requests.length,before);
  reader.run("state.page='skills';renderPage();openSkill('invoice-check')");assert.equal(reader.document.querySelector('[data-action=create]'),null);
  reader.run("state.page='controls';renderPage()");assert.match(reader.document.querySelector('#main').textContent,/Lecture seule/);
  passed('Reader has no mutation/export controls across pages and handlers refuse direct attempts');

  reader.run("state.page='tasks';state.query='SYNTH-042';renderPage()");
  assert.equal(reader.document.querySelectorAll('.task-title-button').length,0);
  assert.match(reader.document.querySelector('.search-scope').textContent,/titres, contextes/);
  reader.run("state.query='Confidentiel';updateTaskList()");assert.equal(reader.document.querySelectorAll('.task-title-button').length,1);
  passed('Production search describes and honors the lightweight dossier-summary scope');

  const history=await makeUI('reader');
  history.setHandler(async url=>url==='/api/tasks/synthetic-1'?history.reply({task,events:Array.from({length:200},()=>({action:'task.created',created_at:'2026-10-02T12:00:00Z'})),events_total:245,events_truncated:true}):null);
  await history.run("openTask('synthetic-1')");
  assert.match(history.document.querySelector('.audit-truncation').textContent,/200 derniers événements sur 245 ; historique complet dans l’export administrateur/);
  history.setHandler(null);await history.run("openTask('synthetic-1')");
  assert.equal(history.document.querySelector('.audit-truncation'),null);
  passed('Truncated history identifies displayed and total counts and resets on a complete response');

  const admin=await makeUI('admin');assert.ok(admin.document.querySelector('[data-action=export]'));
  admin.run("state.page='controls';renderPage()");assert.match(admin.document.querySelector('#main').textContent,/Administrateur/);
  assert.equal(admin.document.querySelector('[data-action=seed]'),null);
  passed('Admin sees export and explicit dedicated-client metadata without a production demo');

  anonymous.run("document.querySelector('#detail-dialog').close();openCreate(null,state.detail)");
  anonymous.document.querySelector('#task-description').value='SECRET UNSENT SYNTHETIC';
  await anonymous.run('logout()');
  assert.equal(anonymous.run('state.tasks.length'),0);assert.equal(anonymous.run('state.detail'),null);assert.equal(anonymous.run('state.creationAttempt'),null);
  assert.equal(anonymous.document.querySelector('#create-dialog').innerHTML,'');assert.equal(anonymous.document.querySelector('#detail-dialog').innerHTML,'');
  assert.equal(anonymous.document.body.textContent.includes('SECRET UNSENT SYNTHETIC'),false);
  assert.equal(anonymous.document.body.textContent.includes('Confidentiel synthétique'),false);
  assert.equal(anonymous.run('state.csrfToken'),'rotated-pre-csrf');
  passed('Logout clears dossier state, unsent form content and dialogs while accepting rotated pre-session');

  const expired=await makeUI('operator');await expired.run("openTask('synthetic-1')");
  expired.run("document.querySelector('#detail-dialog').close();openCreate(null,state.detail)");
  expired.document.querySelector('#task-title').value='Unsent expiry';
  expired.setRole(null);await expired.run("openTask('synthetic-1')");
  assert.equal(expired.run('state.sessionPhase'),'anonymous');assert.equal(expired.run('state.tasks.length'),0);assert.equal(expired.run('state.csrfToken'),null);
  assert.equal(expired.document.querySelectorAll('dialog[open]').length,0);assert.equal(expired.document.querySelector('#detail-dialog').innerHTML,'');
  assert.match(expired.document.querySelector('#main').textContent,/aucune action ne sera relancée/);
  const oldRequests=expired.requests.length;await expired.login();
  assert.equal(expired.requests.slice(oldRequests).filter(r=>r.options.method==='POST'&&r.url!=='/api/login').length,0);
  assert.equal(expired.document.querySelector('#create-dialog').innerHTML,'');
  passed('401 purges sensitive state and reauthentication never replays the interrupted request');

  const race=await makeUI('operator');let release;
  race.setHandler(async url=>url==='/api/tasks/synthetic-1'?new Promise(resolve=>{release=()=>resolve(race.reply({task,events:[]}));}):null);
  const opening=race.run("openTask('synthetic-1')");
  await race.run('logout()');release();await opening;
  assert.equal(race.run('state.detail'),null);assert.equal(race.document.querySelector('#detail-dialog').innerHTML,'');assert.equal(race.document.body.textContent.includes('Confidentiel synthétique'),false);
  passed('Late successful responses from an old session cannot repopulate the page after logout');

  const peers=[];const broadcasts=[];
  class SyntheticChannel {
    constructor(name){this.name=name;this.listeners=[];peers.push(this);}
    addEventListener(type,listener){if(type==='message')this.listeners.push(listener);}
    postMessage(data){broadcasts.push(data);for(const peer of peers)if(peer!==this&&peer.name===this.name)for(const listener of peer.listeners)listener({data});}
  }
  const firstTab=await makeUI('operator',SyntheticChannel);const secondTab=await makeUI('operator',SyntheticChannel);
  let finishSecond;
  secondTab.setHandler(async url=>url==='/api/tasks/synthetic-1'?new Promise(resolve=>{finishSecond=()=>resolve(secondTab.reply({task,events:[]}));}):null);
  const pendingSecond=secondTab.run("openTask('synthetic-1')");
  await firstTab.run('logout()');finishSecond();await pendingSecond;
  assert.equal(broadcasts.length,1);assert.equal(JSON.stringify(broadcasts[0]),'{"type":"logout"}');
  assert.equal(secondTab.run('state.sessionPhase'),'anonymous');assert.equal(secondTab.run('state.tasks.length'),0);
  assert.equal(secondTab.run('state.detail'),null);assert.equal(secondTab.document.querySelector('#detail-dialog').innerHTML,'');
  assert.match(secondTab.document.querySelector('#main').textContent,/autre onglet/);
  passed('Logout broadcasts only an invalidation signal and clears sibling tabs without echo or late-response leaks');

  const idle=await makeUI('operator');
  idle.run("state.sessionDeadline=Date.now()-1;checkSessionDeadline()");
  assert.equal(idle.run('state.sessionPhase'),'anonymous');assert.equal(idle.run('state.tasks.length'),0);assert.ok(idle.document.querySelector('#login-form'));
  assert.match(idle.document.querySelector('#main').textContent,/session a expiré/);
  passed('Idle deadline clears sensitive data even without a new API request');

  const failedLogout=await makeUI('operator');let fail=true;
  failedLogout.setHandler(async url=>{if(url==='/api/logout'&&fail)throw new Error('Synthetic network outage');return null;});
  await failedLogout.run('logout()');
  assert.equal(failedLogout.run('state.tasks.length'),0);assert.equal(failedLogout.document.querySelector('#login-form'),null);
  assert.match(failedLogout.document.querySelector('#main').textContent,/Déconnexion serveur non confirmée/);
  fail=false;await failedLogout.run('logout()');assert.ok(failedLogout.document.querySelector('#login-form'));
  passed('Failed logout keeps data masked, states the unresolved server session, and supports explicit retry');
  assert.equal(/localStorage|sessionStorage/.test(source),false);
  console.log(`${count} authentication DOM scenarios passed; transport is simulated, not a backend or visual test.`);
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
