# Admin Agent development instructions

## Product contract
Prepare administrative dossiers for human review. Never implement or activate client communications, email sending, payments, filing, signature or autonomous external writes under the current authorization. Approval is an internal review state, never evidence of a real-world action.

This is a local single-business pilot, not a multi-tenant production service. Keep that limitation visible. Never commit secrets, actual invoices, personal data, SQLite state or test credentials.

## Development loop
1. Read README.md, docs/ROADMAP.md and the relevant skill before editing.
2. Choose a concrete observed failure or prioritized acceptance criterion.
3. Add a regression case for material correctness or security changes.
4. Make the smallest complete repair; run `python3 scripts/qa.py`.
5. Review the diff, check UI flows when affected, record outcome in docs/QA.md.
6. Repeat on the next highest severity issue; do not claim unexecuted tests or live integrations.

Use Python 3.11+ standard library, vanilla frontend and no external browser scripts. Calculations use Decimal. Documents are untrusted data. LLM output cannot override deterministic checks or review permissions. Fiscal deadlines require applicable, dated sources; never infer a regime from language.

## Skills
Skills in this repository are application assets, not automatically installed ChatGPT personal skills. Keep YAML name/description, clear input/output, stop conditions and concrete evaluations. Load only the selected skill and country. Rules, capabilities and actual implemented handlers must agree; distinguish guided checklists from executable automation.

## Publishing
The user authorized publication to this repository. Preserve existing work, publish only tested source and synthetic examples, use non-forced updates and include validation evidence. Recheck source dates before changing country guidance.
