"""Synthetic accounting-state tests, without banks, customers or provider calls."""
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from admin_agent.engine import analyze
from admin_agent.errors import AppError
from admin_agent.finance import FinanceStore
from admin_agent.storage import Store, audit_actor, audit_guard


class FinanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "finance.sqlite3")
        self.finance = FinanceStore(self.store)
        self.counter = 0
        self.today = date.today()
        self.opening = (self.today - timedelta(days=2)).isoformat()

    def tearDown(self):
        self.temp.cleanup()

    def task(self, *, number=None, total="120.00", currency="EUR", due=None, **overrides):
        self.counter += 1
        payload = dict(invoice_number=number or f"FAC-{self.counter}", supplier="Supplier Synthetic", customer="Customer Synthetic",
                       issue_date=(self.today - timedelta(days=30)).isoformat(), due_date=due or (self.today + timedelta(days=30)).isoformat(),
                       net_amount=total, vat_rate="0.00", vat_amount="0.00", total_amount=total, currency=currency, paid=False)
        payload.update(overrides)
        task, _ = self.store.create(dict(title="Finance synthetic", description="Simple invoice for tests", skill_id="invoice-check", country="FR", payload=payload))
        task = self.store.save_analysis(task["id"], analyze(task), task["version"])
        return self.store.review(task["id"], "approve", "Synthetic source checked", task["version"])

    def register(self, task=None, **overrides):
        task = task or self.task()
        data = dict(task_id=task["id"], task_version=task["version"], direction="receivable", opening_paid_amount="0.00",
                    opening_as_of=self.opening, opening_confirmed=True, evidence_ref="Synthetic closing balance", disputed=False)
        data.update(overrides)
        return self.finance.register_invoice(data)

    def import_bank(self, lines=None, account="synthetic-account"):
        lines = lines or [f"TX-1,{self.today.isoformat()},120.00,EUR,Payment FAC-1"]
        data = {"account_ref": account, "csv_text": "transaction_id,date,amount,currency,reference\n" + "\n".join(lines) + "\n"}
        preview = self.finance.preview_bank(data)
        result = self.finance.import_bank(dict(data, preview_digest=preview["preview_digest"]))
        return result["transactions"]

    def allocation(self, invoice, transaction, amount="120.00", key="request-1"):
        return self.finance.confirm_allocation(dict(invoice_id=invoice["id"], invoice_version=invoice["version"],
            transaction_id=transaction["id"], transaction_version=transaction["version"], amount=amount, evidence_ref="Synthetic bank proof", idempotency_key=key))

    def factoring(self, invoice, **overrides):
        data = dict(invoice_id=invoice["id"], invoice_version=invoice["version"], advance_rate="80.00", fee_rate="1.00",
                    annual_interest_rate="6.00", fixed_fee="0.00", funding_date=self.today.isoformat(), day_basis=360)
        data.update(overrides)
        return self.finance.simulate_factoring(data)

    def test_registration_is_explicit_and_invoice_numbers_not_reusable(self):
        task = self.task()
        for overrides in ({"opening_confirmed": False}, {"opening_paid_amount": "121.00"}, {"opening_as_of": (self.today + timedelta(days=1)).isoformat()}, {"disputed": "false"}):
            with self.subTest(overrides=overrides), self.assertRaises(AppError):
                self.register(task, **overrides)
        self.register(task)
        with self.assertRaises(AppError) as caught:
            self.register(self.task(number=task["payload"]["invoice_number"]))
        self.assertEqual("invoice_already_registered", caught.exception.code)

    def test_only_ready_invoice_check_can_register(self):
        task, _ = self.store.create(dict(title="Triage", description="invoice", skill_id="admin-triage", country="FR", payload={}))
        with self.assertRaises(AppError):
            self.register(task)
        ready = self.task()
        edited = self.store.update(ready["id"], {"version": ready["version"], "description": "New source"})
        with self.assertRaises(AppError):
            self.register(edited)

    def test_paid_source_cannot_open_unpaid_balance(self):
        task = self.task(paid=True)
        with self.assertRaises(AppError):
            self.register(task)
        invoice = self.register(task, opening_paid_amount="120.00")
        self.assertEqual("paid", invoice["payment_status"])
        self.assertEqual("0.00", invoice["remaining_amount"])

    def test_partial_opening_and_overdue_are_independent(self):
        invoice = self.register(self.task(due=(self.today - timedelta(days=1)).isoformat()), opening_paid_amount="20.01")
        self.assertEqual("partial", invoice["payment_status"])
        self.assertEqual("99.99", invoice["remaining_amount"])
        self.assertTrue(invoice["overdue"])
        self.assertEqual(1, invoice["days_overdue"])

    def test_initialization_persists_all_finance_data_in_same_database(self):
        invoice = self.register()
        tx = self.import_bank()[0]
        self.allocation(invoice, tx)
        reopened = FinanceStore(Store(self.store.path))
        self.assertEqual("paid", reopened.list_invoices()[0]["payment_status"])
        self.assertEqual(1, len(reopened.list_allocations()))
        exported = reopened.export()
        self.assertEqual("transaction_id,date,amount,currency,reference", exported["bank_imports"][0]["csv_text"].splitlines()[0])
        self.assertEqual(64, len(exported["bank_imports"][0]["source_sha256"]))

    def test_csv_preview_is_read_only_and_digest_binds_contents(self):
        data = {"account_ref": "account", "csv_text": f"\ufefftransaction_id,date,amount,currency,reference\nA,{self.today},+120.00,EUR,Payment\n"}
        preview = self.finance.preview_bank(data)
        self.assertEqual(1, preview["new_count"])
        self.assertEqual([], self.finance.list_transactions())
        self.assertEqual([], self.finance.export()["events"])
        with self.assertRaises(AppError):
            self.finance.import_bank(dict(data, csv_text=data["csv_text"].replace("120.00", "120.01"), preview_digest=preview["preview_digest"]))

    def test_csv_requires_strict_schema_and_rejects_nonfinite_or_fractional_cents(self):
        for value in ("NaN", "Infinity", "1e3", "-1.005", "1 000.00", "0.00"):
            with self.subTest(value=value), self.assertRaises(AppError):
                self.import_bank([f"A,{self.today},{value},EUR,Reference"])
        for text in ("date,transaction_id,amount,currency,reference\n", "transaction_id,date,amount,currency,reference,extra\n"):
            with self.subTest(text=text), self.assertRaises(AppError):
                self.finance.preview_bank({"account_ref": "test", "csv_text": text})

    def test_csv_duplicate_in_batch_and_future_date_rejected(self):
        row = f"A,{self.today},1.00,EUR,Reference"
        with self.assertRaises(AppError):
            self.import_bank([row, row])
        with self.assertRaises(AppError):
            self.import_bank([f"A,{self.today + timedelta(days=1)},1.00,EUR,Reference"])

    def test_csv_conflict_rejects_entire_batch(self):
        self.import_bank([f"A,{self.today},10.00,EUR,A"])
        before = self.finance.export()
        with self.assertRaises(AppError):
            self.import_bank([f"NEW,{self.today},10.00,EUR,N", f"A,{self.today},11.00,EUR,A"])
        self.assertEqual(before, self.finance.export())

    def test_csv_same_external_id_in_different_accounts_is_not_deduplicated(self):
        self.import_bank(account="a")
        self.import_bank(account="b")
        self.assertEqual(2, len(self.finance.list_transactions()))

    def test_one_transaction_can_settle_two_invoices_sequentially(self):
        invoice1 = self.register(self.task(total="40.00"))
        invoice2 = self.register(self.task(total="80.00"))
        tx = self.import_bank()[0]
        self.allocation(invoice1, tx, "40.00", "first")
        tx = self.finance.list_transactions()[0]
        self.assertEqual("80.00", tx["remaining_amount"])
        self.allocation(invoice2, tx, "80.00", "second")
        self.assertTrue(all(invoice["payment_status"] == "paid" for invoice in self.finance.list_invoices()))
        self.assertEqual("0.00", self.finance.list_transactions()[0]["remaining_amount"])

    def test_two_transactions_can_settle_one_invoice_sequentially(self):
        invoice = self.register()
        txs = self.import_bank([f"A,{self.today},40.01,EUR,FAC-1", f"B,{self.today},79.99,EUR,FAC-1"])
        self.allocation(invoice, txs[0], "40.01", "a")
        invoice = self.finance.list_invoices()[0]
        self.assertEqual("partial", invoice["payment_status"])
        self.allocation(invoice, txs[1], "79.99", "b")
        self.assertEqual("120.00", self.finance.list_invoices()[0]["paid_amount"])

    def test_allocation_replay_refused_even_after_reversal(self):
        invoice = self.register()
        tx = self.import_bank()[0]
        allocation = self.allocation(invoice, tx)
        with self.assertRaises(AppError) as caught:
            self.allocation(invoice, tx)
        self.assertEqual("allocation_replay", caught.exception.code)
        invoice = self.finance.list_invoices()[0]
        tx = self.finance.list_transactions()[0]
        self.finance.reverse_allocation(allocation["id"], {"version": allocation["version"], "invoice_version": invoice["version"], "transaction_version": tx["version"], "reason": "Synthetic correction"})
        with self.assertRaises(AppError):
            self.allocation(self.finance.list_invoices()[0], self.finance.list_transactions()[0])

    def test_snapshot_date_boundary_blocks_preopening_payment(self):
        invoice = self.register(opening_as_of=self.today.isoformat())
        tx = self.import_bank()[0]
        with self.assertRaises(AppError) as caught:
            self.allocation(invoice, tx)
        self.assertEqual("transaction_before_opening", caught.exception.code)

    def test_finance_never_changes_source_task_paid_boolean(self):
        task = self.task()
        invoice = self.register(task)
        self.allocation(invoice, self.import_bank()[0])
        self.assertFalse(self.store.get(task["id"])["payload"]["paid"])
        self.assertEqual(task["version"], self.store.get(task["id"])["version"])

    def test_changed_source_blocks_allocation_simulation_assignment(self):
        task = self.task()
        invoice = self.register(task)
        self.store.update(task["id"], {"version": task["version"], "title": "Corrected source"})
        self.assertTrue(self.finance.list_invoices()[0]["source_stale"])
        with self.assertRaises(AppError):
            self.allocation(invoice, self.import_bank()[0])
        with self.assertRaises(AppError):
            self.factoring(invoice)
        with self.assertRaises(AppError):
            self.finance.set_assignment(invoice["id"], {"version": invoice["version"], "status": "assigned", "effective_date": self.today.isoformat(), "evidence_ref": "test", "note": "External contract observed"})

    def test_suggestions_require_distinct_whole_reference_and_never_allocate(self):
        invoice = self.register(self.task(number="FA-1"))
        self.import_bank([f"A,{self.today},120.00,EUR,Payment FA-10", f"B,{self.today},120.00,EUR,Payment FA-1"])
        result = self.finance.suggestions()
        self.assertEqual(1, len(result["suggestions"]))
        self.assertEqual(invoice["id"], result["suggestions"][0]["invoice_id"])
        self.assertEqual("amount_only", result["manual_only"][0]["reason"])
        self.assertFalse(result["auto_allocated"])
        self.assertEqual([], self.finance.list_allocations())

    def test_multiple_references_are_manual_not_arbitrarily_selected(self):
        self.register(self.task(number="FA-1"))
        self.register(self.task(number="FA-2"))
        self.import_bank([f"A,{self.today},120.00,EUR,Payment FA-1 and FA-2"])
        result = self.finance.suggestions()
        self.assertEqual([], result["suggestions"])
        self.assertEqual("ambiguous_reference", result["manual_only"][0]["reason"])

    def test_payables_need_negative_transactions_same_currency(self):
        invoice = self.register(direction="payable")
        tx = self.import_bank()[0]
        with self.assertRaises(AppError):
            self.allocation(invoice, tx)
        tx = self.import_bank([f"OUT,{self.today},-120.00,EUR,Supplier FAC-1"])[0]
        self.allocation(invoice, tx)
        self.assertEqual("paid", self.finance.list_invoices()[0]["payment_status"])

    def test_factoring_calculation_never_subtracts_reserve_twice(self):
        invoice = self.register(self.task(total="1000.00"))
        output = self.factoring(invoice, fixed_fee="2.00")
        self.assertEqual("800.00", output["advance"])
        self.assertEqual("200.00", output["reserve"])
        self.assertEqual("12.00", output["fees"])
        self.assertEqual("4.00", output["interest"])
        self.assertEqual("16.00", output["total_cost"])
        self.assertEqual("784.00", output["net_cash"])
        self.assertEqual(Decimal("984.00"), Decimal(output["net_cash"]) + Decimal(output["reserve"]))
        self.assertTrue(output["indicative"])
        self.assertFalse(output["external_offer"])
        self.assertEqual([], self.finance.list_transactions())
        self.assertEqual("0.00", self.finance.list_invoices()[0]["paid_amount"])

    def test_factoring_rejects_bad_rates_negative_net_past_or_overdue_maturity(self):
        invoice = self.register()
        for fields in ({"advance_rate": "101"}, {"advance_rate": "0"}, {"fee_rate": "100", "fixed_fee": "100"}, {"day_basis": True}, {"funding_date": (self.today - timedelta(days=1)).isoformat()}, {"funding_date": invoice["due_date"]}):
            with self.subTest(fields=fields), self.assertRaises(AppError):
                self.factoring(invoice, **fields)

    def test_assignment_blocks_payments_and_does_not_create_cash(self):
        invoice = self.register()
        assigned = self.finance.set_assignment(invoice["id"], {"version": invoice["version"], "status": "assigned", "effective_date": self.today.isoformat(), "evidence_ref": "Synthetic contract reference", "note": "Externally confirmed by operator"})
        self.assertEqual("0.00", assigned["paid_amount"])
        self.assertEqual("120.00", assigned["remaining_amount"])
        with self.assertRaises(AppError):
            self.allocation(assigned, self.import_bank()[0])
        with self.assertRaises(AppError):
            self.factoring(assigned)

    def test_financing_label_cannot_be_recorded_as_customer_payment(self):
        invoice = self.register()
        tx = self.import_bank([f"A,{self.today},120.00,EUR,Factoring advance FAC-1"])[0]
        with self.assertRaises(AppError) as caught:
            self.allocation(invoice, tx)
        self.assertEqual("financing_not_payment", caught.exception.code)

    def test_dispute_state_can_change_after_registration_and_invalidate_old_review(self):
        invoice = self.register()
        self.import_bank()
        self.assertEqual(1, len(self.finance.suggestions()["suggestions"]))
        new = self.finance.set_invoice_state(invoice["id"], {"version": invoice["version"], "disputed": True, "confirmed_on": self.today.isoformat(), "evidence_ref": "New complaint", "note": "Human-observed dispute"})
        self.assertTrue(new["disputed"])
        self.assertEqual([], self.finance.suggestions()["suggestions"])
        with self.assertRaises(AppError):
            self.factoring(new)
        with self.assertRaises(AppError):
            self.factoring(invoice)
        cleared = self.finance.set_invoice_state(new["id"], {"version": new["version"], "disputed": False, "confirmed_on": self.today.isoformat(), "evidence_ref": "Resolution", "note": "Resolution observed"})
        self.assertFalse(cleared["disputed"])
        self.assertTrue(self.factoring(cleared)["indicative"])

    def test_summary_never_combines_currencies(self):
        self.register(self.task(currency="EUR"))
        self.register(self.task(currency="USD"))
        result = self.finance.summary()
        self.assertEqual(["EUR", "USD"], [row["currency"] for row in result["by_currency"]])
        self.assertTrue(all(row["receivable_remaining"] == "120.00" for row in result["by_currency"]))
        self.assertFalse(result["outbound_enabled"])

    def test_audit_actor_and_late_revocation_roll_back_financial_mutation(self):
        actor_token = audit_actor.set("named.operator")
        try:
            self.register()
        finally:
            audit_actor.reset(actor_token)
        self.assertEqual("named.operator", self.finance.export()["events"][0]["actor"])
        task = self.task()
        calls = []
        def guard(con):
            calls.append(1)
            self.assertTrue(con.in_transaction)
            if len(calls) > 1:
                raise AppError("Revoked", 403)
        guard_token = audit_guard.set(guard)
        try:
            with self.assertRaises(AppError):
                self.register(task)
        finally:
            audit_guard.reset(guard_token)
        self.assertEqual(1, len(self.finance.list_invoices()))

    def test_database_identity_change_is_detected_on_reads_and_writes(self):
        with self.store.connection() as con:
            con.execute("CREATE TABLE instance_identity(singleton INTEGER,client_id TEXT)")
            con.execute("INSERT INTO instance_identity VALUES(1,'different-client')")
        for method in (self.finance.summary, self.finance.list_transactions, self.finance.export):
            with self.subTest(method=method.__name__), self.assertRaises(AppError) as caught:
                method()
            self.assertEqual("client_mismatch", caught.exception.code)

    def test_invoice_transaction_row_and_event_caps_fail_closed(self):
        with patch("admin_agent.finance.MAX_INVOICES", 0):
            with self.assertRaises(AppError):
                self.register()
        with patch("admin_agent.finance.MAX_TRANSACTIONS", 0):
            with self.assertRaises(AppError):
                self.import_bank()
        with patch("admin_agent.finance.MAX_CSV_ROWS", 1):
            with self.assertRaises(AppError):
                self.import_bank([f"A,{self.today},1.00,EUR,One", f"B,{self.today},1.00,EUR,Two"])
        with patch("admin_agent.finance.MAX_FINANCE_EVENTS", 0):
            with self.assertRaises(AppError):
                self.register()
        self.assertEqual([], self.finance.list_invoices())
        self.assertEqual([], self.finance.list_transactions())

    def test_export_accepts_existing_consistent_sqlite_snapshot(self):
        self.register()
        with self.store.connection() as con:
            con.execute("BEGIN")
            result = self.finance.export(connection=con)
            self.assertTrue(con.in_transaction)
            self.assertEqual(1, len(result["invoices"]))


if __name__ == "__main__":
    unittest.main()
