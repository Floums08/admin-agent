/* Real Chromium against the production WSGI server behind a temporary local TLS proxy.
 * Synthetic users/data only. The self-signed certificate is accepted ONLY in this test context.
 * Run: npm ci && npx playwright install chromium && npm run test:finance-browser
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
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'admin-agent-finance-browser-'));
const artifacts = path.resolve(process.env.ADMIN_AGENT_BROWSER_ARTIFACTS || path.join(root, 'artifacts', 'finance-browser'));
const password = crypto.randomBytes(24).toString('base64url');
const secret = crypto.randomBytes(32).toString('hex');
const clientName = 'Atelier QA — entreprise fictive';
const hostname = '127.0.0.1';
let server, worker, proxy, browser, origin, environment, serverOutput = '', workerOutput = '', count = 0;
let diagnosticDocumentId=null, stage='initialization';
const httpDiagnostics=[];
const redactions=[password,secret];
const javascriptErrors = [];
const unexpectedRequests = [];
function passed(label) { count++; console.log(`PASS ${count}: ${label}`); }
function redact(value) {
  let text=String(value ?? '');
  for(const sensitive of redactions)if(sensitive)text=text.split(sensitive).join('[redacted]');
  return text.split('\n').map(line=>/authorization|set-cookie|csrf[_-]?token|totp[_-]?secret|api[_-]?key|password|session[_-]?secret/i.test(line)?'[redacted sensitive log line]':line).join('\n');
}
function documentSummary(document) {
  if(!document)return null;
  return {id:document.id,status:document.status,extraction_version:document.extraction_version,last_error:document.last_error,
    linked_task:Boolean(document.task_id),size_bytes:document.size_bytes,media_type:document.media_type,
    extraction:document.extraction?{page_count:document.extraction.pages?.length,
      methods:document.extraction.pages?.map(page=>page.method),candidate_fields:Object.keys(document.extraction.candidates||{}),
      review_required:document.extraction.review_required}:null};
}
async function extractThroughUI(page, documentId, label) {
  stage=label;
  const [response]=await Promise.all([
    page.waitForResponse(response=>{const url=new URL(response.url());return url.origin===origin&&url.pathname===`/api/documents/${documentId}/extract`&&response.request().method()==='POST';},{timeout:70000}),
    page.locator('#document-extract-button').click()
  ]);
  const body=await response.json().catch(()=>null);
  const summary={stage:label,status:response.status(),error:body?.error?{code:body.error.code,message:body.error.message}:null,document:documentSummary(body?.document)};
  // Never wait 70 seconds for a field that cannot appear after a known HTTP refusal.
  assert.equal(response.status(),200,redact(JSON.stringify(summary)));
  assert.ok(body?.document?.extraction,redact(JSON.stringify(summary)));
  await page.locator('[data-document-field="invoice_number"]').waitFor({timeout:10000});
  await page.waitForFunction(()=>{const button=document.querySelector('#document-extract-button');return button&&!button.disabled;},null,{timeout:10000});
  return body.document;
}
async function failureDiagnostics() {
  const details={stage,http:httpDiagnostics.slice(-30),javascriptErrors,unexpectedRequests,
    processes:{server:{pid:server?.pid,exitCode:server?.exitCode,signal:server?.signalCode},worker:{pid:worker?.pid,exitCode:worker?.exitCode,signal:worker?.signalCode}},
    server_log:redact(serverOutput.slice(-8000)),worker_log:redact(workerOutput.slice(-8000)),pages:[]};
  if(browser)for(const page of browser.contexts().flatMap(context=>context.pages())){
    try{
      const info=await page.evaluate(async documentId=>{
        const errors=['finance-form-error','finance-bank-error','document-reverify-error','document-upload-error','document-action-error','document-create-error','login-error'].map(id=>({id,text:document.querySelector('#'+id)?.textContent?.slice(0,500)||''})).filter(item=>item.text);
        const response=await fetch(documentId?'/api/documents/'+documentId:'/api/documents');
        const body=await response.json().catch(()=>null);
        return {errors,status:response.status,error:body?.error,document:body?.document,
          documents:body?.documents?.map(document=>({id:document.id,status:document.status,extraction_version:document.extraction_version,last_error:document.last_error}))};
      },diagnosticDocumentId);
      if(info.document)info.document=documentSummary(info.document);
      details.pages.push(info);
    }catch(error){details.pages.push({diagnostic_error:redact(error.message).slice(0,300)});}
  }
  try {
    details.runtime=JSON.parse(runPython(`import json,os,sys,resource
from pathlib import Path
uid=os.getuid();processes=threads=0
for status in Path('/proc').glob('[0-9]*/status'):
 try:
  fields={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in status.read_text().splitlines() if ':' in line}
  if int(fields.get('Uid','-1').split()[0])==uid: processes+=1;threads+=int(fields.get('Threads','0'))
 except (OSError,ValueError): pass
