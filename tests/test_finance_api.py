"""Finance HTTP contracts, authorization, atomic races and backup boundary."""

from datetime import date, timedelta
import http.client
import importlib.util
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from unittest.mock import patch

from admin_agent.server import LocalHTTPServer, analyze_task
from admin_agent.storage import Store

PRODUCTION_AVAILABLE = all(importlib.util.find_spec(name) for name in ("flask", "pyotp", "cryptography"))
if PRODUCTION_AVAILABLE:
    import pyotp
    from admin_agent.ops import backup_database, restore_database
    from admin_agent.production import ProductionConfig, create_app, COOKIE_NAME


def reviewed_invoice(store, number="HTTP-FIN-001"):
    today = date.today()
    payload = {"invoice_number": number, "supplier": "Fournisseur fictif", "customer": "Client fictif", "issue_date": (today - timedelta(days=5)).isoformat(),
               "due_date": (today + timedelta(days=30)).isoformat(), "net_amount": "1000.00", "vat_rate": "20.00", "vat_amount": "200.00", "total_amount": "1200.00",
               "currency": "EUR", "paid": False, "disputed": False}
    task, _ = store.create({"title": "Facture synthétique API", "description": "Test interne, aucune action externe", "country": "FR", "skill_id": "invoice-check", "payload": payload})
    task = analyze_task(store, task)
    return store.review(task["id"], "approve", "Vérification synthétique", task["version"])


def registration(task):
    return {"task_id": task["id"], "task_version": task["version"], "direction": "receivable", "opening_paid_amount": "0.00",
            "opening_as_of": (date.today() - timedelta(days=1)).isoformat(), "opening_confirmed": True, "evidence_ref": "SYNTHETIC-OPENING", "disputed": False}


def csv_import():
    return {"account_ref": "SYNTHETIC-ACCOUNT", "csv_text": "transaction_id,date,amount,currency,reference\nBANK-HTTP-001," + date.today().isoformat() + ",600.00,EUR,HTTP-FIN-001\n"}


class LocalFinanceAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "local.sqlite3")
        self.server = LocalHTTPServer(("127.0.0.1", 0), self.store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self, method, path, data=None, headers=None):
        con = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            con.request(method, path, body=json.dumps(data) if data is not None else None, headers={"Content-Type": "application/json", **(headers or {})})
            response = con.getresponse()
            return response.status, json.loads(response.read())
        finally:
            con.close()

    def test_local_register_preview_import_and_full_export(self):
        task = reviewed_invoice(self.store)
        status, response = self.request("POST", "/api/finance/invoices/register", registration(task))
        self.assertEqual(200, status, response)
        invoice_id = response["invoice"]["id"]
        status, response = self.request("POST", "/api/finance/bank/preview", csv_import())
        self.assertEqual(200, status, response)
        data = dict(csv_import(), preview_digest=response["preview"]["preview_digest"])
        status, response = self.request("POST", "/api/finance/bank/import", data)
        self.assertEqual(200, status, response)
        self.assertEqual(1, response["import"]["created"])
        status, response = self.request("GET", "/api/export")
        self.assertEqual(200, status)
        self.assertEqual("1.1", response["format_version"])
        self.assertEqual(invoice_id, response["finance"]["invoices"][0]["id"])
        self.assertEqual(1, len(response["finance"]["transactions"]))

    def test_loopback_finance_rejects_foreign_origin_and_unknown_execution_routes(self):
        status, _ = self.request("POST", "/api/finance/bank/preview", csv_import(), {"Origin": "https://untrusted.invalid"})
        self.assertEqual(403, status)
        for path in ("/api/finance/payments/send", "/api/finance/factoring/submit", "/api/finance/bank/connect"):
            status, _ = self.request("POST", path, {})
            self.assertEqual(404, status)
        status, session = self.request("GET", "/api/session")
        self.assertEqual(200, status)
        self.assertTrue(session["capabilities"]["finance_write"])


