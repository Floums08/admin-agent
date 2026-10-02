# Development contract (2026-10-02)

Local pilot for a single business; Python 3.11+ standard library HTTP API + SQLite, no dependencies. UI vanilla HTML/CSS/JS. Never claim production/multitenant readiness. No outbound customer communications, payments, tax filings or external CRM writes. Optional LLM analysis may send explicitly submitted text to configured provider only when operator enables it. Offline deterministic mode must be clearly labelled.

## API
- GET /api/health -> {status, mode, outbound_enabled:false}
- GET /api/dashboard -> {metrics:{total,needs_review,blocked,ready},tasks:[Task],recent_events:[],mode}
- GET /api/skills -> {skills:[{id,name,description,priority,agent,inputs:[],outputs:[],status,body}]}
- GET /api/tasks -> {tasks:[Task]}
- POST /api/tasks {title,description,skill_id,country:'FR'|'ES',payload:object,idempotency_key?} -> {task:Task} (201 or existing 200)
- GET /api/tasks/:id -> {task:Task,events:[]}
- POST /api/tasks/:id/analyze {use_ai:false} -> {task:Task}
- POST /api/tasks/:id/review {decision:'approve'|'reject',note:string,version:int} -> {task:Task}. Approve reviews displayed output version only; NEVER sends or files. Reject stale versions with 409.
- POST /api/tasks/:id/update {title?,description?,payload?,version:int} -> {task:Task}. Clears result and approval, resets status to new; optimistic version lock.
- POST /api/demo/seed {} -> {created:number} (idempotent)
- GET /api/export -> JSON download of tasks, events, skills metadata, format_version.

Task {id,title,description,skill_id,country,payload,status:'new'|'needs_review'|'blocked'|'ready'|'rejected',created_at,updated_at,result:null|{summary,findings:[{severity:'info'|'warning'|'error',message,field?}],missing_fields:[],draft:string,checks:[],mode:'offline'|'ai',context?:object},version:number}.

Catalog: data/skills.json {skills:[{id,name,description,priority:'P0'|'P1'|'P2',agent,inputs:[],outputs:[],status:'implemented'|'guided',path:'skills/<id>/SKILL.md'}]}.

Core implemented ids: invoice-check, receivables-followup, bookkeeping-pack, admin-triage. Guided: expense-review, deadline-watch, supplier-watch, contract-watch, hr-onboarding, compliance-watch, cash-visibility, weekly-brief. Backend loads catalog. Result statuses: blocked for missing mandatory fields/errors; needs_review when complete; ready only after human approval with no blockers. No frontend-only security promises.

Invoice payload: invoice_number,supplier,customer,issue_date (ISO date),due_date,net_amount,vat_rate,vat_amount,total_amount,currency,paid (boolean). Monetary inputs strings, Decimal calculations; never infer legal VAT eligibility. Receivables payload same plus disputed(boolean),last_reminder_date; totals verified before draft. Bookkeeping payload {period:'YYYY-MM',documents:[{id,type,number,date,total_amount,currency}],expected_documents?:number}. Triage accepts description without required payload.

UI requests same-origin JSON. Server localhost only by default, bounded bodies, rejects cross-origin mutations, strict enums, safe static paths, no debug secrets, audit events. Document auth/tenant isolation missing for production. AI mode disabled by default; backend model output advisory and cannot authorize actions. Skills/resources loaded selectively with byte/token estimate cap and provenance; no context from other tasks.

Tests unittest, invoke python3 -m unittest discover -s tests -v; app python3 -m admin_agent --port 8765. README owned by root. Frontend owns web/. Backend owns admin_agent/ and backend tests. Skills author owns skills/, data/skills.json and docs/skills-architecture.md. Root owns docs, integration QA, scripts, workflow, fixtures.