print(json.dumps({'python':sys.version.split()[0],'uid':uid,'same_uid_processes':processes,'same_uid_threads':threads,'inherited_nproc':list(resource.getrlimit(resource.RLIMIT_NPROC)),'inherited_nofile':list(resource.getrlimit(resource.RLIMIT_NOFILE))}))`));
  }catch(error){details.runtime={diagnostic_error:redact(error.message).slice(0,300)};}
  const output=redact(JSON.stringify(details,null,2));
  fs.writeFileSync(path.join(artifacts,'failure-diagnostics.json'),output+'\n');
  console.error('FINANCE BROWSER DIAGNOSTICS\n'+output);
}
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
  throw new Error(`Production document server startup timeout: ${serverOutput}`);
}
async function noHorizontalPageOverflow(page, label) {
  const bounds = await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth}));
  assert.ok(bounds.document<=bounds.viewport+1 && bounds.body<=bounds.viewport+1, `${label}: ${JSON.stringify(bounds)}`);
}
async function screenshot(page, name) {
  // A full-page capture relocates viewport-fixed dialog/backdrop context on long pages.
  await page.waitForFunction(()=>document.querySelectorAll('#toast-region .toast').length===0,null,{timeout:8000});
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
  const otpValue=code || otp(user.totp_secret);redactions.push(otpValue);
  await page.locator('#login-otp').fill(otpValue);
  await page.locator('#login-form button[type=submit]').click();
}
async function contextPage(viewport) {
  const context=await browser.newContext({viewport,ignoreHTTPSErrors:true,locale:'fr-FR'});
  await context.route('**/*',route=>{
    const url=new URL(route.request().url());
    if(url.hostname!==hostname){unexpectedRequests.push(url.hostname);return route.abort();}
    return route.continue();
  });
  const page=await context.newPage();
  page.on('pageerror',error=>javascriptErrors.push(redact(error.message)));
  page.on('response',response=>{
    const url=new URL(response.url());
    if(url.origin===origin&&url.pathname.startsWith('/api/')){
      httpDiagnostics.push({method:response.request().method(),path:url.pathname,status:response.status()});
      if(httpDiagnostics.length>50)httpDiagnostics.shift();
    }
  });
  page.on('requestfailed',request=>{
    const url=new URL(request.url());
    if(url.origin===origin&&url.pathname.startsWith('/api/'))httpDiagnostics.push({method:request.method(),path:url.pathname,failed:request.failure()?.errorText});
  });
  await page.goto(origin,{waitUntil:'networkidle'});
  await page.locator('#login-form').waitFor();
  return {context,page};
}

function syntheticPDF() {
  const invoice = ['Invoice number: QA-DOC-001','Supplier: Atelier Synthetic','Customer: Demo Client','Issue date: 2026-10-01','Due date: 2026-10-31','Net amount: 100.00','VAT rate: 20','VAT amount: 20.00','Total amount: 120.00','Currency: EUR','SYNTHETIC DOCUMENT - NO REAL TRANSACTION'];
  const pages = [invoice,['Synthetic annex - page two','Use the original document to review all extracted fields.']];
  const objects = [null,'<< /Type /Catalog /Pages 2 0 R >>','', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  const pageIds = [];
  for (const lines of pages) {
    const pageId=objects.length;const contentId=pageId+1;pageIds.push(pageId);
    const stream='BT /F1 14 Tf 45 780 Td 24 TL '+lines.map((line,index)=>`${index?'T* ':''}(${line.replace(/[\\()]/g,'\\$&')}) Tj`).join('\n')+' ET';
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents ${contentId} 0 R >>`);
    objects.push(`<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`);
  }
  objects[2]=`<< /Type /Pages /Kids [${pageIds.map(id=>id+' 0 R').join(' ')}] /Count ${pages.length} >>`;
  let pdf='%PDF-1.4\n';const offsets=[0];
  objects.slice(1).forEach((object,index)=>{offsets.push(Buffer.byteLength(pdf));pdf+=`${index+1} 0 obj\n${object}\nendobj\n`;});
  const xref=Buffer.byteLength(pdf);pdf+=`xref\n0 ${objects.length}\n0000000000 65535 f \n`+offsets.slice(1).map(offset=>String(offset).padStart(10,'0')+' 00000 n \n').join('');
  pdf+=`trailer\n<< /Size ${objects.length} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(pdf);
}
async function waitForWorker(port) {
  const end=Date.now()+15000;
  while(Date.now()<end){
    if(worker.exitCode!==null)throw new Error('OCR worker exited: '+redact(workerOutput));
    const ready=await new Promise(resolve=>{const req=http.get({hostname:'127.0.0.1',port,path:'/health'},res=>{res.resume();resolve(res.statusCode===200);});req.on('error',()=>resolve(false));});
    if(ready)return;
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw new Error('OCR worker did not become ready: '+redact(workerOutput));
}

(async()=>{
  fs.mkdirSync(artifacts,{recursive:true});
  const original=syntheticPDF();
  const pdfPath=path.join(temp,'synthetic-invoice.pdf');fs.writeFileSync(pdfPath,original);
  fs.writeFileSync(path.join(temp,'session-secret'),secret,{mode:0o600});
  execFileSync('openssl',['req','-x509','-newkey','rsa:2048','-nodes','-keyout',path.join(temp,'tls.key'),'-out',path.join(temp,'tls.crt'),'-days','1','-subj',`/CN=${hostname}`,'-addext',`subjectAltName=IP:${hostname}`],{stdio:'ignore'});
  const backendPort=await freePort();const workerPort=await freePort();
  proxy=https.createServer({key:fs.readFileSync(path.join(temp,'tls.key')),cert:fs.readFileSync(path.join(temp,'tls.crt'))},(incoming,outgoing)=>{
    const upstream=http.request({hostname:'127.0.0.1',port:backendPort,path:incoming.url,method:incoming.method,headers:incoming.headers},response=>{outgoing.writeHead(response.statusCode,response.headers);response.pipe(outgoing);});
    upstream.on('error',()=>{if(!outgoing.headersSent)outgoing.writeHead(502);outgoing.end();});incoming.pipe(upstream);
  });
  await new Promise((resolve,reject)=>{proxy.once('error',reject);proxy.listen(0,'127.0.0.1',resolve);});
  origin=`https://${hostname}:${proxy.address().port}`;
  environment={...process.env,ADMIN_AGENT_CLIENT_ID:'finance-browser',ADMIN_AGENT_CLIENT_NAME:clientName,ADMIN_AGENT_PUBLIC_ORIGIN:origin,
    ADMIN_AGENT_DB:path.join(temp,'browser.sqlite3'),ADMIN_AGENT_SESSION_SECRET_FILE:path.join(temp,'session-secret'),
    ADMIN_AGENT_BIND:'127.0.0.1',ADMIN_AGENT_PORT:String(backendPort),ADMIN_AGENT_AI_ENABLED:'0',ADMIN_AGENT_OCR_ENABLED:'1'};
  const users=JSON.parse(runPython(`import json,os,sys
from pathlib import Path
from admin_agent.storage import Store
from admin_agent.auth import AuthStore
auth=AuthStore(Store(os.environ['ADMIN_AGENT_DB']),os.environ['ADMIN_AGENT_CLIENT_ID'],os.environ['ADMIN_AGENT_CLIENT_NAME'],Path(os.environ['ADMIN_AGENT_SESSION_SECRET_FILE']).read_bytes())
password=sys.stdin.read()
print(json.dumps({role:auth.provision_user('finance-'+role,password,role) for role in ['operator','reader','admin']}))`,password));
  for(const user of Object.values(users))redactions.push(user.totp_secret);
  worker=spawn(python,['-m','admin_agent.ocr_worker','--host','127.0.0.1','--port',String(workerPort)],{cwd:root,env:environment,stdio:['ignore','pipe','pipe']});
  worker.stdout.on('data',chunk=>{workerOutput=(workerOutput+chunk).slice(-12000);});worker.stderr.on('data',chunk=>{workerOutput=(workerOutput+chunk).slice(-12000);});
  await waitForWorker(workerPort);
  // The only OCR destination override is inside this isolated test process.
  // The production environment never accepts a configurable arbitrary OCR URL.
  const harness=`import os
from waitress import serve
from admin_agent.production import create_app,ProductionConfig
from admin_agent.documents import OCRClient
# Test injection is fixed to the local worker started above.
client=OCRClient('http://ocr:8766')
client.url='http://127.0.0.1:${workerPort}'
app=create_app(ProductionConfig.from_environment(),ocr_client=client)
serve(app,host='127.0.0.1',port=${backendPort},threads=4,url_scheme='https',max_request_body_size=6*1024*1024,expose_tracebacks=False)`;
  server=spawn(python,['-c',harness],{cwd:root,env:environment,stdio:['ignore','pipe','pipe']});
  server.stdout.on('data',chunk=>{serverOutput=(serverOutput+chunk).slice(-12000);});server.stderr.on('data',chunk=>{serverOutput=(serverOutput+chunk).slice(-12000);});
  await waitForBackend(backendPort);
  browser=await chromium.launch({headless:true,...(process.env.CHROMIUM_EXECUTABLE?{executablePath:process.env.CHROMIUM_EXECUTABLE}:{}),args:['--no-sandbox','--disable-dev-shm-usage']});
  console.log(`Browser: Chromium ${await browser.version()}; real isolated OCR worker, production app, local test TLS.`);
  const {context,page}=await contextPage({width:1360,height:960});
  assert.equal((await request(page,'/api/documents')).status,401);
  await signIn(page,users.operator);await page.locator('.metric-card').first().waitFor();
  assert.equal((await session(page)).capabilities.documents_upload,true);
  const relative=days=>{const date=new Date();date.setUTCDate(date.getUTCDate()+days);return date.toISOString().slice(0,10);};
  const today=relative(0),yesterday=relative(-1),due=relative(30);
  stage='create reviewed source';
  const created=await request(page,'/api/tasks',{title:'Facture finance synthétique',description:'Synthetic browser QA only',skill_id:'invoice-check',country:'FR',payload:{invoice_number:'SYN-FIN-001',supplier:'Atelier fictif',customer:'Client fictif',issue_date:yesterday,due_date:due,net_amount:'100.00',vat_rate:'20.00',vat_amount:'20.00',total_amount:'120.00',currency:'EUR',paid:false}});
  assert.equal(created.status,201,JSON.stringify(created.data));let invoiceTask=created.data.task;
  assert.equal((await request(page,`/api/tasks/${invoiceTask.id}/analyze`,{})).status,200);
  invoiceTask=(await request(page,`/api/tasks/${invoiceTask.id}`)).data.task;
  assert.equal((await request(page,`/api/tasks/${invoiceTask.id}/review`,{decision:'approve',note:'Synthetic reviewed fixture',version:invoiceTask.version})).status,200);
  await page.reload({waitUntil:'networkidle'});await page.locator('[data-page=finance]').click();
  await page.locator('[data-action=finance-register]').waitFor();await page.locator('[data-action=finance-register]').click();
  await page.locator('#finance-register-task').selectOption(invoiceTask.id);await page.locator('#finance-register-source').getByText(/SYN-FIN-001/).waitFor();
  await page.locator('#finance-direction').selectOption('receivable');await page.locator('#finance-opening-paid').fill('0.00');await page.locator('#finance-opening-date').fill(yesterday);await page.locator('#finance-disputed').selectOption('false');await page.locator('#finance-register-evidence').fill('Synthetic closing balance verified');
  await page.locator('#finance-register-form button[type=submit]').click();await page.locator('#finance-form-error').getByText(/Confirmez/).waitFor();
  await page.locator('#finance-opening-confirmed').check();await page.locator('#finance-register-form button[type=submit]').click();await page.locator('#finance-dialog').waitFor({state:'hidden'});
  await page.locator('.finance-record').first().waitFor();let financial=(await request(page,'/api/finance/invoices')).data.invoices[0];assert.equal(financial.remaining_amount,'120.00');assert.equal(financial.direction,'receivable');
  await noHorizontalPageOverflow(page,'Finance desktop');await screenshot(page,'finance-invoices-desktop');
  passed('Ready source registration requires explicit opening confirmation and persists correct invoice balance');

  stage='factoring explicit terms';
  await page.locator('[data-action=finance-tab][data-tab=factoring]').click();await page.locator('[data-action=finance-factor]').click();assert.equal(await page.locator('#finance-advance-rate').inputValue(),'');
  await page.locator('#finance-factor-invoice').selectOption(financial.id);await page.locator('#finance-funding-date').fill(today);
  for(const [id,value]of Object.entries({'finance-advance-rate':'80','finance-fee-rate':'1','finance-interest-rate':'6','finance-fixed-fee':'0'}))await page.locator('#'+id).fill(value);
  await page.locator('#finance-day-basis').selectOption('360');await page.locator('#finance-factoring-form button[type=submit]').click();await page.locator('#finance-simulation h3').waitFor();
  assert.match(await page.locator('#finance-simulation').innerText(),/94.32 EUR/);assert.match(await page.locator('#finance-simulation').innerText(),/Aucun financeur consulté/);await screenshot(page,'finance-factoring-desktop');
  passed('Simulation requires declared terms and displays exact 30-day deterministic cost without an offer or payment');

  stage='bank preview import duplicate';
  const csv=`transaction_id,date,amount,currency,reference\nSYN-BANK-001,${today},60.00,EUR,SYN-FIN-001\n`;
  await page.locator('[data-action=finance-tab][data-tab=bank]').click();await page.locator('#finance-account').fill('synthetic-bank');await page.locator('#finance-csv').fill(csv);
  await page.locator('#finance-bank-form button[type=submit]').click();await page.locator('#finance-import-confirmed').waitFor();assert.equal((await request(page,'/api/finance/bank-transactions')).data.transactions.length,0);
  await page.locator('[data-action=finance-import]').click();assert.match(await page.locator('#finance-bank-error').innerText(),/confirmez/);
  await page.locator('#finance-import-confirmed').check();await page.locator('[data-action=finance-import]').click();await page.waitForFunction(()=>document.querySelector('#finance-csv')?.value==='');
  assert.equal((await request(page,'/api/finance/bank-transactions')).data.transactions.length,1);
  await page.locator('#finance-csv').fill(csv);await page.locator('#finance-bank-form button[type=submit]').click();await page.locator('#finance-import-confirmed').waitFor();assert.match(await page.locator('#finance-bank-preview').innerText(),/1 déjà importées/);
  await page.locator('#finance-import-confirmed').check();await page.locator('[data-action=finance-import]').click();await page.waitForFunction(()=>document.querySelector('#finance-csv')?.value==='');assert.equal((await request(page,'/api/finance/bank-transactions')).data.transactions.length,1);
  passed('CSV preview is separate from confirmed import, duplicate replay does not create another movement');

  stage='partial allocation reversal';
  await page.locator('[data-action=finance-suggestion]').first().click();await page.locator('#finance-allocation-amount').fill('40.00');await page.locator('#finance-allocation-evidence').fill('Synthetic reference cross-check');await page.locator('#finance-allocation-confirmed').check();await page.locator('#finance-allocation-form button[type=submit]').click();await page.locator('#finance-dialog').waitFor({state:'hidden'});
  financial=(await request(page,'/api/finance/invoices')).data.invoices[0];assert.equal(financial.remaining_amount,'80.00');assert.equal(financial.payment_status,'partial');assert.equal((await request(page,'/api/finance/bank-transactions')).data.transactions[0].remaining_amount,'20.00');
  await page.locator('[data-action=finance-reverse]').first().click();await page.locator('#finance-reverse-reason').fill('Synthetic audit reversal');await page.locator('#finance-reverse-confirmed').check();await page.locator('#finance-reverse-form button[type=submit]').click();await page.locator('#finance-dialog').waitFor({state:'hidden'});
  assert.equal((await request(page,'/api/finance/invoices')).data.invoices[0].remaining_amount,'120.00');assert.equal((await request(page,'/api/finance/allocations')).data.allocations[0].status,'reversed');
  await page.setViewportSize({width:390,height:844});await noHorizontalPageOverflow(page,'Bank mobile');await screenshot(page,'finance-bank-mobile');
  passed('Human-confirmed partial allocation updates both available balances; reversal restores them with audit retained');

  stage='invoice dispute and assignment';
  await page.locator('[data-action=finance-tab][data-tab=invoices]').click();await page.locator('[data-action=finance-state]').click();await page.locator('#finance-state-disputed').selectOption('true');await page.locator('#finance-state-date').fill(today);await page.locator('#finance-state-evidence').fill('Synthetic claim record');await page.locator('#finance-state-note').fill('Synthetic dispute opened');await page.locator('#finance-state-form button[type=submit]').click();await page.locator('#finance-dialog').waitFor({state:'hidden'});
  assert.equal((await request(page,'/api/finance/invoices')).data.invoices[0].disputed,true);await page.locator('[data-action=finance-state]').click();await page.locator('#finance-state-disputed').selectOption('false');await page.locator('#finance-state-date').fill(today);await page.locator('#finance-state-evidence').fill('Synthetic resolution record');await page.locator('#finance-state-note').fill('Synthetic dispute resolved');await page.locator('#finance-state-form button[type=submit]').click();await page.locator('#finance-dialog').waitFor({state:'hidden'});
  await page.locator('[data-action=finance-tab][data-tab=factoring]').click();await page.locator('[data-action=finance-assignment]').click();await page.locator('#finance-assignment-invoice').selectOption(financial.id);await page.locator('#finance-assignment-status').selectOption('assigned');await page.locator('#finance-assignment-date').fill(today);await page.locator('#finance-assignment-evidence').fill('Synthetic existing decision');await page.locator('#finance-assignment-note').fill('No real transfer');await page.locator('#finance-assignment-confirmed').check();await page.locator('#finance-assignment-form button[type=submit]').click();await page.locator('#finance-dialog').waitFor({state:'hidden'});
  financial=(await request(page,'/api/finance/invoices')).data.invoices[0];assert.equal(financial.assignment_status,'assigned');assert.equal(financial.paid_amount,'0.00');
  passed('Dispute state is revisable with evidence; declaring a cession never records a customer payment');

  stage='receipt actual OCR';
  const receiptPath=path.join(temp,'synthetic-receipt.png');
  runPython(`from PIL import Image,ImageDraw,ImageFont
from pathlib import Path
image=Image.new('RGB',(1600,1100),'white');draw=ImageDraw.Draw(image);font=ImageFont.load_default(size=36)
lines=['SYNTHETIC RECEIPT - NO REAL PAYMENT','Merchant: Synthetic Cafe','Receipt date: ${yesterday}','Total amount: 24.00','Currency: EUR','One synthetic professional expense']
for index,line in enumerate(lines):draw.text((55,50+index*135),line,font=font,fill='black')
image.save(${JSON.stringify(receiptPath)})`);
  await page.setViewportSize({width:1360,height:960});await page.locator('[data-page=documents]').click();await page.locator('#document-file').setInputFiles(receiptPath);await page.locator('#document-upload-form button[type=submit]').click();await page.locator('#document-extract-form').waitFor();
  let doc=(await request(page,'/api/documents')).data.documents[0];diagnosticDocumentId=doc.id;
  await page.locator('#document-language').selectOption('eng');const [extractionResponse]=await Promise.all([page.waitForResponse(r=>r.url().endsWith(`/api/documents/${doc.id}/extract`)&&r.request().method()==='POST',{timeout:70000}),page.locator('#document-extract-button').click()]);const extracted=await extractionResponse.json();assert.equal(extractionResponse.status(),200,JSON.stringify(extracted.error));assert.equal(extracted.document.extraction.pages[0].method,'ocr');
  await page.locator('#document-skill').selectOption('expense-review');await page.locator('#document-field-merchant').waitFor();assert.equal(await page.locator('#document-field-payment_confirmed').inputValue(),'');await page.locator('#document-country').selectOption('FR');
  // Intentionally compare and correct actual OCR proposals; this is synthetic explicit review, not an OCR accuracy claim.
  const textFields={merchant:'Synthetic Cafe',expense_date:yesterday,total_amount:'24.00',currency:'EUR',employee_ref:'SYN-EMP-01',business_purpose:'Synthetic professional meeting',policy_ref:'SYN-POLICY-v1'};
  for(const [field,value]of Object.entries(textFields))await page.locator('#document-field-'+field).fill(value);
  await page.locator('#document-field-category').selectOption('meals');await page.locator('#document-field-payment_method').selectOption('employee_card');
  for(const [field,value]of Object.entries({paid_by_company:'false',reimbursed:'false',business_only:'true',policy_confirmed:'true',payment_confirmed:'true'}))await page.locator('#document-field-'+field).selectOption(value);
  for(const input of await page.locator('[data-document-field]').all())if(await input.inputValue())await page.locator('#document-verify-'+await input.getAttribute('data-document-field')).check();
  await page.locator('#document-human-verified').check();await page.setViewportSize({width:390,height:844});await noHorizontalPageOverflow(page,'Receipt review mobile');await screenshot(page,'expense-review-mobile');
  await page.locator('#document-create-form button[type=submit]').click();await page.locator('#detail-dialog [data-action=analyze]').waitFor();
  const expense=(await request(page,'/api/tasks')).data.tasks.find(t=>t.skill_id==='expense-review');assert.ok(expense);assert.equal(expense.status,'new');await page.locator('#detail-dialog [data-action=analyze]').click();await page.locator('#review-note').waitFor();assert.equal((await request(page,`/api/tasks/${expense.id}`)).data.task.status,'needs_review');
  passed('Real receipt OCR proposes sourced expense fields; explicit human context and checks create a new expense then permit review');

  stage='expense correction reverify';
  await page.locator('[data-action=edit-task]').click();await page.locator('#field-merchant').fill('Synthetic Cafe corrected');await page.locator('#task-form button[type=submit]').click();await page.locator('#detail-dialog .status-alert.blocked').waitFor();
  let edited=(await request(page,`/api/tasks/${expense.id}`)).data.task;assert.equal(edited.status,'blocked');
  await page.locator('#detail-dialog [data-action=document-open]').click();await page.locator('#document-reverify-form').waitFor();assert.match(await page.locator('#document-reverify-form').innerText(),/Synthetic Cafe corrected/);
  for(const checkbox of await page.locator('[data-reverify-field]').all())await checkbox.check();await page.locator('#document-reverify-confirmed').check();await screenshot(page,'expense-reconfirmation-mobile');await page.locator('#document-reverify-form button[type=submit]').click();await page.locator('#detail-dialog [data-action=analyze]').waitFor();
  edited=(await request(page,`/api/tasks/${expense.id}`)).data.task;assert.equal(edited.status,'new');assert.equal(edited.result,null);assert.equal(edited.payload._document_source.receipt_reviews.length,1);
  await page.locator('#detail-dialog [data-action=analyze]').click();await page.locator('#review-note').waitFor();await page.locator('#detail-dialog [data-action=close]').first().click();
  passed('Changing a receipt source field blocks reuse; explicit four-field reconfirmation preserves source history and resets analysis');

  stage='reader and logout';
  const {context:readerContext,page:reader}=await contextPage({width:390,height:844});await signIn(reader,users.reader);await reader.locator('.metric-card').first().waitFor();await reader.locator('[data-page=finance]').click();await reader.locator('.finance-record').first().waitFor();assert.equal(await reader.locator('[data-action=finance-register]').count(),0);assert.equal((await request(reader,'/api/finance/bank/preview',{account_ref:'synthetic',csv_text:csv})).status,403);assert.equal((await request(reader,'/api/finance/export')).status,403);await noHorizontalPageOverflow(reader,'Finance reader mobile');await screenshot(reader,'finance-reader-mobile');
  await page.locator('[data-page=finance]').click();await page.locator('[data-action=finance-tab][data-tab=bank]').click();await page.locator('#finance-csv').fill('SENSITIVE UNSENT SYNTHETIC CSV');await page.locator('#logout-button').click();await page.locator('#login-form').waitFor();assert.equal(await page.locator('#finance-csv').count(),0);assert.equal(await page.locator('#finance-dialog').innerHTML(),'');assert.equal((await request(page,'/api/finance/invoices')).status,401);
  assert.deepEqual(javascriptErrors,[]);assert.deepEqual(unexpectedRequests,[]);
  passed('Reader finance writes/export denied; logout purges unsent CSV; mobile views fit with no script errors or external requests');
  await readerContext.close();await context.close();
  console.log(`${count} finance browser scenarios passed. Synthetic screenshots: ${artifacts}`);
})().catch(async error=>{
  console.error(redact(error.stack));process.exitCode=1;
  try{await failureDiagnostics();}catch(e){console.error('Diagnostic failure: '+redact(e.message));}
  if(browser)for(const [index,page]of browser.contexts().flatMap(c=>c.pages()).entries()){try{await screenshot(page,'failure-'+index);}catch{}}
}).finally(async()=>{
  if(browser)await browser.close();
  for(const child of [server,worker])if(child&&!child.killed){child.kill('SIGTERM');await new Promise(resolve=>{child.once('exit',resolve);setTimeout(resolve,3000).unref();});}
  if(proxy){proxy.closeAllConnections();await new Promise(resolve=>proxy.close(resolve));}
  fs.rmSync(temp,{recursive:true,force:true});
});
