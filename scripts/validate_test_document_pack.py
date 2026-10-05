"""Validate an authored synthetic pack through real OCR and review workflows.

The manifest is the independently authored answer key. It is never derived from
OCR output. Binary parsing runs in the actual bounded worker subprocess; this
local rehearsal is not a claim that a production container was deployed.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import date, datetime, time, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from admin_agent.documents import DocumentStore, MAX_FILE_BYTES, validate_extraction
from admin_agent.errors import AppError
from admin_agent.finance import FinanceStore
from admin_agent.ocr_worker import _isolated_extract
from admin_agent.server import analyze_task
from admin_agent.storage import Store, audit_actor


INVOICE_FACTS = {"invoice_number", "supplier", "customer", "issue_date", "due_date", "net_amount", "vat_rate", "vat_amount", "total_amount", "currency"}
EXPENSE_FACTS = {"merchant", "expense_date", "total_amount", "currency", "vat_amount"}
HUMAN_STATES = {"paid", "disputed", "paid_by_company", "reimbursed", "business_only", "policy_confirmed", "payment_confirmed", "employee_ref", "policy_ref", "policy_limit"}


class PackError(ValueError):
    pass


def _read(pack, relative, limit):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise PackError("Pack references must be relative paths without parent traversal.")
    source = pack / path
    if any(item.is_symlink() for item in (source, *source.parents)) or not source.is_file():
        raise PackError("Pack source must be a regular file without symbolic links.")
    with source.open("rb") as stream:
        data = stream.read(limit + 1)
    if not data or len(data) > limit:
        raise PackError("Pack source is empty or exceeds its size limit.")
    return data


def _require(condition, message):
    if not condition:
        raise PackError(message)


class RealWorker:
    def __init__(self):
        self.extractions = []

    def extract(self, content, media, language, force=False):
        result = _isolated_extract(content, media, language, force)
        result = validate_extraction(result, media)
        self.extractions.append(result)
        return result


def _clock(as_of):
    class PackDate(date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(as_of)
    class PackDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            fixed = datetime.combine(date.fromisoformat(as_of), time(12), timezone.utc)
            return fixed.astimezone(tz) if tz is not None else fixed.replace(tzinfo=None)
    stack = ExitStack()
    stack.enter_context(patch("admin_agent.engine.date", PackDate))
    stack.enter_context(patch("admin_agent.finance.date", PackDate))
    stack.enter_context(patch("admin_agent.storage.datetime", PackDateTime))
    return stack


def _ocr_comparison(case, extraction):
    fields = EXPENSE_FACTS if case["kind"] == "expense" else INVOICE_FACTS
    expected = {field: value for field, value in case["payload"].items() if field in fields}
    candidates = extraction["candidates"]
    comparison = {"correct": [], "missing": [], "different": [], "unexpected": [], "expected_count": len(expected)}
    for field, value in expected.items():
        if field not in candidates:
            comparison["missing"].append({"field": field, "expected": value})
        elif candidates[field]["value"] != value:
            comparison["different"].append({"field": field, "expected": value, "observed": candidates[field]["value"]})
        else:
            comparison["correct"].append(field)
    for field in fields - set(expected):
        if field in candidates:
            comparison["unexpected"].append({"field": field, "observed": candidates[field]["value"]})
    _require(not (set(candidates) & HUMAN_STATES), "OCR proposed an unauthorised human/payment state.")
    for value in candidates.values():
        _require(value["quote"] in extraction["pages"][value["page"] - 1]["text"], "Candidate evidence is absent from its cited page.")
    comparison["manual_corrections_or_completions"] = len(comparison["missing"]) + len(comparison["different"])
    comparison["all_authored_fields_recognized_exactly"] = not comparison["missing"] and not comparison["different"] and not comparison["unexpected"]
    return comparison


def _case(store, documents, pack, case, prior):
    required = {"id", "kind", "file", "format", "language", "skill_id", "country", "payload", "expected", "title"}
    _require(isinstance(case, dict) and required <= set(case), "Case schema is incomplete.")
    _require(case["kind"] in {"invoice", "expense"}, "Unsupported synthetic document kind.")
    _require(case["format"] in {"pdf", "png"}, "Unsupported synthetic document format.")
    _require(isinstance(case["payload"], dict), "Each case needs an independently authored reviewed payload.")
    media = "application/pdf" if case["format"] == "pdf" else "image/png"
    content = _read(pack, case["file"], MAX_FILE_BYTES)
    digest = hashlib.sha256(content).hexdigest()
    if "sha256" in case:
        _require(digest == case["sha256"], "Document checksum differs from its manifest.")
    document, created = documents.add(content, Path(case["file"]).name, media, case["language"])
    record = {"id": case["id"], "file": case["file"], "kind": case["kind"], "sha256": digest, "document_id": document["id"],
              "original_created": created, "passed": True, "expected_analysis_status": case["expected"]["analysis_status"]}
    if case.get("duplicate_of") and case.get("duplicate_kind", "exact") == "exact":
        target = prior.get(case.get("duplicate_of"))
        _require(target is not None and not created and target["document_id"] == document["id"], "Expected original-document deduplication did not occur.")
        _require(digest == target["sha256"], "Exact duplicate does not contain identical bytes.")
        record.update(task_id=target["task_id"], analysis_status=target["analysis_status"], duplicate_verified=True,
                      extraction_reused=True, note="Original exact déjà présent : aucun nouveau dossier ni extraction créée.")
        return record
    _require(created, "Unexpected exact duplicate; every non-copy case must have distinct source bytes.")
    document = documents.extract(document["id"], {"version": 0, "language": case["language"]})
    extraction = document["extraction"]
    record["ocr"] = _ocr_comparison(case, extraction)
    record["page_methods"] = [page["method"] for page in extraction["pages"]]
    if case["format"] == "png":
        _require(record["page_methods"] == ["ocr"], "PNG did not exercise actual optical recognition.")
    task, _, created_task = documents.create_task(document["id"], {
        "title": case["title"], "description": "Exercice synthétique : revue explicite à partir du corrigé indépendant, sans action externe.",
        "skill_id": case["skill_id"], "country": case["country"], "payload": case["payload"],
        "extraction_version": document["extraction_version"], "human_verified": True, "verified_fields": sorted(case["payload"]),
    })
    _require(created_task and task["status"] == "new", "Document review did not create an unreviewed task.")
    analyzed = analyze_task(store, task)
    result = analyzed["result"]
    failed_checks = sorted(check["name"] for check in result["checks"] if not check["passed"])
    expected_checks = sorted(case["expected"].get("check_ids", []))
    record.update(task_id=task["id"], analysis_status=analyzed["status"], failed_checks=failed_checks,
                  missing_fields=result["missing_fields"], findings=result["findings"], outbound_executed=result["outbound_executed"])
    _require(analyzed["status"] == case["expected"]["analysis_status"], "Reviewed workflow status differs from independently authored expectation.")
    _require(failed_checks == expected_checks, "Failed check IDs differ from independently authored expectation.")
    _require(result["outbound_executed"] is False, "Synthetic workflow claims an external action.")
    if analyzed["status"] == "blocked":
        _require(not result["draft"], "A blocked synthetic case produced a draft.")
        try:
            store.review(task["id"], "approve", "La validation d'un blocage doit être refusée", analyzed["version"])
        except AppError:
            record["blocked_approval_refused"] = True
        else:
            raise PackError("Blocked case was internally approved.")
    return record


def _finance(store, finance, pack, cases, records, bank):
    """Exercise separately authored banking expectations; never infer matches."""
    if not bank:
        return {"executed": False, "reason": "No authored banking scenarios in the manifest."}
    scenarios = bank["expected_scenarios"]
    _require([item["id"] for item in scenarios] == [f"B{i:02}" for i in range(1, 10)], "Bank answer key must define B01 through B09 in order.")
    csv_bytes = _read(pack, bank["file"], 60_000)
    request = {"account_ref": bank["account_ref"], "csv_text": csv_bytes.decode("utf-8")}
    registered = {}
    source_tasks = {}
    for case in cases:
        if "finance" not in case:
            continue
        task = store.get(records[case["id"]]["task_id"])
        _require(task["status"] == "needs_review", "Financial source did not pass the reviewed invoice workflow.")
        task = store.review(task["id"], "approve", "Validation synthétique des valeurs du corrigé", task["version"])
        source_tasks[task["id"]] = task
        registered[case["id"]] = finance.register_invoice({"task_id": task["id"], "task_version": task["version"],
            **case["finance"], "opening_confirmed": True})["id"]
    _require(len(registered) == 7, "Expected seven valid financial invoices, excluding blocked originals and the exact copy.")

    def invoice(case_id):
        return next(item for item in finance.list_invoices() if item["id"] == registered[case_id])

    def transaction(external_id):
        return next(item for item in finance.list_transactions() if item["transaction_id"] == external_id)

    def balances():
        return {"invoices": finance.list_invoices(), "transactions": finance.list_transactions(), "allocations": finance.list_allocations()}

    def refusal(operation, code):
        before = balances()
        try:
            operation()
        except AppError as exc:
            _require(exc.code == code, f"Expected refusal {code}, observed {exc.code}.")
        else:
            raise PackError(f"Expected refusal {code} did not occur.")
        _require(balances() == before, f"Refused operation {code} changed financial balances/history.")
        return code

    def allocate_request(case_id, external_id, amount):
        inv, tx = invoice(case_id), transaction(external_id)
        return {"invoice_id": inv["id"], "invoice_version": inv["version"], "transaction_id": tx["id"],
                "transaction_version": tx["version"], "amount": amount,
                "evidence_ref": "PREUVE-FICTIVE-VALIDATEUR-" + external_id, "idempotency_key": str(uuid.uuid4())}

    initial_preview = finance.preview_bank(request)
    _require(not finance.list_transactions(), "Bank preview wrote transactions.")
    first_import = finance.import_bank({**request, "preview_digest": initial_preview["preview_digest"]})
    _require(first_import["outbound_executed"] is False, "Bank import claims an external action.")
    _require(not finance.list_allocations(), "Bank import created an automatic allocation.")
    report = {"executed": True, "bank_sha256": hashlib.sha256(csv_bytes).hexdigest(), "registered_invoice_count": len(registered),
              "initial_import": {key: first_import[key] for key in ("created", "duplicates", "outbound_executed")}, "scenarios": []}
    successful_requests = []
    for scenario in scenarios:
        expected = scenario["expected"]
        row = {"id": scenario["id"], "passed": True}
        case_ids, transaction_ids = scenario["invoice_case_ids"], scenario["transaction_ids"]
        if "allocation_steps" in expected:
            row["steps"] = []
            for step in expected["allocation_steps"]:
                payload = allocate_request(case_ids[0], step["transaction_id"], step["amount"])
                allocation = finance.confirm_allocation(payload)
                successful_requests.append((payload, allocation, case_ids[0], step["transaction_id"]))
                updated = invoice(case_ids[0])
                observed = {key: updated[key] for key in ("payment_status", "paid_amount", "remaining_amount")}
                _require(all(observed[key] == step[key] for key in observed), "Allocation did not produce the authored partial/paid balance.")
                _require(transaction(step["transaction_id"])["remaining_amount"] == "0.00", "Confirmed bank amount was not fully consumed.")
                row["steps"].append({"transaction_id": step["transaction_id"], "amount": allocation["amount"], **observed})
        elif "allocation_error_code" in expected:
            tx = transaction(transaction_ids[0])
            payload = allocate_request(case_ids[0], transaction_ids[0], tx["remaining_amount"])
            row["refusal"] = refusal(lambda: finance.confirm_allocation(payload), expected["allocation_error_code"])
            inv = invoice(case_ids[0])
            for field in ("remaining_amount", "paid_amount", "overdue", "days_overdue"):
                if field in expected:
                    _require(inv[field] == expected[field], "Refused match changed or misrepresented invoice " + field + ".")
                    row[field] = inv[field]
            if "allocated_amount" in expected:
                _require(transaction(transaction_ids[0])["allocated_amount"] == expected["allocated_amount"], "Refused match allocated a bank amount.")
        elif "manual_only_reason" in expected:
            tx = transaction(transaction_ids[0])
            suggestions = finance.suggestions()
            selected = [item for item in suggestions["suggestions"] if item["transaction_id"] == tx["id"]]
            manual = [item for item in suggestions["manual_only"] if item["transaction_id"] == tx["id"]]
            _require(len(selected) == expected["suggestion_count"] and suggestions["auto_allocated"] is False, "Amount-only ambiguous match produced an automatic suggestion/allocation.")
            _require(len(manual) == 1 and manual[0]["reason"] == expected["manual_only_reason"], "Ambiguous movement lacks its expected manual-only explanation.")
            _require(set(manual[0]["candidate_invoice_ids"]) == {registered[key] for key in expected["candidate_invoice_cases"]}, "Amount-only ambiguity has the wrong candidate invoices.")
            _require(tx["allocated_amount"] == expected["allocated_amount"], "Ambiguous bank movement was allocated.")
            row.update(suggestion_count=len(selected), manual_only_reason=manual[0]["reason"], candidate_invoice_cases=expected["candidate_invoice_cases"], allocated_amount=tx["allocated_amount"])
        elif "factoring_error_code" in expected:
            inv, tx = invoice(case_ids[0]), transaction(transaction_ids[0])
            _require(inv["disputed"] is expected["disputed"], "Dispute assertion was lost.")
            selected = [item for item in finance.suggestions()["suggestions"] if item["transaction_id"] == tx["id"]]
            _require(len(selected) == expected["suggestion_count"] and tx["allocated_amount"] == expected["allocated_amount"], "Disputed invoice produced a suggestion or allocation.")
            inputs = {key: value for key, value in bank["simulate_inputs"].items() if key != "invoice_case_id"}
            row["refusal"] = refusal(lambda: finance.simulate_factoring({**inputs, "invoice_id": inv["id"], "invoice_version": inv["version"]}), expected["factoring_error_code"])
            row.update(disputed=inv["disputed"], suggestion_count=len(selected), allocated_amount=tx["allocated_amount"])
        elif "repeat_import_created" in expected:
            preview = finance.preview_bank(request)
            before = balances()
            repeat = finance.import_bank({**request, "preview_digest": preview["preview_digest"]})
            _require(first_import["created"] == expected["first_import_created"] and repeat["created"] == expected["repeat_import_created"] and repeat["duplicates"] == expected["repeat_import_duplicates"], "Bank repeat import did not preserve authored deduplication counts.")
            _require(balances() == before, "Bank repeat import changed existing transactions or allocations.")
            row.update(first_import_created=first_import["created"], repeat_import_created=repeat["created"], repeat_import_duplicates=repeat["duplicates"])
        elif "net_cash" in expected:
            inv = invoice(case_ids[0])
            inputs = {key: value for key, value in bank["simulate_inputs"].items() if key != "invoice_case_id"}
            before = balances()
            simulated = finance.simulate_factoring({**inputs, "invoice_id": inv["id"], "invoice_version": inv["version"]})
            _require(all(simulated[key] == value for key, value in expected.items() if key != "paid_amount"), "Factoring simulation differs from independently calculated amounts.")
            _require(invoice(case_ids[0])["paid_amount"] == expected["paid_amount"] and balances() == before, "Factoring simulation changed invoice balances or created allocations.")
            _require(simulated["indicative"] is True and simulated["external_offer"] is False and simulated["outbound_executed"] is False, "Factoring simulation implies an external offer/action.")
            row["simulation"] = simulated
        else:
            raise PackError("Unsupported authored bank scenario " + scenario["id"])
        report["scenarios"].append(row)

    # Independent negative checks beyond the answer key: source replay, changed
    # bank identity and reversal cannot silently duplicate or destroy balances.
    first_request, allocation, case_id, external_id = successful_requests[0]
    report["allocation_replay"] = refusal(lambda: finance.confirm_allocation(first_request), "allocation_replay")
    conflict = {"account_ref": request["account_ref"], "csv_text": _read(pack, "03_banque/02_releve_conflit.csv", 60_000).decode("utf-8")}
    report["bank_changed_identity"] = refusal(lambda: finance.preview_bank(conflict), "bank_id_conflict")
    report["bank_changed_after_preview"] = refusal(lambda: finance.import_bank({**conflict, "preview_digest": initial_preview["preview_digest"]}), "preview_changed")
    # Use the real digest parser to explicitly exercise commit-time identity
    # conflict too. No source data is changed or written by this parsing step.
    _, conflict_digest = finance._parse_bank(conflict)
    report["bank_changed_identity_commit"] = refusal(lambda: finance.import_bank({**conflict, "preview_digest": conflict_digest}), "bank_id_conflict")
    inv, tx = invoice(case_id), transaction(external_id)
    reversed_item = finance.reverse_allocation(allocation["id"], {"version": allocation["version"], "invoice_version": inv["version"],
        "transaction_version": tx["version"], "reason": "Contrepassation synthétique contrôlée puis nouvelle confirmation"})
    reversed_invoice = invoice(case_id)
    _require(reversed_item["status"] == "reversed" and reversed_invoice["paid_amount"] == "800.00" and reversed_invoice["remaining_amount"] == "400.00", "Reversal did not restore the known 400 EUR balance.")
    current_tx = transaction(external_id)
    _require(current_tx["allocated_amount"] == "0.00" and current_tx["remaining_amount"] == "400.00", "Reversal did not free the original bank amount.")
    refusal(lambda: finance.reverse_allocation(allocation["id"], {"version": reversed_item["version"], "invoice_version": reversed_invoice["version"],
        "transaction_version": current_tx["version"], "reason": "Le rejeu doit être refusé"}), "allocation_already_reversed")
    finance.confirm_allocation(allocate_request(case_id, external_id, "400.00"))
    _require(invoice(case_id)["remaining_amount"] == "0.00", "Reconfirmation after reversal did not restore the settled invoice.")
    report["reversal"] = {"history_preserved": True, "remaining_after_reversal": "400.00", "remaining_after_reconfirmation": "0.00", "replay_refused": True}
    _require(all(store.get(task_id) == source for task_id, source in source_tasks.items()), "Bank/factoring workflows changed a reviewed source task.")
    report.update(source_tasks_unchanged=True, final_transactions=len(finance.list_transactions()),
                  active_allocations=sum(item["status"] == "active" for item in finance.list_allocations()), outbound_executed=False)
    return report


def validate(pack, progress=None):
    pack = Path(pack).absolute()
    manifest = json.loads(_read(pack, "04_corrige/attendus.json", 1024 * 1024))
    _require(manifest.get("schema_version") == 1 and manifest.get("synthetic") is True, "Only explicitly synthetic v1 packs can be rehearsed.")
    as_of = manifest.get("as_of")
    date.fromisoformat(as_of)
    cases = manifest.get("cases")
    _require(isinstance(cases, list) and len(cases) == 18, "Expected exactly 18 authored document cases.")
    _require(len({case["id"] for case in cases}) == 18, "Case identifiers must be unique.")
    _require(sum(case["kind"] == "invoice" for case in cases) == 10 and sum(case["kind"] == "expense" for case in cases) == 8, "Expected 10 invoices and 8 receipts.")
    report = {"schema_version": 1, "synthetic": True, "as_of": as_of,
              "validation_scope": "Real bounded OCR subprocess and local synthetic review workflows; not client OCR accuracy or production hosting acceptance.",
              "review_uses_authored_truth": True, "external_accounts_used": False, "outbound_executed": False,
              "cases": [], "errors": []}
    worker = RealWorker()
    with tempfile.TemporaryDirectory(prefix="admin-agent-pack-validation-") as temp, _clock(as_of):
        store = Store(Path(temp) / "synthetic.sqlite3", max_tasks=100, max_events=20000, max_result_bytes=32768)
        with store.connection() as con:
            con.execute("CREATE TABLE instance_identity(singleton INTEGER PRIMARY KEY,client_id TEXT,client_name TEXT,schema_version INTEGER)")
            con.execute("INSERT INTO instance_identity VALUES(1,'synthetic-pack','Pack synthétique indépendant',1)")
        documents = DocumentStore(store, worker)
        finance = FinanceStore(store)
        actor = audit_actor.set("synthetic-pack-validator")
        try:
            records = {}
            for case in cases:
                if progress:
                    progress(case["id"])
                try:
                    record = _case(store, documents, pack, case, records)
                    records[case["id"]] = record
                except Exception as exc:
                    record = {"id": case.get("id"), "file": case.get("file"), "passed": False,
                              "error": str(exc) if isinstance(exc, (PackError, AppError)) else type(exc).__name__}
                    report["errors"].append({"stage": "document", **record})
                report["cases"].append(record)
            # A later, visually distinct receipt must invalidate an earlier
            # same-economics expense as well, including across two employees.
            report["duplicate_rechecks"] = []
            for case in cases:
                if case.get("duplicate_kind") == "logical" and case["kind"] == "expense":
                    ids = [case["id"], case["duplicate_of"]]
                    for identifier in ids:
                        try:
                            task = store.get(records[identifier]["task_id"])
                            task = analyze_task(store, task)
                            _require(task["status"] == "blocked" and any(item.get("field") == "expense_duplicates" for item in task["result"]["findings"]), "Logical receipt duplicate did not block both affected tasks.")
                            report["duplicate_rechecks"].append({"id": identifier, "status": task["status"], "passed": True})
                        except Exception as exc:
                            report["errors"].append({"stage": "duplicate_recheck", "id": identifier, "error": str(exc) if isinstance(exc, (PackError, AppError)) else type(exc).__name__})
            try:
                report["finance"] = _finance(store, finance, pack, cases, records, manifest.get("bank"))
            except Exception as exc:
                report["errors"].append({"stage": "finance", "error": str(exc) if isinstance(exc, (PackError, AppError)) else type(exc).__name__})
            report["totals"] = {"physical_document_cases": len(cases), "unique_originals": len(documents.list()),
                                "real_worker_extractions": len(worker.extractions), "tasks": len(store.list()),
                                "case_checks_passed": sum(record.get("passed", False) for record in report["cases"])}
        finally:
            audit_actor.reset(actor)
    comparisons = [case["ocr"] for case in report["cases"] if "ocr" in case]
    report["ocr_observations"] = {"expected_authored_fields": sum(item["expected_count"] for item in comparisons),
                                  "correct_exact_values": sum(len(item["correct"]) for item in comparisons),
                                  "missing_values": sum(len(item["missing"]) for item in comparisons),
                                  "different_values": sum(len(item["different"]) for item in comparisons),
                                  "unexpected_values": sum(len(item["unexpected"]) for item in comparisons),
                                  "interpretation": "Synthetic pack only. Manual review applies authored values; workflow success is not a claim that every field was recognized automatically."}
    report["passed"] = not report["errors"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, help="Pack containing 04_corrige/attendus.json and the 18 document cases")
    parser.add_argument("--report", help="Optional JSON report output; no database is retained")
    args = parser.parse_args(argv)
    try:
        report = validate(args.pack, progress=lambda case_id: print("Validation " + case_id, file=sys.stderr, flush=True))
        text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.report:
            path = Path(args.report)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            if os.name == "posix":
                path.chmod(0o600)
            print(json.dumps({"passed": report["passed"], "totals": report["totals"], "errors": report["errors"], "report": str(path)}, ensure_ascii=False))
        else:
            print(text, end="")
        return 0 if report["passed"] else 1
    except Exception as exc:
        print(json.dumps({"passed": False, "error": str(exc) if isinstance(exc, (PackError, AppError)) else type(exc).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
