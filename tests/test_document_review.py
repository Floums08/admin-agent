"""Independent adversarial document/import regressions using synthetic data only.

HTTP tests exercise the real production authorization and persistence boundary.
The OCR callable is deliberately deterministic here; real extraction is exercised
separately by browser_documents.cjs against the isolated worker.
"""

import base64
import copy
from datetime import date, timedelta
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock

from admin_agent.errors import AppError
from admin_agent.ops import backup_database, restore_database
from admin_agent.storage import Store

HAS_PRODUCTION = all(importlib.util.find_spec(name) for name in ("flask", "pyotp", "cryptography"))
if HAS_PRODUCTION:
    import pyotp
    from admin_agent.auth import AuthStore
    from admin_agent.production import ProductionConfig, create_app

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jXAAAAABJRU5ErkJggg==")


def invoice_payload():
    return {"invoice_number": "QA-2026-001", "supplier": "Atelier fictif", "customer": "Client fictif",
            "issue_date": "2026-10-01", "due_date": "2026-10-31", "net_amount": "100.00",
            "vat_rate": "20", "vat_amount": "20.00", "total_amount": "120.00", "currency": "EUR", "paid": False}


def fake_extraction(*args, **kwargs):
    payload = invoice_payload()
    return {"version": 1, "media_type": "image/png", "pages": [{"number": 1, "text": "Facture QA-2026-001\nTotal TTC 120,00 EUR", "method": "ocr",
                       "width": 800, "height": 1100, "words": []}],
            "candidates": {"invoice_number": {"value": payload["invoice_number"], "page": 1,
                                                 "quote": "Facture QA-2026-001", "bbox": [0.01, 0.01, 0.5, 0.04], "method": "ocr"},
                           "total_amount": {"value": payload["total_amount"], "page": 1,
                                            "quote": "Total TTC 120,00 EUR", "bbox": [0.01, 0.06, 0.5, 0.09], "method": "ocr"}},
            "warnings": [], "engine": {"name": "poppler+tesseract", "languages": "fra", "forced_ocr": False}, "review_required": True}


