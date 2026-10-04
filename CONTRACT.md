# Development contract (2026-10-04)

Two modes: a loopback-only local demonstration (Python 3.11+ standard library) and a separate Flask/Waitress production application with named accounts and mandatory TOTP. One isolated production deployment/database per client; never claim shared multi-tenant readiness or completed client go-live from code publication. UI vanilla HTML/CSS/JS. No outbound customer communications, payments, tax filings or external CRM writes. Optional LLM analysis is available for local tests only; the production entrypoint refuses AI enablement.

## Production additions and differences

- Run `python -m admin_agent.production` only behind the supplied TLS/network boundary. Required environment and CLI are documented in `docs/launch/03-DEPLOIEMENT.md`.
- GET `/api/session` bootstraps a pre-auth session and returns `{authenticated,user,csrf_token,client,scope,mode,capabilities,session?}`. Session credentials stay in Secure/HttpOnly/SameSite cookies; CSRF is kept in memory.
- POST `/api/login` requires `{username,password,otp}`. POST `/api/logout` takes `{}`. All POSTs require exact public `Origin`, current session cookie and `X-CSRF-Token`, including login.
- Admin and operator can create/update/analyze/review; reader can only read. Export requires admin. No web account provisioning. Password/MFA recovery and role changes use the protected host CLI.
- Production list/dashboard return compact summaries, excluding payload and full analysis results. GET task returns full dossier plus at most 200 latest events, `events_total` and `events_truncated`. Full business history remains in the administrator export.
- Production demo route is absent; `use_ai:true` is rejected. New writes are bounded at 100 total tasks and 20,000 business events. Analysis result size is limited to 32 KiB; oversized results are refused, never silently truncated.
- GET `/healthz` is minimal liveness; GET `/readyz` checks the database. Neither certifies client acceptance, backups or regulatory compliance.
- Unauthorized access returns 401; role/Origin/CSRF refusals return 403; quota/refusal errors remain explicit. The server rechecks mutation authorization inside the write transaction.
- See `docs/ARCHITECTURE.md` for session expiration, logging retention, isolated-instance and restore semantics.

## Production document API and import boundary

- GET `/api/documents` -> `{documents,enabled,ocr_enabled,limits}`; summaries omit binary content and full extractions.
- POST `/api/documents`: multipart with exactly one `file` and optional `language` (`eng`, `fra`, `spa`, `fra+spa+eng`); maximum 5 MiB file / 6 MiB envelope. Returns `{document}` with 201 or existing 200. Upload never starts OCR or creates a task.
- GET `/api/documents/:uuid` -> `{document}` with extraction and source references. GET `.../original` downloads the authenticated attachment with `nosniff` and `no-store`.
- POST `.../extract` `{language,force_ocr}` -> `{document}` with versioned pages, word boxes, candidates and warnings. Only configured fixed internal worker; no arbitrary endpoint. One active worker extraction, 60-second budget, maximum 5 pages.
- POST `.../create-task` `{title,description,skill_id,country,payload,extraction_version,human_verified:true,verified_fields:[...]}` requires current successful extraction and confirmation of every retained field. Allowed skills: invoice-check, receivables-followup, admin-triage, expense-review. Returns `{task,document}` with 201 or existing 200. Creates a new, unanalyzed task and immutable source linkage atomically; identical retry returns existing result.
- POST `.../reverify-expense` `{task_version,extraction_version,human_verified:true,verified_fields:["merchant","expense_date","total_amount","currency"]}` -> `{task,document}` (200). Rechecks the four current receipt facts against the linked original through explicit human confirmation. Both versions must match; the extraction must be successful. Preserves original evidence and appends up to ten `receipt_reviews`, retains observed risk flags, increments task version, clears analysis/approval and resets status to `new`. Context edits still require ordinary analysis/review. Refusals: 400 invalid input; 409 `version_conflict`, `expense_task_required`, `extraction_review_required`, `invalid_receipt_source` or `capacity_reached`. No generic update may forge this evidence.
- All document routes require authentication; writes require operator/admin, exact Origin and CSRF. Reader can inspect/download only. Originals, revisions and linkage share the client SQLite backup. Global JSON task export excludes original bytes.
- `_document_source` and `_connector_source` are reserved provenance; HTTP creation cannot forge them and edits preserve the original evidence. Reviewed-document edits record changed fields and invalidate business analysis/review as usual.
- Host-only connector CLI supports local folder, mapped CSV, Nextcloud/WebDAV and Dolibarr REST. Preview is the default. Explicit import creates only local unreviewed records, retains source hashes and refuses changed-source conflicts. No remote mutation, scheduling, mail, private-network endpoint or live account certification.

