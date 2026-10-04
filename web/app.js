'use strict';

const $ = (selector, scope = document) => scope.querySelector(selector);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {page:'overview',tasks:[],skills:[],metrics:{},health:{mode:'offline'},filter:'all',query:'',country:'all',skillQuery:'',skillStatus:'all',detail:null,events:[],eventsTotal:0,eventsTruncated:false,editing:null,creationAttempt:null,loading:false,loadError:null,session:null,sessionPhase:'loading',sessionEpoch:0,csrfToken:null,sessionMessage:'',logoutUnconfirmed:false,sessionTimer:null,sessionDeadline:0,lastServerActivity:0};
const pendingRequests = new Set();
const documentBlobURLs = new Set();
Object.assign(state,{documents:[],documentsLoaded:false,documentsLoading:false,documentsError:null,documentLimits:{max_file_bytes:5242880},documentDetail:null,documentLinkedTask:null,documentOpenSeq:0,documentUploadBusy:false,documentExtractBusy:false,documentCreateBusy:false});
const sessionChannel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('admin-agent-session-v1') : null;
const roleNames = {admin:'Administrateur',operator:'Opérateur',reader:'Lecture seule'};
const isProduction = () => state.session?.scope === 'production_single_client';
const can = capability => state.sessionPhase === 'authenticated' && state.session?.capabilities?.[capability] === true;
const sessionInterrupted = error => error?.code === 'session_changed' || error?.code === 'auth_required';
const statuses = {new:'À analyser',needs_review:'À réviser',blocked:'À compléter',ready:'Validé',rejected:'À reprendre'};
const pageNames = {overview:'Vue d’ensemble',tasks:'Dossiers',documents:'Documents',finance:'Finances',skills:'Agents & skills',controls:'Contrôle & données'};
const icons = {'invoice-check':'▧','receivables-followup':'↗','bookkeeping-pack':'▤','admin-triage':'⌘','expense-review':'▱','deadline-watch':'◷','supplier-watch':'◇','contract-watch':'▥','hr-onboarding':'♧','compliance-watch':'◎','cash-visibility':'≋','weekly-brief':'◫'};
const api = async (url, options = {}) => {
  const controller = new AbortController();
  const epoch = state.sessionEpoch;
  const startedAt = Date.now();
  pendingRequests.add(controller);
  const timeout = setTimeout(() => controller.abort(), 90000);
  try {
    const multipart = typeof FormData === 'function' && options.body instanceof FormData;
    const headers = {...(multipart?{}:{'Content-Type':'application/json'}),...((options.method && options.method !== 'GET' && state.csrfToken) ? {'X-CSRF-Token':state.csrfToken} : {}),...options.headers};
    const response = await fetch(url,{...options,credentials:'same-origin',cache:'no-store',signal:controller.signal,headers});
    const body = response.ok && options.responseType==='blob' ? await response.blob() : await response.json().catch(() => ({}));
    if (epoch !== state.sessionEpoch) { const error = new Error('Session interrompue.'); error.code = 'session_changed'; throw error; }
    if (!response.ok) {
      const detail = typeof body.error === 'string' ? body.error : body.error?.message || body.message || `Erreur ${response.status}`;
      const error = new Error(detail); error.status = response.status; error.code = body.error?.code || body.code;
      if (response.status === 401 && url !== '/api/login') {
        error.code = 'auth_required';
        lockSession('Votre session a expiré. Reconnectez-vous pour continuer. Les saisies non enregistrées ont été effacées ; aucune action ne sera relancée automatiquement.');
      }
      throw error;
    }
    if(state.sessionPhase==='authenticated' && isProduction())scheduleSessionExpiry(startedAt);
    return body;
  } catch (error) {
    if (epoch !== state.sessionEpoch && error.code !== 'auth_required') { const interrupted = new Error('Session interrompue.'); interrupted.code = 'session_changed'; throw interrupted; }
    if (error.name === 'AbortError') throw new Error('La requête a pris trop de temps. Vérifiez la connexion puis réessayez.');
    throw error;
  } finally { clearTimeout(timeout); pendingRequests.delete(controller); }
};
const post = (url, body = {}) => api(url,{method:'POST',body:JSON.stringify(body)});
const skillById = id => state.skills.find(s => s.id === id);
const skillName = id => skillById(id)?.name || id;
const displayDate = value => { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat('fr-FR',{day:'2-digit',month:'short',year:'numeric'}).format(date); };
const displayDateTime = value => { if (!value) return ''; const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat('fr-FR',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(date); };
const pill = status => `<span class="status-pill ${escapeHTML(status)}">${escapeHTML(statuses[status] || status)}</span>`;
const toast = (message, error = false) => {const node = document.createElement('div');node.className = `toast${error ? ' error' : ''}`;node.textContent = message;$('#toast-region').append(node);while($('#toast-region').children.length>2)$('#toast-region').firstElementChild.remove();setTimeout(() => node.remove(),6500);};
const aiAvailable = () => !isProduction() && can('analyze') && (state.health.mode === 'ai_available' || state.health.ai_available === true);

function updateSessionChrome() {
  const session = state.session;
  const client = session?.client?.name || 'Espace administratif';
  $('#client-label').textContent = client;
  $('#client-mobile').textContent = client;
  $('#scope-label').textContent = isProduction() ? 'CLIENT' : session ? 'LOCAL' : '—';
  $('#footer-scope').textContent = isProduction() ? 'Admin Agent · Instance client isolée' : 'Admin Agent · Pilote local';
  $('#profile-label').innerHTML = session?.user ? `${escapeHTML(session.user.username)}<small>${escapeHTML(roleNames[session.user.role] || session.user.role)}</small>` : 'Espace entrepreneur<small>Pilote mono-entreprise</small>';
  $('#logout-button').hidden = !isProduction() || state.sessionPhase !== 'authenticated';
  $('#documents-nav').hidden = !isProduction() || !can('documents_read');
  $('#finance-nav').hidden = !can('finance_read');
  $('.app-shell').classList.toggle('auth-mode',state.sessionPhase !== 'authenticated');
  $('#mode-badge').innerHTML = `<span class="status-dot"></span>${state.sessionPhase !== 'authenticated' ? 'Accès protégé' : aiAvailable() ? 'Analyse locale · IA disponible' : 'Contrôles locaux · IA inactive'}`;
}
function purgeSensitive() {
  resetFinance();
  state.sessionEpoch++;
  clearTimeout(state.sessionTimer);state.sessionTimer=null;state.sessionDeadline=0;state.lastServerActivity=0;
  for (const controller of pendingRequests) controller.abort();
  pendingRequests.clear();
  for(const url of documentBlobURLs)URL.revokeObjectURL(url);documentBlobURLs.clear();
  Object.assign(state,{documents:[],documentsLoaded:false,documentsLoading:false,documentsError:null,documentLimits:{max_file_bytes:5242880},documentDetail:null,documentLinkedTask:null,documentOpenSeq:state.documentOpenSeq+1,documentUploadBusy:false,documentExtractBusy:false,documentCreateBusy:false});
  Object.assign(state,{tasks:[],skills:[],metrics:{},health:{mode:'offline'},detail:null,events:[],eventsTotal:0,eventsTruncated:false,editing:null,creationAttempt:null,loadError:null,query:'',filter:'all',country:'all',skillQuery:'',skillStatus:'all',page:'overview',csrfToken:null});
  for (const dialog of document.querySelectorAll('dialog')) { if (dialog.open) dialog.close(); dialog.innerHTML=''; }
  $('#main').innerHTML=''; $('#toast-region').innerHTML=''; $('#nav-task-count').textContent='0';
  $('#current-page').textContent='Connexion'; document.title='Connexion — Admin Agent';
}
function setSession(session) {
  state.session=session; state.csrfToken=session.csrf_token || null;
  state.sessionPhase=session.authenticated ? 'authenticated' : 'anonymous';
  updateSessionChrome();
  if(state.sessionPhase==='authenticated' && isProduction())scheduleSessionExpiry();
}
function lockSession(message) {
  purgeSensitive();
  if(state.session)state.session={...state.session,authenticated:false,user:null,csrf_token:null,capabilities:{}};
  state.sessionPhase='anonymous'; state.sessionMessage=message; updateSessionChrome(); renderLogin();
}
function scheduleSessionExpiry(startedAt=Date.now()) {
  if(!isProduction()||state.sessionPhase!=='authenticated')return;
  clearTimeout(state.sessionTimer);
  state.lastServerActivity=Math.max(state.lastServerActivity,startedAt);
  const idleMs=Number(state.session.idle_timeout_seconds || 1800)*1000;
  const absoluteMs=Number(state.session.expires_at || 0)*1000;
  state.sessionDeadline=Math.min(state.lastServerActivity+idleMs,absoluteMs || Infinity);
  state.sessionTimer=setTimeout(checkSessionDeadline,Math.max(0,state.sessionDeadline-Date.now()));
}
function checkSessionDeadline() {
  if(state.sessionPhase==='authenticated' && isProduction() && state.sessionDeadline && Date.now()>=state.sessionDeadline)
    lockSession('Votre session a expiré. Reconnectez-vous pour continuer. Les saisies non enregistrées ont été effacées ; aucune action ne sera relancée automatiquement.');
}
function renderLogin() {
  const retryOnly = state.logoutUnconfirmed;
  $('#main').innerHTML=`<section class="login-card" aria-labelledby="login-title"><div class="eyebrow">Admin Agent · accès personnel</div><h1 id="login-title">${retryOnly?'Confirmer la déconnexion':'Bienvenue dans votre atelier'}</h1><p class="login-client">${escapeHTML(state.session?.client?.name || 'Espace administratif')}</p>${state.sessionMessage?`<div class="session-notice" role="status">${escapeHTML(state.sessionMessage)}</div>`:''}${retryOnly?'<p>Vos données ont été masquées, mais le serveur n’a pas confirmé la fermeture de la session. Réessayez avant de quitter un ordinateur partagé.</p><button class="btn btn-primary" data-action="logout">Réessayer la déconnexion</button>':`<p>Connectez-vous avec le compte personnel fourni par votre administrateur.</p><form id="login-form"><div class="form-field"><label for="login-username">Identifiant</label><input id="login-username" name="username" type="text" autocomplete="username" required maxlength="80" autocapitalize="none" spellcheck="false"></div><div class="form-field"><label for="login-password">Mot de passe</label><input id="login-password" name="password" type="password" autocomplete="current-password" required maxlength="256"></div><div class="form-field"><label for="login-otp">Code authentificateur</label><input id="login-otp" name="otp" type="text" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" minlength="6" maxlength="6" required aria-describedby="otp-help"><small id="otp-help">Code à 6 chiffres de votre application d’authentification.</small></div><div class="form-error" id="login-error" role="alert"></div><button class="btn btn-primary" type="submit">Se connecter</button></form><p class="login-help">Besoin d’un accès ou mot de passe oublié ? Demandez une réinitialisation à votre administrateur. Aucun compte n’est créé automatiquement.</p>`}</section>`;
  $('#login-username')?.focus();
}
async function readSession() { return api('/api/session'); }
async function bootstrapSession() {
  try {
    setSession(await readSession());
    if(state.sessionPhase==='authenticated'){await loadData(false);navigate();}else renderLogin();
  } catch(error) {
    if(sessionInterrupted(error))return;
    state.sessionPhase='error'; updateSessionChrome();
    $('#main').innerHTML=`<section class="login-card"><h1>Connexion indisponible</h1><div class="error-banner" role="alert">${escapeHTML(error.message)}</div><button class="btn btn-secondary" data-action="session-retry">Réessayer</button></section>`;
  }
}
async function login(form) {
  const button=$('button[type="submit"]',form);const errorTarget=$('#login-error');
  button.disabled=true; errorTarget.textContent='';
  try {
    // Obtain a fresh pre-session and CSRF token after expiry, without replaying the interrupted action.
    const fresh=await api('/api/session'); state.csrfToken=fresh.csrf_token || null;
    const username=$('#login-username',form).value.trim();const password=$('#login-password',form).value;
    const otp=$('#login-otp',form).value.trim();
    const session=await post('/api/login',{username,password,otp});
    $('#login-password',form).value='';$('#login-otp',form).value='';
    purgeSensitive();state.sessionMessage='';state.logoutUnconfirmed=false;setSession(session);
    if(state.sessionPhase!=='authenticated')throw new Error('La connexion n’a pas été confirmée.');
    await loadData(false);navigate();
  } catch(error) {
    const password=$('#login-password',form);if(password)password.value='';const otp=$('#login-otp',form);if(otp)otp.value='';
    if(sessionInterrupted(error))return;
    if($('#login-error'))$('#login-error').textContent=error.status===401?'Identifiant, mot de passe ou code incorrect.':error.status===429?'Trop de tentatives. Patientez avant de réessayer.':error.message;
    else {state.loadError=error.message;renderPage();}
    button.disabled=false;
  }
}
async function logout() {
  const token=state.csrfToken;
  lockSession('Déconnexion en cours…');
  sessionChannel?.postMessage({type:'logout'});
  state.logoutUnconfirmed=true;state.csrfToken=token;renderLogin();
  document.querySelector('[data-action="logout"]:not([hidden])')?.setAttribute('disabled','');
  try {
    const session=await api('/api/logout',{method:'POST',body:'{}',headers:{'X-CSRF-Token':token || ''}});
    state.logoutUnconfirmed=false;state.sessionMessage='Vous êtes déconnecté. Les données de cet espace ont été effacées de cette page.';setSession(session);renderLogin();
  } catch(error) {
    if(sessionInterrupted(error)){state.logoutUnconfirmed=false;renderLogin();return;}
    state.csrfToken=token;state.sessionMessage='Déconnexion serveur non confirmée. Vos données sont masquées.';renderLogin();
  }
}


async function loadData(render = true) {
  const [dashboard,catalog,health] = await Promise.all([api('/api/dashboard'),api('/api/skills'),api('/api/health')]);
  if(state.sessionPhase !== 'authenticated')return;
  state.tasks = dashboard.tasks || [];
  state.metrics = dashboard.metrics || {};
  state.skills = catalog.skills || [];
  state.health = health;
  state.loadError = null;
  $('#nav-task-count').textContent = state.tasks.length;
  updateSessionChrome();
  if (render) renderPage();
}

function heading(title,description,actions = true) {
  return `<div class="page-heading"><div><div class="eyebrow">Votre atelier administratif</div><h1>${title}</h1><p>${description}</p></div>${actions ? `<div class="heading-actions">${can('export')?'<button class="btn btn-secondary" data-action="export"><span aria-hidden="true">↓</span> Exporter</button>':''}${can('create')?'<button class="btn btn-primary" data-action="create"><span class="plus" aria-hidden="true">+</span> Nouveau dossier</button>':''}</div>` : ''}</div>`;
}
function renderPage() {
  if(state.sessionPhase !== 'authenticated'){if(state.sessionPhase==='anonymous')renderLogin();return;}
  const page = state.page;
  document.querySelectorAll('.nav-link').forEach(link => {link.classList.toggle('active',link.dataset.page === page);if(link.dataset.page===page)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
  $('#current-page').textContent = pageNames[page];
  document.title = `${pageNames[page]} — Admin Agent`;
  if (state.loadError) {
    $('#main').innerHTML = `${heading('L’atelier est indisponible','Vérifiez votre connexion pour accéder aux dossiers de cet espace.',false)}<div class="error-banner" role="alert"><strong>Impossible de charger les données.</strong><p>${escapeHTML(state.loadError)}</p><button class="btn btn-secondary" data-action="reload">Réessayer</button></div>`;
    return;
  }
  if (page === 'overview') renderOverview();
  else if (page === 'tasks') renderTasks();
  else if (page === 'documents') renderDocuments();
  else if (page === 'finance') renderFinance();
  else if (page === 'skills') renderSkills();
  else renderControls();
}
function renderOverview() {
  const metrics = [
    ['Dossiers au total','total','all','▤','', 'Dans cet espace'],
    ['À réviser','needs_review','needs_review','◷','amber','Votre validation attendue'],
    ['À compléter','blocked','blocked','!','red','Une information manque'],
    ['Validés','ready','ready','✓','green','Après contrôle humain']
  ];
  const core = state.skills.filter(s => s.status === 'implemented');
  $('#main').innerHTML = `${heading('Moins d’administratif. Plus de visibilité.','Vos dossiers, vos points de vigilance et les prochaines décisions, au même endroit.')}
    <section class="hero" aria-label="Fonctionnement de votre atelier"><div class="hero-copy"><div class="eyebrow">De la pièce reçue au dossier vérifié</div><h2>Faites avancer l’administratif.<br><em>Gardez la main sur l’essentiel.</em></h2><p>Contrôlez vos factures, préparez vos relances et rassemblez les pièces pour votre comptabilité.</p><div class="hero-path"><span><b>1</b> Vous déposez</span><i aria-hidden="true">→</i><span><b>2</b> L’agent prépare</span><i aria-hidden="true">→</i><span><b>3</b> Vous validez</span></div></div><div class="hero-art" aria-hidden="true"><div class="flow-card"><div class="flow-card-head"><span class="flow-card-icon">▧</span> Un dossier bien préparé</div><div class="flow-card-row"><span class="check">✓</span> Informations structurées</div><div class="flow-card-row"><span class="check">✓</span> Points de contrôle visibles</div><div class="flow-card-row"><span class="check">✓</span> Proposition à relire</div><div class="flow-card-badge"><span>◎</span> La décision vous appartient</div></div></div></section>
    <section class="metrics-grid" aria-label="État des dossiers">${metrics.map(([label,key,filter,icon,tone,foot]) => `<button class="metric-card" data-action="metric" data-filter="${filter}"><div class="metric-top"><span>${label}</span><span class="metric-icon ${tone}" aria-hidden="true">${icon}</span></div><div class="metric-number">${Number(state.metrics[key] ?? state.tasks.filter(t=>key==='total'||t.status===key).length)}</div><div class="metric-foot">${foot}</div><span class="arrow" aria-hidden="true">↗</span></button>`).join('')}</section>
    <div class="dashboard-grid"><section><div class="section-heading"><div><h2>Vos dossiers en cours</h2><p>Chaque préparation reste soumise à votre contrôle.</p></div><a class="text-link" href="#tasks">Tous les dossiers <span aria-hidden="true">↗</span></a></div><div class="panel"><div class="table-toolbar">${taskTabs()}<label class="search-field"><span aria-hidden="true">⌕</span><span class="sr-only">Rechercher un dossier</span><input type="search" id="task-search" placeholder="${isProduction()?'Titre ou contexte…':'Rechercher un dossier…'}" title="${isProduction()?'Recherche dans les titres, contextes et références de dossiers':'Recherche dans les dossiers et leurs données'}" value="${escapeHTML(state.query)}"></label></div><div id="task-list"></div></div></section>
    <aside class="rail" aria-label="Agents disponibles"><section class="panel"><h3>Vos agents de préparation</h3><p class="rail-lead">${core.length} skills avec contrôles exécutables</p>${core.slice(0,4).map(s=>`<div class="agent-row"><span class="agent-symbol" aria-hidden="true">${icons[s.id]||'✳'}</span><div class="agent-label">${escapeHTML(s.name)}<small>Règles locales · à vérifier</small></div><span class="status-dot" aria-hidden="true"></span></div>`).join('')}<a class="text-link rail-skills-link" href="#skills">Explorer les skills <span aria-hidden="true">→</span></a></section><div class="rail-note"><div class="note-icon" aria-hidden="true">◎</div><h3>Un copilote, avec des limites claires.</h3><p>Le mode hors ligne applique des règles déterministes. ${can('documents_read')?'Les documents peuvent être extraits puis vérifiés dans votre espace.':'La démonstration analyse les informations saisies.'} Il ne remplace pas votre expert-comptable. Aucun message client n’est envoyé.</p></div></aside></div>`;
  updateTaskList();
}
function taskTabs() {
  return `<div class="tabs" role="group" aria-label="Filtrer les dossiers">${[['all','Tous'],['needs_review','À réviser'],['blocked','À compléter'],['ready','Validés']].map(([key,label])=>`<button class="tab ${state.filter===key?'active':''}" data-action="filter" data-filter="${key}" aria-pressed="${state.filter===key}">${label}<span class="tab-count">${state.tasks.filter(t=>key==='all'||t.status===key).length}</span></button>`).join('')}</div>`;
}
function renderTasks() {
  $('#main').innerHTML = `${heading('Tous vos dossiers','Une trace claire de ce qui a été préparé, corrigé et validé.')}<div class="filters-bar"><label class="search-field"><span aria-hidden="true">⌕</span><span class="sr-only">Rechercher dans les dossiers</span><input id="task-search" type="search" placeholder="${isProduction()?'Rechercher un titre, un contexte, une référence dossier…':'Rechercher un titre, un client, une référence…'}" value="${escapeHTML(state.query)}"></label><label class="sr-only" for="status-filter">État du dossier</label><select id="status-filter"><option value="all">Tous les états</option>${Object.entries(statuses).map(([key,label])=>`<option value="${key}" ${state.filter===key?'selected':''}>${label}</option>`).join('')}</select><label class="sr-only" for="country-filter">Pays</label><select id="country-filter" class="tasks-country-filter"><option value="all">Tous les pays</option><option value="FR" ${state.country==='FR'?'selected':''}>France</option><option value="ES" ${state.country==='ES'?'selected':''}>Espagne</option></select></div>${isProduction()?'<p class="search-scope inline-muted">La recherche porte sur les titres, contextes, références de dossiers et noms de skills. Consultez chaque dossier pour ses données détaillées.</p>':''}<div class="panel table-task-page" id="task-list"></div>`;
  updateTaskList();
}
function filteredTasks() {
  const query = state.query.toLocaleLowerCase('fr').trim();
  return state.tasks.filter(task => (state.filter==='all'||task.status===state.filter) && (state.country==='all'||task.country===state.country) && (!query||[task.title,task.description,task.id,skillName(task.skill_id),isProduction()?'':JSON.stringify(task.payload)].join(' ').toLocaleLowerCase('fr').includes(query))).sort((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at)));
}
function updateTaskList() {
  const target = $('#task-list');if(!target)return;
  const tasks = filteredTasks();
  const limit = state.page==='overview'?6:tasks.length;
  if (!tasks.length) {
    target.innerHTML = `<div class="empty-state"><div class="empty-symbol" aria-hidden="true">▤</div><h3>${state.tasks.length?'Aucun dossier ne correspond':'Votre premier dossier commence ici'}</h3><p>${state.tasks.length?'Essayez un autre mot-clé ou affichez tous les états.':can('create')?'Ajoutez une facture, préparez une relance ou rassemblez vos pièces.':'Aucun dossier n’a encore été enregistré dans cet espace.'}</p><div class="empty-actions">${state.tasks.length?'<button class="btn btn-secondary" data-action="clear-filters">Réinitialiser les filtres</button>':`${can('create')?'<button class="btn btn-primary" data-action="create">Créer un dossier</button>':''}${can('demo')&&!isProduction()?'<button class="btn btn-secondary" data-action="seed">Charger la démonstration</button>':''}`}</div></div>`;
    return;
  }
  target.innerHTML = `<div class="table-wrap"><table><caption class="sr-only">Dossiers administratifs</caption><thead><tr><th scope="col">Dossier / agent</th><th scope="col">Pays</th><th scope="col">État</th><th scope="col">Modifié le</th></tr></thead><tbody>${tasks.slice(0,limit).map(task=>`<tr><td><div class="task-type"><span class="type-icon" aria-hidden="true">${icons[task.skill_id]||'▤'}</span><div><button class="task-title-button" data-action="task" data-id="${escapeHTML(task.id)}">${escapeHTML(task.title)}</button><div class="task-subtitle">${escapeHTML(skillName(task.skill_id))}</div></div></td><td><span class="country">${escapeHTML(task.country)}</span></td><td>${pill(task.status)}</td><td><span class="inline-muted">${escapeHTML(displayDate(task.updated_at))}</span></td></tr>`).join('')}</tbody></table></div><div class="table-tail"><span>${Math.min(tasks.length,limit)} dossier${Math.min(tasks.length,limit)>1?'s':''} affiché${Math.min(tasks.length,limit)>1?'s':''} sur ${tasks.length}</span><span>Validation interne uniquement</span></div>`;
}
function renderSkills() {
  $('#main').innerHTML = `${heading('Des agents spécialisés. Des règles explicites.','Explorez le périmètre, les entrées et les limites de chaque skill.',false)}<div class="skills-intro"><p><strong>Un niveau de maturité visible.</strong> Les skills « Exécutable » réalisent des contrôles locaux. Les skills « Guidé » proposent une procédure de travail et restent bloqués pour validation manuelle.</p></div><div class="filters-bar"><label class="search-field"><span aria-hidden="true">⌕</span><span class="sr-only">Rechercher un agent ou un skill</span><input id="skill-search" type="search" placeholder="Rechercher une fonction, un agent ou une règle…" value="${escapeHTML(state.skillQuery)}"></label><label class="sr-only" for="skill-status-filter">Maturité du skill</label><select id="skill-status-filter"><option value="all">Tous les niveaux</option><option value="implemented" ${state.skillStatus==='implemented'?'selected':''}>Exécutable</option><option value="guided" ${state.skillStatus==='guided'?'selected':''}>Guidé</option></select></div><div id="skills-list" class="skills-grid"></div>`;
  updateSkillsList();
}
function updateSkillsList() {
  const skills = state.skills.filter(s=>(state.skillStatus==='all'||s.status===state.skillStatus)&&[s.name,s.description,s.agent,s.body].join(' ').toLocaleLowerCase('fr').includes(state.skillQuery.toLocaleLowerCase('fr').trim()));
  $('#skills-list').innerHTML = skills.length ? skills.map(s=>`<article class="skill-card"><div class="skill-card-header"><span class="agent-symbol" aria-hidden="true">${icons[s.id]||'✳'}</span><span class="skill-status ${s.status==='guided'?'guided':''}">${s.status==='implemented'?'Exécutable':'Guidé'}</span></div><h3>${escapeHTML(s.name)}</h3><p>${escapeHTML(s.description)}</p><div class="skill-agent">${escapeHTML(s.agent)} · ${escapeHTML(s.priority)}</div><div class="skill-actions"><button class="text-link" data-action="skill" data-id="${escapeHTML(s.id)}">Voir les règles <span aria-hidden="true">↗</span></button>${can('create')?`<button class="btn btn-secondary btn-sm" data-action="create" data-skill="${escapeHTML(s.id)}">Préparer un dossier</button>`:''}</div></article>`).join('') : '<div class="empty-state"><h3>Aucun skill trouvé</h3><p>Essayez un autre terme ou un autre niveau de maturité.</p></div>';
}
function renderControls() {
  $('#main').innerHTML = `${heading('Un fonctionnement que vous pouvez vérifier.','Les données, les limites et les décisions restent visibles.',false)}<div class="control-grid"><section class="panel control-card"><h2>Mode de fonctionnement</h2><p>Les contrôles locaux analysent les données saisies. Les brouillons restent dans cet espace.</p><ul class="control-list"><li><span>Espace</span><strong>${escapeHTML(state.session?.client?.name)}</strong></li><li><span>Votre accès</span><strong>${escapeHTML(roleNames[state.session?.user?.role] || 'Pilote local')}</strong></li><li><span>Analyse par défaut</span><strong>Règles locales · sans modèle IA</strong></li><li><span>IA optionnelle</span><strong>${aiAvailable()?'Configurée · activation par dossier':'Non activée'}</strong></li><li><span>Envoi d’e-mails / contacts clients</span><strong>Désactivé</strong></li><li><span>Paiements et dépôts officiels</span><strong>Désactivés</strong></li><li><span>Validation</span><strong>Humaine, dossier par dossier</strong></li></ul></section><section class="panel control-card"><h2>Vos données et votre historique</h2><p>${can('export')?'Exportez les dossiers et le journal des événements au format JSON. Cet export confidentiel contient les informations saisies.':'L’export global est réservé à l’administrateur de cet espace. Vous pouvez consulter les dossiers et leur historique selon votre accès.'}</p>${can('export')?'<button class="btn btn-primary" data-action="export"><span aria-hidden="true">↓</span> Exporter les données</button>':''}<ul class="control-list"><li><span>Dossiers enregistrés</span><strong>${state.tasks.length}</strong></li><li><span>Skills disponibles</span><strong>${state.skills.length}</strong></li><li><span>Source des indicateurs</span><strong>Données de cet espace</strong></li></ul></section>${can('demo')&&!isProduction()?'<section class="panel control-card"><h2>Explorer avec des exemples</h2><p>Ajoutez des dossiers fictifs pour découvrir les contrôles. Un second chargement ne crée pas de doublons.</p><button class="btn btn-secondary" data-action="seed">Charger la démonstration</button></section>':''}<section class="panel control-card"><h2>Périmètre actuel</h2><p>${can('documents_read')?'Les PDF et images peuvent être déposés et leur texte extrait lorsque ce service est activé. Les pièces collectées par votre administrateur conservent leur source. Chaque valeur doit être vérifiée avant de créer un dossier.':'Cette démonstration utilise les informations saisies ou fournies sous forme structurée. Les documents sont disponibles dans un espace client avec accès personnel.'} Chaque résultat doit être relu.</p><a href="#skills" class="text-link">Voir le périmètre de chaque skill →</a></section></div><div class="control-note">${isProduction()?'Cet espace est une instance dédiée à une seule entreprise. Les comptes sont personnels et les droits contrôlés par le serveur. La validation reste une revue interne.':'Pilote local pour une seule entreprise. Utilisez le déploiement avec comptes personnels et instance dédiée avant de partager l’accès.'}</div>`;
}
const documentStatusNames={uploaded:'À extraire',extracting:'Extraction en cours',extracted:'À vérifier',failed:'Extraction à reprendre'};
const documentFields=[['invoice_number','Référence'],['supplier','Fournisseur / émetteur'],['customer','Client / destinataire'],['issue_date','Date d’émission'],['due_date','Date d’échéance'],['currency','Devise'],['net_amount','Montant HT'],['vat_rate','Taux de TVA (%)'],['vat_amount','Montant de TVA'],['total_amount','Montant TTC']];
const expenseFields=[['merchant','Commerçant'],['expense_date','Date de la dépense'],['total_amount','Montant total'],['currency','Devise'],['vat_amount','TVA indiquée (facultatif)'],['employee_ref','Référence interne du demandeur'],['business_purpose','Motif professionnel'],['policy_ref','Politique interne · référence et version'],['policy_limit','Plafond déclaré (facultatif)'],['policy_currency','Devise du plafond']];
const expenseEnums={category:[['travel','Transport'],['meals','Repas'],['lodging','Hébergement'],['office','Fournitures'],['other','Autre']],payment_method:[['employee_card','Carte personnelle'],['company_card','Carte entreprise'],['cash','Espèces'],['bank_transfer','Virement'],['other','Autre']]};
const expenseEnumLabels={category:'Catégorie',payment_method:'Moyen de paiement'};
const expenseBooleans=[['paid_by_company','Payée par l’entreprise ?'],['reimbursed','Déjà remboursée ?'],['business_only','Dépense exclusivement professionnelle ?'],['policy_confirmed','Politique interne vérifiée ?'],['payment_confirmed','Paiement confirmé séparément ?']];
const expenseKeys=[...expenseFields.map(([key])=>key),...Object.keys(expenseEnums),...expenseBooleans.map(([key])=>key)];
const documentBooleanFields=['paid','disputed',...expenseBooleans.map(([key])=>key)];
const documentDecimalFields=['net_amount','vat_rate','vat_amount','total_amount','policy_limit'];
const documentSize=bytes=>`${(Number(bytes||0)/1024).toLocaleString('fr-FR',{maximumFractionDigits:0})} Kio`;
const documentSource=record=>{if(record.sources?.length)return record.sources.map(source=>source.connector_id).join(' · ');if(record.connector_ids?.length)return record.connector_ids.join(' · ');const source=record.source;return typeof source==='string'?source:source?.label||source?.kind||'Document de cet espace';};
const languageOptions=(current='fra+spa+eng')=>[['fra+spa+eng','Français · espagnol · anglais'],['fra','Français'],['spa','Espagnol'],['eng','Anglais']].map(([value,label])=>`<option value="${value}" ${value===current?'selected':''}>${label}</option>`).join('');
function renderDocuments() {
  // A selected File cannot be reconstructed from HTML. Preserve the actual form
  // across list refreshes, including the initial asynchronous response. Refresh
  // only the library section so even focus and an open file chooser survive.
  const existingUploadForm=$('#document-upload-form');
  if(!isProduction()||!can('documents_read')){
    $('#main').innerHTML=`${heading('Documents','Les documents sont disponibles dans un espace client avec accès personnel.',false)}<div class="panel control-card"><p>Vous pouvez continuer à préparer les dossiers à partir des informations saisies.</p><a class="text-link" href="#tasks">Voir les dossiers →</a></div>`;return;
  }
  const content=`${heading('Vos pièces, leurs sources et vos vérifications.','Déposez une pièce, extrayez son texte puis vérifiez les valeurs avant de préparer un dossier.',false)}<div class="documents-layout">${can('documents_upload')?`<section class="panel document-upload"><h2>Ajouter un document</h2><p>PDF, PNG ou JPEG · ${documentSize(state.documentLimits.max_file_bytes)} maximum par pièce · ${Number(state.documentLimits.max_pages||5)} pages maximum. L’original reste conservé dans cet espace.</p><form id="document-upload-form"><div class="form-field"><label for="document-file">Document à déposer</label><input id="document-file" name="file" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" required ${state.documentUploadBusy?'disabled':''}></div><div class="form-field"><label for="document-upload-language">Langue du document</label><select id="document-upload-language" name="language" ${state.documentUploadBusy?'disabled':''}>${languageOptions()}</select></div><div id="document-upload-error" class="form-error" role="alert"></div><button class="btn btn-primary" type="submit" ${state.documentUploadBusy?'disabled':''}>${state.documentUploadBusy?'Dépôt en cours…':'Déposer le document'}</button></form></section>`:''}<section class="panel document-library"><div class="section-heading"><div><h2>Documents de l’espace</h2><p>Les valeurs extraites sont des propositions à vérifier.</p></div><button class="btn btn-secondary btn-sm" data-action="documents-refresh" ${state.documentsLoading?'disabled':''}>Actualiser</button></div>${state.documentsError?`<div class="error-banner" role="alert">${escapeHTML(state.documentsError)}</div>`:''}<div id="document-list">${state.documentsLoading&&!state.documentsLoaded?'<p class="form-help">Chargement des documents…</p>':renderDocumentList()}</div></section></div>`;
  if(existingUploadForm&&can('documents_upload')&&$('.document-library')){
    const updated=document.createElement('div');updated.innerHTML=content;
    $('.document-library').replaceWith($('.document-library',updated));
    $('.document-upload>p').textContent=$('.document-upload>p',updated).textContent;
  }else $('#main').innerHTML=content;
  if(!state.documentsLoaded&&!state.documentsLoading&&!state.documentsError)loadDocuments();
}
function renderDocumentList() {
  if(!state.documents.length)return `<div class="empty-state"><div class="empty-symbol" aria-hidden="true">▧</div><h3>Aucun document pour le moment</h3><p>${can('documents_upload')?'Déposez votre première pièce. Si votre entreprise utilise un dossier de collecte, les documents apparaîtront ici après leur collecte par l’administrateur.':'Les pièces déposées par votre équipe apparaîtront ici. Vous pourrez consulter leur texte et télécharger les originaux.'}</p></div>`;
  return `<ul class="document-list">${state.documents.map(record=>`<li><div><button class="task-title-button document-title-button" data-action="document-open" data-id="${escapeHTML(record.id)}">${escapeHTML(record.filename)}</button><p>${escapeHTML(documentSource(record))} · ${documentSize(record.size_bytes)} · ${escapeHTML(displayDate(record.created_at))}</p></div><span class="status-pill ${record.status==='failed'?'blocked':'needs_review'}">${record.task_id?'Dossier créé':escapeHTML(documentStatusNames[record.status]||record.status)}</span></li>`).join('')}</ul>`;
}
async function loadDocuments() {
  if(!can('documents_read')||!isProduction()||state.documentsLoading)return;
  state.documentsLoading=true;
  try {const response=await api('/api/documents');state.documents=response.documents||[];state.documentLimits=response.limits||state.documentLimits;state.documentsLoaded=true;state.documentsError=null;}
  catch(error){if(sessionInterrupted(error))return;state.documentsError=error.message;}
  finally{state.documentsLoading=false;if(state.sessionPhase==='authenticated'&&state.page==='documents')renderDocuments();}
}
async function uploadDocument(form) {
  if(!can('documents_upload')||!isProduction()||state.documentUploadBusy)return;
  const epoch=state.sessionEpoch,target=$('#document-upload-error',form),input=$('#document-file',form),file=input?.files?.[0];
  target.textContent='';
  if(!file){target.textContent='Choisissez un document PDF, PNG ou JPEG.';return;}
  if(file.size>state.documentLimits.max_file_bytes){target.textContent=`Le document dépasse la limite de ${documentSize(state.documentLimits.max_file_bytes)}.`;return;}
  if(!/\.(pdf|png|jpe?g)$/i.test(file.name)){target.textContent='Ce format n’est pas accepté. Choisissez un PDF, PNG ou JPEG.';return;}
  const body=new FormData();body.append('file',file);body.append('language',$('#document-upload-language',form).value);
  state.documentUploadBusy=true;for(const control of form.querySelectorAll('input,select,button'))control.disabled=true;
  const button=$('button[type="submit"]',form);button.textContent='Dépôt en cours…';
  try{const response=await api('/api/documents',{method:'POST',body});input.value='';await loadDocuments();await openDocument(response.document.id);toast('Document enregistré. Extrayez le texte puis vérifiez les informations.');}
  catch(error){if(sessionInterrupted(error))return;target.textContent=error.message;}
  finally{if(epoch===state.sessionEpoch){state.documentUploadBusy=false;for(const control of form.querySelectorAll('input,select,button'))control.disabled=false;button.textContent='Déposer le document';if(state.sessionPhase==='authenticated'&&state.page==='documents'&&!form.isConnected)renderDocuments();}}
}
async function openDocument(id) {
  if(!can('documents_read')||!isProduction())return;
  const seq=++state.documentOpenSeq;state.documentDetail=null;state.documentLinkedTask=null;
  const dialog=$('#document-dialog');
  dialog.innerHTML='<div class="dialog-header"><h2 id="document-dialog-title">Document</h2><button class="icon-button" data-action="close" aria-label="Fermer">×</button></div><div class="dialog-body"><p>Chargement de la pièce…</p></div>';
  if(!dialog.open)dialog.showModal();
  try{const response=await api(`/api/documents/${encodeURIComponent(id)}`);if(seq!==state.documentOpenSeq)return;state.documentDetail=response.document;if(response.document.task_id){const linked=await api(`/api/tasks/${encodeURIComponent(response.document.task_id)}`);if(seq!==state.documentOpenSeq)return;state.documentLinkedTask=linked.task;}renderDocumentDetail();}
  catch(error){if(sessionInterrupted(error)||seq!==state.documentOpenSeq)return;dialog.innerHTML=`<div class="dialog-header"><h2 id="document-dialog-title">Document indisponible</h2><button class="icon-button" data-action="close" aria-label="Fermer">×</button></div><div class="dialog-body"><div class="error-banner" role="alert">${escapeHTML(error.message)}</div></div>`;}
}
function renderDocumentDetail() {
  const record=state.documentDetail;if(!record||!can('documents_read'))return;
  const extraction=record.extraction,candidates=extraction?.candidates||{},pages=extraction?.pages||[];
  $('#document-dialog').innerHTML=`<div class="dialog-header"><div><div class="eyebrow">Pièce d’origine & vérification</div><h2 id="document-dialog-title">${escapeHTML(record.filename)}</h2><p>${escapeHTML(documentSource(record))} · ${documentSize(record.size_bytes)} · ${escapeHTML(displayDate(record.created_at))}</p></div><button class="icon-button" data-action="close" aria-label="Fermer">×</button></div><div class="dialog-body"><div class="document-actions"><span class="status-pill ${record.status==='failed'?'blocked':'needs_review'}">${escapeHTML(documentStatusNames[record.status]||record.status)}</span><button class="btn btn-secondary" data-action="document-download">Télécharger l’original</button></div>${record.last_error?'<div class="error-banner" role="alert">L’extraction n’a pas abouti. L’original est conservé. Vérifiez le format et le nombre de pages, puis réessayez. Les propositions d’une extraction précédente ne peuvent pas être utilisées avant une nouvelle extraction réussie.</div>':''}${can('documents_extract')&&!record.task_id?`<form id="document-extract-form" class="document-extract-form"><div class="form-field"><label for="document-language">Langue à reconnaître</label><select id="document-language" name="language">${languageOptions(record.language||'fra+spa+eng')}</select></div><label class="checkbox-field"><input id="document-force-ocr" type="checkbox"> Relire toutes les pages comme des images</label><p class="form-help">À utiliser si le texte d’un PDF est vide ou incorrect. Une nouvelle extraction remplace les propositions précédentes et nécessite une nouvelle vérification.</p><button class="btn btn-primary" id="document-extract-button" type="submit" ${state.documentExtractBusy?'disabled':''}>${state.documentExtractBusy?'Extraction en cours…':extraction?'Relancer l’extraction':'Extraire le texte'}</button></form>`:!extraction&&!can('documents_extract')?'<div class="form-help">L’extraction n’est pas disponible avec votre accès ou dans cet espace. Votre administrateur peut vérifier sa disponibilité.</div>':''}${extraction?.warnings?.length?`<ul class="document-warnings">${extraction.warnings.map(w=>`<li>${escapeHTML(typeof w==='string'?w:w.message||JSON.stringify(w))}</li>`).join('')}</ul>`:''}<div id="document-action-error" class="form-error" role="alert"></div>${extraction?`<section class="document-evidence"><h3>Texte lu · ${pages.length} page${pages.length>1?'s':''}</h3><p>Le texte ci-dessous peut contenir des erreurs. Comparez les montants, les dates et les identités avec l’original téléchargé.</p>${pages.map(page=>`<details class="document-page" ${pages.length===1?'open':''}><summary>Page ${Number(page.number)} · ${page.method==='ocr'?'Reconnaissance d’image':'Texte du document'}</summary><pre>${escapeHTML(page.text||'Aucun texte lisible sur cette page.')}</pre></details>`).join('')}</section>${record.task_id?renderLinkedDocumentTask(record):can('documents_create_task')&&record.status==='extracted'?`<section class="document-review"><h3>Préparer un dossier après vérification</h3><p>Chaque valeur proposée conserve sa page et son extrait d’origine. Corrigez-la si nécessaire, puis cochez les champs réellement vérifiés. Les données laissées vides resteront manquantes.</p><form id="document-create-form"><div class="form-grid"><div class="form-field full"><label for="document-title">Titre du dossier *</label><input id="document-title" required maxlength="180" value="${escapeHTML(record.filename)}"></div><div class="form-field"><label for="document-skill">Préparation souhaitée *</label><select id="document-skill"><option value="invoice-check">Contrôle de facture</option><option value="receivables-followup">Préparation de relance</option><option value="admin-triage">Tri administratif</option><option value="expense-review">Note de frais</option></select></div><div class="form-field"><label for="document-country">Pays applicable *</label><select id="document-country" required><option value="">À sélectionner</option><option value="FR">France</option><option value="ES">Espagne</option></select></div><div class="form-field full"><label for="document-description">Contexte et points de vigilance</label><textarea id="document-description" rows="3" maxlength="12000"></textarea></div></div><div id="document-candidate-fields"></div><label class="checkbox-field document-human-check"><input type="checkbox" id="document-human-verified" required> J’ai comparé les informations retenues avec l’original et vérifié le contexte du dossier.</label><div id="document-create-error" class="form-error" role="alert"></div><button class="btn btn-primary" type="submit" ${state.documentCreateBusy?'disabled':''}>Créer le dossier à analyser</button><p class="draft-warning">Le dossier sera créé sans analyse ni approbation automatique. L’état du paiement et les litiges nécessitent une vérification séparée.</p></form></section>`:`<section class="document-review"><h3>Informations proposées</h3>${Object.entries(candidates).map(([field,candidate])=>`<div class="document-candidate"><strong>${escapeHTML([...documentFields,...expenseFields,...expenseBooleans].find(([key])=>key===field)?.[1]||field)} : ${escapeHTML(candidate.value)}</strong>${candidateEvidence(candidate)}</div>`).join('')||'<p>Aucune valeur suffisamment explicite n’a été repérée.</p>'}</section>`}`:''}</div><div class="dialog-footer"><small>Document original conservé · Toute extraction reste à vérifier.</small><button class="btn btn-secondary" data-action="close">Fermer</button></div>`;
  if($('#document-candidate-fields'))renderDocumentFields();
}
function renderLinkedDocumentTask(record) {
  const task=state.documentLinkedTask;
  const link=`<div class="status-alert">Un dossier est déjà lié à cette pièce. <button class="text-link" data-action="document-linked-task" data-id="${escapeHTML(record.task_id)}">Ouvrir le dossier →</button></div>`;
  if(task?.skill_id!=='expense-review'||!can('documents_create_task'))return link;
  const fields=['merchant','expense_date','total_amount','currency'];
  return link+`<section class="document-review"><h3>Reconfirmer le reçu après correction</h3><p>Comparez ces valeurs actuelles du dossier avec l’original téléchargé. La reconfirmation conserve les valeurs d’origine et la nouvelle preuve, puis invalide l’analyse et la validation précédentes.</p><form id="document-reverify-form"><div class="document-candidates-grid">${fields.map(field=>`<div class="document-candidate"><strong>${escapeHTML(expenseFields.find(([key])=>key===field)?.[1])} : ${escapeHTML(task.payload?.[field]??'Non renseigné')}</strong>${candidateEvidence(record.extraction?.candidates?.[field])}<label class="checkbox-field"><input type="checkbox" data-reverify-field="${field}" required> J’ai comparé cette valeur actuelle avec l’original.</label></div>`).join('')}</div><label class="checkbox-field document-human-check"><input type="checkbox" id="document-reverify-confirmed" required> Je confirme avoir relu le reçu et les quatre valeurs actuelles.</label><div id="document-reverify-error" class="form-error" role="alert"></div><button type="submit" class="btn btn-primary">Reconfirmer le reçu</button><p class="draft-warning">Le dossier repassera à analyser. Aucun remboursement effectué.</p></form></section>`;
}
async function reverifyExpenseDocument(form) {
  if(!can('documents_create_task')||state.documentCreateBusy||!state.documentLinkedTask||!state.documentDetail)return;
  const record=state.documentDetail,task=state.documentLinkedTask,epoch=state.sessionEpoch,target=$('#document-reverify-error',form);target.textContent='';
  const fields=[...form.querySelectorAll('[data-reverify-field]')];
  if(!$('#document-reverify-confirmed',form).checked||fields.some(input=>!input.checked)){target.textContent='Comparez les quatre valeurs avec l’original et confirmez chaque vérification.';return;}
  state.documentCreateBusy=true;for(const c of form.querySelectorAll('input,button'))c.disabled=true;
  try{const result=await post(`/api/documents/${encodeURIComponent(record.id)}/reverify-expense`,{task_version:task.version,extraction_version:record.extraction_version,human_verified:true,verified_fields:fields.map(input=>input.dataset.reverifyField)});$('#document-dialog').close();await loadData();await openTask(result.task.id);toast('Reçu reconfirmé. Relancez l’analyse puis relisez le résultat.');}
  catch(error){if(sessionInterrupted(error))return;if(error.status===409){await openDocument(record.id);toast(error.message+' Vérifiez de nouveau les valeurs actuelles.',true);}else target.textContent=error.message;}
  finally{if(epoch===state.sessionEpoch){state.documentCreateBusy=false;for(const c of form.querySelectorAll('input,button'))c.disabled=false;}}
}
function candidateEvidence(candidate) {
  return candidate?`<div class="candidate-source"><span>Proposition initiale : <strong>${escapeHTML(candidate.value)}</strong> · page ${Number(candidate.page)}</span><blockquote>${escapeHTML(candidate.quote||'Extrait non disponible : vérifiez l’original.')}</blockquote></div>`:'<p class="candidate-source">Aucune proposition. Saisissez uniquement une information vérifiée.</p>';
}
function renderDocumentFields() {
  const skill=$('#document-skill').value,candidates=state.documentDetail?.extraction?.candidates||{};
  const expense=skill==='expense-review';
  const verify=field=>`<label class="checkbox-field"><input type="checkbox" id="document-verify-${field}" data-document-verify="${field}"> J’ai vérifié cette information.</label>`;
  let fields=skill==='admin-triage'?`<div class="document-candidate form-field"><label for="document-field-text">Demande à orienter</label><textarea id="document-field-text" data-document-field="text" rows="5" maxlength="12000"></textarea><small>Résumez le besoin après lecture du document. Le texte extrait reste visible et inchangé au-dessus.</small>${verify('text')}</div>`:(expense?expenseFields:documentFields).map(([field,label])=>`<div class="document-candidate form-field"><label for="document-field-${field}">${label}</label><input id="document-field-${field}" data-document-field="${field}" type="${field.endsWith('_date')?'date':'text'}" ${documentDecimalFields.includes(field)?'inputmode="decimal"':''} maxlength="500" value="${escapeHTML(candidates[field]?.value??'')}">${candidateEvidence(candidates[field])}${verify(field)}</div>`).join('');
  if(expense)fields+=Object.entries(expenseEnums).map(([field,options])=>`<div class="document-candidate form-field"><label for="document-field-${field}">${expenseEnumLabels[field]}</label><select id="document-field-${field}" data-document-field="${field}"><option value="">À vérifier</option>${options.map(([value,label])=>`<option value="${value}">${label}</option>`).join('')}</select><small>Information à confirmer auprès du demandeur ; elle n’est pas déduite de l’image.</small>${verify(field)}</div>`).join('');
  if(skill!=='admin-triage')fields+=(expense?expenseBooleans:[['paid','Paiement confirmé ?'],...(skill==='receivables-followup'?[['disputed','Litige en cours ?']]:[])]).map(([field,label])=>`<div class="document-candidate form-field"><label for="document-field-${field}">${label}</label><select id="document-field-${field}" data-document-field="${field}"><option value="">Non vérifié</option><option value="true">Oui · vérifié</option><option value="false">Non · vérifié</option></select><small>La présence d’un justificatif ne permet pas de déduire cette réponse.</small>${verify(field)}</div>`).join('');
  $('#document-candidate-fields').innerHTML=`${expense?'<p class="form-help">Une dépense par justificatif. Renseignez la politique fournie et son contexte ; aucun plafond ni traitement fiscal n’est présumé. Aucun remboursement ne sera effectué.</p>':''}<div class="document-candidates-grid">${fields}</div>`;
  $('#document-human-verified').checked=false;
}

async function extractDocument(form) {
  if(!can('documents_extract')||state.documentExtractBusy||state.documentCreateBusy||!state.documentDetail)return;
  const record=state.documentDetail,id=record.id,epoch=state.sessionEpoch;
  const body={version:record.extraction_version,language:$('#document-language',form).value,force_ocr:$('#document-force-ocr',form).checked};
  state.documentExtractBusy=true;for(const control of form.querySelectorAll('button,input,select'))control.disabled=true;
  $('#document-action-error').textContent='';$('#document-extract-button').textContent='Extraction en cours…';
  // Prevent creation against an extraction being replaced in this tab.
  const createForm=$('#document-create-form');if(createForm)for(const control of createForm.querySelectorAll('button,input,select,textarea'))control.disabled=true;
  try{const response=await post(`/api/documents/${encodeURIComponent(id)}/extract`,body);if(state.documentDetail?.id===id){state.documentDetail=response.document;renderDocumentDetail();}await loadDocuments();toast('Extraction terminée. Vérifiez chaque information avec l’original.');}
  catch(error){if(sessionInterrupted(error))return;if(error.status===409){await openDocument(id);toast('La pièce a changé. Vérifiez la version actualisée avant de continuer.',true);}else{await openDocument(id);if($('#document-action-error'))$('#document-action-error').textContent=error.message;}}
  finally{if(epoch===state.sessionEpoch){state.documentExtractBusy=false;for(const control of form.querySelectorAll('button,input,select'))control.disabled=false;const button=$('#document-extract-button');if(button){button.disabled=false;button.textContent=state.documentDetail?.extraction?'Relancer l’extraction':'Extraire le texte';}if(createForm?.isConnected)for(const control of createForm.querySelectorAll('button,input,select,textarea'))control.disabled=false;}}
}
async function createDocumentTask(form) {
  if(!can('documents_create_task')||state.documentCreateBusy||state.documentExtractBusy||!state.documentDetail)return;
  const target=$('#document-create-error',form);target.textContent='';
  const record=state.documentDetail,epoch=state.sessionEpoch;
  try{
    const title=$('#document-title',form).value.trim(),country=$('#document-country',form).value,skill_id=$('#document-skill',form).value;
    if(!title)throw new Error('Donnez un titre au dossier.');if(!['FR','ES'].includes(country))throw new Error('Sélectionnez le pays applicable au dossier.');
    if(!$('#document-human-verified',form).checked)throw new Error('Vérifiez l’original et confirmez votre relecture.');
    const payload={},verified_fields=[];
    for(const input of form.querySelectorAll('[data-document-field]')){
      const field=input.dataset.documentField,value=input.value.trim();if(!value)continue;
      if(!$(`#document-verify-${field}`,form).checked)throw new Error('Cochez chaque information renseignée après l’avoir vérifiée, ou effacez-la si elle est incertaine.');
      payload[field]=documentBooleanFields.includes(field)?value==='true':documentDecimalFields.includes(field)?value.replace(/\s/g,'').replace(',','.'):['currency','policy_currency'].includes(field)?value.toUpperCase():value;
      verified_fields.push(field);
    }
    if(!verified_fields.length)throw new Error('Renseignez au moins une information vérifiée pour préparer le dossier.');
    const description=$('#document-description',form).value.trim();
    if(description.length>12000)throw new Error('Le contexte doit rester sous 12 000 caractères.');
    const body={title,country,skill_id,description,payload,verified_fields,extraction_version:record.extraction_version,human_verified:true};
    state.documentCreateBusy=true;for(const control of form.querySelectorAll('input,textarea,select,button'))control.disabled=true;
    const response=await post(`/api/documents/${encodeURIComponent(record.id)}/create-task`,body);
    $('#document-dialog').close();state.documentDetail=response.document;state.documentsLoaded=false;await loadData();await openTask(response.task.id);
    toast('Dossier créé. Lancez les contrôles et relisez les résultats avant toute validation.');
  }catch(error){if(sessionInterrupted(error))return;if(error.status===409){await openDocument(record.id);toast('La pièce a changé ou possède déjà un dossier. Consultez la version actualisée.',true);}else target.textContent=error.message;}
  finally{if(epoch===state.sessionEpoch){state.documentCreateBusy=false;for(const control of form.querySelectorAll('input,textarea,select,button'))control.disabled=false;}}
}
async function downloadDocument(button) {
  if(!can('documents_read')||!state.documentDetail)return;button.disabled=true;
  try{const record=state.documentDetail,blob=await api(`/api/documents/${encodeURIComponent(record.id)}/original`,{responseType:'blob'}),url=URL.createObjectURL(blob);documentBlobURLs.add(url);const link=document.createElement('a');link.href=url;link.download=record.filename;document.body.append(link);link.click();link.remove();setTimeout(()=>{URL.revokeObjectURL(url);documentBlobURLs.delete(url);},1000);}
  catch(error){if(!sessionInterrupted(error))toast(error.message,true);}finally{button.disabled=false;}
}
function inputField(key,label,options={}) {
  return `<div class="form-field ${options.full?'full':''}"><label for="field-${key}">${label}</label><input id="field-${key}" name="${key}" type="${options.type||'text'}" ${options.inputmode?`inputmode="${options.inputmode}"`:''} ${options.placeholder?`placeholder="${escapeHTML(options.placeholder)}"`:''} value="${escapeHTML(options.value??'')}" ${options.maxlength?`maxlength="${options.maxlength}"`:''}>${options.hint?`<small>${options.hint}</small>`:''}</div>`;
}
function invoiceFields(payload={},receivable=false) {
  return `<div class="form-help">Renseignez les données de la facture. Une information manquante sera signalée lors du contrôle. Les montants sont dans la même devise ; la conformité fiscale n’est pas certifiée.</div><div class="form-grid">${inputField('invoice_number','Référence de la facture',{value:payload.invoice_number,placeholder:'FAC-2026-042'})}${inputField('currency','Devise',{value:payload.currency||'EUR',placeholder:'EUR',maxlength:3})}${inputField('supplier','Fournisseur / émetteur',{value:payload.supplier,placeholder:'Nom de l’entreprise'})}${inputField('customer','Client / destinataire',{value:payload.customer,placeholder:'Nom du client'})}${inputField('issue_date','Date d’émission',{type:'date',value:payload.issue_date})}${inputField('due_date','Date d’échéance',{type:'date',value:payload.due_date})}${inputField('net_amount','Montant hors taxes',{value:payload.net_amount,inputmode:'decimal',placeholder:'1 000,00'})}${inputField('vat_rate','Taux de TVA (%)',{value:payload.vat_rate,inputmode:'decimal',placeholder:'20'})}${inputField('vat_amount','Montant de TVA',{value:payload.vat_amount,inputmode:'decimal',placeholder:'200,00'})}${inputField('total_amount','Montant total TTC',{value:payload.total_amount,inputmode:'decimal',placeholder:'1 200,00'})}${receivable?inputField('last_reminder_date','Dernière relance (facultatif)',{type:'date',value:payload.last_reminder_date}):''}</div><div class="form-grid space-top"><div class="form-field"><label for="field-paid">La facture est-elle déjà payée ?</label><select id="field-paid" name="paid"><option value="" ${typeof payload.paid!=='boolean'?'selected':''}>Non vérifié</option><option value="true" ${payload.paid===true?'selected':''}>Oui · règlement confirmé</option><option value="false" ${payload.paid===false?'selected':''}>Non · facture non réglée</option></select><small>Choisissez une réponse après vérification du suivi.</small></div>${receivable?`<div class="form-field"><label for="field-disputed">Un litige est-il en cours ?</label><select id="field-disputed" name="disputed"><option value="" ${typeof payload.disputed!=='boolean'?'selected':''}>Non vérifié</option><option value="true" ${payload.disputed===true?'selected':''}>Oui · litige déclaré</option><option value="false" ${payload.disputed===false?'selected':''}>Non · absence de litige vérifiée</option></select></div>`:''}</div>`;
}
function renderExpenseFields(payload={}) {
  return `<div class="form-help">Une dépense par dossier. Le reçu original doit être importé et vérifié dans Documents. Le contexte saisi ici ne remplace pas sa preuve. Aucun remboursement ni TVA déductible ne sont calculés.${can('documents_read')?'<br><button type="button" class="text-link" data-action="expense-documents">Importer un reçu dans Documents →</button>':''}</div><div class="form-grid">${expenseFields.map(([key,label])=>inputField(key,label,{value:payload[key],type:key.endsWith('_date')?'date':'text',inputmode:documentDecimalFields.includes(key)?'decimal':undefined,maxlength:500})).join('')}${Object.entries(expenseEnums).map(([key,options])=>`<div class="form-field"><label for="field-${key}">${expenseEnumLabels[key]}</label><select id="field-${key}" name="${key}"><option value="">Non vérifié</option>${options.map(([value,label])=>`<option value="${value}" ${payload[key]===value?'selected':''}>${label}</option>`).join('')}</select></div>`).join('')}${expenseBooleans.map(([key,label])=>`<div class="form-field"><label for="field-${key}">${label}</label><select id="field-${key}" name="${key}"><option value="" ${typeof payload[key]!=='boolean'?'selected':''}>Non vérifié</option><option value="true" ${payload[key]===true?'selected':''}>Oui · vérifié</option><option value="false" ${payload[key]===false?'selected':''}>Non · vérifié</option></select></div>`).join('')}</div>`;
}
function renderSkillFields(skillId,payload={}) {
  const skill = skillById(skillId);
  let body;
  if (['invoice-check','receivables-followup'].includes(skillId)) body = invoiceFields(payload,skillId==='receivables-followup');
  else if (skillId==='expense-review') body = renderExpenseFields(payload);
  else if (skillId==='bookkeeping-pack') body = `<div class="form-help">Ce contrôle prépare l’inventaire des pièces pour votre comptabilité. Il vérifie les données déclarées, sans lire ni certifier les documents originaux.</div><div class="form-grid">${inputField('period','Période comptable',{type:'month',value:payload.period})}${inputField('expected_documents','Nombre de pièces attendu (facultatif)',{type:'number',value:payload.expected_documents??''})}<div class="form-field full"><label for="field-documents">Liste des pièces · JSON</label><textarea id="field-documents" class="code-input" name="documents" rows="10" spellcheck="false">${escapeHTML(JSON.stringify(payload.documents||[],null,2))}</textarea><small>Chaque pièce : id, type, number, date, total_amount et currency. Utilisez « Exemple fictif » pour voir le format.</small></div></div>`;
  else body = `<div class="form-help">${skill?.status==='guided'?'Ce skill est guidé : il prépare une liste de vérifications et restera à compléter. Il n’automatise pas la démarche. Décrivez le besoin dans le champ ci-dessus.':'Décrivez la demande, les pièces disponibles et l’échéance. L’agent prépare une orientation et une liste de prochaines actions à vérifier.'}</div>`;
  const fields=['invoice_number','supplier','customer','issue_date','due_date','currency','net_amount','vat_rate','vat_amount','total_amount','paid',...(skillId==='receivables-followup'?['disputed','last_reminder_date']:[])];
  const managedFields=skillId==='expense-review'?expenseKeys:skillId==='bookkeeping-pack'?['period','documents','expected_documents']:['invoice-check','receivables-followup'].includes(skillId)?fields:[];
  const extras=Object.fromEntries(Object.entries(state.editing?.payload||{}).filter(([key])=>!managedFields.includes(key)));
  if(Object.keys(extras).length)body+=`<details class="detail-disclosure"><summary>Données complémentaires conservées</summary><p class="inline-muted space-top">Ces données ne sont pas modifiées par ce formulaire. Elles restent soumises aux contrôles.</p><pre>${escapeHTML(JSON.stringify(extras,null,2))}</pre></details>`;
  $('#skill-fields').innerHTML = `<div class="form-section-head"><h3>Informations du dossier</h3>${!isProduction()?'<button type="button" class="text-link" data-action="prefill">Exemple fictif <span aria-hidden="true">↙</span></button>':''}</div>${body}`;
}
function openCreate(skillId,task=null) {
  if(!can(task?'update':'create'))return;
  state.editing = task;
  state.creationAttempt = null;
  const selected = task?.skill_id || skillId || state.skills.find(s=>s.id==='invoice-check')?.id || state.skills[0]?.id;
  if(!selected){toast('Aucun skill disponible. Rechargez les données.',true);return;}
  const dialog = $('#create-dialog');
  dialog.innerHTML = `<form id="task-form"><div class="dialog-header"><div><div class="eyebrow">${task?'Corriger & recontrôler':'Un dossier, une mission'}</div><h2 id="create-dialog-title">${task?'Compléter le dossier':'Préparer un nouveau dossier'}</h2><p>${task?'La nouvelle version devra être analysée puis validée à nouveau.':'Renseignez les éléments à contrôler. Aucun envoi externe ne sera effectué.'}</p></div><button type="button" class="icon-button" data-action="close" aria-label="Fermer">×</button></div><div class="dialog-body"><div class="form-grid"><div class="form-field full"><label for="task-title">Titre du dossier *</label><input id="task-title" name="title" required maxlength="180" placeholder="Ex. Contrôler la facture de mon fournisseur" value="${escapeHTML(task?.title||'')}"></div><div class="form-field full-mobile"><label for="task-skill">Skill spécialisé</label><select id="task-skill" name="skill_id" ${task?'disabled':''}>${state.skills.map(s=>`<option value="${escapeHTML(s.id)}" ${s.id===selected?'selected':''}>${escapeHTML(s.name)}${s.status==='guided'?' · guidé':''}</option>`).join('')}</select></div><div class="form-field full-mobile"><label for="task-country">Pays du dossier</label><select id="task-country" name="country" ${task?'disabled':''}><option value="FR" ${task?.country!=='ES'?'selected':''}>France</option><option value="ES" ${task?.country==='ES'?'selected':''}>Espagne</option></select></div><div class="form-field full"><label for="task-description">Contexte et consignes</label><textarea id="task-description" name="description" rows="3" maxlength="12000" placeholder="Que voulez-vous préparer ? Y a-t-il un point de vigilance ou une échéance ?">${escapeHTML(task?.description||'')}</textarea></div></div><section id="skill-fields" class="form-section" aria-label="Données spécialisées"></section><div id="task-form-error" class="form-error" role="alert"></div></div><div class="dialog-footer"><small>Contrôles locaux · Résultat à relire.<br>Les champs laissés vides seront signalés.</small><div class="dialog-footer-actions"><button class="btn btn-secondary" type="button" data-action="close">Annuler</button><button class="btn btn-primary" type="submit">${task?'Enregistrer et recontrôler':'Créer et analyser'}</button></div></div></form>`;
  renderSkillFields(selected,task?.payload||{});
  dialog.showModal();
  $('#task-title').focus();
}
function prefill() {
  if(isProduction()||!can('create'))return;
  const skillId = $('#task-skill').value;
  const today = new Date();
  const date = offset=>{const value=new Date(today);value.setDate(value.getDate()+offset);return value.toISOString().slice(0,10);};
  const receivable=skillId==='receivables-followup';
  $('#task-title').value = skillId==='invoice-check'?'Exemple fictif · Facture Atelier Horizon':receivable?'Exemple fictif · Relance Maison Alba':skillId==='bookkeeping-pack'?'Exemple fictif · Pièces du mois':'Exemple fictif · Organiser mes documents';
  $('#task-description').value = 'Dossier de démonstration avec des données fictives. Préparer le contrôle et les prochaines étapes pour validation.';
  const payload = skillId==='bookkeeping-pack'?{period:date(0).slice(0,7),expected_documents:2,documents:[{id:'DOC-001',type:'invoice',number:'FAC-DEMO-001',date:date(0),total_amount:'1200.00',currency:'EUR'},{id:'DOC-002',type:'receipt',number:'RECU-DEMO-002',date:date(0),total_amount:'48.00',currency:'EUR'}]}:{invoice_number:'FAC-DEMO-042',supplier:'Atelier Horizon (fictif)',customer:'Maison Alba (fictif)',issue_date:date(receivable?-50:0),due_date:date(receivable?-20:30),net_amount:'1000.00',vat_rate:'20',vat_amount:'200.00',total_amount:'1200.00',currency:'EUR',paid:false,disputed:false};
  renderSkillFields(skillId,skillId==='expense-review'?{merchant:'Commerçant fictif',expense_date:date(0),total_amount:'24.00',currency:'EUR',employee_ref:'DEMO-01',business_purpose:'Déplacement professionnel fictif',category:'travel'}:payload);
  toast('Exemple fictif inséré. Modifiez les valeurs avant de créer le dossier.');
}
function collectPayload(form,skillId) {
  const values = new FormData(form);
  if(['invoice-check','receivables-followup'].includes(skillId)) {
    const payload={...(state.editing?.payload||{})};
    for(const key of ['invoice_number','supplier','customer','issue_date','due_date','currency','net_amount','vat_rate','vat_amount','total_amount','paid',...(skillId==='receivables-followup'?['disputed','last_reminder_date']:[])])delete payload[key];
    for(const key of ['invoice_number','supplier','customer','issue_date','due_date','currency']){const value=String(values.get(key)||'').trim();if(value)payload[key]=key==='currency'?value.toUpperCase():value;}
    for(const key of ['net_amount','vat_rate','vat_amount','total_amount']){const value=String(values.get(key)||'').replace(/\s/g,'').replace(',','.');if(value)payload[key]=value;}
    if(['true','false'].includes(values.get('paid')))payload.paid=values.get('paid')==='true';
    if(skillId==='receivables-followup'){if(['true','false'].includes(values.get('disputed')))payload.disputed=values.get('disputed')==='true';if(values.get('last_reminder_date'))payload.last_reminder_date=values.get('last_reminder_date');}
    return payload;
  }
  if(skillId==='expense-review') {
    const payload={...(state.editing?.payload||{})};
    for(const key of expenseKeys){delete payload[key];const value=String(values.get(key)||'').trim();if(!value)continue;payload[key]=expenseBooleans.some(([field])=>field===key)?value==='true':documentDecimalFields.includes(key)?value.replace(/\s/g,'').replace(',','.'):['currency','policy_currency'].includes(key)?value.toUpperCase():value;}
    return payload;
  }
  if(skillId==='bookkeeping-pack') {
    let documents;
    try{documents=JSON.parse(String(values.get('documents')||'[]'));}catch{throw new Error('La liste des pièces doit être un tableau JSON valide. Utilisez « Exemple fictif » pour voir le format.');}
    if(!Array.isArray(documents))throw new Error('La liste des pièces doit être un tableau JSON entre [ et ].');
    const payload={...(state.editing?.payload||{}),documents};
    delete payload.period;delete payload.expected_documents;
    if(values.get('period'))payload.period=values.get('period');
    if(values.get('expected_documents')!==''){const count=Number(values.get('expected_documents'));if(!Number.isInteger(count)||count<0)throw new Error('Le nombre de pièces attendu doit être un entier positif ou nul.');payload.expected_documents=count;}
    return payload;
  }
  return state.editing?.payload || {};
}
async function saveTask(form) {
  if(!can(state.editing?'update':'create'))return;
  const button=$('button[type="submit"]',form);const original=button.textContent;
  try {
    $('#task-form-error').textContent='';
    const values=new FormData(form);const skillId=state.editing?.skill_id||values.get('skill_id');
    const payload=collectPayload(form,skillId);
    const title=String(values.get('title')||'').trim();if(!title)throw new Error('Donnez un titre au dossier.');
    button.disabled=true;button.textContent='Préparation en cours…';
    const body={title,description:String(values.get('description')||'').trim(),payload};
    let response;
    if(state.editing)response=await post(`/api/tasks/${encodeURIComponent(state.editing.id)}/update`,{...body,version:state.editing.version});
    else {
      const createBody={...body,skill_id:skillId,country:values.get('country')};
      const fingerprint=JSON.stringify(createBody);
      if(state.creationAttempt?.fingerprint!==fingerprint)state.creationAttempt={fingerprint,key:crypto.randomUUID()};
      response=await post('/api/tasks',{...createBody,idempotency_key:state.creationAttempt.key});
      state.creationAttempt=null;
    }
    const task=response.task;
    let analysisError=null;
    try{await post(`/api/tasks/${encodeURIComponent(task.id)}/analyze`,{use_ai:false});}catch(error){if(sessionInterrupted(error))throw error;analysisError=error.message;}
    $('#create-dialog').close();
    state.editing=null;
    await loadData();
    await openTask(task.id);
    toast(analysisError?`Dossier enregistré, analyse non terminée : ${analysisError}`:'Dossier enregistré et contrôlé. Relisez les résultats.',Boolean(analysisError));
  } catch(error){if(sessionInterrupted(error))return;const errorTarget=$('#task-form-error');if(errorTarget)errorTarget.textContent=error.message;else toast(error.message,true);button.disabled=false;button.textContent=original;}
}
async function openTask(id) {
  if(state.sessionPhase!=='authenticated')return;
  const dialog=$('#detail-dialog');
  dialog.innerHTML='<div class="dialog-header"><h2 id="detail-dialog-title">Dossier</h2><button class="icon-button" data-action="close" aria-label="Fermer">×</button></div><div class="initial-loading"><div class="loader"></div><p>Chargement du dossier…</p></div>';
  if(!dialog.open)dialog.showModal();
  try{const response=await api(`/api/tasks/${encodeURIComponent(id)}`);state.detail=response.task;state.events=response.events||[];state.eventsTotal=response.events_total??state.events.length;state.eventsTruncated=response.events_truncated===true;renderTaskDetail();}
  catch(error){if(sessionInterrupted(error))return;dialog.innerHTML=`<div class="dialog-header"><h2 id="detail-dialog-title">Dossier indisponible</h2><button class="icon-button" data-action="close" aria-label="Fermer">×</button></div><div class="dialog-body"><div class="error-banner" role="alert">${escapeHTML(error.message)}</div></div>`;}
}
function taskDocumentSource(task) {
  const source=task.payload?._document_source;if(!source)return '';
  const latest=task.skill_id==='expense-review'&&Array.isArray(source.receipt_reviews)?source.receipt_reviews.at(-1):null;
  const changed=(Array.isArray(source.changed_since_document_review)?source.changed_since_document_review:[]).filter(field=>!latest?.fields?.[field]||latest.fields[field].reviewed_value!==task.payload?.[field]);
  const label=field=>[...documentFields,...expenseFields,...expenseBooleans].find(([key])=>key===field)?.[1]||({paid:'Paiement',disputed:'Litige',text:'Demande'}[field])||field;
  return `<section class="result-section task-document-source"><div class="section-heading"><h3>Pièce source</h3>${can('documents_read')?`<button class="text-link" data-action="document-open" data-id="${escapeHTML(source.document_id)}">Consulter l’original et ses extraits →</button>`:''}</div><p>Informations vérifiées le ${escapeHTML(displayDateTime(source.reviewed_at))} · extraction version ${Number(source.extraction_version)}.</p>${latest?`<p>Champs du reçu reconfirmés le ${escapeHTML(displayDateTime(latest.reviewed_at))}. La preuve initiale et l’historique sont conservés.</p>`:''}${changed.length?`<p class="draft-warning">Données modifiées depuis cette vérification : ${changed.map(field=>escapeHTML(label(field))).join(', ')}. Comparez à nouveau ces valeurs avec la pièce source.</p>`:'<p class="draft-warning">Les propositions d’origine et les corrections retenues restent conservées avec ce dossier. La validation administrative reste une étape distincte.</p>'}</section>`;
}
function renderTaskDetail() {
  if(state.sessionPhase!=='authenticated'||!state.detail)return;
  const task=state.detail,result=task.result;
  const checks=result?.checks||[];
  const findings=result?.findings||[];
  const eventNames={'task.expense_reverified':'Reçu reconfirmé sur l’original','task.created':'Dossier créé','task.analyzed':'Analyse effectuée','task.reviewed':'Décision enregistrée','task.updated':'Dossier modifié',created:'Dossier créé',task_created:'Dossier créé',analyzed:'Analyse effectuée',task_analyzed:'Analyse effectuée',approved:'Validation enregistrée',review_approved:'Validation enregistrée',rejected:'Reprise demandée',review_rejected:'Reprise demandée',updated:'Dossier modifié',task_updated:'Dossier modifié'};
  $('#detail-dialog').innerHTML=`<div class="dialog-header"><div><div class="eyebrow">${escapeHTML(skillName(task.skill_id))}</div><h2 id="detail-dialog-title">${escapeHTML(task.title)}</h2><p>Modifié le ${escapeHTML(displayDate(task.updated_at))} · version ${Number(task.version||1)}</p></div><button class="icon-button" data-action="close" aria-label="Fermer">×</button></div><div class="dialog-body"><div class="detail-meta">${pill(task.status)}<span>${task.country==='ES'?'Espagne':'France'}</span><span>Analyse ${result?.mode==='ai'?'avec avis IA':'locale'}</span>${can('update')?'<button class="text-link" data-action="edit-task">Modifier / compléter le dossier ↗</button>':''}</div>${taskDocumentSource(task)}${task.skill_id==='invoice-check'&&task.status==='ready'&&can('finance_write')?'<section class="status-alert"><button class="btn btn-secondary" data-action="finance-register-task">Ajouter au suivi des factures</button><p>Confirmez le sens et les règlements antérieurs avant inscription.</p></section>':''}${task.description?`<p class="detail-description">${escapeHTML(task.description)}</p>`:''}${!result?'<div class="form-help">Ce dossier n’a pas encore été analysé. Lancez les contrôles pour obtenir les points de vigilance et une préparation à relire.</div>':`<section class="result-section"><h3>Résultat du contrôle</h3><p class="result-summary">${escapeHTML(result.summary)}</p>${findings.length?`<ul class="findings">${findings.map(f=>`<li class="finding ${escapeHTML(f.severity||'info')}"><span class="finding-icon" aria-hidden="true">${f.severity==='error'?'!':f.severity==='warning'?'△':'✓'}</span><span>${escapeHTML(f.message)}${f.field?` <span class="inline-muted">(${escapeHTML(f.field)})</span>`:''}</span></li>`).join('')}</ul>`:''}${result.missing_fields?.length?`<p class="form-help">À compléter : ${result.missing_fields.map(escapeHTML).join(', ')}.</p>`:''}${checks.length?`<details class="detail-disclosure"><summary>${checks.length} point${checks.length>1?'s':''} de contrôle</summary><ul class="check-list">${checks.map(c=>`<li>${typeof c==='string'?escapeHTML(c):`${c.passed?'✓':'!'} ${escapeHTML(c.name||c.label||'Contrôle')} ${c.detail?'— '+escapeHTML(c.detail):''}`}</li>`).join('')}</ul></details>`:''}</section>${result.draft?`<section class="result-section"><div class="section-heading"><h3>Préparation à relire</h3><button class="text-link" data-action="copy-draft">Copier le texte</button></div><pre class="draft-text">${escapeHTML(result.draft)}</pre><p class="draft-warning">Brouillon interne. La validation ne déclenche ni envoi ni dépôt.</p></section>`:''}${result.ai_advice?`<section class="result-section"><h3>Avis IA · à vérifier séparément</h3><p class="result-summary">${escapeHTML(result.ai_advice.summary)}</p>${result.ai_advice.suggested_draft?`<pre class="draft-text">${escapeHTML(result.ai_advice.suggested_draft)}</pre>`:''}${result.ai_advice.questions?.length?`<ul class="check-list">${result.ai_advice.questions.map(q=>`<li>${escapeHTML(q)}</li>`).join('')}</ul>`:''}<p class="draft-warning">Cet avis ne modifie pas les contrôles bloquants et n’autorise aucune action.</p></section>`:''}`}
  ${task.status==='needs_review'&&can('review')?`<section class="review-box"><h3>Votre décision</h3><p>Vérifiez les données et le brouillon. Valider signifie que vous avez relu la préparation ; aucune action externe n’est exécutée.</p><div class="form-field"><label for="review-note">Note de relecture (requise pour demander une reprise)</label><textarea id="review-note" rows="2" maxlength="2000" placeholder="Ex. Montants vérifiés avec le document original."></textarea></div><div class="review-actions"><button class="btn btn-danger" data-action="review" data-decision="reject">Demander une reprise</button><button class="btn btn-primary" data-action="review" data-decision="approve">Valider la préparation</button></div><div id="review-error" class="form-error" role="alert"></div></section>`:task.status==='ready'?'<div class="status-alert">Préparation validée en interne. Aucun message envoyé et aucune démarche effectuée.</div>':task.status==='blocked'||task.status==='rejected'?`<div class="status-alert ${task.status}">${task.status==='blocked'?'Complétez ou corrigez le dossier avant sa validation.':'Une reprise est nécessaire. Modifiez les informations puis relancez le contrôle.'}</div>`:''}
  ${aiAvailable()?'<section class="result-section"><h3>Enrichissement IA optionnel</h3><p class="detail-description">Le contenu de ce dossier sera transmis au fournisseur configuré. L’avis IA restera une proposition à vérifier.</p><label class="checkbox-field"><input id="ai-consent" type="checkbox"> J’autorise cette transmission pour ce dossier.</label><button class="btn btn-secondary space-top" id="analyze-ai-button" data-action="analyze-ai" disabled>Analyser avec IA</button></section>':''}
  <details class="detail-disclosure"><summary>Données du dossier</summary><pre>${escapeHTML(JSON.stringify(task.payload,null,2))}</pre></details>${result?.context?`<details class="detail-disclosure"><summary>Contexte utilisé et traçabilité</summary><pre>${escapeHTML(JSON.stringify(result.context,null,2))}</pre></details>`:''}<details class="detail-disclosure"><summary>Historique · ${state.events.length} événement${state.events.length>1?'s':''}</summary>${state.eventsTruncated?`<p class="audit-truncation inline-muted space-top">${state.events.length} derniers événements sur ${Number(state.eventsTotal)} ; historique complet dans l’export administrateur.</p>`:''}${state.events.length?`<ul class="audit-list">${state.events.map(event=>`<li><span>${escapeHTML(event.action==='task.reviewed'?(event.details?.decision==='approve'?'Préparation validée':'Reprise demandée'):(eventNames[event.action]||event.action||'Événement'))}${event.details?.note?`<br>${escapeHTML(event.details.note)}`:''}</span><span>${escapeHTML(displayDateTime(event.created_at))}</span></li>`).join('')}</ul>`:'<p class="inline-muted space-top">Aucun événement disponible.</p>'}</details><div id="detail-error" class="form-error" role="alert"></div></div><div class="dialog-footer"><small>Vos pièces d’origine restent la référence.<br>Contrôle technique, pas une certification juridique ou fiscale.</small><div class="dialog-footer-actions"><button class="btn btn-secondary" data-action="close">Fermer</button>${task.status!=='ready'&&can('analyze')?`<button class="btn btn-primary" data-action="analyze">${result?'Recontrôler':'Analyser le dossier'}</button>`:''}</div></div>`;
  if(!$('#detail-dialog').contains(document.activeElement))$('#detail-dialog .icon-button')?.focus({preventScroll:true});
}
async function analyzeTask(useAI,button) {
  if(!can('analyze')||(useAI&&!aiAvailable()))return;
  if(useAI&&!$('#ai-consent')?.checked)return;
  const label=button.textContent;button.disabled=true;button.textContent='Analyse en cours…';
  try{const id=state.detail.id;await post(`/api/tasks/${encodeURIComponent(id)}/analyze`,{use_ai:useAI});await loadData();await openTask(id);toast('Analyse terminée. Vérifiez les résultats avant de valider.');}
  catch(error){if(sessionInterrupted(error))return;$('#detail-error').textContent=error.message;button.disabled=false;button.textContent=label;}
}
async function reviewTask(decision,button) {
  if(!can('review'))return;
  const note=$('#review-note').value.trim();
  if(decision==='reject'&&note.length<3){$('#review-error').textContent='Précisez ce qui doit être corrigé pour demander une reprise (3 caractères minimum).';$('#review-note').focus();return;}
  button.disabled=true;
  try{const id=state.detail.id;await post(`/api/tasks/${encodeURIComponent(id)}/review`,{decision,note,version:state.detail.version});await loadData();await openTask(id);toast(decision==='approve'?'Préparation validée. Aucune action externe effectuée.':'Reprise demandée. Votre note est conservée dans l’historique.');}
  catch(error){if(sessionInterrupted(error))return;if(error.code==='version_conflict'){await openTask(state.detail.id);toast(error.message+' Le contenu actualisé est affiché.',true);}else{$('#review-error').textContent=error.message;button.disabled=false;}}
}
function openSkill(id) {
  if(state.sessionPhase!=='authenticated')return;
  const skill=skillById(id);if(!skill)return;
  $('#skill-dialog').innerHTML=`<div class="dialog-header"><div><div class="eyebrow">${escapeHTML(skill.agent)} · ${escapeHTML(skill.priority)}</div><h2 id="skill-dialog-title">${escapeHTML(skill.name)}</h2><p>${skill.status==='implemented'?'Skill avec contrôles exécutables':'Skill guidé · procédure de travail'}</p></div><button class="icon-button" data-action="close" aria-label="Fermer">×</button></div><div class="dialog-body"><p class="detail-description">${escapeHTML(skill.description)}</p><div class="skill-io"><section><h3>Informations attendues</h3><ul>${(skill.inputs||[]).map(input=>`<li>${escapeHTML(typeof input==='object'?JSON.stringify(input):input)}</li>`).join('')}</ul></section><section><h3>Préparation fournie</h3><ul>${(skill.outputs||[]).map(output=>`<li>${escapeHTML(typeof output==='object'?JSON.stringify(output):output)}</li>`).join('')}</ul></section></div><h3 class="space-top">Instructions complètes du skill</h3><pre class="skill-body">${escapeHTML(skill.body||'Les instructions détaillées ne sont pas disponibles.')}</pre></div><div class="dialog-footer"><small>Consultez le périmètre et les limites avant de créer votre dossier.</small><div class="dialog-footer-actions"><button class="btn btn-secondary" data-action="close">Fermer</button>${can('create')?`<button class="btn btn-primary" data-action="create" data-skill="${escapeHTML(skill.id)}">Préparer un dossier</button>`:''}</div></div>`;
  $('#skill-dialog').showModal();
}
async function exportData(button) {
  if(!can('export'))return;
  const label=button.textContent;button.disabled=true;
  try{const data=await api('/api/export');const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=`admin-agent-export-${new Date().toISOString().slice(0,10)}.json`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('Export JSON téléchargé. Il contient les données de cet espace.');}
  catch(error){if(sessionInterrupted(error))return;toast(error.message,true);}finally{button.disabled=false;button.textContent=label;}
}
async function seedDemo(button) {
  if(!can('demo')||isProduction())return;
  button.disabled=true;const label=button.textContent;button.textContent='Chargement…';
  try{const result=await post('/api/demo/seed');await loadData();toast(result.created?`${result.created} dossiers fictifs ajoutés.`:'Les dossiers de démonstration sont déjà présents.');}
  catch(error){if(sessionInterrupted(error))return;toast(error.message,true);button.disabled=false;button.textContent=label;}
}
function navigate() {if(state.sessionPhase!=='authenticated'){if(state.sessionPhase==='anonymous')renderLogin();return;}const page=location.hash.replace('#','')||'overview';state.page=Object.hasOwn(pageNames,page)?page:'overview';if(state.page==='overview'){state.country='all';if(!['all','needs_review','blocked','ready'].includes(state.filter))state.filter='all';}renderPage();}
sessionChannel?.addEventListener('message',event=>{
  if(event.data?.type==='logout' && isProduction()){
    state.logoutUnconfirmed=false;
    lockSession('Une déconnexion a été demandée dans un autre onglet. Les données de cette page ont été effacées. Reconnectez-vous pour continuer.');
  }
});
window.addEventListener('hashchange',navigate);
window.addEventListener('pageshow',checkSessionDeadline);
document.addEventListener('visibilitychange',checkSessionDeadline);
document.addEventListener('input',event=>{if(event.target.id==='task-search'){state.query=event.target.value;updateTaskList();}if(event.target.id==='skill-search'){state.skillQuery=event.target.value;updateSkillsList();}if(event.target.dataset.documentField){const checkbox=$(`#document-verify-${event.target.dataset.documentField}`);if(checkbox)checkbox.checked=false;}if(event.target.closest('#document-create-form')&&event.target.id!=='document-human-verified')$('#document-human-verified').checked=false;});
document.addEventListener('change',event=>{
  if(event.target.id==='task-skill')renderSkillFields(event.target.value);
  if(event.target.id==='status-filter'){state.filter=event.target.value;updateTaskList();}
  if(event.target.id==='country-filter'){state.country=event.target.value;updateTaskList();}
  if(event.target.id==='skill-status-filter'){state.skillStatus=event.target.value;updateSkillsList();}
  if(event.target.id==='ai-consent')$('#analyze-ai-button').disabled=!event.target.checked;
  if(event.target.id==='document-skill')renderDocumentFields();
  if(event.target.dataset.documentField){const checkbox=$(`#document-verify-${event.target.dataset.documentField}`);if(checkbox)checkbox.checked=false;$('#document-human-verified').checked=false;}
  if(['document-country','document-title','document-description'].includes(event.target.id))$('#document-human-verified').checked=false;
});
document.addEventListener('submit',event=>{if(event.target.id==='login-form'){event.preventDefault();login(event.target);}else if(event.target.id==='task-form'){event.preventDefault();saveTask(event.target);}else if(event.target.id==='document-upload-form'){event.preventDefault();uploadDocument(event.target);}else if(event.target.id==='document-extract-form'){event.preventDefault();extractDocument(event.target);}else if(event.target.id==='document-create-form'){event.preventDefault();createDocumentTask(event.target);}else if(event.target.id==='document-reverify-form'){event.preventDefault();reverifyExpenseDocument(event.target);}});
document.addEventListener('click',async event=>{
  if(event.target.closest('.skip-link')){event.preventDefault();$('#main').focus();return;}
  const button=event.target.closest('[data-action]');if(!button||button.disabled)return;
  const action=button.dataset.action;
  if(action==='logout'){await logout();return;}
  if(action==='session-retry'){button.disabled=true;await bootstrapSession();return;}
  if(state.sessionPhase!=='authenticated')return;
  if(action==='close'){button.closest('dialog').close();return;}
  if(action==='create'){if($('#skill-dialog').open)$('#skill-dialog').close();openCreate(button.dataset.skill);}
  else if(action==='prefill')prefill();
  else if(action==='expense-documents'){$('#create-dialog').close();location.hash='documents';}
  else if(action==='task')await openTask(button.dataset.id);
  else if(action==='skill')openSkill(button.dataset.id);
  else if(action==='documents-refresh')await loadDocuments();
  else if(action==='document-open'){if($('#detail-dialog').open)$('#detail-dialog').close();await openDocument(button.dataset.id);}
  else if(action==='document-download')await downloadDocument(button);
  else if(action==='document-linked-task'){$('#document-dialog').close();await openTask(button.dataset.id);}
  else if(action==='edit-task'){$('#detail-dialog').close();openCreate(null,state.detail);}
  else if(action==='filter'){state.filter=button.dataset.filter;document.querySelectorAll('.tab').forEach(tab=>{tab.classList.toggle('active',tab.dataset.filter===state.filter);tab.setAttribute('aria-pressed',tab.dataset.filter===state.filter);});updateTaskList();}
  else if(action==='metric'){state.filter=button.dataset.filter;state.country='all';state.query='';if(location.hash==='#tasks'){state.page='tasks';renderPage();}else location.hash='tasks';}
  else if(action==='clear-filters'){state.filter='all';state.query='';state.country='all';renderPage();}
  else if(action==='analyze'||action==='analyze-ai')await analyzeTask(action==='analyze-ai',button);
  else if(action==='review')await reviewTask(button.dataset.decision,button);
  else if(action==='seed')await seedDemo(button);
  else if(action==='export')await exportData(button);
  else if(action==='reload'){button.disabled=true;try{await loadData();}catch(error){if(sessionInterrupted(error))return;state.loadError=error.message;renderPage();}}
  else if(action==='copy-draft'){try{await navigator.clipboard.writeText(state.detail.result.draft);toast('Brouillon copié.');}catch{toast('La copie automatique est indisponible. Sélectionnez le texte du brouillon pour le copier.',true);}}
});
for(const dialog of document.querySelectorAll('dialog'))dialog.addEventListener('click',event=>{if(event.target===dialog){const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();}});
// Finance records stay in memory for this authenticated session only.
function resetFinance() {
  state.finance={loaded:false,loading:false,error:null,tab:'invoices',summary:{},invoices:[],transactions:[],allocations:[],suggestions:[],manualOnly:[],preview:null,previewInput:null,previewRevision:0,registerSource:null,sourceSeq:0,allocationAttempt:null,simulation:null,busy:false};
}
resetFinance();
const financeMoney=(amount,currency)=>`${escapeHTML(amount??'—')} ${escapeHTML(currency||'')}`;
const financeDirection=direction=>direction==='receivable'?'À encaisser':'À payer';
const financeStatus=invoice=>invoice.source_stale?'Source modifiée':({unpaid:'Non réglée',partial:'Règlement partiel',paid:'Réglée'}[invoice.payment_status]||'À vérifier');
const financeInput=(id,label,options={})=>`<div class="form-field ${options.full?'full':''}"><label for="${id}">${label}${options.required?' *':''}</label><input id="${id}" ${options.required?'required':''} type="${options.type||'text'}" ${options.decimal?'inputmode="decimal"':''} maxlength="${options.maxlength||200}" value="${escapeHTML(options.value??'')}" ${options.placeholder?`placeholder="${escapeHTML(options.placeholder)}"`:''}>${options.help?`<small>${escapeHTML(options.help)}</small>`:''}</div>`;
const financeSelect=(id,label,options,current='',required=true)=>`<div class="form-field"><label for="${id}">${label}${required?' *':''}</label><select id="${id}" ${required?'required':''}>${options.map(([value,text])=>`<option value="${escapeHTML(value)}" ${value===current?'selected':''}>${escapeHTML(text)}</option>`).join('')}</select></div>`;
const financeDecimal=value=>value.trim().replace(/\s/g,'').replace(',','.');
function financeDialog(title,body,formId,submitLabel) {
  state.finance.busy=false;state.finance.allocationAttempt=null;
  const dialog=$('#finance-dialog');
  dialog.innerHTML=`<form id="${formId}"><div class="dialog-header"><div><div class="eyebrow">Finances · vérification humaine</div><h2 id="finance-dialog-title">${title}</h2></div><button type="button" class="icon-button" data-action="close" aria-label="Fermer">×</button></div><div class="dialog-body">${body}<div id="finance-form-error" class="form-error" role="alert"></div></div><div class="dialog-footer"><small>Aucune opération bancaire ni transmission externe.</small><div class="dialog-footer-actions"><button type="button" class="btn btn-secondary" data-action="close">Annuler</button><button type="submit" class="btn btn-primary">${submitLabel}</button></div></div></form>`;
  if(!dialog.open)dialog.showModal();$('input,select,textarea',dialog)?.focus();
}
async function loadFinance() {
  if(!can('finance_read')||state.finance.loading)return;
  const current=state.finance;current.loading=true;current.error=null;
  try {
    const [summary,invoices,transactions,allocations,suggestions]=await Promise.all(['summary','invoices','bank-transactions','allocations','suggestions'].map(path=>api(`/api/finance/${path}`)));
    if(state.finance!==current)return;
    Object.assign(current,{summary,invoices:invoices.invoices||[],transactions:transactions.transactions||[],allocations:allocations.allocations||[],suggestions:suggestions.suggestions||[],manualOnly:suggestions.manual_only||[],loaded:true});
  } catch(error) {if(!sessionInterrupted(error)&&state.finance===current)current.error=error.message;}
  finally {if(state.finance===current){current.loading=false;if(state.page==='finance')renderFinance();}}
}
function renderFinance() {
  if(!can('finance_read')){$('#main').innerHTML=`${heading('Finances','Ce suivi n’est pas disponible avec votre accès.',false)}`;return;}
  const f=state.finance;
  const retainedBank=f.tab==='bank'?$('#finance-bank-form'):null;
  $('#main').innerHTML=`${heading('Vos factures, vos règlements, vos décisions.','Un suivi séparé par devise, fondé sur les pièces validées et les rapprochements que vous confirmez.',false)}<div class="finance-topline"><div class="finance-tabs" role="group" aria-label="Vue finances">${[['invoices','Factures'],['bank','Banque & rapprochements'],['factoring','Affacturage']].map(([id,label])=>`<button class="btn ${f.tab===id?'btn-primary':'btn-secondary'}" data-action="finance-tab" data-tab="${id}" aria-pressed="${f.tab===id}">${label}</button>`).join('')}</div><div class="heading-actions"><button class="btn btn-secondary" data-action="finance-refresh" ${f.loading?'disabled':''}>Actualiser</button>${can('finance_export')?'<button class="btn btn-secondary" data-action="finance-export">Exporter le suivi</button>':''}</div></div><div class="finance-notice">Suivi interne uniquement. Aucun accès bancaire en direct, paiement, envoi de relance ou cession de créance.</div>${f.error?`<div class="error-banner" role="alert">${escapeHTML(f.error)} <button class="text-link" data-action="finance-refresh">Réessayer</button></div>`:!f.loaded?'<div class="initial-loading"><div class="loader"></div><p>Chargement du suivi…</p></div>':`<div id="finance-content">${f.tab==='invoices'?renderFinanceInvoices():f.tab==='bank'?renderFinanceBank():renderFinanceFactoring()}</div>`}`;
  if(retainedBank&&$('#finance-bank-form'))$('#finance-bank-form').replaceWith(retainedBank);
  if(!f.loaded&&!f.loading&&!f.error)loadFinance();
}
function renderFinanceInvoices() {
  const f=state.finance;
  return `<div class="finance-balances">${(f.summary.by_currency||[]).map(row=>`<section class="panel finance-balance"><span class="eyebrow">${escapeHTML(row.currency)} · soldes suivis</span><dl><div><dt>À encaisser</dt><dd>${financeMoney(row.receivable_remaining,row.currency)}</dd></div><div><dt>Dont en retard</dt><dd>${financeMoney(row.receivable_overdue,row.currency)}</dd></div><div><dt>À payer</dt><dd>${financeMoney(row.payable_remaining,row.currency)}</dd></div><div><dt>Dont en retard</dt><dd>${financeMoney(row.payable_overdue,row.currency)}</dd></div></dl></section>`).join('')}</div>${f.summary.warnings?.length?`<ul class="document-warnings">${f.summary.warnings.map(w=>`<li>${escapeHTML(typeof w==='string'?w:w.message||JSON.stringify(w))}</li>`).join('')}</ul>`:''}<section class="panel finance-section"><div class="section-heading"><div><h2>Registre des factures</h2><p>${f.invoices.length} facture${f.invoices.length>1?'s':''} · Les devises ne sont jamais additionnées entre elles.</p></div>${can('finance_write')?'<button class="btn btn-primary" data-action="finance-register">Ajouter une facture validée</button>':''}</div>${f.invoices.length?`<div class="finance-records">${f.invoices.map(invoice=>`<article class="finance-record"><div><span class="eyebrow">${financeDirection(invoice.direction)}</span><h3>${escapeHTML(invoice.invoice_number)}</h3><p>${escapeHTML(invoice.direction==='receivable'?invoice.customer:invoice.supplier)}</p><button class="text-link" data-action="task" data-id="${escapeHTML(invoice.task_id)}">Consulter le dossier source →</button></div><dl><div><dt>Total</dt><dd>${financeMoney(invoice.total_amount,invoice.currency)}</dd></div><div><dt>Déjà réglé</dt><dd>${financeMoney(invoice.paid_amount,invoice.currency)}</dd></div><div><dt>Reste à ${invoice.direction==='receivable'?'encaisser':'payer'}</dt><dd class="finance-amount">${financeMoney(invoice.remaining_amount,invoice.currency)}</dd></div><div><dt>Échéance</dt><dd>${escapeHTML(displayDate(invoice.due_date))}</dd></div></dl><div class="finance-record-status"><span class="status-pill ${invoice.source_stale?'blocked':invoice.payment_status==='paid'?'ready':'needs_review'}">${financeStatus(invoice)}</span>${invoice.overdue?`<span class="finance-overdue">${Number(invoice.days_overdue)} jour${Number(invoice.days_overdue)>1?'s':''} de retard</span>`:''}${invoice.disputed!==false?`<small>${invoice.disputed===true?'Litige déclaré':'Litige non vérifié'}</small>`:''}${invoice.assignment_status==='assigned'?'<small>Cession déclarée · hors encaissement client</small>':''}${invoice.source_stale?'<small>Le dossier source a changé. Revue nécessaire avant toute nouvelle affectation.</small>':''}${can('finance_write')?`<button class="text-link" data-action="finance-state" data-id="${escapeHTML(invoice.id)}">Mettre à jour le litige</button>`:''}</div></article>`).join('')}</div>`:'<div class="finance-empty"><h3>Commencez par une facture relue.</h3><p>Contrôlez une pièce avec le skill « Contrôle de facture », validez sa préparation, puis ajoutez-la ici en confirmant les règlements déjà connus.</p><a class="text-link" href="#documents">Ouvrir les documents →</a></div>'}</section>`;
}
function renderFinanceBank() {
  const f=state.finance;
  const invoiceName=id=>f.invoices.find(x=>x.id===id)?.invoice_number||id;
  const txName=id=>f.transactions.find(x=>x.id===id)?.reference||id;
  return `${can('finance_write')?`<section class="panel finance-section"><div class="section-heading"><div><h2>Importer un relevé CSV</h2><p>Un extrait fourni par vos soins. Prévisualisez les lignes avant de les intégrer.</p></div></div><form id="finance-bank-form"><div class="form-grid">${financeInput('finance-account','Référence interne du compte',{required:true,placeholder:'compte-principal',help:'Utilisez un alias, sans identifiant de connexion ni secret.'})}<div class="form-field"><label for="finance-csv-file">Fichier CSV (facultatif)</label><input type="file" id="finance-csv-file" accept=".csv,text/csv"></div><div class="form-field full"><label for="finance-csv">Contenu CSV *</label><textarea id="finance-csv" class="code-input" rows="5" maxlength="50000" required spellcheck="false" placeholder="transaction_id,date,amount,currency,reference"></textarea><small>En-tête exact : transaction_id,date,amount,currency,reference. Dates AAAA-MM-JJ, montants signés avec point décimal : entrée positive, sortie négative. Une ligne doit avoir un identifiant stable.</small></div></div><div id="finance-bank-error" class="form-error" role="alert"></div><button type="submit" class="btn btn-secondary">Prévisualiser le CSV</button><div id="finance-bank-preview">${renderBankPreview()}</div></form></section>`:''}<section class="panel finance-section"><div class="section-heading"><div><h2>Mouvements bancaires</h2><p>Montants d’origine conservés. Un mouvement peut être affecté partiellement.</p></div>${can('finance_write')?'<button class="btn btn-primary" data-action="finance-allocate">Rapprocher un mouvement</button>':''}</div>${f.transactions.length?`<div class="finance-table-scroll"><table class="finance-table"><thead><tr><th>Date / compte</th><th>Référence</th><th>Montant signé</th><th>Reste à affecter</th></tr></thead><tbody>${f.transactions.map(tx=>`<tr><td>${escapeHTML(displayDate(tx.date))}<small>${escapeHTML(tx.account_ref)}</small></td><td>${escapeHTML(tx.reference)}<small>${escapeHTML(tx.transaction_id)}</small></td><td>${financeMoney(tx.amount,tx.currency)}</td><td>${financeMoney(tx.remaining_amount,tx.currency)}</td></tr>`).join('')}</tbody></table></div>`:'<p class="finance-empty">Aucun mouvement importé. Les factures ne sont jamais réglées automatiquement à partir de leur seul montant.</p>'}</section><section class="panel finance-section"><h2>Suggestions à vérifier</h2><p>Ces propositions ne modifient aucun solde. Comparez la référence, le sens, la devise et le montant avant de confirmer.</p>${f.suggestions.length?`<ul class="finance-suggestions">${f.suggestions.map((s,index)=>`<li><div><strong>${escapeHTML(invoiceName(s.invoice_id))}</strong><p>${escapeHTML(txName(s.transaction_id))} · ${financeMoney(s.amount,f.invoices.find(i=>i.id===s.invoice_id)?.currency)}</p><small>${s.reason==='reference_partial'?'Référence concordante · affectation partielle proposée':'Référence et montant concordants'}</small></div>${can('finance_write')?`<button class="btn btn-secondary" data-action="finance-suggestion" data-index="${index}">Vérifier le rapprochement</button>`:''}</li>`).join('')}</ul>`:'<p class="inline-muted">Aucune correspondance suffisamment étayée à proposer.</p>'}${f.manualOnly.length?`<p class="form-help">${f.manualOnly.length} mouvement${f.manualOnly.length>1?'s':''} à examiner manuellement : montant seul ou référence ambiguë. Aucun rapprochement automatique.</p>`:''}</section><section class="panel finance-section"><h2>Historique des rapprochements</h2>${f.allocations.length?`<ul class="finance-suggestions">${f.allocations.map(a=>`<li><div><strong>${escapeHTML(invoiceName(a.invoice_id))} · ${financeMoney(a.amount,a.currency)}</strong><p>${escapeHTML(txName(a.transaction_id))} · ${escapeHTML(displayDateTime(a.created_at))}</p><small>Preuve : ${escapeHTML(a.evidence_ref)}${a.status==='reversed'?` · Annulé : ${escapeHTML(a.reverse_reason)}`:''}</small></div>${a.status==='active'&&can('finance_write')?`<button class="btn btn-secondary" data-action="finance-reverse" data-id="${escapeHTML(a.id)}">Annuler le rapprochement</button>`:`<span class="status-pill">${a.status==='reversed'?'Annulé':'Actif'}</span>`}</li>`).join('')}</ul>`:'<p class="inline-muted">Aucune affectation confirmée.</p>'}</section>`;
}
function renderBankPreview() {
  const p=state.finance.preview;if(!p)return '';
  return `<div class="finance-preview"><h3>Vérifier avant import</h3><p>${Number(p.row_count)} lignes · ${Number(p.new_count)} nouvelles · ${Number(p.duplicate_count)} déjà importées.</p><div class="finance-table-scroll"><table class="finance-table"><thead><tr><th>Date</th><th>Référence</th><th>Montant signé</th><th>Import</th></tr></thead><tbody>${(p.rows||[]).map(row=>`<tr><td>${escapeHTML(row.date)}</td><td>${escapeHTML(row.reference)}</td><td>${financeMoney(row.amount,row.currency)}</td><td>${row.state==='duplicate'?'Déjà présente':'Nouvelle ligne'}</td></tr>`).join('')}</tbody></table></div><label class="checkbox-field space-top"><input type="checkbox" id="finance-import-confirmed"> J’ai vérifié le compte, les dates, les montants signés et les doublons.</label><button type="button" class="btn btn-primary space-top" data-action="finance-import">Confirmer l’import</button></div>`;
}
function renderFinanceFactoring() {
  return `<div class="finance-factoring-intro panel finance-section"><div class="eyebrow">Une préparation à partir de vos hypothèses</div><h2>Comprendre le coût d’une avance.</h2><p>Saisissez les conditions que vous souhaitez examiner. La simulation ne constitue ni une offre de financement, ni une décision d’éligibilité, ni une cession.</p>${can('finance_simulate')?'<button class="btn btn-primary" data-action="finance-factor">Calculer une simulation</button>':'<p class="inline-muted">La saisie de simulations est réservée aux opérateurs.</p>'}<div id="finance-simulation">${renderFactoringResult()}</div></div><div class="control-grid"><section class="panel finance-section"><h2>Pièces à préparer</h2><ul class="check-list"><li>Facture et dossier validé, avec son original.</li><li>Contrat, commande et preuve de livraison ou de prestation.</li><li>Échéance, règlements déjà reçus et solde à jour.</li><li>Situation des litiges et des cessions déjà déclarées.</li><li>Conditions complètes du financeur : frais, intérêts, retenue et recours.</li></ul><p class="draft-warning">Liste indicative à adapter aux demandes du professionnel choisi. Aucun document n’est transmis.</p></section><section class="panel finance-section"><h2>Suivre une cession déjà décidée</h2><p>Enregistrez une décision externe documentée, ou sa mainlevée. Cette déclaration ne change pas le solde payé par le client et n’exécute aucune cession.</p>${can('finance_write')?'<button class="btn btn-secondary" data-action="finance-assignment">Déclarer un statut de cession</button>':''}<ul class="finance-assignment-list">${state.finance.invoices.filter(i=>i.assignment_status!=='none').map(i=>`<li><strong>${escapeHTML(i.invoice_number)}</strong> · ${i.assignment_status==='assigned'?'Cession déclarée':'Mainlevée déclarée'}</li>`).join('')}</ul></section></div>`;
}
function renderFactoringResult() {
  const s=state.finance.simulation;if(!s)return '';
  const labels=[['nominal','Montant étudié'],['advance','Avance brute'],['reserve','Retenue'],['fees','Frais'],['interest','Intérêts'],['total_cost','Coût total estimé'],['net_cash','Trésorerie nette estimée']];
  return `<section class="finance-preview" aria-live="polite"><h3>Simulation indicative</h3><dl class="finance-calculation">${labels.map(([key,label])=>`<div><dt>${label}</dt><dd>${financeMoney(s[key],s.currency)}</dd></div>`).join('')}</dl><p>${Number(s.days)} jours · base ${Number(s.day_basis)} jours · du ${escapeHTML(displayDate(s.funding_date))} au ${escapeHTML(displayDate(s.maturity_date))}.</p><ul class="check-list">${(s.assumptions||[]).map(a=>`<li>${escapeHTML(a)}</li>`).join('')}</ul><p class="draft-warning">Hypothèses saisies : avance ${escapeHTML(s.advance_rate)} %, commission ${escapeHTML(s.fee_rate)} %, intérêt annuel ${escapeHTML(s.annual_interest_rate)} %, frais fixes ${financeMoney(s.fixed_fee,s.currency)}. Aucun financeur consulté. Aucun versement effectué.</p></section>`;
}
async function openFinanceRegister(task=null) {
  if(!can('finance_write'))return;
  if(!state.finance.loaded){await loadFinance();if(!state.finance.loaded||!can('finance_write'))return;}
  const registered=new Set(state.finance.invoices.map(i=>i.task_id));
  const eligible=state.tasks.filter(t=>t.skill_id==='invoice-check'&&t.status==='ready'&&!registered.has(t.id));
  state.finance.registerSource=null;
  financeDialog('Ajouter une facture validée',`<p>Choisissez un dossier relu, puis confirmez les règlements déjà connus à la date de départ du suivi. Le total de la facture ne suffit pas à connaître son solde.</p><p class="form-help">La source et le solde de départ sont figés après inscription. En cas d’erreur, demandez une reprise contrôlée ; aucune réinscription ou correction automatique n’est effectuée.</p><div class="form-grid">${financeSelect('finance-register-task','Dossier source',[['','Choisir une facture validée'],...eligible.map(t=>[t.id,t.title])])}<div id="finance-register-source" class="full form-help">Aucune source sélectionnée.</div>${financeSelect('finance-direction','Sens de la facture',[['','À sélectionner'],['receivable','À encaisser (client)'],['payable','À payer (fournisseur)']])}${financeInput('finance-opening-paid','Déjà réglé avant ce suivi',{required:true,decimal:true,help:'Indiquez explicitement 0.00 si aucun règlement n’a été reçu ou effectué.'})}${financeInput('finance-opening-date','Solde à la fin du',{required:true,type:'date',help:'Solde à la fin de cette journée ; mouvements de cette date ou antérieurs exclus.'})}${financeSelect('finance-disputed','Litige',[['unknown','Non vérifié'],['false','Absence de litige vérifiée'],['true','Litige déclaré']],'unknown')}${financeInput('finance-register-evidence','Référence de la preuve du solde',{required:true,full:true,maxlength:500})}</div><label class="checkbox-field space-top"><input type="checkbox" id="finance-opening-confirmed"> J’ai vérifié les règlements antérieurs et le sens de cette facture.</label>${eligible.length?'':'<p class="form-help">Aucun dossier éligible. Contrôlez et validez une facture avant son ajout au registre.</p>'}`,'finance-register-form','Ajouter au suivi');
  if(task&&eligible.some(t=>t.id===task.id)){$('#finance-register-task').value=task.id;await loadFinanceSource(task.id);}
}
async function loadFinanceSource(id) {
  const f=state.finance,seq=++f.sourceSeq;f.registerSource=null;
  if(!id){if($('#finance-register-source'))$('#finance-register-source').textContent='Aucune source sélectionnée.';return;}
  $('#finance-register-source').textContent='Lecture du dossier source…';
  try{const {task}=await api(`/api/tasks/${encodeURIComponent(id)}`);if(state.finance!==f||seq!==f.sourceSeq||!$('#finance-register-source'))return;f.registerSource=task;const p=task.payload||{};$('#finance-register-source').innerHTML=`<strong>${escapeHTML(p.invoice_number)} · ${financeMoney(p.total_amount,p.currency)}</strong><p>${escapeHTML(p.supplier)} → ${escapeHTML(p.customer)}<br>Échéance : ${escapeHTML(displayDate(p.due_date))} · dossier version ${Number(task.version)} · ${escapeHTML(statuses[task.status]||task.status)}</p>`;}
  catch(error){if(!sessionInterrupted(error)&&$('#finance-register-source'))$('#finance-register-source').textContent=error.message;}
}
async function financeSubmit(form,operation) {
  if(!can('finance_write')||state.finance.busy)return;
  const f=state.finance,target=$('#finance-form-error',form),button=$('button[type=submit]',form);target.textContent='';f.busy=true;button.disabled=true;
  try{await operation(f);}catch(error){if(sessionInterrupted(error))return;if(target.isConnected)target.textContent=error.message;if(error.status===409){state.finance.loaded=false;await loadFinance();if(target.isConnected){target.textContent+=' Fermez ce formulaire puis relisez les données actualisées avant de recommencer.';button.dataset.conflict='true';}}}
  finally{if(state.finance===f){f.busy=false;if(button.dataset.conflict!=='true')button.disabled=false;}}
}
async function registerFinanceInvoice(form) {
  return financeSubmit(form,async f=>{
    const task=f.registerSource;if(!task||task.status!=='ready'||task.skill_id!=='invoice-check')throw new Error('Sélectionnez un dossier de facture actuellement validé.');
    if(!$('#finance-opening-confirmed',form).checked)throw new Error('Confirmez la vérification des règlements antérieurs.');
    const disputed=$('#finance-disputed',form).value;
    await post('/api/finance/invoices/register',{task_id:task.id,task_version:task.version,direction:$('#finance-direction',form).value,opening_paid_amount:financeDecimal($('#finance-opening-paid',form).value),opening_as_of:$('#finance-opening-date',form).value,opening_confirmed:true,evidence_ref:$('#finance-register-evidence',form).value.trim(),disputed:disputed==='unknown'?'unknown':disputed==='true'});
    $('#finance-dialog').close();await loadFinance();toast('Facture ajoutée au suivi. Aucun règlement effectué.');
  });
}
function clearBankPreview() {const f=state.finance;f.preview=null;f.previewInput=null;f.previewRevision++;if($('#finance-bank-preview'))$('#finance-bank-preview').innerHTML='';}
async function readBankCSV(input) {
  if(!can('finance_write'))return;const file=input.files?.[0];if(!file)return;const epoch=state.sessionEpoch;
  clearBankPreview();
  try{if(file.size>50000)throw new Error('Le CSV doit rester sous 50 000 octets. Divisez le relevé en lots plus petits.');const content=await file.text();if(epoch!==state.sessionEpoch||!input.isConnected)return;$('#finance-csv').value=content;$('#finance-bank-error').textContent='';}catch(error){if(epoch===state.sessionEpoch&&$('#finance-bank-error'))$('#finance-bank-error').textContent=error.message;}
}
async function previewBank(form) {
  if(!can('finance_write')||state.finance.busy)return;
  const f=state.finance;clearBankPreview();const revision=f.previewRevision,body={account_ref:$('#finance-account',form).value.trim(),csv_text:$('#finance-csv',form).value};const button=$('button[type=submit]',form);button.disabled=true;f.busy=true;$('#finance-bank-error',form).textContent='';
  try{if(new Blob([JSON.stringify(body)]).size>64000||new Blob([body.csv_text]).size>50000)throw new Error('Le CSV doit rester sous 50 000 octets.');const {preview}=await post('/api/finance/bank/preview',body);if(state.finance!==f||revision!==f.previewRevision)return;f.preview=preview;f.previewInput=body;$('#finance-bank-preview',form).innerHTML=renderBankPreview();}
  catch(error){if(!sessionInterrupted(error)&&form.isConnected)$('#finance-bank-error',form).textContent=error.message;}
  finally{if(state.finance===f){f.busy=false;button.disabled=false;}}
}
async function importBank(button) {
  if(!can('finance_write')||state.finance.busy)return;
  const f=state.finance,form=$('#finance-bank-form');if(!form)return;
  const target=$('#finance-bank-error',form);target.textContent='';
  if(!f.preview||!f.previewInput||!$('#finance-import-confirmed')?.checked){target.textContent='Prévisualisez puis confirmez la vérification des lignes avant l’import.';return;}
  if(f.previewInput.account_ref!==$('#finance-account').value.trim()||f.previewInput.csv_text!==$('#finance-csv').value){clearBankPreview();target.textContent='Le contenu a changé. Prévisualisez de nouveau le CSV.';return;}
  const body={...f.previewInput,preview_digest:f.preview.preview_digest};f.busy=true;button.disabled=true;
  try{const result=await post('/api/finance/bank/import',body);clearBankPreview();$('#finance-csv',form).value='';$('#finance-csv-file',form).value='';await loadFinance();toast(`${Number(result.import.created)} mouvement(s) ajouté(s), ${Number(result.import.duplicates)} doublon(s) conservé(s) sans nouvel import.`);}
  catch(error){if(!sessionInterrupted(error)&&target.isConnected){target.textContent=error.message;if(error.status===409)clearBankPreview();}}
  finally{if(state.finance===f){f.busy=false;button.disabled=false;}}
}
function openFinanceAllocation(suggestion=null) {
  if(!can('finance_write'))return;const f=state.finance;
  const invoices=f.invoices.filter(i=>i.payment_status!=='paid'),transactions=f.transactions.filter(t=>t.remaining_amount!=='0.00');
  financeDialog('Rapprocher un mouvement',`<p>Une suggestion ne prouve pas un règlement. Vérifiez les deux pièces ; vous pouvez affecter une partie du mouvement. Aucun montant ne sera changé sans cette confirmation.</p><div class="form-grid">${financeSelect('finance-allocation-invoice','Facture',[['','À sélectionner'],...invoices.map(i=>[i.id,`${i.invoice_number} · ${financeDirection(i.direction)} · reste ${i.remaining_amount} ${i.currency}`])],suggestion?.invoice_id||'')}${financeSelect('finance-allocation-transaction','Mouvement',[['','À sélectionner'],...transactions.map(t=>[t.id,`${t.date} · ${t.reference} · ${t.amount} ${t.currency} · disponible ${t.remaining_amount}`])],suggestion?.transaction_id||'')}${financeInput('finance-allocation-amount','Montant à affecter',{required:true,decimal:true,value:suggestion?.amount||''})}${financeInput('finance-allocation-evidence','Référence de vérification',{required:true,maxlength:500})}</div><label class="checkbox-field space-top"><input id="finance-allocation-confirmed" type="checkbox"> J’ai vérifié la facture, le compte, la référence, le sens, la devise et le montant.</label>`,'finance-allocation-form','Confirmer le rapprochement');
  f.allocationInvoices=structuredCloneFinance(invoices);f.allocationTransactions=structuredCloneFinance(transactions);
}
const structuredCloneFinance=value=>JSON.parse(JSON.stringify(value));
async function confirmFinanceAllocation(form) {
  return financeSubmit(form,async f=>{
    if(!$('#finance-allocation-confirmed',form).checked)throw new Error('Confirmez votre vérification avant d’affecter ce montant.');
    const invoice=f.allocationInvoices?.find(i=>i.id===$('#finance-allocation-invoice',form).value),tx=f.allocationTransactions?.find(t=>t.id===$('#finance-allocation-transaction',form).value);
    if(!invoice||!tx)throw new Error('Sélectionnez une facture et un mouvement.');
    const body={invoice_id:invoice.id,invoice_version:invoice.version,transaction_id:tx.id,transaction_version:tx.version,amount:financeDecimal($('#finance-allocation-amount',form).value),evidence_ref:$('#finance-allocation-evidence',form).value.trim()};const signature=JSON.stringify(body);
    if(f.allocationAttempt?.signature!==signature)f.allocationAttempt={signature,key:crypto.randomUUID()};
    await post('/api/finance/allocations/confirm',{...body,idempotency_key:f.allocationAttempt.key});f.allocationAttempt=null;$('#finance-dialog').close();await loadFinance();toast('Rapprochement enregistré. Aucun mouvement bancaire exécuté.');
  });
}
function openFinanceReverse(id) {
  if(!can('finance_write'))return;const f=state.finance,a=f.allocations.find(x=>x.id===id);if(!a||a.status!=='active')return;
  const invoice=f.invoices.find(i=>i.id===a.invoice_id),tx=f.transactions.find(t=>t.id===a.transaction_id);if(!invoice||!tx)return;
  financeDialog('Annuler le rapprochement',`<p>${escapeHTML(invoice.invoice_number)} · ${financeMoney(a.amount,a.currency)}<br>${escapeHTML(tx.reference)}</p><p>Les montants disponibles seront recalculés. Le rapprochement et son annulation resteront dans l’historique ; aucune opération bancaire ne sera annulée.</p>${financeInput('finance-reverse-reason','Motif de l’annulation',{required:true,full:true,maxlength:500})}<label class="checkbox-field space-top"><input type="checkbox" id="finance-reverse-confirmed"> Je confirme l’annulation de cette affectation interne.</label>`,'finance-reverse-form','Confirmer l’annulation');
  f.reverseSnapshot={id:a.id,version:a.version,invoice_version:invoice.version,transaction_version:tx.version};
}
async function reverseFinanceAllocation(form) {
  return financeSubmit(form,async f=>{if(!$('#finance-reverse-confirmed',form).checked)throw new Error('Confirmez l’annulation de cette affectation.');const {id,...versions}=f.reverseSnapshot;await post(`/api/finance/allocations/${encodeURIComponent(id)}/reverse`,{...versions,reason:$('#finance-reverse-reason',form).value.trim()});$('#finance-dialog').close();await loadFinance();toast('Rapprochement annulé ; historique conservé.');});
}
function openFinanceFactoring() {
  if(!can('finance_simulate'))return;const options=state.finance.invoices.filter(i=>i.direction==='receivable');
  financeDialog('Calculer une simulation',`<p>Renseignez toutes les conditions examinées, y compris les frais à zéro s’ils sont effectivement nuls. Aucun taux de marché ou accord d’un financeur n’est présumé.</p><div class="form-grid">${financeSelect('finance-factor-invoice','Facture client',[['','Choisir une facture'],...options.map(i=>[i.id,`${i.invoice_number} · solde ${i.remaining_amount} ${i.currency}`])])}${financeInput('finance-funding-date','Date de l’avance envisagée',{type:'date',required:true})}${financeInput('finance-advance-rate','Pourcentage avancé (%)',{decimal:true,required:true})}${financeInput('finance-fee-rate','Commission (%)',{decimal:true,required:true})}${financeInput('finance-interest-rate','Taux d’intérêt annuel (%)',{decimal:true,required:true})}${financeInput('finance-fixed-fee','Frais fixes (devise de la facture)',{decimal:true,required:true})}${financeSelect('finance-day-basis','Base de calcul des intérêts',[['','À sélectionner'],['360','360 jours'],['365','365 jours']])}</div>`,'finance-factoring-form','Calculer la simulation');
  state.finance.factoringInvoices=structuredCloneFinance(options);
}
async function simulateFactoring(form) {
  if(!can('finance_simulate'))return;
  return financeSubmit(form,async f=>{const invoice=f.factoringInvoices?.find(i=>i.id===$('#finance-factor-invoice',form).value);if(!invoice)throw new Error('Sélectionnez la facture étudiée.');const {simulation}=await post('/api/finance/factoring/simulate',{invoice_id:invoice.id,invoice_version:invoice.version,advance_rate:financeDecimal($('#finance-advance-rate',form).value),fee_rate:financeDecimal($('#finance-fee-rate',form).value),annual_interest_rate:financeDecimal($('#finance-interest-rate',form).value),fixed_fee:financeDecimal($('#finance-fixed-fee',form).value),funding_date:$('#finance-funding-date',form).value,day_basis:Number($('#finance-day-basis',form).value)});f.simulation=simulation;f.tab='factoring';$('#finance-dialog').close();if(state.page!=='finance'){state.page='finance';location.hash='finance';}renderFinance();});
}
function openFinanceAssignment() {
  if(!can('finance_write'))return;const invoices=state.finance.invoices.filter(i=>i.direction==='receivable');
  financeDialog('Déclarer un statut de cession',`<p>Consignez uniquement une décision déjà prise hors de cet outil, avec sa preuve. Une avance reçue d’un financeur n’est pas un paiement du client. Cette saisie ne transmet aucune créance.</p><div class="form-grid">${financeSelect('finance-assignment-invoice','Facture client',[['','À sélectionner'],...invoices.map(i=>[i.id,i.invoice_number])])}${financeSelect('finance-assignment-status','Décision documentée',[['','À sélectionner'],['assigned','Cession déjà décidée'],['released','Mainlevée déjà décidée']])}${financeInput('finance-assignment-date','Date d’effet',{type:'date',required:true})}${financeInput('finance-assignment-evidence','Référence de la preuve',{required:true,maxlength:500})}${financeInput('finance-assignment-note','Note de suivi',{required:true,full:true,maxlength:500})}</div><label class="checkbox-field space-top"><input type="checkbox" id="finance-assignment-confirmed"> J’ai vérifié la décision et la preuve correspondantes.</label>`,'finance-assignment-form','Enregistrer la déclaration');state.finance.assignmentInvoices=structuredCloneFinance(invoices);
}
async function saveFinanceAssignment(form) {
  return financeSubmit(form,async f=>{if(!$('#finance-assignment-confirmed',form).checked)throw new Error('Confirmez la vérification de cette décision externe.');const invoice=f.assignmentInvoices?.find(i=>i.id===$('#finance-assignment-invoice',form).value);if(!invoice)throw new Error('Sélectionnez une facture.');await post(`/api/finance/invoices/${encodeURIComponent(invoice.id)}/assignment`,{version:invoice.version,status:$('#finance-assignment-status',form).value,effective_date:$('#finance-assignment-date',form).value,evidence_ref:$('#finance-assignment-evidence',form).value.trim(),note:$('#finance-assignment-note',form).value.trim()});$('#finance-dialog').close();await loadFinance();toast('Statut documenté enregistré. Aucune cession exécutée.');});
}
function openFinanceState(id) {
  if(!can('finance_write'))return;const invoice=state.finance.invoices.find(i=>i.id===id);if(!invoice)return;
  financeDialog('Mettre à jour le litige',`<p>${escapeHTML(invoice.invoice_number)} · ${escapeHTML(invoice.customer)}. Conservez la preuve de votre vérification. Le solde ne change pas.</p><div class="form-grid">${financeSelect('finance-state-disputed','État du litige',[['unknown','Non vérifié'],['true','Litige déclaré'],['false','Absence de litige vérifiée']],'unknown')}${financeInput('finance-state-date','Vérifié le',{type:'date',required:true})}${financeInput('finance-state-evidence','Référence de la preuve',{required:true,maxlength:500})}${financeInput('finance-state-note','Note de suivi',{required:true,maxlength:500})}</div>`,'finance-state-form','Enregistrer la vérification');state.finance.stateSnapshot={id:invoice.id,version:invoice.version};
}
async function saveFinanceState(form) {
  return financeSubmit(form,async f=>{const value=$('#finance-state-disputed',form).value;await post(`/api/finance/invoices/${encodeURIComponent(f.stateSnapshot.id)}/state`,{version:f.stateSnapshot.version,disputed:value==='unknown'?'unknown':value==='true',confirmed_on:$('#finance-state-date',form).value,evidence_ref:$('#finance-state-evidence',form).value.trim(),note:$('#finance-state-note',form).value.trim()});$('#finance-dialog').close();await loadFinance();toast('État du litige mis à jour et conservé dans l’historique.');});
}
async function exportFinance(button) {
  if(!can('finance_export'))return;button.disabled=true;
  try{const data=await api('/api/finance/export'),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));documentBlobURLs.add(url);const link=document.createElement('a');link.href=url;link.download=`admin-agent-finances-${new Date().toISOString().slice(0,10)}.json`;document.body.append(link);link.click();link.remove();setTimeout(()=>{URL.revokeObjectURL(url);documentBlobURLs.delete(url);},1000);toast('Export confidentiel du suivi téléchargé.');}catch(error){if(!sessionInterrupted(error))toast(error.message,true);}finally{button.disabled=false;}
}
document.addEventListener('submit',event=>{
  const actions={'finance-register-form':registerFinanceInvoice,'finance-bank-form':previewBank,'finance-allocation-form':confirmFinanceAllocation,'finance-reverse-form':reverseFinanceAllocation,'finance-factoring-form':simulateFactoring,'finance-assignment-form':saveFinanceAssignment,'finance-state-form':saveFinanceState};
  if(actions[event.target.id]){event.preventDefault();actions[event.target.id](event.target);}
});
document.addEventListener('input',event=>{
  if(['finance-account','finance-csv'].includes(event.target.id))clearBankPreview();
  if(event.target.closest('#finance-allocation-form')&&event.target.id!=='finance-allocation-confirmed')$('#finance-allocation-confirmed').checked=false;
  if(event.target.closest('#finance-register-form')&&event.target.id!=='finance-opening-confirmed')$('#finance-opening-confirmed').checked=false;
});
document.addEventListener('change',event=>{
  if(event.target.id==='finance-csv-file')readBankCSV(event.target);
  if(event.target.id==='finance-register-task')loadFinanceSource(event.target.value);
  for(const [formId,checkbox] of [['finance-register-form','finance-opening-confirmed'],['finance-allocation-form','finance-allocation-confirmed'],['finance-assignment-form','finance-assignment-confirmed']])if(event.target.closest('#'+formId)&&event.target.id!==checkbox)$('#'+checkbox).checked=false;
});
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action^="finance-"]');if(!button||button.disabled||state.sessionPhase!=='authenticated')return;
  const action=button.dataset.action;
  if(action==='finance-tab'){if(button.dataset.tab!=='bank')clearBankPreview();state.finance.tab=button.dataset.tab;renderFinance();}
  else if(action==='finance-refresh')await loadFinance();
  else if(action==='finance-register')await openFinanceRegister();
  else if(action==='finance-register-task'){const task=state.detail;$('#detail-dialog').close();await openFinanceRegister(task);}
  else if(action==='finance-import')await importBank(button);
  else if(action==='finance-allocate')openFinanceAllocation();
  else if(action==='finance-suggestion')openFinanceAllocation(state.finance.suggestions[Number(button.dataset.index)]);
  else if(action==='finance-reverse')openFinanceReverse(button.dataset.id);
  else if(action==='finance-factor')openFinanceFactoring();
  else if(action==='finance-assignment')openFinanceAssignment();
  else if(action==='finance-export')await exportFinance(button);
  else if(action==='finance-state')openFinanceState(button.dataset.id);
});

bootstrapSession();
