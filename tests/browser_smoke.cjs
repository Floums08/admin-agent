/* Real Chromium against the production WSGI server behind a temporary local TLS proxy.
 * Synthetic users/data only. The self-signed certificate is accepted ONLY in this test context.
 * Run: npm ci && npx playwright install chromium && npm run test:browser
 * PYTHON selects an interpreter with requirements installed; CHROMIUM_EXECUTABLE is optional.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const https = require('node:https');
const net = require('node:net');
const crypto = require('node:crypto');
const {spawn, execFileSync} = require('node:child_process');
let chromium;
try { ({chromium} = require('playwright')); }
catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; ({chromium} = require('playwright-core')); }

const root = path.resolve(__dirname, '..');
const python = process.env.PYTHON || 'python3';
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'admin-agent-browser-'));
const artifacts = path.resolve(process.env.ADMIN_AGENT_BROWSER_ARTIFACTS || path.join(root, 'artifacts', 'browser'));
const password = crypto.randomBytes(24).toString('base64url');
const secret = crypto.randomBytes(32).toString('hex');
const clientName = 'Atelier QA — entreprise fictive';
const hostname = '127.0.0.1';
let server, proxy, browser, origin, environment, serverOutput = '', count = 0;
const javascriptErrors = [];
const unexpectedRequests = [];
function passed(label) { count++; console.log(`PASS ${count}: ${label}`); }
function runPython(source, input = '') {
  return execFileSync(python, ['-c', source], {cwd:root, env:environment || process.env, input, encoding:'utf8', maxBuffer:1024*1024}).trim();
}
function otp(secretValue) { return runPython('import pyotp,sys; print(pyotp.TOTP(sys.stdin.read()).now())', secretValue); }
async function freePort() {
  const probe = net.createServer();
  await new Promise((resolve,reject)=>{probe.once('error',reject);probe.listen(0,'127.0.0.1',resolve);});
  const port = probe.address().port;
  await new Promise(resolve=>probe.close(resolve));
  return port;
}
async function waitForBackend(port) {
  const deadline = Date.now()+20000;
  while (Date.now()<deadline) {
    if (server.exitCode !== null) throw new Error(`Production server exited ${server.exitCode}: ${serverOutput}`);
    const ready = await new Promise(resolve=>{
      const request=http.get({hostname:'127.0.0.1',port,path:'/healthz',headers:{Host:new URL(origin).host}},response=>{response.resume();resolve(response.statusCode===200);});
      request.on('error',()=>resolve(false));request.setTimeout(500,()=>request.destroy());
    });
    if (ready) return;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw new Error(`Production server startup timeout: ${serverOutput}`);
}
async function noHorizontalPageOverflow(page, label) {
  const bounds = await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
  assert.ok(bounds.document<=bounds.viewport+1 && bounds.body<=bounds.viewport+1, `${label}: ${JSON.stringify(bounds)}`);
}
async function screenshot(page, name) {
  // A full-page capture relocates viewport-fixed dialog/backdrop context on long pages.
  const modalOpen=await page.locator('dialog[open]').count();
  await page.screenshot({path:path.join(artifacts,name+'.png'),fullPage:modalOpen===0});
}
async function session(page) { return page.evaluate(async()=>await (await fetch('/api/session')).json()); }
async function request(page, route, body) {
  return page.evaluate(async({route,body})=>{
    const session=await (await fetch('/api/session')).json();
    const response=await fetch(route,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':session.csrf_token},body:JSON.stringify(body)});
    return {status:response.status,data:await response.json()};
  },{route,body});
}
async function signIn(page, user, code) {
  await page.locator('#login-username').fill(user.username);
  await page.locator('#login-password').fill(password);
  await page.locator('#login-otp').fill(code || otp(user.totp_secret));
  await page.locator('#login-form button[type=submit]').click();
}
async function contextPage(viewport) {
  const context=await browser.newContext({viewport,ignoreHTTPSErrors:true});
  await context.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(url.hostname!==hostname){unexpectedRequests.push(url.hostname);return route.abort();}
    return route.continue();
  });
  const page=await context.newPage();
  page.on('pageerror',error=>javascriptErrors.push(error.message));
  await page.goto(origin,{waitUntil:'networkidle'});
  await page.locator('#login-form').waitFor();
  return {context,page};
}

(async()=>{
  fs.mkdirSync(artifacts,{recursive:true});
  fs.writeFileSync(path.join(temp,'session-secret'),secret,{mode:0o600});
  execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-keyout',path.join(temp,'tls.key'),'-out',path.join(temp,'tls.crt'),'-days','1','-subj',`/CN=${hostname}`,'-addext',`subjectAltName=IP:${hostname}`],{stdio:'ignore'});
  const backendPort=await freePort();
  proxy=https.createServer({key:fs.readFileSync(path.join(temp,'tls.key')),cert:fs.readFileSync(path.join(temp,'tls.crt'))},(incoming,outgoing)=>{
    const upstream=http.request({hostname:'127.0.0.1',port:backendPort,path:incoming.url,method:incoming.method,headers:incoming.headers},response=>{
      outgoing.writeHead(response.statusCode,response.headers);response.pipe(outgoing);
    });
    upstream.on('error',()=>{if(!outgoing.headersSent)outgoing.writeHead(502);outgoing.end();});
    incoming.pipe(upstream);
  });
  await new Promise((resolve,reject)=>{proxy.once('error',reject);proxy.listen(0,'127.0.0.1',resolve);});
  origin=`https://${hostname}:${proxy.address().port}`;
  environment={...process.env,ADMIN_AGENT_CLIENT_ID:'browser-qa',ADMIN_AGENT_CLIENT_NAME:clientName,ADMIN_AGENT_PUBLIC_ORIGIN:origin,
    ADMIN_AGENT_DB:path.join(temp,'browser.sqlite3'),ADMIN_AGENT_SESSION_SECRET_FILE:path.join(temp,'session-secret'),
    ADMIN_AGENT_BIND:'127.0.0.1',ADMIN_AGENT_PORT:String(backendPort),ADMIN_AGENT_AI_ENABLED:'0'};
  // No enrollment secret or password is written to the test report, command line or screenshots.
  const users=JSON.parse(runPython(`import json,os,sys
from pathlib import Path
from admin_agent.storage import Store
from admin_agent.auth import AuthStore
auth=AuthStore(Store(os.environ['ADMIN_AGENT_DB']),os.environ['ADMIN_AGENT_CLIENT_ID'],os.environ['ADMIN_AGENT_CLIENT_NAME'],Path(os.environ['ADMIN_AGENT_SESSION_SECRET_FILE']).read_bytes())
password=sys.stdin.read()
print(json.dumps({role:auth.provision_user('browser-'+role,password,role) for role in ['admin','operator','reader']}))`,password));
  server=spawn(python,['-m','admin_agent.production'],{cwd:root,env:environment,stdio:['ignore','pipe','pipe']});
  server.stdout.on('data',chunk=>{serverOutput=(serverOutput+chunk).slice(-8000);});
  server.stderr.on('data',chunk=>{serverOutput=(serverOutput+chunk).slice(-8000);});
  await waitForBackend(backendPort);
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{}),args:['--no-sandbox','--disable-dev-shm-usage']});
  console.log(`Browser: Chromium ${await browser.version()}; real production server and local test TLS.`);

  const {context,page}=await contextPage({width:1280,height:900});
  assert.equal((await session(page)).authenticated,false);
  assert.equal((await request(page,'/api/tasks')).status,401);
  assert.equal(await page.locator('.task-title-button').count(),0);
  await noHorizontalPageOverflow(page,'Login desktop');await screenshot(page,'login-desktop');
  await page.setViewportSize({width:390,height:844});await noHorizontalPageOverflow(page,'Login mobile');await screenshot(page,'login-mobile');
  passed('Unauthenticated data denied; desktop and mobile login fit viewport');

  await page.setViewportSize({width:1280,height:900});
  const badCode=String((Number(otp(users.operator.totp_secret))+1)%1000000).padStart(6,'0');
  await signIn(page,users.operator,badCode);
  await page.waitForFunction(()=>document.querySelector('#login-error')?.textContent.trim());
  assert.equal((await session(page)).authenticated,false);
  assert.equal(await page.locator('#login-password').inputValue(),'');
  assert.equal(await page.locator('#login-otp').inputValue(),'');
  passed('Wrong TOTP rejected and sensitive login inputs cleared');

  await signIn(page,users.operator);
  await page.locator('.metric-card').first().waitFor();
  assert.equal((await session(page)).user.role,'operator');
  const cookies=await context.cookies();
  const authCookie=cookies.find(cookie=>cookie.name.includes('session'));
  assert.ok(authCookie,'Authenticated session cookie exists');
  assert.equal(authCookie.secure,true);assert.equal(authCookie.httpOnly,true);assert.equal(authCookie.sameSite,'Strict');
  assert.equal(await page.locator('[data-action=seed]').count(),0);
  assert.equal(await page.locator('[data-action=export]').count(),0);
  await noHorizontalPageOverflow(page,'Dashboard desktop');await screenshot(page,'dashboard-desktop');
  passed('Password and TOTP login; secure cookie and operator privileges');

  await page.locator('[data-action=create]').first().click();
  await page.locator('#task-skill').selectOption('invoice-check');
  const title='Facture QA synthétique — Atelier Exemple';
  await page.locator('#task-title').fill(title);
  await page.locator('#task-description').fill('Données fictives réservées aux tests navigateur.');
  const date=new Date();const today=date.toISOString().slice(0,10);date.setDate(date.getDate()+30);const due=date.toISOString().slice(0,10);
  const fields={invoice_number:'QA-001',supplier:'Fournisseur fictif',customer:clientName,issue_date:today,due_date:due,net_amount:'1000.00',vat_rate:'20',vat_amount:'200.00',total_amount:'1200.00',currency:'EUR'};
  for(const [field,value]of Object.entries(fields))await page.locator('#field-'+field).fill(value);
  await page.locator('#field-paid').selectOption('false');
  await page.locator('#task-form button[type=submit]').click();
  await page.locator('#detail-dialog [data-decision=approve]').waitFor();
  assert.equal(await page.locator('#detail-dialog-title').textContent(),title);
  const task=(await request(page,'/api/tasks')).data.tasks.find(task=>task.title===title);
  assert.equal(task.status,'needs_review');
  passed('Operator creates and analyzes a synthetic invoice through the UI');

  await page.locator('#review-note').fill('Contrôle synthétique réalisé pour la QA navigateur.');
  await page.locator('[data-decision=approve]').click();
  await page.locator('#detail-dialog .status-pill.ready').waitFor();
  assert.equal((await request(page,'/api/tasks/'+task.id)).data.task.status,'ready');
  await page.locator('[data-action=edit-task]').click();
  await page.locator('#field-total_amount').fill('1300.00');
  await page.locator('#task-form button[type=submit]').click();
  await page.locator('#detail-dialog .status-pill.blocked').waitFor();
  assert.equal(await page.locator('[data-decision=approve]').count(),0);
  assert.equal((await request(page,'/api/tasks/'+task.id)).data.task.status,'blocked');
  passed('Review persists; correcting an approved invoice invalidates review and blocks a mismatch');

  await page.setViewportSize({width:390,height:844});
  await noHorizontalPageOverflow(page,'Detail mobile');await screenshot(page,'dossier-mobile');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('dialog[open]').count(),0);
  await page.locator('.nav-link[data-page=tasks]').click();
  await page.locator('.task-title-button').waitFor();
  await noHorizontalPageOverflow(page,'Tasks mobile');await screenshot(page,'tasks-mobile');
  const statusBounds=await page.locator('.table-wrap .status-pill').first().boundingBox();
  assert.ok(statusBounds.x>=0&&statusBounds.x+statusBounds.width<=391,'Task status must be entirely visible on mobile');
  await page.locator('[data-action=create]').first().click();
  await noHorizontalPageOverflow(page,'Create mobile');await screenshot(page,'create-mobile');
  await page.keyboard.press('Escape');
  await page.locator('.nav-link[data-page=skills]').click();await page.locator('.skill-card').first().waitFor();
  assert.equal(await page.locator('.skill-card').count(),12);await noHorizontalPageOverflow(page,'Skills mobile');
  await page.locator('.nav-link[data-page=controls]').click();await page.locator('.control-card').first().waitFor();await noHorizontalPageOverflow(page,'Controls mobile');
  passed('Mobile dossier, create, task status, skills and controls fit; Escape closes native dialogs');

  await page.locator('#logout-button').click();
  await page.locator('#login-form').waitFor();
  assert.equal((await session(page)).authenticated,false);
  assert.equal((await request(page,'/api/tasks')).status,401);
  assert.equal(await page.locator('dialog[open]').count(),0);
  assert.ok(!(await page.locator('body').innerText()).includes(title));
  assert.equal(await page.evaluate(()=>[...document.querySelectorAll('dialog')].some(dialog=>dialog.textContent.trim())),false);
  passed('Mobile logout revokes session and clears dossier/modal contents');

  const {context:readerContext,page:reader}=await contextPage({width:390,height:844});
  await signIn(reader,users.reader);await reader.locator('.task-title-button').waitFor();
  assert.equal((await session(reader)).user.role,'reader');
  assert.equal(await reader.locator('[data-action=create],[data-action=export],[data-action=seed]').count(),0);
  await reader.locator('.task-title-button').click();await reader.locator('#detail-dialog[open]').waitFor();
  assert.equal(await reader.locator('[data-action=edit-task],[data-action=analyze],[data-action=analyze-ai],[data-action=review]').count(),0);
  const forbidden=await request(reader,'/api/tasks',{title:'Forbidden reader write',country:'FR',skill_id:'admin-triage',description:'Synthetic denied action',payload:{}});
  assert.equal(forbidden.status,403);
  assert.equal((await request(reader,'/api/export')).status,403);
  await noHorizontalPageOverflow(reader,'Read-only detail mobile');await screenshot(reader,'reader-mobile');
  passed('Reader can inspect dossiers; write, analysis, review and export denied in UI and API');

  // Simulate a real operator-driven revocation while a reader is viewing a dossier.
  runPython(`import os
from pathlib import Path
from admin_agent.storage import Store
from admin_agent.auth import AuthStore
AuthStore(Store(os.environ['ADMIN_AGENT_DB']),os.environ['ADMIN_AGENT_CLIENT_ID'],os.environ['ADMIN_AGENT_CLIENT_NAME'],Path(os.environ['ADMIN_AGENT_SESSION_SECRET_FILE']).read_bytes()).revoke_user_sessions('browser-reader')`);
  await reader.keyboard.press('Escape');await reader.locator('.task-title-button').click();
  await reader.locator('#login-form').waitFor();
  assert.ok(!(await reader.locator('body').innerText()).includes(title));
  assert.equal(await reader.locator('dialog[open]').count(),0);
  assert.match(await reader.locator('.session-notice').innerText(),/expiré/);
  passed('Server-side session revocation returns to login and clears previously visible data');

  assert.deepEqual(javascriptErrors,[],'No browser JavaScript exceptions');
  assert.deepEqual(unexpectedRequests,[],'No request outside the local test origin');
  passed('No browser JavaScript errors and no external network requests');
  await readerContext.close();await context.close();
  console.log(`${count} real Chromium scenarios passed. Synthetic screenshots: ${artifacts}`);
})().catch(async error=>{
  console.error(error.stack);process.exitCode=1;
  if(browser){for(const [index,page]of browser.contexts().flatMap(context=>context.pages()).entries()){try{await screenshot(page,'failure-'+index);}catch{}}}
}).finally(async()=>{
  if(browser)await browser.close();
  if(server&&!server.killed){server.kill('SIGTERM');await new Promise(resolve=>{server.once('exit',resolve);setTimeout(resolve,3000).unref();});}
  if(proxy){proxy.closeAllConnections();await new Promise(resolve=>proxy.close(resolve));}
  fs.rmSync(temp,{recursive:true,force:true});
});
