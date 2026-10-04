"""Independent finance adversarial cases. Synthetic records and local SQLite only.

These tests exercise financial invariants rather than model quality, a bank account,
or a financing provider. An internal approval is never an external operation.
"""
from datetime import date, timedelta
from pathlib import Path
import tempfile
import threading
import unittest

from admin_agent.errors import AppError
from admin_agent.documents import DocumentStore
from admin_agent.engine import analyze, result_status
from admin_agent.server import analyze_task
from admin_agent.storage import Store, audit_guard


TODAY = date.today()


def day(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


def invoice_payload(reference="QA-FACT-001", total="120.00", currency="EUR"):
    return {"invoice_number": reference, "supplier": "Entreprise synthétique",
            "customer": "Client synthétique", "issue_date": day(-60), "due_date": day(30),
            "net_amount": "100.00", "vat_rate": "20", "vat_amount": "20.00",
            "total_amount": total, "currency": currency, "paid": False}


class IndependentLedgerReview(unittest.TestCase):
    def setUp(self):
        from admin_agent.finance import FinanceStore
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "qa.sqlite3")
        with self.store.connection() as con:
            con.execute("CREATE TABLE instance_identity(singleton INTEGER PRIMARY KEY,client_id TEXT,client_name TEXT,schema_version INTEGER)")
            con.execute("INSERT INTO instance_identity VALUES(1,'qa-finance','Synthetic QA finance',1)")
        self.finance = FinanceStore(self.store)
        self.counter = 0

    def task(self, reference=None, currency="EUR"):
        self.counter += 1
        reference = reference or f"QA-FACT-{self.counter:03d}"
        task, _ = self.store.create({"title": "Facture synthétique " + reference, "description": "QA interne uniquement",
                                     "country": "FR", "skill_id": "invoice-check", "payload": invoice_payload(reference, currency=currency)})
        analyzed = analyze_task(self.store, task)
        self.assertEqual("needs_review", analyzed["status"])
        return self.store.review(task["id"], "approve", "Contrôle synthétique effectué", analyzed["version"])

    def register(self, task=None, direction="receivable", opening="0.00", disputed=False):
        task = task or self.task()
        return self.finance.register_invoice({"task_id": task["id"], "task_version": task["version"], "direction": direction,
                                              "opening_paid_amount": opening, "opening_as_of": day(-10), "opening_confirmed": True,
                                              "evidence_ref": "SYNTHETIC-OPENING-001", "disputed": disputed})

    def import_rows(self, rows, account="synthetic-account"):
        data = {"account_ref": account, "csv_text": "transaction_id,date,amount,currency,reference\n" + "\n".join(rows) + "\n"}
        preview = self.finance.preview_bank(data)
        self.finance.import_bank(dict(data, preview_digest=preview["preview_digest"]))
        return self.finance.list_transactions()

    def transaction(self, amount="120.00", currency="EUR", source_id="bank-001", reference="QA-FACT-001", when=None):
        existing = {row["id"] for row in self.finance.list_transactions()}
        rows = self.import_rows([f"{source_id},{when or day(-1)},{amount},{currency},{reference}"])
        return next(row for row in rows if row["id"] not in existing)

    def allocation_data(self, invoice, transaction, amount="120.00", key="qa-allocation-001"):
        return {"invoice_id": invoice["id"], "invoice_version": invoice["version"],
                "transaction_id": transaction["id"], "transaction_version": transaction["version"],
                "amount": amount, "evidence_ref": "SYNTHETIC-RECONCILIATION-001", "idempotency_key": key}

    def fresh_invoice(self, identifier):
        return next(row for row in self.finance.list_invoices() if row["id"] == identifier)

    def fresh_transaction(self, identifier):
        return next(row for row in self.finance.list_transactions() if row["id"] == identifier)

    def test_opening_payment_is_explicit_and_leaves_exact_residual(self):
        invoice = self.register(opening="40.00")
        self.assertEqual("40.00", invoice["paid_amount"])
        self.assertEqual("80.00", invoice["remaining_amount"])
        transaction = self.transaction(amount="80.00")
        self.finance.confirm_allocation(self.allocation_data(invoice, transaction, "80.00"))
        current = self.fresh_invoice(invoice["id"])
        self.assertEqual("120.00", current["paid_amount"])
        self.assertEqual("0.00", current["remaining_amount"])

    def test_overallocation_cannot_consume_more_than_invoice_or_transaction(self):
        invoice = self.register(opening="40.00")
        transaction = self.transaction(amount="90.00")
        for amount in ("80.01", "90.00", "120.00"):
            with self.subTest(amount=amount), self.assertRaises(AppError):
                self.finance.confirm_allocation(self.allocation_data(invoice, transaction, amount))
        self.assertEqual([], self.finance.list_allocations())
        self.assertEqual("80.00", self.fresh_invoice(invoice["id"])["remaining_amount"])

    def test_money_parser_refuses_float_and_fractional_cents(self):
        invoice = self.register()
        transaction = self.transaction()
        for amount in (120.0, True, "NaN", "Infinity", "1e2", "120,00", "119.999", "-1.00", "0.00"):
            with self.subTest(amount=amount), self.assertRaises(AppError):
                self.finance.confirm_allocation(self.allocation_data(invoice, transaction, amount))
        self.assertEqual([], self.finance.list_allocations())

    def test_wrong_currency_and_wrong_flow_do_not_reconcile(self):
        invoice = self.register()
        wrong_currency = self.transaction(currency="USD")
        debit = self.transaction(amount="-120.00", source_id="bank-002")
        for transaction in (wrong_currency, debit):
            with self.subTest(transaction=transaction["id"]), self.assertRaises(AppError):
                self.finance.confirm_allocation(self.allocation_data(invoice, transaction))
        self.assertEqual([], self.finance.list_allocations())

    def test_payable_needs_outgoing_movement(self):
        invoice = self.register(direction="payable")
        credit = self.transaction()
        with self.assertRaises(AppError):
            self.finance.confirm_allocation(self.allocation_data(invoice, credit))
        debit = self.transaction(amount="-120.00", source_id="bank-002")
        self.finance.confirm_allocation(self.allocation_data(invoice, debit))
        self.assertEqual("0.00", self.fresh_invoice(invoice["id"])["remaining_amount"])

    def test_snapshot_before_opening_date_cannot_count_twice(self):
        invoice = self.register(opening="40.00")
        transaction = self.transaction(amount="40.00", when=day(-11))
        with self.assertRaises(AppError):
            self.finance.confirm_allocation(self.allocation_data(invoice, transaction, "40.00"))
        self.assertEqual("40.00", self.fresh_invoice(invoice["id"])["paid_amount"])

    def test_preview_and_similar_row_import_are_not_implicit_payment(self):
        task = self.task()
        invoice = self.register(task)
        self.transaction(reference=task["payload"]["invoice_number"])
        self.finance.suggestions()
        self.assertEqual([], self.finance.list_allocations())
        self.assertEqual("120.00", self.fresh_invoice(invoice["id"])["remaining_amount"])
        self.assertFalse(self.store.get(task["id"])["payload"]["paid"])

    def test_csv_duplicate_source_id_changed_content_is_refused_atomically(self):
        self.import_rows([f"fixed-id,{day(-1)},120.00,EUR,QA-FACT-001"])
        rows = [f"new-id,{day(-1)},20.00,EUR,QA-NEW", f"fixed-id,{day(-1)},125.00,EUR,QA-FACT-001"]
        with self.assertRaises(AppError):
            self.import_rows(rows)
        self.assertEqual(1, len(self.finance.list_transactions()))

    def test_csv_replay_does_not_duplicate_transactions(self):
        row = f"fixed-id,{day(-1)},120.00,EUR,QA-FACT-001"
        self.import_rows([row])
        self.import_rows([row])
        self.assertEqual(1, len(self.finance.list_transactions()))

    def test_csv_forged_preview_digest_does_not_import(self):
        data = {"account_ref": "synthetic", "csv_text": f"transaction_id,date,amount,currency,reference\nx,{day(-1)},120.00,EUR,QA-1\n"}
        preview = self.finance.preview_bank(data)
        changed = dict(data, csv_text=data["csv_text"].replace("120.00", "125.00"), preview_digest=preview["preview_digest"])
        with self.assertRaises(AppError):
            self.finance.import_bank(changed)
        self.assertEqual([], self.finance.list_transactions())

    def test_csv_refuses_ambiguous_amounts_dates_and_duplicate_headers(self):
        for csv_text in (
            f"transaction_id,date,amount,currency,reference\nx,{day(-1)},1e2,EUR,QA-1\n",
            f"transaction_id,date,amount,currency,reference\nx,{day(-1)},120.001,EUR,QA-1\n",
            "transaction_id,date,amount,currency,reference\nx,04/10/2026,120.00,EUR,QA-1\n",
            f"transaction_id,date,amount,currency,reference,amount\nx,{day(-1)},120.00,EUR,QA-1,999.00\n",
        ):
            with self.subTest(csv=csv_text), self.assertRaises(AppError):
                self.finance.preview_bank({"account_ref": "synthetic", "csv_text": csv_text})
        self.assertEqual([], self.finance.list_transactions())

    def test_allocation_retry_and_same_key_new_amount_are_refused_without_duplication(self):
        invoice = self.register()
        transaction = self.transaction()
        body = self.allocation_data(invoice, transaction, "40.00")
        first = self.finance.confirm_allocation(body)
        with self.assertRaises(AppError) as replay:
            self.finance.confirm_allocation(body)
        self.assertEqual("allocation_replay", replay.exception.code)
        with self.assertRaises(AppError):
            self.finance.confirm_allocation(dict(body, amount="50.00"))
        self.assertEqual("40.00", self.fresh_invoice(invoice["id"])["paid_amount"])
        self.assertEqual([first["id"]], [item["id"] for item in self.finance.list_allocations()])

    def test_stale_invoice_or_bank_version_cannot_allocate_twice(self):
        invoice = self.register()
        transaction = self.transaction()
        body = self.allocation_data(invoice, transaction, "40.00")
        self.finance.confirm_allocation(body)
        with self.assertRaises(AppError):
            self.finance.confirm_allocation(dict(body, idempotency_key="qa-another"))
        self.assertEqual(1, len(self.finance.list_allocations()))

    def test_source_task_edited_after_register_requires_reconciliation_review(self):
        task = self.task()
        invoice = self.register(task)
        transaction = self.transaction()
        payload = dict(task["payload"], total_amount="121.00")
        self.store.update(task["id"], {"version": task["version"], "payload": payload})
        with self.assertRaises(AppError):
            self.finance.confirm_allocation(self.allocation_data(invoice, transaction))
        self.assertEqual([], self.finance.list_allocations())

    def test_revocation_guard_rolls_back_allocation_and_versions(self):
        invoice = self.register()
        transaction = self.transaction()
        def revoked(_):
            raise AppError("Session révoquée", 401, "unauthorized")
        token = audit_guard.set(revoked)
        try:
            with self.assertRaises(AppError):
                self.finance.confirm_allocation(self.allocation_data(invoice, transaction))
        finally:
            audit_guard.reset(token)
        self.assertEqual([], self.finance.list_allocations())
        self.assertEqual(invoice["version"], self.fresh_invoice(invoice["id"])["version"])
        self.assertEqual(transaction["version"], self.fresh_transaction(transaction["id"])["version"])

    def test_reversal_restores_availability_once_and_stale_retry_is_refused(self):
        invoice = self.register()
        transaction = self.transaction()
        allocation = self.finance.confirm_allocation(self.allocation_data(invoice, transaction))
        body = {"version": allocation["version"], "invoice_version": self.fresh_invoice(invoice["id"])["version"],
                "transaction_version": self.fresh_transaction(transaction["id"])["version"], "reason": "Erreur de rapprochement synthétique"}
        self.finance.reverse_allocation(allocation["id"], body)
        self.assertEqual("120.00", self.fresh_invoice(invoice["id"])["remaining_amount"])
        with self.assertRaises(AppError):
            self.finance.reverse_allocation(allocation["id"], body)
        self.assertEqual("120.00", self.fresh_invoice(invoice["id"])["remaining_amount"])

    def test_concurrent_full_allocations_allow_exactly_one_winner(self):
        invoice = self.register()
        transaction = self.transaction()
        barrier = threading.Barrier(2)
        succeeded, refused, unexpected = [], [], []
        def attempt(index):
            try:
                barrier.wait(timeout=5)
                succeeded.append(self.finance.confirm_allocation(self.allocation_data(invoice, transaction, key=f"concurrent-{index}")))
            except AppError as exc:
                refused.append(exc.status)
            except Exception as exc:
                unexpected.append(type(exc).__name__)
        workers = [threading.Thread(target=attempt, args=(index,)) for index in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual([], unexpected)
        self.assertEqual(1, len(succeeded))
        self.assertEqual(1, len(refused))
        self.assertEqual("0.00", self.fresh_invoice(invoice["id"])["remaining_amount"])

    def factoring_data(self, invoice):
        return {"invoice_id": invoice["id"], "invoice_version": invoice["version"], "advance_rate": "80",
                "fee_rate": "2", "annual_interest_rate": "12", "fixed_fee": "1.00", "funding_date": day(0), "day_basis": 360}

    def test_factoring_simulation_does_not_settle_invoice_or_create_cash(self):
        invoice = self.register()
        before = self.finance.export()
        simulation = self.finance.simulate_factoring(self.factoring_data(invoice))
        self.assertIsInstance(simulation, dict)
        self.assertEqual([], self.finance.list_allocations())
        self.assertEqual([], self.finance.list_transactions())
        self.assertEqual("120.00", self.fresh_invoice(invoice["id"])["remaining_amount"])
        after = self.finance.export()
        self.assertEqual({key: value for key, value in before.items() if key != "events"},
                         {key: value for key, value in after.items() if key != "events"})
        self.assertEqual("finance.factoring_simulated", after["events"][-1]["action"])
        self.assertEqual("96.00", simulation["advance"])
        self.assertEqual("24.00", simulation["reserve"])
        self.assertEqual("3.40", simulation["fees"])
        self.assertEqual("0.96", simulation["interest"])
        self.assertEqual("4.36", simulation["total_cost"])
        self.assertEqual("91.64", simulation["net_cash"])
        self.assertIs(simulation["external_offer"], False)

    def test_factoring_refuses_payables_partial_settlements_and_unknown_dispute(self):
        for kwargs in ({"direction": "payable"}, {"opening": "1.00"}, {"disputed": "unknown"}, {"disputed": True}):
            invoice = self.register(**kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(AppError):
                self.finance.simulate_factoring(self.factoring_data(invoice))

    def test_assignment_does_not_pay_invoice_or_create_bank_operation(self):
        invoice = self.register()
        self.finance.set_assignment(invoice["id"], {"version": invoice["version"], "status": "assigned", "effective_date": day(0),
                                                       "evidence_ref": "SYNTHETIC-CONTRACT-001", "note": "Cession déclarée pour test uniquement"})
        current = self.fresh_invoice(invoice["id"])
        self.assertEqual("120.00", current["remaining_amount"])
        self.assertEqual([], self.finance.list_allocations())
        self.assertEqual([], self.finance.list_transactions())

    def test_assignment_release_cannot_predate_its_assignment(self):
        invoice = self.register()
        assigned = self.finance.set_assignment(invoice["id"], {"version": invoice["version"], "status": "assigned", "effective_date": day(-1),
            "evidence_ref": "SYNTHETIC-CONTRACT-001", "note": "Cession déclarée pour test uniquement"})
        with self.assertRaises(AppError):
            self.finance.set_assignment(invoice["id"], {"version": assigned["version"], "status": "released", "effective_date": day(-2),
                "evidence_ref": "SYNTHETIC-RELEASE-001", "note": "Levée antérieure à la cession, impossible"})
        self.assertEqual("assigned", self.fresh_invoice(invoice["id"])["assignment_status"])

    def test_reference_substring_and_amount_only_do_not_produce_unique_match(self):
        short = self.register(self.task(reference="FACT-1"))
        long = self.register(self.task(reference="FACT-10"))
        transaction = self.transaction(reference="Virement FACT-10")
        suggestions = self.finance.suggestions()
        matching = [row for row in suggestions["suggestions"] if row["transaction_id"] == transaction["id"]]
        self.assertEqual([long["id"]], [row["invoice_id"] for row in matching])
        self.transaction(source_id="bank-002", reference="Aucune référence facture")
        suggestions = self.finance.suggestions()
        self.assertTrue(any(row["reason"] == "amount_only" for row in suggestions["manual_only"]))
        self.assertNotIn(short["id"], [row["invoice_id"] for row in matching])
        self.assertEqual([], self.finance.list_allocations())

    def test_financing_reference_and_assigned_invoice_cannot_be_customer_payment(self):
        invoice = self.register()
        advance = self.transaction(reference="Avance affacturage QA-FACT-001")
        with self.assertRaises(AppError):
            self.finance.confirm_allocation(self.allocation_data(invoice, advance))
        assigned = self.finance.set_assignment(invoice["id"], {"version": invoice["version"], "status": "assigned", "effective_date": day(0),
            "evidence_ref": "SYNTHETIC-CONTRACT-001", "note": "Cession déclarée pour test uniquement"})
        ordinary = self.transaction(source_id="bank-002")
        with self.assertRaises(AppError):
            self.finance.confirm_allocation(self.allocation_data(assigned, ordinary))
        self.assertEqual([], self.finance.list_allocations())

    def test_instance_identity_change_refuses_reads_and_writes(self):
        invoice = self.register()
        transaction = self.transaction()
        with self.store.connection() as con:
            con.execute("UPDATE instance_identity SET client_id='qa-another-client'")
        for read in (self.finance.list_invoices, self.finance.list_transactions, self.finance.list_allocations, self.finance.summary, self.finance.export):
            with self.subTest(read=read.__name__), self.assertRaises(AppError) as refusal:
                read()
            self.assertEqual("client_mismatch", refusal.exception.code)
        with self.assertRaises(AppError):
            self.finance.confirm_allocation(self.allocation_data(invoice, transaction))
        with self.store.connection() as con:
            self.assertEqual(0, con.execute("SELECT count(*) FROM finance_allocations").fetchone()[0])


def expense_payload(**overrides):
    payload = {"merchant": "Café Synthétique", "expense_date": day(-1), "total_amount": "12.00", "currency": "EUR",
               "employee_ref": "SALARIE-FICTIF-01", "business_purpose": "Réunion professionnelle fictive", "category": "meals",
               "payment_method": "employee_card", "paid_by_company": False, "reimbursed": False,
               "business_only": True, "policy_confirmed": True, "payment_confirmed": True, "policy_ref": "POLITIQUE-FICTIVE-2026"}
    return dict(payload, **overrides)


def receipt_extraction(*_args, **_kwargs):
    return {"version": 1, "media_type": "image/png", "pages": [{"number": 1, "text": "Reçu synthétique\nTotal 12.00 EUR",
             "method": "ocr", "width": 800, "height": 1100, "words": []}],
            "candidates": {"total_amount": {"value": "12.00", "page": 1, "quote": "Total 12.00 EUR", "bbox": [0.1, 0.1, 0.9, 0.2], "method": "ocr"}},
            "warnings": [], "engine": {"name": "poppler+tesseract", "languages": "fra", "forced_ocr": False}, "review_required": True}


class IndependentExpenseReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "expenses.sqlite3")
        with self.store.connection() as con:
            con.execute("CREATE TABLE instance_identity(singleton INTEGER PRIMARY KEY,client_id TEXT,client_name TEXT,schema_version INTEGER)")
            con.execute("INSERT INTO instance_identity VALUES(1,'qa-expenses','Synthetic QA expenses',1)")
        self.documents = DocumentStore(self.store, ocr_client=type("SyntheticOCR", (), {"extract": staticmethod(receipt_extraction)})())
        self.counter = 0

    def create_expense(self, payload=None):
        self.counter += 1
        # This isolates metadata/review logic; native parser validation is elsewhere.
        document, _ = self.documents.add(b"\x89PNG\r\n\x1a\nSYNTHETIC-FIXTURE-" + str(self.counter).encode(), "receipt.png")
        self.documents.extract(document["id"], {"version": 0, "language": "fra"})
        payload = payload or expense_payload()
        task, _, _ = self.documents.create_task(document["id"], {"title": "Frais synthétiques", "description": "QA sans remboursement",
            "skill_id": "expense-review", "country": "FR", "payload": payload, "human_verified": True,
            "verified_fields": sorted(payload), "extraction_version": 1})
        return task

    def test_verified_receipt_still_requires_explicit_payment_confirmation(self):
        payload = expense_payload()
        payload.pop("payment_confirmed")
        task = self.create_expense(payload)
        result = analyze(task, expense_duplicate_ids=[])
        self.assertEqual("blocked", result_status(result))
        self.assertIn("payment_confirmed", result["missing_fields"])
        self.assertFalse(result["outbound_executed"])

    def test_company_payment_existing_reimbursement_and_card_contradiction_block(self):
        for overrides in ({"paid_by_company": True}, {"reimbursed": True}, {"payment_method": "company_card", "paid_by_company": False},
                          {"business_only": False}, {"policy_confirmed": False}, {"payment_confirmed": False}):
            with self.subTest(overrides=overrides):
                result = analyze(self.create_expense(expense_payload(**overrides)), expense_duplicate_ids=[])
                self.assertEqual("blocked", result_status(result))
                self.assertFalse(result["draft"])

    def test_complete_expense_is_internal_draft_without_vat_or_payment_claim(self):
        task = self.create_expense()
        result = analyze(task, expense_duplicate_ids=[])
        self.assertEqual("needs_review", result_status(result))
        self.assertIn("12.00 EUR", result["draft"])
        self.assertFalse(result["outbound_executed"])
        self.assertNotIn("reimbursement_amount", result)
        self.assertNotIn("deductible_vat", result)

    def test_duplicate_receipt_cannot_be_hidden_by_different_employee(self):
        first = self.create_expense()
        second = self.create_expense(expense_payload(employee_ref="SALARIE-FICTIF-02"))
        result = analyze_task(self.store, second)
        self.assertEqual("blocked", result["status"])
        self.assertTrue(any(item.get("field") == "expense_duplicates" for item in result["result"]["findings"]))
        self.assertNotEqual(first["payload"]["_document_source"]["sha256"], second["payload"]["_document_source"]["sha256"])

    def test_receipt_amount_edit_cannot_keep_the_old_review_valid(self):
        task = self.create_expense()
        edited = self.store.update(task["id"], {"version": task["version"], "payload": expense_payload(total_amount="120.00")})
        result = analyze(edited, expense_duplicate_ids=[])
        self.assertEqual("blocked", result_status(result))
        self.assertTrue(any(item.get("field") == "_document_source" for item in result["findings"]))

    def test_new_duplicate_between_analysis_and_approval_blocks_approval(self):
        first = self.create_expense()
        analyzed = analyze_task(self.store, first)
        self.assertEqual("needs_review", analyzed["status"])
        self.create_expense(expense_payload(employee_ref="SALARIE-FICTIF-02"))
        with self.assertRaises(AppError):
            self.store.review(first["id"], "approve", "Relecture devenue périmée", analyzed["version"])
        self.assertNotEqual("ready", self.store.get(first["id"])["status"])

    def test_currency_policy_cannot_silently_convert_or_ignore_missing_limit(self):
        for extra in ({"policy_limit": "20.00", "policy_currency": "USD"}, {"policy_currency": "EUR"}, {"policy_limit": "10.00", "policy_currency": "EUR"}):
            with self.subTest(extra=extra):
                result = analyze(self.create_expense(expense_payload(**extra)), expense_duplicate_ids=[])
                self.assertEqual("blocked", result_status(result))

    def test_receipt_reverification_preserves_original_and_invalidates_approval(self):
        task = self.create_expense()
        analyzed = analyze_task(self.store, task)
        ready = self.store.review(task["id"], "approve", "Revue synthétique initiale", analyzed["version"])
        original_source = ready["payload"]["_document_source"]
        corrected = self.store.update(task["id"], {"version": ready["version"], "payload": expense_payload(total_amount="13.00")})
        document_id = original_source["document_id"]
        request = {"task_version": corrected["version"], "extraction_version": 1, "human_verified": True,
                   "verified_fields": ["merchant", "expense_date", "total_amount", "currency"]}
        confirmed, _ = self.documents.reverify_expense(document_id, request)
        self.assertEqual("new", confirmed["status"])
        self.assertIsNone(confirmed["result"])
        self.assertEqual(corrected["version"] + 1, confirmed["version"])
        source = confirmed["payload"]["_document_source"]
        self.assertEqual(original_source["sha256"], source["sha256"])
        self.assertEqual("12.00", source["fields"]["total_amount"]["reviewed_value"])
        self.assertEqual("13.00", source["receipt_reviews"][-1]["fields"]["total_amount"]["reviewed_value"])
        self.assertEqual("12.00", source["receipt_reviews"][-1]["fields"]["total_amount"]["candidate"]["value"])
        with self.assertRaises(AppError):
            self.store.review(task["id"], "approve", "Validation sans analyse refusée", confirmed["version"])
        with self.assertRaises(AppError):
            self.documents.reverify_expense(document_id, request)
        self.assertEqual("needs_review", analyze_task(self.store, confirmed)["status"])

    def test_receipt_reverification_late_revocation_rolls_back_task_and_both_audits(self):
        task = self.create_expense()
        document_id = task["payload"]["_document_source"]["document_id"]
        request = {"task_version": task["version"], "extraction_version": 1, "human_verified": True,
                   "verified_fields": ["merchant", "expense_date", "total_amount", "currency"]}
        before_task = self.store.get(task["id"])
        before_task_events = self.store.events()
        before_document = self.documents.get(document_id)
        # Refuse after the task SQL update, then after the task audit insertion.
        for fail_at in (2, 3):
            with self.subTest(fail_at=fail_at):
                calls = []
                def revoked_late(_connection):
                    calls.append(True)
                    if len(calls) == fail_at:
                        raise AppError("Session révoquée pendant la mutation", 401, "auth_required")
                token = audit_guard.set(revoked_late)
                try:
                    with self.assertRaises(AppError):
                        self.documents.reverify_expense(document_id, request)
                finally:
                    audit_guard.reset(token)
                self.assertEqual(fail_at, len(calls))
                self.assertEqual(before_task, self.store.get(task["id"]))
                self.assertEqual(before_task_events, self.store.events())
                self.assertEqual(before_document, self.documents.get(document_id))


if __name__ == "__main__":
    unittest.main()
