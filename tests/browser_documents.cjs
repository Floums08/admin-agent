/* Real Chromium against the production WSGI server behind a temporary local TLS proxy.
 * Synthetic users/data only. The self-signed certificate is accepted ONLY in this test context.
 * Run: npm ci && npx playwright install chromium && npm run test:documents-browser
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
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'admin-agent-document-browser-'));
const artifacts = path.resolve(process.env.ADMIN_AGENT_BROWSER_ARTIFACTS || path.join(root, 'artifacts', 'documents-browser'));
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
        const errors=['document-upload-error','document-action-error','document-create-error','login-error'].map(id=>({id,text:document.querySelector('#'+id)?.textContent?.slice(0,500)||''})).filter(item=>item.text);
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
  console.error('DOCUMENT BROWSER DIAGNOSTICS\n'+output);
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
    if(url.origin===origin&&url.pathname.startsWith('/api/documents')){
      httpDiagnostics.push({method:response.request().method(),path:url.pathname,status:response.status()});
      if(httpDiagnostics.length>50)httpDiagnostics.shift();
    }
  });
  page.on('requestfailed',request=>{
    const url=new URL(request.url());
    if(url.origin===origin&&url.pathname.startsWith('/api/documents'))httpDiagnostics.push({method:request.method(),path:url.pathname,failed:request.failure()?.errorText});
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
  environment={...process.env,ADMIN_AGENT_CLIENT_ID:'documents-browser',ADMIN_AGENT_CLIENT_NAME:clientName,ADMIN_AGENT_PUBLIC_ORIGIN:origin,
    ADMIN_AGENT_DB:path.join(temp,'browser.sqlite3'),ADMIN_AGENT_SESSION_SECRET_FILE:path.join(temp,'session-secret'),
    ADMIN_AGENT_BIND:'127.0.0.1',ADMIN_AGENT_PORT:String(backendPort),ADMIN_AGENT_AI_ENABLED:'0',ADMIN_AGENT_OCR_ENABLED:'1'};
  const users=JSON.parse(runPython(`import json,os,sys
from pathlib import Path
from admin_agent.storage import Store
from admin_agent.auth import AuthStore
auth=AuthStore(Store(os.environ['ADMIN_AGENT_DB']),os.environ['ADMIN_AGENT_CLIENT_ID'],os.environ['ADMIN_AGENT_CLIENT_NAME'],Path(os.environ['ADMIN_AGENT_SESSION_SECRET_FILE']).read_bytes())
password=sys.stdin.read()
print(json.dumps({role:auth.provision_user('documents-'+role,password,role) for role in ['operator','reader']}))`,password));
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
  stage='document upload';
  await page.locator('.nav-link[data-page=documents]').click();
  await page.locator('#document-file').setInputFiles(pdfPath);
  await page.locator('#document-upload-form button[type=submit]').click();
  await page.locator('#document-dialog[open]').waitFor();
  let documents=(await request(page,'/api/documents')).data.documents;
  assert.equal(documents.length,1);let doc=documents[0];diagnosticDocumentId=doc.id;
  assert.equal(doc.sha256,crypto.createHash('sha256').update(original).digest('hex'));
  assert.equal((await request(page,'/api/tasks')).data.tasks.length,0);
  passed('Authenticated PDF upload persists original/hash, with no automatic extraction or task creation');

  await page.locator('#document-language').selectOption('eng');
  let extracted=await extractThroughUI(page,doc.id,'native document extraction');
  assert.equal(extracted.extraction.pages.length,2);assert.equal(extracted.extraction.pages[0].method,'native');
  assert.equal(extracted.extraction.candidates.total_amount.value,'120.00');
  assert.equal(extracted.extraction.candidates.total_amount.page,1);
  assert.match(extracted.extraction.candidates.total_amount.quote,/120\.00/);
  assert.ok(extracted.extraction.candidates.total_amount.bbox.every(n=>n>=0&&n<=1));
  assert.equal(await page.locator('#document-verify-total_amount').isChecked(),false);
  await screenshot(page,'document-native-desktop');
  passed('Native PDF extraction presents two pages and sourced amount proposals awaiting individual verification');

  await page.locator('#document-force-ocr').check();
  extracted=await extractThroughUI(page,doc.id,'forced document OCR');
  assert.ok(extracted.extraction.pages.every(p=>p.method==='ocr'));
  assert.ok(extracted.extraction_version>=2);
  assert.equal(await page.locator('#document-verify-total_amount').isChecked(),false);
  passed('Forced OCR invokes real Tesseract and invalidates prior field confirmations');

  stage='individual field confirmation';
  await page.locator('#document-country').selectOption('FR');
  await page.locator('#document-human-verified').check();
  await page.locator('#document-create-form button[type=submit]').click();
  await page.waitForFunction(()=>document.querySelector('#document-create-error')?.textContent.includes('Cochez'));
  assert.equal((await request(page,'/api/tasks')).data.tasks.length,0);
  passed('A global confirmation cannot bypass verification of every populated field');

  const total=page.locator('[data-document-field="total_amount"]');
  await page.locator('#document-verify-total_amount').check();await total.fill('121.00');
  assert.equal(await page.locator('#document-verify-total_amount').isChecked(),false);
  assert.equal((await request(page,'/api/tasks')).data.tasks.length,0);
  await total.fill('120.00');
  await page.locator('#document-skill').selectOption('invoice-check');
  const values={invoice_number:'QA-DOC-001',supplier:'Atelier Synthetic',customer:'Demo Client',issue_date:'2026-10-01',due_date:'2026-10-31',net_amount:'100.00',vat_rate:'20',vat_amount:'20.00',total_amount:'120.00',currency:'EUR',paid:'false'};
  for(const [field,value]of Object.entries(values)){
    const input=page.locator(`[data-document-field="${field}"]`);
    if(await input.evaluate(node=>node.tagName==='SELECT'))await input.selectOption(value);else await input.fill(value);
    await page.locator('#document-verify-'+field).check();
  }
  await page.locator('#document-title').fill('Reviewed synthetic document QA');
  await page.locator('#document-country').selectOption('FR');
  await page.locator('#document-human-verified').check();
  await screenshot(page,'document-reviewed-desktop');
  passed('Editing a proposal clears its confirmation; every included field is explicitly reviewed');

  await page.setViewportSize({width:390,height:844});await noHorizontalPageOverflow(page,'Document review mobile');await screenshot(page,'document-review-mobile');
  await page.locator('#document-create-form button[type=submit]').click();
  await page.locator('#detail-dialog[open]').waitFor();
  const tasks=(await request(page,'/api/tasks')).data.tasks;assert.equal(tasks.length,1);
  const task=(await request(page,'/api/tasks/'+tasks[0].id)).data.task;
  assert.equal(task.status,'new');assert.equal(task.result,null);
  assert.equal(task.payload._document_source.document_id,doc.id);
  assert.equal(task.payload._document_source.sha256,doc.sha256);
  assert.equal(task.payload.total_amount,'120.00');
  assert.match(await page.locator('#detail-dialog').innerText(),/source|original|document/i);
  await screenshot(page,'document-task-mobile');
  passed('Confirmed extraction creates a new unreviewed task with immutable source provenance; mobile dialog fits');

  stage='original source download';
  await page.locator('#detail-dialog [data-action=document-open]').click();
  await page.locator('#document-dialog[open]').waitFor();
  assert.equal(await page.locator('#detail-dialog[open]').count(),0);
  const [download]=await Promise.all([page.waitForEvent('download'),page.locator('[data-action=document-download]').click()]);
  assert.deepEqual(fs.readFileSync(await download.path()),original);
  const downloaded=await page.evaluate(async id=>{const response=await fetch('/api/documents/'+id+'/original');return {status:response.status,disposition:response.headers.get('content-disposition'),bytes:Array.from(new Uint8Array(await response.arrayBuffer()))};},doc.id);
  assert.equal(downloaded.status,200);assert.match(downloaded.disposition,/attachment/);assert.deepEqual(Buffer.from(downloaded.bytes),original);
  passed('Task source opens its original; real UI download is byte-identical and attachment-only');

  stage='reader permissions';
  const {context:readerContext,page:reader}=await contextPage({width:390,height:844});
  await signIn(reader,users.reader);await reader.locator('.metric-card').first().waitFor();
  await reader.locator('.nav-link[data-page=documents]').click();
  assert.equal(await reader.locator('#document-upload-form').count(),0);
  assert.equal((await request(reader,'/api/documents')).status,200);
  assert.equal((await request(reader,'/api/documents/'+doc.id+'/extract',{version:extracted.extraction_version,language:'eng'})).status,403);
  assert.equal((await request(reader,'/api/documents/'+doc.id+'/create-task',{})).status,403);
  await noHorizontalPageOverflow(reader,'Documents reader mobile');await screenshot(reader,'document-reader-mobile');
  await reader.locator('.document-title-button').click();await reader.locator('#document-dialog[open]').waitFor();
  await reader.locator('.document-page').first().waitFor({timeout:10000});
  assert.equal(await reader.locator('#document-extract-form,#document-create-form').count(),0);
  assert.equal(await reader.locator('.document-page').count(),2);
  passed('Reader can consult source documents but cannot upload, extract or create a task');
  assert.deepEqual(javascriptErrors,[]);assert.deepEqual(unexpectedRequests,[]);
  passed('No JavaScript errors and no browser requests outside the local test origin');
  await readerContext.close();await context.close();
  console.log(`${count} document browser scenarios passed. Synthetic screenshots: ${artifacts}`);
})().catch(async error=>{
  console.error(redact(error.stack));process.exitCode=1;
  try{await failureDiagnostics();}catch(diagnosticError){console.error('Diagnostic collection failed: '+redact(diagnosticError.message));}
  if(browser)for(const [index,page]of browser.contexts().flatMap(context=>context.pages()).entries()){try{await screenshot(page,'failure-'+index);}catch{}}
}).finally(async()=>{
  if(browser)await browser.close();
  for(const child of [server,worker])if(child&&!child.killed){child.kill('SIGTERM');await new Promise(resolve=>{child.once('exit',resolve);setTimeout(resolve,3000).unref();});}
  if(proxy){proxy.closeAllConnections();await new Promise(resolve=>proxy.close(resolve));}
  fs.rmSync(temp,{recursive:true,force:true});
});
