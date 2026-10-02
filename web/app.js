'use strict';

const $ = (selector, scope = document) => scope.querySelector(selector);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {page:'overview',tasks:[],skills:[],metrics:{},health:{mode:'offline'},filter:'all',query:'',country:'all',skillQuery:'',skillStatus:'all',detail:null,events:[],eventsTotal:0,eventsTruncated:false,editing:null,creationAttempt:null,loading:false,loadError:null,session:null,sessionPhase:'loading',sessionEpoch:0,csrfToken:null,sessionMessage:'',logoutUnconfirmed:false,sessionTimer:null,sessionDeadline:0,lastServerActivity:0};
const pendingRequests = new Set();
const sessionChannel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('admin-agent-session-v1') : null;
const roleNames = {admin:'Administrateur',operator:'Opérateur',reader:'Lecture seule'};
const isProduction = () => state.session?.scope === 'production_single_client';
const can = capability => state.sessionPhase === 'authenticated' && state.session?.capabilities?.[capability] === true;
const sessionInterrupted = error => error?.code === 'session_changed' || error?.code === 'auth_required';
const statuses = {new:'À analyser',needs_review:'À réviser',blocked:'À compléter',ready:'Validé',rejected:'À reprendre'};
const pageNames = {overview:'Vue d’ensemble',tasks:'Dossiers',skills:'Agents & skills',controls:'Contrôle & données'};
const icons = {'invoice-check':'▧','receivables-followup':'↗','bookkeeping-pack':'▤','admin-triage':'⌘','expense-review':'▱','deadline-watch':'◷','supplier-watch':'◇','contract-watch':'▥','hr-onboarding':'♧','compliance-watch':'◎','cash-visibility':'≋','weekly-brief':'◫'};
const api = async (url, options = {}) => {
  const controller = new AbortController();
  const epoch = state.sessionEpoch;
  const startedAt = Date.now();
  pendingRequests.add(controller);
  const timeout = setTimeout(() => controller.abort(), 90000);
  try {
    const headers = {'Content-Type':'application/json',...((options.method && options.method !== 'GET' && state.csrfToken) ? {'X-CSRF-Token':state.csrfToken} : {}),...options.headers};
    const response = await fetch(url,{...options,credentials:'same-origin',cache:'no-store',signal:controller.signal,headers});
    const body = await response.json().catch(() => ({}));
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
const toast = (message, error = false) => {const node = document.createElement('div');node.className = `toast${error ? ' error' : ''}`;node.textContent = message;$('#toast-region').append(node);setTimeout(() => node.remove(),6500);};
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
  $('.app-shell').classList.toggle('auth-mode',state.sessionPhase !== 'authenticated');
  $('#mode-badge').innerHTML = `<span class="status-dot"></span>${state.sessionPhase !== 'authenticated' ? 'Accès protégé' : aiAvailable() ? 'Analyse locale · IA disponible' : 'Contrôles locaux · IA inactive'}`;
}
function purgeSensitive() {
  state.sessionEpoch++;
  clearTimeout(state.sessionTimer);state.sessionTimer=null;state.sessionDeadline=0;state.lastServerActivity=0;
  for (const controller of pendingRequests) controller.abort();
  pendingRequests.clear();
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
    <aside class="rail" aria-label="Agents disponibles"><section class="panel"><h3>Vos agents de préparation</h3><p class="rail-lead">${core.length} skills avec contrôles exécutables</p>${core.slice(0,4).map(s=>`<div class="agent-row"><span class="agent-symbol" aria-hidden="true">${icons[s.id]||'✳'}</span><div class="agent-label">${escapeHTML(s.name)}<small>Règles locales · à vérifier</small></div><span class="status-dot" aria-hidden="true"></span></div>`).join('')}<a class="text-link rail-skills-link" href="#skills">Explorer les skills <span aria-hidden="true">→</span></a></section><div class="rail-note"><div class="note-icon" aria-hidden="true">◎</div><h3>Un copilote, avec des limites claires.</h3><p>Le mode hors ligne applique des règles déterministes. Il ne lit pas les PDF et ne remplace pas votre expert-comptable. Aucun message client n’est envoyé.</p></div></aside></div>`;
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
  $('#main').innerHTML = `${heading('Un fonctionnement que vous pouvez vérifier.','Les données, les limites et les décisions restent visibles.',false)}<div class="control-grid"><section class="panel control-card"><h2>Mode de fonctionnement</h2><p>Les contrôles locaux analysent les données saisies. Les brouillons restent dans cet espace.</p><ul class="control-list"><li><span>Espace</span><strong>${escapeHTML(state.session?.client?.name)}</strong></li><li><span>Votre accès</span><strong>${escapeHTML(roleNames[state.session?.user?.role] || 'Pilote local')}</strong></li><li><span>Analyse par défaut</span><strong>Règles locales · sans modèle IA</strong></li><li><span>IA optionnelle</span><strong>${aiAvailable()?'Configurée · activation par dossier':'Non activée'}</strong></li><li><span>Envoi d’e-mails / contacts clients</span><strong>Désactivé</strong></li><li><span>Paiements et dépôts officiels</span><strong>Désactivés</strong></li><li><span>Validation</span><strong>Humaine, dossier par dossier</strong></li></ul></section><section class="panel control-card"><h2>Vos données et votre historique</h2><p>${can('export')?'Exportez les dossiers et le journal des événements au format JSON. Cet export confidentiel contient les informations saisies.':'L’export global est réservé à l’administrateur de cet espace. Vous pouvez consulter les dossiers et leur historique selon votre accès.'}</p>${can('export')?'<button class="btn btn-primary" data-action="export"><span aria-hidden="true">↓</span> Exporter les données</button>':''}<ul class="control-list"><li><span>Dossiers enregistrés</span><strong>${state.tasks.length}</strong></li><li><span>Skills disponibles</span><strong>${state.skills.length}</strong></li><li><span>Source des indicateurs</span><strong>Données de cet espace</strong></li></ul></section>${can('demo')&&!isProduction()?'<section class="panel control-card"><h2>Explorer avec des exemples</h2><p>Ajoutez des dossiers fictifs pour découvrir les contrôles. Un second chargement ne crée pas de doublons.</p><button class="btn btn-secondary" data-action="seed">Charger la démonstration</button></section>':''}<section class="panel control-card"><h2>Périmètre actuel</h2><p>Les informations sont saisies ou fournies sous forme structurée. L’import PDF, l’OCR et les connexions aux logiciels externes restent à développer. Chaque résultat doit être relu.</p><a href="#skills" class="text-link">Voir le périmètre de chaque skill →</a></section></div><div class="control-note">${isProduction()?'Cet espace est une instance dédiée à une seule entreprise. Les comptes sont personnels et les droits contrôlés par le serveur. La validation reste une revue interne.':'Pilote local pour une seule entreprise. Utilisez le déploiement avec comptes personnels et instance dédiée avant de partager l’accès.'}</div>`;
}
function inputField(key,label,options={}) {
  return `<div class="form-field ${options.full?'full':''}"><label for="field-${key}">${label}</label><input id="field-${key}" name="${key}" type="${options.type||'text'}" ${options.inputmode?`inputmode="${options.inputmode}"`:''} ${options.placeholder?`placeholder="${escapeHTML(options.placeholder)}"`:''} value="${escapeHTML(options.value??'')}" ${options.maxlength?`maxlength="${options.maxlength}"`:''}>${options.hint?`<small>${options.hint}</small>`:''}</div>`;
}
function invoiceFields(payload={},receivable=false) {
  return `<div class="form-help">Renseignez les données de la facture. Une information manquante sera signalée lors du contrôle. Les montants sont dans la même devise ; la conformité fiscale n’est pas certifiée.</div><div class="form-grid">${inputField('invoice_number','Référence de la facture',{value:payload.invoice_number,placeholder:'FAC-2026-042'})}${inputField('currency','Devise',{value:payload.currency||'EUR',placeholder:'EUR',maxlength:3})}${inputField('supplier','Fournisseur / émetteur',{value:payload.supplier,placeholder:'Nom de l’entreprise'})}${inputField('customer','Client / destinataire',{value:payload.customer,placeholder:'Nom du client'})}${inputField('issue_date','Date d’émission',{type:'date',value:payload.issue_date})}${inputField('due_date','Date d’échéance',{type:'date',value:payload.due_date})}${inputField('net_amount','Montant hors taxes',{value:payload.net_amount,inputmode:'decimal',placeholder:'1 000,00'})}${inputField('vat_rate','Taux de TVA (%)',{value:payload.vat_rate,inputmode:'decimal',placeholder:'20'})}${inputField('vat_amount','Montant de TVA',{value:payload.vat_amount,inputmode:'decimal',placeholder:'200,00'})}${inputField('total_amount','Montant total TTC',{value:payload.total_amount,inputmode:'decimal',placeholder:'1 200,00'})}${receivable?inputField('last_reminder_date','Dernière relance (facultatif)',{type:'date',value:payload.last_reminder_date}):''}</div><div class="form-grid space-top"><div class="form-field"><label for="field-paid">La facture est-elle déjà payée ?</label><select id="field-paid" name="paid"><option value="" ${typeof payload.paid!=='boolean'?'selected':''}>Non vérifié</option><option value="true" ${payload.paid===true?'selected':''}>Oui · règlement confirmé</option><option value="false" ${payload.paid===false?'selected':''}>Non · facture non réglée</option></select><small>Choisissez une réponse après vérification du suivi.</small></div>${receivable?`<div class="form-field"><label for="field-disputed">Un litige est-il en cours ?</label><select id="field-disputed" name="disputed"><option value="" ${typeof payload.disputed!=='boolean'?'selected':''}>Non vérifié</option><option value="true" ${payload.disputed===true?'selected':''}>Oui · litige déclaré</option><option value="false" ${payload.disputed===false?'selected':''}>Non · absence de litige vérifiée</option></select></div>`:''}</div>`;
}
function renderSkillFields(skillId,payload={}) {
  const skill = skillById(skillId);
  let body;
  if (['invoice-check','receivables-followup'].includes(skillId)) body = invoiceFields(payload,skillId==='receivables-followup');
  else if (skillId==='bookkeeping-pack') body = `<div class="form-help">Ce contrôle prépare l’inventaire des pièces pour votre comptabilité. Il vérifie les données déclarées, sans lire ni certifier les documents originaux.</div><div class="form-grid">${inputField('period','Période comptable',{type:'month',value:payload.period})}${inputField('expected_documents','Nombre de pièces attendu (facultatif)',{type:'number',value:payload.expected_documents??''})}<div class="form-field full"><label for="field-documents">Liste des pièces · JSON</label><textarea id="field-documents" class="code-input" name="documents" rows="10" spellcheck="false">${escapeHTML(JSON.stringify(payload.documents||[],null,2))}</textarea><small>Chaque pièce : id, type, number, date, total_amount et currency. Utilisez « Exemple fictif » pour voir le format.</small></div></div>`;
  else body = `<div class="form-help">${skill?.status==='guided'?'Ce skill est guidé : il prépare une liste de vérifications et restera à compléter. Il n’automatise pas la démarche. Décrivez le besoin dans le champ ci-dessus.':'Décrivez la demande, les pièces disponibles et l’échéance. L’agent prépare une orientation et une liste de prochaines actions à vérifier.'}</div>`;
  const fields=['invoice_number','supplier','customer','issue_date','due_date','currency','net_amount','vat_rate','vat_amount','total_amount','paid',...(skillId==='receivables-followup'?['disputed','last_reminder_date']:[])];
  const managedFields=skillId==='bookkeeping-pack'?['period','documents','expected_documents']:['invoice-check','receivables-followup'].includes(skillId)?fields:[];
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
  renderSkillFields(skillId,payload);
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
function renderTaskDetail() {
  if(state.sessionPhase!=='authenticated'||!state.detail)return;
  const task=state.detail,result=task.result;
  const checks=result?.checks||[];
  const findings=result?.findings||[];
  const eventNames={'task.created':'Dossier créé','task.analyzed':'Analyse effectuée','task.reviewed':'Décision enregistrée','task.updated':'Dossier modifié',created:'Dossier créé',task_created:'Dossier créé',analyzed:'Analyse effectuée',task_analyzed:'Analyse effectuée',approved:'Validation enregistrée',review_approved:'Validation enregistrée',rejected:'Reprise demandée',review_rejected:'Reprise demandée',updated:'Dossier modifié',task_updated:'Dossier modifié'};
  $('#detail-dialog').innerHTML=`<div class="dialog-header"><div><div class="eyebrow">${escapeHTML(skillName(task.skill_id))}</div><h2 id="detail-dialog-title">${escapeHTML(task.title)}</h2><p>Modifié le ${escapeHTML(displayDate(task.updated_at))} · version ${Number(task.version||1)}</p></div><button class="icon-button" data-action="close" aria-label="Fermer">×</button></div><div class="dialog-body"><div class="detail-meta">${pill(task.status)}<span>${task.country==='ES'?'Espagne':'France'}</span><span>Analyse ${result?.mode==='ai'?'avec avis IA':'locale'}</span>${can('update')?'<button class="text-link" data-action="edit-task">Modifier / compléter le dossier ↗</button>':''}</div>${task.description?`<p class="detail-description">${escapeHTML(task.description)}</p>`:''}${!result?'<div class="form-help">Ce dossier n’a pas encore été analysé. Lancez les contrôles pour obtenir les points de vigilance et une préparation à relire.</div>':`<section class="result-section"><h3>Résultat du contrôle</h3><p class="result-summary">${escapeHTML(result.summary)}</p>${findings.length?`<ul class="findings">${findings.map(f=>`<li class="finding ${escapeHTML(f.severity||'info')}"><span class="finding-icon" aria-hidden="true">${f.severity==='error'?'!':f.severity==='warning'?'△':'✓'}</span><span>${escapeHTML(f.message)}${f.field?` <span class="inline-muted">(${escapeHTML(f.field)})</span>`:''}</span></li>`).join('')}</ul>`:''}${result.missing_fields?.length?`<p class="form-help">À compléter : ${result.missing_fields.map(escapeHTML).join(', ')}.</p>`:''}${checks.length?`<details class="detail-disclosure"><summary>${checks.length} point${checks.length>1?'s':''} de contrôle</summary><ul class="check-list">${checks.map(c=>`<li>${typeof c==='string'?escapeHTML(c):`${c.passed?'✓':'!'} ${escapeHTML(c.name||c.label||'Contrôle')} ${c.detail?'— '+escapeHTML(c.detail):''}`}</li>`).join('')}</ul></details>`:''}</section>${result.draft?`<section class="result-section"><div class="section-heading"><h3>Préparation à relire</h3><button class="text-link" data-action="copy-draft">Copier le texte</button></div><pre class="draft-text">${escapeHTML(result.draft)}</pre><p class="draft-warning">Brouillon interne. La validation ne déclenche ni envoi ni dépôt.</p></section>`:''}${result.ai_advice?`<section class="result-section"><h3>Avis IA · à vérifier séparément</h3><p class="result-summary">${escapeHTML(result.ai_advice.summary)}</p>${result.ai_advice.suggested_draft?`<pre class="draft-text">${escapeHTML(result.ai_advice.suggested_draft)}</pre>`:''}${result.ai_advice.questions?.length?`<ul class="check-list">${result.ai_advice.questions.map(q=>`<li>${escapeHTML(q)}</li>`).join('')}</ul>`:''}<p class="draft-warning">Cet avis ne modifie pas les contrôles bloquants et n’autorise aucune action.</p></section>`:''}`}
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
document.addEventListener('input',event=>{if(event.target.id==='task-search'){state.query=event.target.value;updateTaskList();}if(event.target.id==='skill-search'){state.skillQuery=event.target.value;updateSkillsList();}});
document.addEventListener('change',event=>{
  if(event.target.id==='task-skill')renderSkillFields(event.target.value);
  if(event.target.id==='status-filter'){state.filter=event.target.value;updateTaskList();}
  if(event.target.id==='country-filter'){state.country=event.target.value;updateTaskList();}
  if(event.target.id==='skill-status-filter'){state.skillStatus=event.target.value;updateSkillsList();}
  if(event.target.id==='ai-consent')$('#analyze-ai-button').disabled=!event.target.checked;
});
document.addEventListener('submit',event=>{if(event.target.id==='login-form'){event.preventDefault();login(event.target);}else if(event.target.id==='task-form'){event.preventDefault();saveTask(event.target);}});
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
  else if(action==='task')await openTask(button.dataset.id);
  else if(action==='skill')openSkill(button.dataset.id);
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
bootstrapSession();
