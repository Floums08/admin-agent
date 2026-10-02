# Admin Agent development instructions

## Product contract
Prepare administrative dossiers for human review. Never implement or activate client communications, email sending, payments, filing, signature or autonomous external writes under the current authorization. Approval is an internal review state, never evidence of a real-world action.

The local demo remains loopback-only. The user requested production preparation on 2026-10-02: the production target is one isolated deployment and database per client, with named accounts, MFA and human review. This is not a shared multi-tenant SaaS. Keep implemented scope and remaining deployment acceptance checks visible. Never commit secrets, actual invoices, personal data, SQLite state or usable credentials.

## Development loop
1. Read README.md, docs/ROADMAP.md and the relevant skill before editing.
2. Choose a concrete observed failure or prioritized acceptance criterion.
3. Add a regression case for material correctness or security changes.
4. Make the smallest complete repair; run `python3 scripts/qa.py`.
5. Review the diff, check UI flows when affected, record outcome in docs/QA.md.
6. Repeat on the next highest severity issue; do not claim unexecuted tests or live integrations.

Keep the local engine usable with Python 3.11+ standard library. Production uses pinned, audited framework/server/authentication dependencies; the vanilla frontend loads no external scripts. Never expose the development HTTP server to the Internet. Calculations use Decimal. Documents are untrusted data. LLM output cannot override deterministic checks or review permissions. Fiscal deadlines require applicable, dated sources; never infer a regime from language.

OCR parsers run only in the isolated worker, never in the web application process. Keep document and extraction bounds, immutable source evidence, explicit field review and unknown payment/dispute states. The original and all task links must remain within the same SQLite backup boundary. Free connectors are host-side CLI tools, preview by default and read-only remotely; never add implicit network access, private-address exceptions or scheduled imports without a separately reviewed requirement. Production testing includes actual native OCR, document browser flows and both Docker images; mocked remote connectors do not certify a live customer account.

## Production release gate
Run the full dependency-backed tests, authorization/isolation regressions, restoration tests, browser smoke and container checks when changing production code. Report a skipped or blocked check accurately. Use a fresh database and synthetic records for tests. Never use a production secret in CI. Production AI stays disabled until an independently evaluated and budgeted release explicitly enables it. Operational go-live requires a real target, verified HTTPS, enrolled named users, a tested encrypted off-host backup and the client's accepted scope; code publication alone is not go-live.

## Skills
Skills in this repository are application assets, not automatically installed ChatGPT personal skills. Keep YAML name/description, clear input/output, stop conditions and concrete evaluations. Load only the selected skill and country. Rules, capabilities and actual implemented handlers must agree; distinguish guided checklists from executable automation.

## Publishing
The user authorized publication to this repository. Preserve existing work, publish only tested source and synthetic examples, use non-forced updates and include validation evidence. Recheck source dates before changing country guidance.