## Finance API and ledger boundary

All paths below start with `/api/finance`. Production GETs require an authenticated reader, operator or admin; `/export` requires admin. Every POST requires operator/admin, the existing Origin/CSRF/session checks and a JSON body no larger than 65,536 bytes. POST success returns 200. `/bank/preview`, `/bank/import` and `/factoring/simulate` each allow 15 requests per user per 15 minutes, in addition to the global API limit. Exports share the administrator export rate limit and reject HEAD with 405 `method_not_allowed`.

| Method/path | Body or response |
|---|---|
| GET `/summary` | Counts, amounts grouped by currency, warnings, `outbound_enabled:false` |
| GET `/invoices`, `/bank-transactions`, `/allocations` | `{invoices}`, `{transactions}`, `{allocations}` respectively |
| GET `/suggestions` | `{suggestions,manual_only,auto_allocated:false}`; never writes allocations |
| POST `/invoices/register` | `{task_id,task_version,direction,opening_paid_amount,opening_as_of,opening_confirmed:true,evidence_ref,disputed}` -> `{invoice}`; current approved `invoice-check` only; direction `receivable` or `payable` |
| POST `/bank/preview` | `{account_ref,csv_text}` -> `{preview}` including `preview_digest`, rows and new/duplicate counts |
| POST `/bank/import` | Same fields plus `preview_digest` -> `{import}`; verifies digest and commits the batch atomically |
| POST `/allocations/confirm` | `{invoice_id,invoice_version,transaction_id,transaction_version,amount,evidence_ref,idempotency_key}` -> `{allocation}` |
| POST `/allocations/:uuid/reverse` | `{version,invoice_version,transaction_version,reason}` -> `{allocation}` with preserved reversal history |
| POST `/invoices/:uuid/state` | `{version,disputed,confirmed_on,evidence_ref,note}` -> `{invoice}`; `disputed` is true, false, null or `"unknown"` |
| POST `/invoices/:uuid/assignment` | `{version,status,effective_date,evidence_ref,note}` -> `{invoice}`; `status` is `assigned` or `released`, records an existing external decision only |
| POST `/factoring/simulate` | `{invoice_id,invoice_version,advance_rate,fee_rate,annual_interest_rate,fixed_fee,funding_date,day_basis}` -> `{simulation}`; `day_basis` is integer 360 or 365 |
| GET `/export` | Confidential JSON attachment: finance `format_version:"1.0"`, invoices, transactions, allocations, original CSV import data/hashes and events |

Finance amounts/rates are decimal strings, dates ISO. CSV uses exactly `transaction_id,date,amount,currency,reference`, comma, UTF-8 (optional BOM), signed amounts and at most 200 rows/60,000 bytes. The account alias and source transaction ID form the stable import key; changed contents under that key cause 409 `bank_id_conflict`, without a partial batch. Originals, canonical row hashes and all ledger state remain inside the same SQLite backup. Limits are cumulative: 100 invoices, 1,000 transactions, 100 imports, 3,000 allocations and 10,000 finance events.

The opening balance is confirmed at the end of `opening_as_of`, is immutable, and is separate from allocations. An allocation must be positive, compatible in direction/currency, within both remaining balances and strictly after the opening date. Replaying its key returns 409 `allocation_replay`. Other explicit 409 codes include `version_conflict`, `over_allocation`, `transaction_before_opening`, `currency_mismatch`, `direction_mismatch`, `invoice_assigned`, `financing_not_payment` and `allocation_already_reversed`.