@unittest.skipUnless(HAS_PRODUCTION, "Production dependencies required for document security gate.")
class IndependentDocumentReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.origin = "https://document-review.test"
        self.path = Path(self.temp.name) / "client.sqlite3"
        self.config = ProductionConfig(client_id="document-review", client_name="Synthetic document review",
                                       public_origin=self.origin, db_path=self.path, secret=b"91" * 32)
        self.app = create_app(self.config, ocr_client=type("SyntheticOCR", (), {"extract": staticmethod(fake_extraction)})())
        self.auth = self.app.extensions["auth"]
        self.store = self.app.extensions["store"]
        self.password = "Synthetic-document-review-74912"
        self.credentials_by_role = {}

    def tearDown(self):
        self.temp.cleanup()

    def post(self, browser, path, csrf, data, **kwargs):
        headers = {"Origin": self.origin, "X-CSRF-Token": csrf}
        headers.update(kwargs.pop("headers", {}))
        return browser.post(path, base_url=self.origin, headers=headers, json=data, **kwargs)

    def login(self, role="operator"):
        browser = self.app.test_client()
        session = browser.get("/api/session", base_url=self.origin).get_json()
        username = "document-" + role
        if role not in self.credentials_by_role:
            self.credentials_by_role[role] = self.auth.provision_user(username, self.password, role)
        code = pyotp.TOTP(self.credentials_by_role[role]["totp_secret"]).at(self.auth.clock())
        response = self.post(browser, "/api/login", session["csrf_token"],
                             {"username": username, "password": self.password, "otp": code})
        self.assertEqual(200, response.status_code, response.get_json())
        return browser, response.get_json()["csrf_token"]

    def upload(self, browser, csrf, content=PNG, filename="synthetic.png", headers=None):
        request_headers = {"Origin": self.origin, "X-CSRF-Token": csrf}
        if headers is not None:
            request_headers = headers
        response = browser.post("/api/documents", base_url=self.origin, headers=request_headers,
                                data={"file": (io.BytesIO(content), filename), "language": "fra"},
                                content_type="multipart/form-data")
        # Werkzeug's synthetic multipart stream can spill to a temporary file.
        # The real WSGI server owns it; this test client must close its copy.
        response.request.environ["wsgi.input"].close()
        return response

    def create_request(self, version):
        payload = invoice_payload()
        return {"title": "Synthetic reviewed invoice", "description": "Synthetic QA only", "country": "FR",
                "skill_id": "invoice-check", "payload": payload, "extraction_version": version,
                "human_verified": True, "verified_fields": sorted(payload)}

    def test_document_reads_require_authentication(self):
        browser = self.app.test_client()
        for route in ("/api/documents", "/api/documents/00000000-0000-0000-0000-000000000000",
                      "/api/documents/00000000-0000-0000-0000-000000000000/original"):
            with self.subTest(route=route):
                self.assertEqual(401, browser.get(route, base_url=self.origin).status_code)

    def test_multipart_csrf_and_reader_write_denials_leave_no_document(self):
        operator, csrf = self.login()
        invalid = ({}, {"Origin": self.origin}, {"Origin": "https://evil.test", "X-CSRF-Token": csrf},
                   {"Origin": self.origin, "X-CSRF-Token": "forged"},
                   {"Origin": self.origin, "X-CSRF-Token": csrf, "Sec-Fetch-Site": "cross-site"})
        for headers in invalid:
            with self.subTest(headers=headers):
                self.assertEqual(403, self.upload(operator, csrf, headers=headers).status_code)
        reader, reader_csrf = self.login("reader")
        self.assertEqual(403, self.upload(reader, reader_csrf).status_code)
        for action in ("extract", "create-task"):
            self.assertEqual(403, self.post(reader, "/api/documents/00000000-0000-0000-0000-000000000000/" + action,
                                           reader_csrf, {}).status_code)
        listing = operator.get("/api/documents", base_url=self.origin)
        self.assertEqual(200, listing.status_code, listing.get_json())
        self.assertEqual([], listing.get_json()["documents"])

    def test_original_hash_dedup_attachment_and_upload_do_not_create_task(self):
        operator, csrf = self.login()
        first = self.upload(operator, csrf)
        self.assertEqual(201, first.status_code, first.get_json())
        document = first.get_json()["document"]
        second = self.upload(operator, csrf, filename="another-name.png")
        self.assertEqual(200, second.status_code, second.get_json())
        self.assertEqual(document["id"], second.get_json()["document"]["id"])
        self.assertEqual(hashlib.sha256(PNG).hexdigest(), document["sha256"])
        self.assertEqual(0, document["extraction_version"])
        self.assertEqual([], self.store.list())
        original = operator.get(f"/api/documents/{document['id']}/original", base_url=self.origin)
        self.assertEqual(PNG, original.data)
        self.assertIn("attachment", original.headers["Content-Disposition"])
        self.assertEqual("nosniff", original.headers["X-Content-Type-Options"])
        self.assertEqual("no-store", original.headers["Cache-Control"])

    def test_active_content_and_oversize_upload_are_rejected_without_persistence(self):
        operator, csrf = self.login()
        for content, filename in ((b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "invoice.svg"),
                                  (b"<html><script>alert(1)</script></html>", "invoice.pdf"),
                                  (PNG + b"0" * (5 * 1024 * 1024), "oversize.png")):
            with self.subTest(filename=filename):
                response = self.upload(operator, csrf, content, filename)
                self.assertIn(response.status_code, (400, 413, 415), response.get_json())
        self.assertEqual([], operator.get("/api/documents", base_url=self.origin).get_json()["documents"])

    def test_direct_task_creation_cannot_forge_document_provenance(self):
        operator, csrf = self.login()
        request = {"title": "Forged provenance", "description": "Synthetic QA", "country": "FR", "skill_id": "invoice-check",
                   "payload": {**invoice_payload(), "_document_source": {"sha256": "0" * 64, "verified_by": "admin"}}}
        response = self.post(operator, "/api/tasks", csrf, request)
        self.assertEqual(400, response.status_code, response.get_json())
        self.assertEqual([], self.store.list())


    def prepared_document(self, browser, csrf):
        response = self.upload(browser, csrf)
        self.assertEqual(201, response.status_code, response.get_json())
        document = response.get_json()["document"]
        response = self.post(browser, f"/api/documents/{document['id']}/extract", csrf,
                             {"version": 0, "language": "fra"})
        self.assertEqual(200, response.status_code, response.get_json())
        return response.get_json()["document"]

    def test_each_field_and_explicit_boolean_confirmation_are_required(self):
        browser, csrf = self.login()
        document = self.prepared_document(browser, csrf)
        valid = self.create_request(document["extraction_version"])
        bad_requests = []
        for value in (False, "true", 1, None):
            bad_requests.append(dict(valid, human_verified=value))
        bad_requests.append(dict(valid, verified_fields=valid["verified_fields"][:-1]))
        bad_requests.append(dict(valid, verified_fields=valid["verified_fields"] + [valid["verified_fields"][0]]))
        forged = copy.deepcopy(valid)
        forged["payload"]["_document_source"] = {"reviewed_by": "forged-admin"}
        forged["verified_fields"].append("_document_source")
        bad_requests.append(forged)
        route = f"/api/documents/{document['id']}/create-task"
        for body in bad_requests:
            with self.subTest(body=body):
                self.assertEqual(400, self.post(browser, route, csrf, body).status_code)
        self.assertEqual([], self.store.list())
        response = self.post(browser, route, csrf, valid)
        self.assertEqual(201, response.status_code, response.get_json())
        task = response.get_json()["task"]
        self.assertEqual("new", task["status"])
        self.assertIsNone(task["result"])
        provenance = task["payload"]["_document_source"]
        self.assertEqual("document-operator", provenance["reviewed_by"])
        self.assertEqual(document["sha256"], provenance["sha256"])
        self.assertEqual(document["id"], provenance["document_id"])
        self.assertEqual("manual", provenance["fields"]["paid"]["origin"])
        self.assertEqual("candidate", provenance["fields"]["total_amount"]["origin"])

    def test_extraction_versions_reject_stale_review_and_duplicate_retry_is_atomic(self):
        browser, csrf = self.login()
        document = self.prepared_document(browser, csrf)
        old = self.create_request(document["extraction_version"])
        route = f"/api/documents/{document['id']}"
        response = self.post(browser, route + "/extract", csrf, {"version": 1, "language": "fra", "force_ocr": True})
        self.assertEqual(200, response.status_code, response.get_json())
        self.assertEqual(409, self.post(browser, route + "/extract", csrf, {"version": 1, "language": "fra"}).status_code)
        self.assertEqual(409, self.post(browser, route + "/create-task", csrf, old).status_code)
        valid = self.create_request(2)
        first = self.post(browser, route + "/create-task", csrf, valid)
        repeat = self.post(browser, route + "/create-task", csrf, valid)
        self.assertEqual(201, first.status_code, first.get_json())
        self.assertEqual(200, repeat.status_code, repeat.get_json())
        self.assertEqual(first.get_json()["task"]["id"], repeat.get_json()["task"]["id"])
        self.assertEqual(1, len(self.store.list()))
        self.assertEqual(409, self.post(browser, route + "/create-task", csrf, dict(valid, title="Different task")).status_code)

    def test_corrected_value_keeps_original_evidence_and_task_edits_cannot_forge_it(self):
        browser, csrf = self.login()
        document = self.prepared_document(browser, csrf)
        data = self.create_request(1)
        data["payload"]["total_amount"] = "121.00"
        response = self.post(browser, f"/api/documents/{document['id']}/create-task", csrf, data)
        self.assertEqual(201, response.status_code, response.get_json())
        task = response.get_json()["task"]
        source = task["payload"]["_document_source"]
        total = source["fields"]["total_amount"]
        self.assertTrue(total["corrected"])
        self.assertEqual("120.00", total["candidate"]["value"])
        self.assertEqual("121.00", total["reviewed_value"])
        forged = copy.deepcopy(task["payload"])
        forged["_document_source"]["fields"]["total_amount"]["candidate"]["quote"] = "Forged evidence"
        response = self.post(browser, f"/api/tasks/{task['id']}/update", csrf,
                             {"version": task["version"], "payload": forged})
        self.assertEqual(400, response.status_code, response.get_json())
        # Omitting provenance must preserve it; later edits are marked as changed.
        updated_payload = invoice_payload()
        response = self.post(browser, f"/api/tasks/{task['id']}/update", csrf,
                             {"version": task["version"], "payload": updated_payload})
        self.assertEqual(200, response.status_code, response.get_json())
        updated = response.get_json()["task"]["payload"]["_document_source"]
        self.assertEqual(total, updated["fields"]["total_amount"])
        self.assertIn("total_amount", updated["changed_since_document_review"])

    def test_untrusted_worker_cannot_inject_payment_or_invent_page_quotes(self):
        browser, csrf = self.login()
        document = self.upload(browser, csrf).get_json()["document"]
        original = fake_extraction()
        invalids = []
        candidate = copy.deepcopy(original)
        candidate["candidates"]["paid"] = {"value": "false", "page": 1, "quote": "Total TTC 120,00 EUR", "bbox": [0, 0, 1, 1], "method": "ocr"}
        invalids.append(candidate)
        candidate = copy.deepcopy(original)
        candidate["candidates"]["total_amount"]["quote"] = "Invented quote absent from the page"
        invalids.append(candidate)
        candidate = copy.deepcopy(original)
        candidate["candidates"]["total_amount"]["page"] = 2
        invalids.append(candidate)
        candidate = copy.deepcopy(original)
        candidate["candidates"]["total_amount"]["bbox"] = [0, 0, 99, 99]
        invalids.append(candidate)
        for invalid in invalids:
            self.app.extensions["documents"].ocr.extract = lambda *args, value=invalid: value
            response = self.post(browser, f"/api/documents/{document['id']}/extract", csrf, {"version": 0, "language": "fra"})
            self.assertEqual(502, response.status_code, response.get_json())
            current = self.app.extensions["documents"].get(document["id"])
            self.assertEqual(0, current["extraction_version"])
            self.assertIsNone(current["extraction"])
        self.assertEqual([], self.store.list())

    def test_document_binary_and_review_provenance_survive_quarantined_restore(self):
        browser, csrf = self.login()
        document = self.prepared_document(browser, csrf)
        response = self.post(browser, f"/api/documents/{document['id']}/create-task", csrf, self.create_request(1))
        self.assertEqual(201, response.status_code, response.get_json())
        task = response.get_json()["task"]
        backup = Path(self.temp.name) / "snapshot"
        backup_database(self.path, self.config.client_id, backup)
        recovered_path = Path(self.temp.name) / "restored.sqlite3"
        restore_database(backup, self.config.client_id, recovered_path)
        recovered_store = Store(recovered_path)
        from admin_agent.documents import DocumentStore
        recovered = DocumentStore(recovered_store)
        self.assertEqual((PNG, "image/png"), recovered.original(document["id"]))
        self.assertEqual(document["extraction"], recovered.get(document["id"])["extraction"])
        self.assertEqual(task["payload"]["_document_source"], recovered_store.get(task["id"])["payload"]["_document_source"])
        with recovered_store.connection() as con:
            self.assertEqual(1, con.execute("SELECT count(*) FROM document_extractions").fetchone()[0])
            self.assertGreater(con.execute("SELECT count(*) FROM document_events").fetchone()[0], 0)
        recovered_auth = AuthStore(recovered_store, self.config.client_id, self.config.client_name, self.config.secret)
        self.assertTrue(all(not user["enabled"] for user in recovered_auth.list_users()))

    def test_concurrent_extraction_does_not_race_or_persist_two_revisions(self):
        documents = self.app.extensions["documents"]
        document, _ = documents.add(PNG, "synthetic.png", language="fra")
        entered, release = threading.Event(), threading.Event()
        results, errors = [], []
        def slow(*args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test timeout")
            return fake_extraction()
        documents.ocr.extract = slow
        def extract():
            try:
                results.append(documents.extract(document["id"], {"version": 0, "language": "fra"}))
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=extract)
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaises(AppError) as refusal:
                documents.extract(document["id"], {"version": 0, "language": "fra"})
            self.assertEqual("extraction_busy", refusal.exception.code)
        finally:
            release.set()
            thread.join(8)
        self.assertFalse(thread.is_alive())
        self.assertEqual([], errors)
        self.assertEqual(1, len(results))
        self.assertEqual(1, documents.get(document["id"])["extraction_version"])

    def test_connector_provenance_cannot_be_forged_removed_or_changed_via_task_api(self):
        browser, csrf = self.login()
        spoof = {"title": "Synthetic forged connector", "description": "QA", "country": "FR", "skill_id": "invoice-check",
                 "payload": {**invoice_payload(), "_connector_source": {"connector_id": "fake", "sha256": "0" * 64}}}
        response = self.post(browser, "/api/tasks", csrf, spoof)
        self.assertEqual(400, response.status_code, response.get_json())
        from admin_agent.connector_cli import import_invoice
        from admin_agent.connectors import SourceItem
        item = SourceItem("qa-import", "source-1", "synthetic.csv", "invoice", "2026-10-02T12:00:00Z", "a" * 64, payload=invoice_payload())
        task, created = import_invoice(self.store, item, "FR")
        self.assertTrue(created)
        source = task["payload"]["_connector_source"]
        tampered = copy.deepcopy(task["payload"])
        tampered["_connector_source"]["sha256"] = "b" * 64
        response = self.post(browser, f"/api/tasks/{task['id']}/update", csrf, {"version": task["version"], "payload": tampered})
        self.assertEqual(400, response.status_code, response.get_json())
        payload = invoice_payload()
        payload["total_amount"] = "121.00"
        response = self.post(browser, f"/api/tasks/{task['id']}/update", csrf, {"version": task["version"], "payload": payload})
        self.assertEqual(200, response.status_code, response.get_json())
        retained = response.get_json()["task"]["payload"]["_connector_source"]
        self.assertEqual(source["sha256"], retained["sha256"])
        self.assertEqual(source["mapped_sha256"], retained["mapped_sha256"])
        self.assertIn("total_amount", retained["changed_since_import"])

    def test_risk_only_in_source_text_blocks_followup_without_drafting(self):
        browser, csrf = self.login()
        source = fake_extraction()
        source["pages"][0]["text"] += "\nAcompte reçu : 20,00 EUR. Le solde reste à rapprocher."
        self.app.extensions["documents"].ocr.extract = lambda *args: copy.deepcopy(source)
        document = self.prepared_document(browser, csrf)
        data = self.create_request(1)
        data["skill_id"] = "receivables-followup"
        data["description"] = "Préparer le suivi après vérification."
        data["payload"].update(issue_date=(date.today() - timedelta(days=90)).isoformat(),
                               due_date=(date.today() - timedelta(days=60)).isoformat(), disputed=False)
        data["verified_fields"] = sorted(data["payload"])
        response = self.post(browser, f"/api/documents/{document['id']}/create-task", csrf, data)
        self.assertEqual(201, response.status_code, response.get_json())
        task = response.get_json()["task"]
        response = self.post(browser, f"/api/tasks/{task['id']}/analyze", csrf, {})
        self.assertEqual(200, response.status_code, response.get_json())
        reviewed = response.get_json()["task"]
        self.assertEqual("blocked", reviewed["status"])
        self.assertEqual("", reviewed["result"]["draft"])

    def test_revocation_during_ocr_prevents_new_extraction_commit(self):
        browser, csrf = self.login()
        document = self.upload(browser, csrf).get_json()["document"]
        def revoke_then_return(*args):
            self.auth.revoke_user_sessions("document-operator")
            return fake_extraction()
        self.app.extensions["documents"].ocr.extract = revoke_then_return
        response = self.post(browser, f"/api/documents/{document['id']}/extract", csrf, {"version": 0, "language": "fra"})
        self.assertIn(response.status_code, (401, 403), response.get_json())
        current = self.app.extensions["documents"].get(document["id"])
        self.assertEqual(0, current["extraction_version"])
        self.assertIsNone(current["extraction"])


