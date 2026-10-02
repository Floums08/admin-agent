"""Original preservation, isolation, OCR distrust and human-review regressions."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import importlib.util
import io
import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from unittest.mock import patch

PRODUCTION_AVAILABLE = all(importlib.util.find_spec(name) for name in ("flask", "pyotp", "cryptography"))
if PRODUCTION_AVAILABLE:
    import pyotp
    from admin_agent.documents import DocumentStore, OCRClient, MAX_FILE_BYTES, validate_extraction, document_risk_flags
    from admin_agent.errors import AppError
    from admin_agent.ops import backup_database, restore_database
    from admin_agent.production import ProductionConfig, create_app
    from admin_agent.storage import Store


def sample_extraction():
    return {"version": 1, "media_type": "application/pdf", "review_required": True,
            "engine": {"name": "poppler+tesseract", "languages": "fra+spa+eng"}, "warnings": [],
            "pages": [{"number": 1, "text": "Facture TEST-01\nTotal TTC 120,00 EUR", "method": "native", "width": 600, "height": 800, "words": []}],
            "candidates": {"invoice_number": {"value": "TEST-01", "page": 1, "quote": "Facture TEST-01", "bbox": [0.1, 0.1, 0.5, 0.2], "method": "native"},
                           "total_amount": {"value": "120.00", "page": 1, "quote": "Total TTC 120,00 EUR", "bbox": [0.1, 0.5, 0.8, 0.6], "method": "native"}}}


class FakeOCR:
    def extract(self, *_args):
        return sample_extraction()


@unittest.skipUnless(PRODUCTION_AVAILABLE, "Installer requirements-production.txt pour la validation production")
class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = ProductionConfig("client-a", "Client fictif", "https://client-a.test", Path(self.temp.name) / "db.sqlite3", secrets.token_hex(32).encode())
        self.app = create_app(self.config, ocr_client=FakeOCR())
        self.docs = self.app.extensions["documents"]
        self.store = self.app.extensions["store"]
        self.auth = self.app.extensions["auth"]
        self.auth.clock = lambda: 1800000000
        self.password = "Synthetique-mot-de-passe-42"
        self.client = self.app.test_client()
        self.csrf = ""
        self.content = b"%PDF-1.7\nSynthetic bytes; the worker validates the complete format."

    def tearDown(self):
        self.temp.cleanup()

    def login(self, role="admin"):
        enrollment = self.auth.provision_user(role + "-test", self.password, role)
        bootstrap = self.get("/api/session").get_json()
        self.csrf = bootstrap["csrf_token"]
        response = self.post("/api/login", {"username": role + "-test", "password": self.password, "otp": pyotp.TOTP(enrollment["totp_secret"]).at(1800000000)})
        self.assertEqual(200, response.status_code)
        self.csrf = response.get_json()["csrf_token"]

    def get(self, path):
        return self.client.get(path, base_url=self.config.public_origin)

    def post(self, path, data):
        return self.client.post(path, json=data, base_url=self.config.public_origin,
                                headers={"Origin": self.config.public_origin, "X-CSRF-Token": self.csrf})

    def upload(self, content=None, headers=None):
        response = self.client.post("/api/documents", base_url=self.config.public_origin,
                                data={"file": (io.BytesIO(content or self.content), "original.pdf", "application/pdf"), "language": "fra"},
                                headers=headers or {"Origin": self.config.public_origin, "X-CSRF-Token": self.csrf})
        response.request.environ["wsgi.input"].close()
        return response

    def extracted(self):
        doc, _ = self.docs.add(self.content, "original.pdf")
        return self.docs.extract(doc["id"], {"version": 0, "language": "fra"})

    def reviewed_data(self):
        return {"title": "Facture relue", "description": "Original vérifié", "skill_id": "invoice-check", "country": "FR",
                "payload": {"invoice_number": "TEST-01", "total_amount": "125.00", "paid": False}, "extraction_version": 1,
                "human_verified": True, "verified_fields": ["invoice_number", "total_amount", "paid"]}

    def test_upload_preserves_original_and_compact_list_excludes_extraction(self):
        self.login()
        # This also exercises multipart streaming above Werkzeug's 64-KiB chunk.
        content = self.content + b" " * 180000
        response = self.upload(content)
        self.assertEqual(201, response.status_code, response.get_data(as_text=True))
        doc = response.get_json()["document"]
        self.assertEqual("admin-test", doc["created_by"])
        self.assertEqual("uploaded", doc["status"])
        original = self.get(f"/api/documents/{doc['id']}/original")
        self.assertEqual(content, original.data)
        self.assertEqual("nosniff", original.headers["X-Content-Type-Options"])
        self.assertTrue(original.headers["Content-Disposition"].startswith("attachment;"))
        self.assertNotIn("extraction", self.get("/api/documents").get_json()["documents"][0])
        self.assertNotIn("content", self.get(f"/api/documents/{doc['id']}").get_json()["document"])

    def test_auth_csrf_and_reader_cannot_mutate_documents(self):
        doc = self.extracted()
        self.assertEqual(401, self.get("/api/documents").status_code)
        self.assertEqual(401, self.get(f"/api/documents/{doc['id']}/original").status_code)
        self.login("reader")
        self.assertEqual(200, self.get("/api/documents").status_code)
        self.assertEqual(200, self.get(f"/api/documents/{doc['id']}/original").status_code)
        self.assertEqual(403, self.upload().status_code)
        self.assertEqual(403, self.post(f"/api/documents/{doc['id']}/extract", {"version": 1}).status_code)
        self.assertEqual(403, self.post(f"/api/documents/{doc['id']}/create-task", self.reviewed_data()).status_code)
        self.assertEqual(403, self.upload(headers={"Origin": self.config.public_origin, "X-CSRF-Token": "invalid"}).status_code)
        caps = self.get("/api/session").get_json()["capabilities"]
        self.assertTrue(caps["documents_read"])
        self.assertFalse(caps["documents_create_task"])

    def test_json_limit_not_relaxed_and_upload_is_bounded(self):
        self.login()
        self.assertEqual(413, self.post("/api/tasks", {"description": "x" * 70000}).status_code)
        self.assertEqual(413, self.upload(self.content + b" " * MAX_FILE_BYTES).status_code)
        self.assertEqual([], self.docs.list())

    def test_mime_and_language_rejected_without_parsing(self):
        for args in ((b"<script>bad</script>", "image.png", "image/png"), (self.content, "x.png", "image/png"), (self.content, "bad\nname.pdf", None)):
            with self.assertRaises(AppError):
                self.docs.add(*args)
        with self.assertRaises(AppError):
            self.docs.add(self.content, "x.pdf", language="../bad")
        doc, _ = self.docs.add(self.content, "../../x.pdf")
        self.assertEqual("x.pdf", doc["filename"])

    def test_hash_deduplication_and_capacity_are_atomic(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            outputs = list(pool.map(lambda n: self.docs.add(self.content, f"copy-{n}.pdf"), range(12)))
        self.assertEqual(1, sum(created for _doc, created in outputs))
        self.assertEqual(1, len({doc["id"] for doc, _created in outputs}))
        with patch("admin_agent.documents.MAX_DOCUMENTS", 1):
            self.assertFalse(self.docs.add(self.content, "retry.pdf")[1])
            with self.assertRaises(AppError):
                self.docs.add(self.content + b"other", "other.pdf")
        self.assertEqual(1, len(self.docs.list()))

    def test_connector_stable_source_changed_is_conflict(self):
        source = {"connector_id": "folder", "source_key": "source-001", "fetched_at": "2026-10-02T00:00:00Z"}
        first, _ = self.docs.add(self.content, "original.pdf", source=source)
        self.assertEqual(first["id"], self.docs.add(self.content, "renamed.pdf", source=source)[0]["id"])
        with self.assertRaises(AppError) as caught:
            self.docs.add(self.content + b"changed", "original.pdf", source=source)
        self.assertEqual("source_changed", caught.exception.code)
        self.assertEqual([source], self.docs.get(first["id"])["sources"])

    def test_worker_quotes_and_shapes_are_untrusted(self):
        for mutate in (lambda data: data["candidates"]["total_amount"].update(quote="invented"),
                       lambda data: data["candidates"]["total_amount"].update(page=True),
                       lambda data: data["candidates"]["total_amount"].update(bbox=[0, 0, 2, 1]),
                       lambda data: data["pages"][0].update(width=float("nan")),
                       lambda data: data.update(review_required=False),
                       lambda data: data["candidates"].update(paid={"value": "false"})):
            data = sample_extraction()
            mutate(data)
            with self.assertRaises(AppError):
                validate_extraction(data, "application/pdf")

    def test_failed_extraction_preserves_original_and_retries(self):
        doc, _ = self.docs.add(self.content, "original.pdf")
        with patch.object(self.docs.ocr, "extract", side_effect=RuntimeError("secret-network-value")):
            with self.assertRaises(AppError) as caught:
                self.docs.extract(doc["id"], {"version": 0})
        failed = self.docs.get(doc["id"])
        self.assertEqual("failed", failed["status"])
        self.assertNotIn("secret-network-value", json.dumps(failed))
        self.assertEqual(self.content, self.docs.original(doc["id"])[0])
        retry = self.docs.extract(doc["id"], {"version": 0})
        self.assertEqual(1, retry["extraction_version"])

    def test_review_requires_all_fields_current_version_and_no_auto_approval(self):
        doc = self.extracted()
        for changed in ({"human_verified": False}, {"verified_fields": ["invoice_number"]}, {"extraction_version": 0}, {"payload": {"_document_source": {}}}):
            data = dict(self.reviewed_data(), **changed)
            with self.assertRaises(AppError):
                self.docs.create_task(doc["id"], data)
        task, linked, created = self.docs.create_task(doc["id"], self.reviewed_data())
        self.assertTrue(created)
        self.assertEqual("new", task["status"])
        self.assertIsNone(task["result"])
        self.assertEqual(task["id"], linked["task_id"])
        provenance = task["payload"]["_document_source"]
        self.assertTrue(provenance["fields"]["total_amount"]["corrected"])
        self.assertEqual("120.00", provenance["fields"]["total_amount"]["candidate"]["value"])
        self.assertEqual("125.00", provenance["fields"]["total_amount"]["reviewed_value"])
        self.assertEqual("manual", provenance["fields"]["paid"]["origin"])

    def test_task_link_idempotence_under_concurrency_and_changed_retry(self):
        doc = self.extracted()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.docs.create_task(doc["id"], self.reviewed_data()), range(8)))
        self.assertEqual(1, sum(created for _task, _doc, created in results))
        self.assertEqual(1, len(self.store.list()))
        with self.assertRaises(AppError):
            self.docs.create_task(doc["id"], dict(self.reviewed_data(), title="Different"))

    def test_no_forged_or_replaced_provenance_and_edits_tracked(self):
        data = self.reviewed_data()
        with self.assertRaises(AppError):
            self.store.create({key: value for key, value in dict(data, payload={"_document_source": {"fake": True}}).items() if key in {"title", "description", "skill_id", "country", "payload"}})
        doc = self.extracted()
        task, _doc, _ = self.docs.create_task(doc["id"], data)
        forged = deepcopy(task["payload"])
        forged["_document_source"]["sha256"] = "forged"
        with self.assertRaises(AppError):
            self.store.update(task["id"], {"version": 1, "payload": forged})
        changed = dict(data["payload"], total_amount="150.00")
        updated = self.store.update(task["id"], {"version": 1, "payload": changed})
        source = updated["payload"]["_document_source"]
        self.assertEqual(doc["sha256"], source["sha256"])
        self.assertEqual(["total_amount"], source["changed_since_document_review"])
        self.assertEqual("125.00", source["fields"]["total_amount"]["reviewed_value"])

    def test_stale_extraction_cannot_create_or_replace_current_revision(self):
        doc = self.extracted()
        self.docs.extract(doc["id"], {"version": 1, "force_ocr": True})
        with self.assertRaises(AppError):
            self.docs.create_task(doc["id"], self.reviewed_data())
        with self.assertRaises(AppError):
            self.docs.extract(doc["id"], {"version": 1})
        self.assertEqual(2, self.docs.get(doc["id"])["extraction_version"])
        with self.store.connection() as con:
            self.assertEqual(2, con.execute("SELECT count(*) FROM document_extractions").fetchone()[0])

    def test_extraction_lease_prevents_parallel_work(self):
        doc, _ = self.docs.add(self.content, "x.pdf")
        entered, release = threading.Event(), threading.Event()
        def blocking(*_args):
            entered.set()
            release.wait(5)
            return sample_extraction()
        with patch.object(self.docs.ocr, "extract", side_effect=blocking), ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.docs.extract, doc["id"], {"version": 0})
            self.assertTrue(entered.wait(3))
            try:
                with self.assertRaises(AppError) as caught:
                    self.docs.extract(doc["id"], {"version": 0})
                self.assertEqual("extraction_busy", caught.exception.code)
            finally:
                release.set()
            self.assertEqual(1, first.result()["extraction_version"])

    def test_original_and_provenance_survive_online_backup_restore(self):
        doc = self.extracted()
        task, _, _ = self.docs.create_task(doc["id"], self.reviewed_data())
        destination = Path(self.temp.name) / "backup"
        backup_database(self.store.path, "client-a", destination)
        restored = Path(self.temp.name) / "restored.sqlite3"
        restore_database(destination, "client-a", restored)
        copied_store = Store(restored)
        copied_docs = DocumentStore(copied_store)
        self.assertEqual(self.content, copied_docs.original(doc["id"])[0])
        self.assertEqual(doc["sha256"], copied_store.get(task["id"])["payload"]["_document_source"]["sha256"])
        self.assertEqual(sample_extraction(), copied_docs.get(doc["id"])["extraction"])

    def test_client_identity_cannot_be_rebound(self):
        self.docs.add(self.content, "x.pdf")
        with self.assertRaises(ValueError):
            create_app(replace(self.config, client_id="client-b"))
        with self.assertRaises(ValueError):
            create_app(replace(self.config, ocr_url="http://attacker.invalid"))

    def test_ocr_disabled_is_explicit_and_read_upload_remain_available(self):
        app = create_app(self.config)
        docs = app.extensions["documents"]
        doc, _ = docs.add(self.content, "x.pdf")
        with self.assertRaises(AppError) as caught:
            docs.extract(doc["id"], {"version": 0})
        self.assertEqual("ocr_disabled", caught.exception.code)
        self.assertEqual("uploaded", docs.get(doc["id"])["status"])

    def test_ocr_client_rejects_arbitrary_endpoints_and_redirects(self):
        for url in ("https://example.com", "http://ocr:8766/", "http://127.0.0.1:8766", "http://ocr:8766@evil"):
            with self.assertRaises(ValueError):
                OCRClient(url)
        client = OCRClient("http://ocr:8766")
        from urllib.error import HTTPError
        with patch.object(client.opener, "open", side_effect=HTTPError(client.url, 302, "redirect", {}, None)):
            with self.assertRaises(AppError) as caught:
                client.extract(self.content, "application/pdf", "fra")
        self.assertEqual("ocr_unavailable", caught.exception.code)

    def test_risk_context_is_retained_with_exact_quotes_despite_field_selection(self):
        extracted = sample_extraction()
        extracted["pages"][0]["text"] += "\nRèglement partiel reçu. Nouveau RIB. Factura rectificativa. Autoliquidación."
        flags = document_risk_flags(extracted)
        self.assertEqual({"partial_payment", "bank_change", "credit_note", "special_vat"}, {item["code"] for item in flags})
        for item in flags:
            self.assertIn(item["quote"], extracted["pages"][item["page"] - 1]["text"])
        doc, _ = self.docs.add(self.content, "risk.pdf")
        with patch.object(self.docs.ocr, "extract", return_value=extracted):
            self.docs.extract(doc["id"], {"version": 0})
        task, _, _ = self.docs.create_task(doc["id"], self.reviewed_data())
        self.assertEqual(flags, task["payload"]["_document_source"]["document_risk_flags"])

    def test_multiple_tax_rate_and_advance_mentions_are_review_triggers(self):
        for text, expected in (("TVA 20 %\nTVA 20,00 %", set()), ("IVA 10%\nIVA 21%", {"multiple_tax_rates"}),
                               ("An advance payment has been received.", {"partial_payment"}), ("Retenue de garantie 5 %", {"retention"})):
            extraction = sample_extraction()
            extraction["pages"][0]["text"] = text
            flags = document_risk_flags(extraction)
            self.assertEqual(expected, {flag["code"] for flag in flags})
            for flag in flags:
                self.assertIn(flag["quote"], text)


if __name__ == "__main__":
    unittest.main()