Any update or reanalysis of the registered source changes its version and blocks new allocations, assignment declarations and simulations with stale-source checks; there is no ledger refresh/rebase endpoint. Corrective reversals remain possible. The ledger never mutates the source task's `paid` field or approves it. Disputed/unknown invoices are excluded from suggestions and factoring, while a proven receipt can still be manually allocated. Assignment never counts a factor advance as debtor payment.

Factoring accepts only wholly unpaid, undisputed, unassigned receivables with a current approved source. Funding date must be today or later and before maturity; interest days are maturity minus funding date. Decimal calculations round to cents with `ROUND_HALF_UP`. Results separate nominal, advance, reserve, fees, interest, total cost and immediate net cash. Invalid scope returns 409 `factoring_blocked`; this is a model scope check, never financier eligibility. Rates are operator inputs; no external offer, financing, payment or cession occurs.

General failures retain HTTP 400 for invalid inputs, 401 for authentication, 403 for role/Origin/CSRF, 409 for state/version/capacity conflicts, 413 `payload_too_large` or `csv_too_large`, and 429 `rate_limited`. UI must preserve the distinction between a rejected action and an unknown response after a network failure, then reload before retrying mutations.

The administrator global GET `/api/export` is now `format_version:"1.1"` and includes `finance` from the same SQLite read snapshot as tasks and events. The nested finance schema remains `1.0`. Raw bank CSVs are included; original document binary content remains excluded. See [Finance and expenses](docs/launch/09-FINANCE-ET-FRAIS.md) for operational limits and client acceptance cases.

## Shared business API (full local task representations below)
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

Core implemented ids: invoice-check, receivables-followup, bookkeeping-pack, admin-triage, expense-review. Guided: deadline-watch, supplier-watch, contract-watch, hr-onboarding, compliance-watch, cash-visibility, weekly-brief. The separate finance ledger is not an implementation of the guided cash forecast skill. Backend loads catalog. Result statuses: blocked for missing mandatory fields/errors; needs_review when complete; ready only after human approval with no blockers. No frontend-only security promises.

Invoice payload: invoice_number,supplier,customer,issue_date (ISO date),due_date,net_amount,vat_rate,vat_amount,total_amount,currency,paid (boolean). Monetary inputs strings, Decimal calculations; never infer legal VAT eligibility. Receivables payload same plus disputed(boolean),last_reminder_date; totals verified before draft. Bookkeeping payload {period:'YYYY-MM',documents:[{id,type,number,date,total_amount,currency}],expected_documents?:number}. Triage accepts description without required payload, or reviewed payload.text with description as additional context. Preserved document risk flags and imported partial-payment evidence block simple financial workflows even after editing visible fields.

Expense payload requires merchant, expense_date, total_amount, currency, employee_ref, business_purpose, category (`travel|meals|lodging|office|other`), payment_method (`employee_card|company_card|cash|bank_transfer|other`), policy_ref and strict booleans payment_confirmed, paid_by_company, reimbursed, business_only, policy_confirmed. Unknown states block preparation. Optional policy_limit/policy_currency must be paired in the receipt currency. Genuine linked original and current review of merchant/date/total/currency are required; context alone cannot establish a receipt. Current duplicate checks compare merchant/date/total/currency across claimants. Company-paid, reimbursed, mixed or unconfirmed payments block this reimbursement-preparation workflow. VAT remains observed information, never an automatically recoverable amount; no reimbursement is executed.

UI requests same-origin JSON or the bounded multipart document upload. The demonstration server stays localhost-only. Production requires the separate authenticated entrypoint and one isolated deployment per client. Both bound bodies, reject cross-origin mutations and use strict enums, safe static paths and audit events. AI mode disabled by default; backend model output advisory and cannot authorize actions. Skills/resources loaded selectively with byte/token estimate cap and provenance; no context from other tasks.

Tests unittest, invoke python3 -m unittest discover -s tests -v; app python3 -m admin_agent --port 8765. README owned by root. Frontend owns web/. Backend owns admin_agent/ and backend tests. Skills author owns skills/, data/skills.json and docs/skills-architecture.md. Root owns docs, integration QA, scripts, workflow, fixtures.