class IndependentConnectorReviewTests(unittest.TestCase):
    def test_forbidden_destination_forms_and_encoded_traversal_are_rejected(self):
        from admin_agent.connectors import ConnectorError, ReadOnlyHTTPS
        for url in ("http://public.example", "https://127.0.0.1", "https://[::1]", "https://u:password@public.example",
                    "https://public.example:8443", "https://public.example/a/%2e%2e/private", "https://public.example/a/%252e%252e/"):
            with self.subTest(url=url), self.assertRaises(ConnectorError):
                ReadOnlyHTTPS(url)
        client = ReadOnlyHTTPS("https://cloud.example.test/root/")
        for href in ("https://evil.example.test/root/a.pdf", "/root/../a.pdf", "/root/%2e%2e/a.pdf", "/root/%252fsecret.pdf",
                     "/root/a/b.pdf", "/root/a.pdf?token=secret", "//evil.example.test/root/a.pdf"):
            with self.subTest(href=href), self.assertRaises(ConnectorError):
                client.child(href)

    def test_mixed_public_private_dns_fails_before_opening_transport(self):
        import socket
        from admin_agent.connectors import ConnectorError, ReadOnlyHTTPS
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                   (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
        with patch("admin_agent.connectors.socket.getaddrinfo", return_value=answers), patch("admin_agent.connectors.PinnedHTTPS") as transport:
            with self.assertRaises(ConnectorError):
                ReadOnlyHTTPS("https://cloud.example.test/root/").request("GET")
            transport.assert_not_called()

    def test_readonly_transport_refuses_redirect_without_credential_forwarding(self):
        import socket
        from admin_agent.connectors import ConnectorError, ReadOnlyHTTPS
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        connection = Mock()
        connection.getresponse.return_value.status = 302
        with patch("admin_agent.connectors.socket.getaddrinfo", return_value=answers), patch("admin_agent.connectors.PinnedHTTPS", return_value=connection) as factory:
            client = ReadOnlyHTTPS("https://cloud.example.test/root/")
            with self.assertRaises(ConnectorError):
                client.request("GET", headers={"Authorization": "Synthetic token"})
            self.assertEqual(1, factory.call_count)
            self.assertEqual(1, connection.request.call_count)
            self.assertEqual("GET", connection.request.call_args.args[0])
            connection.close.assert_called_once()
            for method in ("POST", "PUT", "PATCH", "DELETE", "MOVE", "COPY"):
                with self.subTest(method=method), self.assertRaises(ConnectorError):
                    client.request(method)

    def test_folder_symlink_and_world_readable_credentials_are_rejected(self):
        from admin_agent.connectors import ConnectorError, read_secret, scan_folder
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            secret = root / "private.txt"
            secret.write_text("Synthetic credential")
            secret.chmod(0o644)
            with self.assertRaises(ConnectorError):
                read_secret(secret)
            intake = root / "intake"
            intake.mkdir()
            (intake / "invoice.pdf").symlink_to(secret)
            with self.assertRaises(ConnectorError):
                scan_folder({"id": "qa-folder", "folder": str(intake)})

    def test_csv_unknown_financial_state_is_preserved_and_changed_source_hashes_differ(self):
        from admin_agent.connectors import scan_csv
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.csv"
            config = {"id": "qa-csv", "file": str(source), "mapping": {"source_id": "id", "invoice_number": "ref", "paid": "paid", "disputed": "disputed", "total_amount": "amount"},
                      "delimiter": ";", "decimal_separator": ",", "date_format": "%Y-%m-%d"}
            source.write_text("id;ref;paid;disputed;amount\n1;QA-1;unknown;;120,00\n")
            original = scan_csv(config)[0]
            self.assertNotIn("paid", original.payload)
            self.assertNotIn("disputed", original.payload)
            self.assertEqual("120.00", original.payload["total_amount"])
            source.write_text("id;ref;paid;disputed;amount\n1;QA-1;unknown;;121,00\n")
            changed = scan_csv(config)[0]
            self.assertEqual(original.source_key, changed.source_key)
            self.assertNotEqual(original.sha256, changed.sha256)

    def test_connector_retry_preserves_edits_and_refuses_changed_raw_or_mapping(self):
        from admin_agent.connector_cli import import_invoice
        from admin_agent.connectors import ConnectorError, SourceItem
        with tempfile.TemporaryDirectory() as temp:
            store = Store(Path(temp) / "synthetic.sqlite3")
            item = SourceItem("qa-import", "source-1", "synthetic.csv", "invoice", "2026-10-02T12:00:00Z", "a" * 64, payload=invoice_payload())
            task, created = import_invoice(store, item, "FR")
            self.assertTrue(created)
            updated = store.update(task["id"], {"title": "Human correction retained", "version": task["version"]})
            same = copy.deepcopy(item)
            same.fetched_at = "2026-10-02T13:00:00Z"
            repeat, created = import_invoice(store, same, "FR")
            self.assertFalse(created)
            self.assertEqual(updated, repeat)
            changed = copy.deepcopy(item)
            changed.sha256 = "b" * 64
            with self.assertRaises(ConnectorError):
                import_invoice(store, changed, "FR")
            changed = copy.deepcopy(item)
            changed.payload["total_amount"] = "121.00"
            with self.assertRaises(ConnectorError):
                import_invoice(store, changed, "FR")
            with self.assertRaises(ConnectorError):
                import_invoice(store, item, "ES")
            self.assertEqual(1, len(store.list()))
            self.assertEqual(updated, store.get(task["id"]))


if __name__ == "__main__":
    unittest.main()
