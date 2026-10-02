/* Document UI boundary tests with simulated transport; browser_documents.cjs tests actual HTTPS+worker. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const {parseHTML}=require('linkedom');
const root=path.resolve(__dirname,'..'),source=fs.readFileSync(path.join(root,'web/app.js'),'utf8');
let count=0;const passed=label=>console.log(`PASS documents ${++count}: ${label}`);
const extraction={version:1,pages:[{number:1,text:'Invoice <img src=x onerror=alert(1)>\nTOTAL TTC 120,00 EUR',method:'ocr'}],candidates:{invoice_number:{value:'SYNTH-01',page:1,quote:'Invoice SYNTH-01'},total_amount:{value:'120.00',page:1,quote:'TOTAL TTC 120,00 EUR'},currency:{value:'EUR',page:1,quote:'TOTAL TTC 120,00 EUR'}},warnings:['Vérification humaine obligatoire'],review_required:true};
const record={id:'synthetic-document',filename:'Piece <img src=x onerror=alert(1)>.pdf',media_type:'application/pdf',size_bytes:400,created_at:'2026-10-02T12:00:00Z',status:'uploaded',extraction_version:0,task_id:null,source:{kind:'Dossier de collecte'}};
const task={id:'synthetic-task',title:'Facture vérifiée',skill_id:'invoice-check',country:'FR',status:'new',version:1,payload:{}};
async function makeUI(role='operator',ocr=true){
  const {window,document}=parseHTML(fs.readFileSync(path.join(root,'web/index.html'),'utf8'));
  for(const dialog of document.querySelectorAll('dialog')){Object.defineProperty(dialog,'open',{get(){return this.hasAttribute('open');}});dialog.showModal=function(){this.setAttribute('open','');};dialog.close=function(){this.removeAttribute('open');};}
  Object.defineProperty(window.HTMLInputElement.prototype,'checked',{configurable:true,get(){return this.hasAttribute('checked');},set(v){v?this.setAttribute('checked',''):this.removeAttribute('checked');}});
  Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){const o=this.querySelector('option[selected]')||this.querySelector('option');return o?.getAttribute('value')||'';},set(v){for(const o of this.querySelectorAll('option'))o.getAttribute('value')===String(v)?o.setAttribute('selected',''):o.removeAttribute('selected');}});
  let serverRole=role,handler=null,current=structuredClone(record);const requests=[];
  const reply=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
  const session=()=>({authenticated:!!serverRole,user:serverRole?{username:'synthetic-user',role:serverRole}:null,csrf_token:'synthetic-csrf',scope:'production_single_client',client:{name:'Synthetic client'},capabilities:{documents_read:!!serverRole,documents_upload:['operator','admin'].includes(serverRole),documents_extract:['operator','admin'].includes(serverRole)&&ocr,documents_create_task:['operator','admin'].includes(serverRole),create:['operator','admin'].includes(serverRole),analyze:['operator','admin'].includes(serverRole)}});
  const fetch=async(url,options={})=>{
    const body=typeof options.body==='string'?JSON.parse(options.body):options.body;requests.push({url,options,body});
    if(handler){const response=await handler(url,options,body);if(response)return response;}
    if(url==='/api/session')return reply(session());
    if(!serverRole)return reply({error:{code:'auth_required',message:'Session expirée'}},401);
    if(options.method==='POST')assert.equal(options.headers['X-CSRF-Token'],'synthetic-csrf');
    if(url==='/api/logout'){serverRole=null;return reply(session());}
    if(url==='/api/dashboard')return reply({tasks:[],metrics:{}});
    if(url==='/api/skills')return reply({skills:[{id:'invoice-check',name:'Contrôle de facture',status:'implemented',inputs:[],outputs:[]}]});
    if(url==='/api/health')return reply({mode:'offline'});
    if(url==='/api/documents'&&options.method==='POST'){
      assert.ok(body instanceof FormData);assert.equal(options.headers['Content-Type'],undefined);assert.ok(body.get('file') instanceof Blob);return reply({document:current},201);
    }
    if(url==='/api/documents')return reply({documents:[current],enabled:true,limits:{max_file_bytes:5242880}});
    if(url==='/api/documents/synthetic-document/extract'){current={...current,status:'extracted',extraction_version:1,extraction:structuredClone(extraction)};return reply({document:current});}
    if(url==='/api/documents/synthetic-document/create-task'){current={...current,task_id:task.id};return reply({task:{...task,payload:body.payload},document:current},201);}
    if(url==='/api/documents/synthetic-document')return reply({document:current});
    if(url==='/api/tasks/synthetic-task')return reply({task,events:[]});
    throw new Error(`Unexpected request ${url}`);
  };
  const context=vm.createContext({window,document,console,FormData,crypto:webcrypto,AbortController,Blob,URL,location:{hash:'',origin:'https://client.example.test'},navigator:{clipboard:{writeText:async()=>{}}},fetch,setTimeout:(fn,ms)=>{const t=setTimeout(fn,ms);t.unref();return t;},clearTimeout});
  const run=code=>vm.runInContext(code,context);await run(source);
  return {run,document,requests,reply,window,context,setHandler:fn=>handler=fn,setRole:role=>serverRole=role,setRecord:r=>current=r};
}
(async()=>{
  const loading=await makeUI();let finishList;
  loading.setHandler(async(url,options)=>url==='/api/documents'&&!options.method?new Promise(resolve=>{finishList=()=>resolve(loading.reply({documents:[record],enabled:true,limits:{max_file_bytes:5242880}}));}):null);
  loading.run("state.page='documents';renderDocuments()");
  const originalForm=loading.document.querySelector('#document-upload-form'),originalFileInput=loading.document.querySelector('#document-file');
  const pendingFile=new File(['%PDF test selection'],'pending.pdf',{type:'application/pdf'});Object.defineProperty(originalFileInput,'files',{value:[pendingFile]});
  loading.document.querySelector('#document-upload-language').value='spa';finishList();
  for(let i=0;i<20&&!loading.run('state.documentsLoaded');i++)await new Promise(resolve=>setImmediate(resolve));
  assert.equal(loading.run('state.documentsLoaded'),true);assert.equal(loading.document.querySelector('#document-upload-form'),originalForm);assert.equal(loading.document.querySelector('#document-file'),originalFileInput);
  assert.equal(loading.document.querySelector('#document-file').files[0],pendingFile);assert.equal(loading.document.querySelector('#document-upload-language').value,'spa');
  assert.equal(loading.document.querySelectorAll('.document-title-button').length,1);
  passed('A delayed initial document list preserves the actual selected File and language while refreshing results');

  const ui=await makeUI();assert.equal(ui.document.querySelector('#documents-nav').hidden,false);
  ui.run("state.page='documents'");await ui.run('loadDocuments()');assert.equal(ui.document.querySelectorAll('.document-title-button').length,1);
  assert.equal(ui.document.querySelectorAll('img').length,0);assert.match(ui.document.querySelector('#document-list').textContent,/Dossier de collecte/);
  const file=new File(['%PDF synthetic'],'synthetic.pdf',{type:'application/pdf'});Object.defineProperty(ui.document.querySelector('#document-file'),'files',{value:[file]});
  let release;ui.setHandler(async(url,options)=>url==='/api/documents'&&options.method==='POST'?new Promise(resolve=>{release=()=>resolve(ui.reply({document:record},201));}):null);
  const uploading=ui.run("uploadDocument(document.querySelector('#document-upload-form'))");await ui.run("uploadDocument(document.querySelector('#document-upload-form'))");
  assert.equal(ui.requests.filter(r=>r.url==='/api/documents'&&r.options.method==='POST').length,1);
  const upload=ui.requests.find(r=>r.options.body instanceof FormData);assert.equal(upload.options.headers['Content-Type'],undefined);assert.equal(upload.options.headers['X-CSRF-Token'],'synthetic-csrf');
  release();await uploading;ui.setHandler(null);assert.ok(ui.document.querySelector('#document-extract-form'));
  passed('Upload keeps multipart boundary browser-owned, adds CSRF and suppresses simultaneous duplicate submissions');

  await ui.run("extractDocument(document.querySelector('#document-extract-form'))");assert.equal(ui.document.querySelectorAll('#document-dialog img').length,0);
  assert.match(ui.document.querySelector('.document-page pre').textContent,/<img/);assert.match(ui.document.querySelector('#document-field-total_amount').closest('.document-candidate').textContent,/TOTAL TTC 120,00 EUR/);
  assert.equal(ui.document.querySelector('#document-field-paid').value,'');assert.equal(ui.document.querySelector('#document-country').value,'');
  assert.equal(ui.document.querySelector('#document-verify-total_amount').checked,false);assert.equal(ui.document.querySelector('#document-human-verified').checked,false);
  passed('Extracted text is escaped; candidates retain adjacent page/quote evidence and no payment or country is inferred');

  await ui.run("createDocumentTask(document.querySelector('#document-create-form'))");assert.match(ui.document.querySelector('#document-create-error').textContent,/pays/);
  ui.document.querySelector('#document-country').value='FR';ui.document.querySelector('#document-human-verified').checked=true;
  await ui.run("createDocumentTask(document.querySelector('#document-create-form'))");assert.match(ui.document.querySelector('#document-create-error').textContent,/chaque information/);
  ui.document.querySelector('#document-field-total_amount').value='121,00';ui.document.querySelector('#document-verify-total_amount').checked=true;
  ui.document.querySelector('#document-field-total_amount').dispatchEvent(new ui.window.Event('input',{bubbles:true}));assert.equal(ui.document.querySelector('#document-verify-total_amount').checked,false);assert.equal(ui.document.querySelector('#document-human-verified').checked,false);
  for(const field of ['invoice_number','total_amount','currency'])ui.document.querySelector(`#document-verify-${field}`).checked=true;ui.document.querySelector('#document-human-verified').checked=true;
  await ui.run("createDocumentTask(document.querySelector('#document-create-form'))");
  const create=ui.requests.find(r=>r.url.endsWith('/create-task'));assert.equal(create.body.payload.total_amount,'121.00');assert.equal(Object.hasOwn(create.body.payload,'paid'),false);assert.equal(Object.hasOwn(create.body.payload,'disputed'),false);assert.deepEqual(create.body.verified_fields.sort(),['currency','invoice_number','total_amount']);assert.equal(create.body.human_verified,true);assert.equal(create.body.extraction_version,1);
  assert.equal(ui.run('state.documentDetail.extraction.candidates.total_amount.value'),'120.00');assert.equal(ui.requests.some(r=>r.url.endsWith('/analyze')||r.url.endsWith('/review')),false);
  ui.run("state.detail.payload._document_source={document_id:'synthetic-document',extraction_version:1,reviewed_at:'2026-10-02T12:00:00Z',changed_since_document_review:['total_amount']};renderTaskDetail()");
  assert.match(ui.document.querySelector('.task-document-source').textContent,/Pièce source/);assert.match(ui.document.querySelector('.task-document-source').textContent,/extraction version 1/);assert.match(ui.document.querySelector('.task-document-source').textContent,/Montant TTC/);
  assert.equal(ui.document.querySelector('#detail-dialog [data-action=document-open]').dataset.id,'synthetic-document');
  passed('Creation requires field-by-field review; corrections preserve source candidate and create without analysis, payment inference or approval');

  const reader=await makeUI('reader');reader.setRecord({...record,status:'extracted',extraction_version:1,extraction});reader.run("state.page='documents'");await reader.run('loadDocuments()');await reader.run("openDocument('synthetic-document')");
  for(const id of ['document-upload-form','document-extract-form','document-create-form'])assert.equal(reader.document.querySelector('#'+id),null);
  assert.ok(reader.document.querySelector('[data-action=document-download]'));assert.match(reader.document.querySelector('.document-review').textContent,/120.00/);
  const before=reader.requests.length;await reader.run('uploadDocument({});extractDocument({});createDocumentTask({})');assert.equal(reader.requests.length,before);
  passed('Reader can inspect source text, candidates and original but cannot upload, extract or create through controls or direct handlers');

  const retry=await makeUI();retry.setRecord({...record,status:'extracted',extraction_version:1,extraction});await retry.run("openDocument('synthetic-document')");
  retry.document.querySelector('#document-country').value='ES';for(const field of ['invoice_number','total_amount','currency'])retry.document.querySelector(`#document-verify-${field}`).checked=true;retry.document.querySelector('#document-human-verified').checked=true;
  let first=true;retry.setHandler(async(url,options)=>{if(url.endsWith('/create-task')&&first){first=false;throw new Error('Lost response');}return null;});
  await retry.run("createDocumentTask(document.querySelector('#document-create-form'))");assert.match(retry.document.querySelector('#document-create-error').textContent,/Lost response/);
  await retry.run("createDocumentTask(document.querySelector('#document-create-form'))");const attempts=retry.requests.filter(r=>r.url.endsWith('/create-task'));assert.equal(attempts.length,2);assert.deepEqual(attempts[0].body,attempts[1].body);
  passed('Retry after uncertain create response sends identical reviewed data for backend idempotency');

  const race=await makeUI();race.setRecord({...record,status:'extracted',extraction_version:1,extraction});await race.run("openDocument('synthetic-document')");let finish;
  race.setHandler(async url=>url.endsWith('/extract')?new Promise(resolve=>{finish=()=>resolve(race.reply({document:{...record,extraction,extraction_version:2}}));}):null);
  const pending=race.run("extractDocument(document.querySelector('#document-extract-form'))");await race.run('logout()');finish();await pending;
  assert.equal(race.run('state.documentDetail'),null);assert.equal(race.run('state.documents.length'),0);assert.equal(race.document.querySelector('#document-dialog').innerHTML,'');assert.equal(race.document.querySelector('#document-file'),null);assert.equal(race.document.body.textContent.includes('SYNTH-01'),false);
  passed('Logout purges files, document text and candidates; an old extraction response cannot restore sensitive content');

  const unavailable=await makeUI('operator',false);await unavailable.run("openDocument('synthetic-document')");assert.equal(unavailable.document.querySelector('#document-extract-form'),null);assert.match(unavailable.document.querySelector('#document-dialog').textContent,/extraction n’est pas disponible/);
  unavailable.setRole(null);await unavailable.run("openDocument('synthetic-document')");assert.equal(unavailable.run('state.sessionPhase'),'anonymous');assert.equal(unavailable.run('state.documentDetail'),null);assert.equal(unavailable.document.querySelector('#document-dialog').innerHTML,'');
  passed('Unavailable OCR has an honest empty state, and an expired session clears document content');

  const failed=await makeUI();failed.setRecord({...record,status:'extracted',extraction_version:1,extraction});await failed.run("openDocument('synthetic-document')");
  failed.setHandler(async url=>{if(url.endsWith('/extract')){failed.setRecord({...record,status:'failed',extraction_version:1,extraction,last_error:'ocr_unavailable'});return failed.reply({error:{code:'ocr_unavailable',message:'Lecture momentanément indisponible.'}},503);}return null;});
  await failed.run("extractDocument(document.querySelector('#document-extract-form'))");
  assert.equal(failed.document.querySelector('#document-create-form'),null);assert.ok(failed.document.querySelector('#document-extract-form'));assert.equal(failed.document.querySelector('#document-extract-button').disabled,false);
  assert.match(failed.document.querySelector('#document-action-error').textContent,/momentanément indisponible/);assert.match(failed.document.querySelector('.error-banner').textContent,/extraction précédente/);
  assert.ok(failed.document.querySelector('.document-page pre'));
  passed('Failed re-extraction preserves readable prior evidence, requires a successful retry before creation and reports the actual error');

  const triage=await makeUI();triage.setRecord({...record,status:'extracted',extraction_version:1,extraction});await triage.run("openDocument('synthetic-document')");
  triage.document.querySelector('#document-skill').value='admin-triage';triage.run('renderDocumentFields()');triage.document.querySelector('#document-country').value='FR';
  triage.document.querySelector('#document-field-text').value='Facture à préparer pour la comptabilité';triage.document.querySelector('#document-description').value='Contexte complémentaire';
  triage.document.querySelector('#document-verify-text').checked=true;triage.document.querySelector('#document-human-verified').checked=true;
  await triage.run("createDocumentTask(document.querySelector('#document-create-form'))");
  const triageCreate=triage.requests.find(r=>r.url.endsWith('/create-task'));assert.equal(triageCreate.body.payload.text,'Facture à préparer pour la comptabilité');assert.equal(triageCreate.body.description,'Contexte complémentaire');assert.deepEqual(triageCreate.body.verified_fields,['text']);
  passed('Reviewed triage demand and optional context remain separate inputs, preserving manual text provenance');
  console.log(`${count} document DOM scenarios passed; transport simulated, no OCR quality or visual-layout claim.`);
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