@unittest.skipUnless(PRODUCTION_AVAILABLE, "Installer les dépendances production pour vérifier l'API finance authentifiée")
class ProductionFinanceAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = ProductionConfig("finance-client", "Finance fictive", "https://finance.test", self.root / "client.sqlite3", secrets.token_hex(32).encode())
        self.app = create_app(self.config)
        self.store = self.app.extensions["store"]
        self.auth = self.app.extensions["auth"]
        self.finance = self.app.extensions["finance"]
        self.clock = 1800000000
        self.auth.clock = lambda: self.clock
        self.password = "Synthétique-uniquement-API-42"
        self.enrollments = {role: self.auth.provision_user(role + "-test", self.password, role) for role in ("admin", "operator", "reader")}
        self.client = self.app.test_client()
        self.csrf = None

    def tearDown(self):
        self.temp.cleanup()

    def get(self, path, client=None):
        return (client or self.client).get(path, base_url=self.config.public_origin)

    def post(self, path, data, client=None, csrf=None):
        return (client or self.client).post(path, base_url=self.config.public_origin, json=data,
                                          headers={"Origin": self.config.public_origin, "X-CSRF-Token": self.csrf if csrf is None else csrf})

    def login(self, role="admin"):
        self.clock += 30
        csrf = self.get("/api/session").get_json()["csrf_token"]
        response = self.post("/api/login", {"username": role + "-test", "password": self.password,
                              "otp": pyotp.TOTP(self.enrollments[role]["totp_secret"]).at(self.clock)}, csrf=csrf)
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        self.csrf = response.get_json()["csrf_token"]
        return response.get_json()

    def invoice_and_transaction(self):
        task = reviewed_invoice(self.store)
        response = self.post("/api/finance/invoices/register", registration(task))
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        invoice = response.get_json()["invoice"]
        preview = self.post("/api/finance/bank/preview", csv_import())
        self.assertEqual(200, preview.status_code, preview.get_data(as_text=True))
        response = self.post("/api/finance/bank/import", dict(csv_import(), preview_digest=preview.get_json()["preview"]["preview_digest"]))
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        return task, invoice, response.get_json()["import"]["transactions"][0]

    def allocation_request(self, invoice, transaction, key="http-confirm-1"):
        return {"invoice_id": invoice["id"], "invoice_version": invoice["version"], "transaction_id": transaction["id"],
                "transaction_version": transaction["version"], "amount": "600.00", "evidence_ref": "SYNTHETIC-BANK-CHECK", "idempotency_key": key}

    def test_all_finance_reads_require_login_and_reader_cannot_mutate_or_export(self):
        for endpoint in ("summary", "invoices", "bank-transactions", "allocations", "suggestions", "export"):
            self.assertEqual(401, self.get("/api/finance/" + endpoint).status_code)
        session = self.login("reader")
        self.assertTrue(session["capabilities"]["finance_read"])
        self.assertFalse(session["capabilities"]["finance_write"])
        self.assertFalse(session["capabilities"]["finance_export"])
        for endpoint in ("summary", "invoices", "bank-transactions", "allocations", "suggestions"):
            self.assertEqual(200, self.get("/api/finance/" + endpoint).status_code)
        item_id = "00000000-0000-0000-0000-000000000000"
        for endpoint in ("invoices/register", "bank/preview", "bank/import", "allocations/confirm", "factoring/simulate",
                         f"invoices/{item_id}/state", f"invoices/{item_id}/assignment", f"allocations/{item_id}/reverse"):
            self.assertEqual(403, self.post("/api/finance/" + endpoint, {}).status_code)
        self.assertEqual(403, self.post(f"/api/documents/{item_id}/reverify-expense", {}).status_code)
        self.assertEqual(403, self.get("/api/finance/export").status_code)

    def test_csrf_origin_and_body_limits_reject_before_finance_side_effect(self):
        self.login("operator")
        task = reviewed_invoice(self.store)
        self.assertEqual(403, self.post("/api/finance/invoices/register", registration(task), csrf="wrong").status_code)
        response = self.client.post("/api/finance/bank/preview", base_url=self.config.public_origin, json=csv_import(),
                                    headers={"Origin": "https://different.invalid", "X-CSRF-Token": self.csrf})
        self.assertEqual(403, response.status_code)
        response = self.post("/api/finance/bank/preview", {"account_ref": "TEST", "csv_text": "x" * 65536})
        self.assertEqual(413, response.status_code)
        response = self.client.post("/api/finance/bank/preview", base_url=self.config.public_origin, data='{"account_ref":"a","account_ref":"b"}',
                                    content_type="application/json", headers={"Origin": self.config.public_origin, "X-CSRF-Token": self.csrf})
        self.assertEqual(400, response.status_code)
        self.assertEqual([], self.finance.list_invoices())
        self.assertEqual([], self.finance.list_transactions())

    def test_operator_registers_and_allocates_internal_records_but_cannot_export(self):
        self.login("operator")
        _, invoice, transaction = self.invoice_and_transaction()
        response = self.post("/api/finance/allocations/confirm", self.allocation_request(invoice, transaction))
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        self.assertEqual(1, len(self.get("/api/finance/allocations").get_json()["allocations"]))
        self.assertEqual(403, self.get("/api/finance/export").status_code)
        self.assertEqual(403, self.get("/api/export").status_code)

    def test_stale_registration_and_allocation_are_http_conflicts(self):
        self.login()
        task, invoice, transaction = self.invoice_and_transaction()
        response = self.post("/api/finance/allocations/confirm", self.allocation_request(invoice, transaction))
        self.assertEqual(200, response.status_code)
        response = self.post("/api/finance/allocations/confirm", self.allocation_request(invoice, transaction, "different-operation"))
        self.assertEqual(409, response.status_code)
        self.assertEqual(1, len(self.finance.list_allocations()))
        different = reviewed_invoice(self.store, "HTTP-FIN-002")
        self.store.update(different["id"], {"version": different["version"], "description": "Version modifiée après revue"})
        self.assertEqual(409, self.post("/api/finance/invoices/register", registration(different)).status_code)

    def test_concurrent_allocation_only_commits_one_version(self):
        self.login("operator")
        _, invoice, transaction = self.invoice_and_transaction()
        token = self.client.get_cookie(COOKIE_NAME, domain="finance.test").value
        barrier = threading.Barrier(2)
        statuses, failures = [], []
        def attempt(index):
            try:
                client = self.app.test_client()
                client.set_cookie(COOKIE_NAME, token, domain="finance.test")
                barrier.wait(timeout=5)
                response = self.post("/api/finance/allocations/confirm", self.allocation_request(invoice, transaction, "race-" + str(index)), client=client)
                statuses.append(response.status_code)
            except Exception as exc:
                failures.append(type(exc).__name__)
        workers = [threading.Thread(target=attempt, args=(index,)) for index in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual([], failures)
        self.assertEqual([200, 409], sorted(statuses))
        self.assertEqual(1, len(self.finance.list_allocations()))

    def test_revoked_session_between_request_check_and_commit_rolls_back_allocation(self):
        self.login("operator")
        _, invoice, transaction = self.invoice_and_transaction()
        original = self.finance.confirm_allocation
        def revoke_then_confirm(data):
            self.auth.revoke_user_sessions("operator-test")
            return original(data)
        with patch.object(self.finance, "confirm_allocation", side_effect=revoke_then_confirm):
            response = self.post("/api/finance/allocations/confirm", self.allocation_request(invoice, transaction))
        self.assertEqual(401, response.status_code, response.get_data(as_text=True))
        self.assertEqual([], self.finance.list_allocations())
        self.assertEqual(invoice["version"], self.finance.list_invoices()[0]["version"])
        self.assertEqual(transaction["version"], self.finance.list_transactions()[0]["version"])

    def test_finance_survives_full_database_backup_and_restores_accounts_quarantined(self):
        self.login()
        _, invoice, transaction = self.invoice_and_transaction()
        response = self.post("/api/finance/allocations/confirm", self.allocation_request(invoice, transaction))
        self.assertEqual(200, response.status_code)
        expected = self.finance.export()
        destination = self.root / "backup"
        backup_database(self.config.db_path, self.config.client_id, destination)
        recovered_path = self.root / "restored.sqlite3"
        restore_database(destination, self.config.client_id, recovered_path)
        from admin_agent.finance import FinanceStore
        recovered = FinanceStore(Store(recovered_path))
        exported = recovered.export()
        for name in ("invoices", "transactions", "allocations", "events", "bank_imports"):
            self.assertEqual(expected[name], exported[name], name)
        with recovered.store.connection() as con:
            self.assertEqual(0, con.execute("SELECT count(*) FROM auth_users WHERE enabled=1").fetchone()[0])
            self.assertEqual(0, con.execute("SELECT count(*) FROM auth_sessions").fetchone()[0])

    def test_admin_finance_export_and_global_export_include_full_finance_source(self):
        self.login()
        self.invoice_and_transaction()
        standalone = self.get("/api/finance/export")
        self.assertEqual(200, standalone.status_code)
        self.assertIn("attachment", standalone.headers["Content-Disposition"])
        global_export = self.get("/api/export")
        self.assertEqual(200, global_export.status_code)
        self.assertEqual(standalone.get_json(), global_export.get_json()["finance"])
        self.assertIn(csv_import()["csv_text"], json.dumps(standalone.get_json(), ensure_ascii=False).replace("\\n", "\n"))
        response = self.client.head("/api/finance/export", base_url=self.config.public_origin)
        self.assertEqual(405, response.status_code)

    def test_bank_only_local_database_cannot_be_silently_bound_to_production(self):
        from admin_agent.finance import FinanceStore
        local_store = Store(self.root / "bank-only-local.sqlite3")
        local_finance = FinanceStore(local_store)
        preview = local_finance.preview_bank(csv_import())
        local_finance.import_bank(dict(csv_import(), preview_digest=preview["preview_digest"]))
        self.assertEqual([], local_store.list())
        config = ProductionConfig("another-client", "Another synthetic client", "https://another.test", Path(local_store.path), secrets.token_hex(32).encode())
        with self.assertRaises(ValueError):
            create_app(config)

    def test_simulation_assignment_reversal_and_dispute_are_reviewed_internal_events(self):
        self.login("operator")
        _, invoice, transaction = self.invoice_and_transaction()
        simulation_request = {"invoice_id": invoice["id"], "invoice_version": invoice["version"], "advance_rate": "80.00", "fee_rate": "1.00",
                              "annual_interest_rate": "6.00", "fixed_fee": "0.00", "funding_date": date.today().isoformat(), "day_basis": 360}
        response = self.post("/api/finance/factoring/simulate", simulation_request)
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        self.assertEqual("960.00", response.get_json()["simulation"]["advance"])
        self.assertFalse(response.get_json()["simulation"]["external_offer"])
        self.assertFalse(response.get_json()["simulation"]["outbound_executed"])
        self.assertEqual(invoice["version"], self.finance.list_invoices()[0]["version"])
        assignment = {"version": invoice["version"], "status": "assigned", "effective_date": date.today().isoformat(),
                      "evidence_ref": "SYNTHETIC-ASSIGNMENT", "note": "Justificatif fictif contrôlé, aucune cession exécutée"}
        response = self.post(f"/api/finance/invoices/{invoice['id']}/assignment", assignment)
        self.assertEqual(200, response.status_code, response.get_data(as_text=True))
        invoice = response.get_json()["invoice"]
        self.assertFalse(invoice["assignment"]["external_action_executed"])
        self.assertEqual(409, self.post("/api/finance/allocations/confirm", self.allocation_request(invoice, transaction)).status_code)
        response = self.post(f"/api/finance/invoices/{invoice['id']}/assignment", dict(assignment, version=invoice["version"], status="released"))
        self.assertEqual(200, response.status_code)
        invoice = response.get_json()["invoice"]
        allocation = self.post("/api/finance/allocations/confirm", self.allocation_request(invoice, transaction)).get_json()["allocation"]
        invoice = self.finance.list_invoices()[0]
        transaction = self.finance.list_transactions()[0]
        response = self.post(f"/api/finance/allocations/{allocation['id']}/reverse", {"version": allocation["version"], "invoice_version": invoice["version"],
                             "transaction_version": transaction["version"], "reason": "Affectation fictive corrigée après revue"})
        self.assertEqual(200, response.status_code)
        self.assertEqual("reversed", response.get_json()["allocation"]["status"])
        invoice = self.finance.list_invoices()[0]
        response = self.post(f"/api/finance/invoices/{invoice['id']}/state", {"version": invoice["version"], "disputed": "unknown", "confirmed_on": date.today().isoformat(),
                             "evidence_ref": "SYNTHETIC-DISPUTE-REVIEW", "note": "État non confirmé"})
        self.assertEqual(200, response.status_code)
        invoice = response.get_json()["invoice"]
        response = self.post("/api/finance/factoring/simulate", dict(simulation_request, invoice_version=invoice["version"]))
        self.assertEqual(409, response.status_code)
        self.assertTrue(all(event["actor"] == "operator-test" for event in self.finance.export()["events"]))


if __name__ == "__main__":
    unittest.main()
