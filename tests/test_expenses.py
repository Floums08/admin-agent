"""Expense receipt controls: synthetic evidence, no reimbursement or tax claims."""
from copy import deepcopy
from datetime import date
import importlib.util
from pathlib import Path
import os
import secrets
import tempfile
import unittest

from admin_agent.engine import analyze, expense_duplicates, result_status
from admin_agent.errors import AppError
from admin_agent import ocr
from ocr_fixtures import make_pdf, make_image

PRODUCTION = all(importlib.util.find_spec(name) for name in ("flask", "pyotp", "cryptography"))


def expense_payload(**changes):
    value = {"merchant": "Restaurant Demo", "expense_date": "2026-09-30", "total_amount": "42.00", "currency": "EUR",
             "employee_ref": "EMP-SYNTHETIC", "business_purpose": "Repas de déplacement fictif", "category": "meals",
             "payment_method": "employee_card", "payment_confirmed": True, "paid_by_company": False, "reimbursed": False,
             "business_only": True, "policy_confirmed": True, "policy_ref": "POL-DEMO-2026"}
    value.update(changes)
    return value


def task(payload, source=True):
    value = deepcopy(payload)
    if source:
        value["_document_source"] = {"document_id": "synthetic-document", "sha256": "a" * 64, "extraction_version": 1,
                                      "human_verified": True, "document_risk_flags": [],
                                      "fields": {field: {"reviewed_value": value[field]} for field in ("merchant", "expense_date", "total_amount", "currency")}}
    return {"id": "expense-test", "title": "Reçu synthétique", "description": "Exercice seulement", "skill_id": "expense-review", "country": "FR", "payload": value}


class ExpenseEngineTests(unittest.TestCase):
    def check(self, payload=None, **options):
        return analyze(task(payload or expense_payload()), today=date(2026, 10, 4), expense_duplicate_ids=options.get("duplicates", []))

    def test_complete_receipt_needs_review_and_never_refunds(self):
        result = self.check()
        self.assertEqual(result_status(result), "needs_review")
        self.assertIn("42.00 EUR", result["draft"])
        self.assertFalse(result["outbound_executed"])
        self.assertNotIn("invoice_number", result["missing_fields"])
        self.assertNotIn("customer", result["missing_fields"])
        self.assertNotIn("due_date", result["missing_fields"])

    def test_payment_business_policy_booleans_cannot_be_guessed(self):
        for field in ("paid_by_company", "reimbursed", "business_only", "policy_confirmed", "payment_confirmed"):
            for value in (None, "false", "true", 0, 1):
                with self.subTest(field=field, value=value):
                    payload = expense_payload(**{field: value})
                    if value is None:
                        del payload[field]
                    result = self.check(payload)
                    self.assertEqual(result_status(result), "blocked")
                    self.assertEqual(result["draft"], "")

    def test_already_paid_company_reimbursed_mixed_or_unconfirmed_stops(self):
        for overrides in ({"paid_by_company": True}, {"reimbursed": True}, {"business_only": False}, {"policy_confirmed": False},
                          {"payment_confirmed": False}, {"payment_method": "company_card", "paid_by_company": False}):
            self.assertEqual(result_status(self.check(expense_payload(**overrides))), "blocked")

    def test_limits_dates_and_observed_tax(self):
        for overrides in ({"total_amount": "0.00"}, {"total_amount": "-1"}, {"expense_date": "2026-02-30"}, {"expense_date": "2027-01-01"},
                          {"policy_limit": "40.00", "policy_currency": "EUR"}, {"policy_limit": "50.00", "policy_currency": "USD"},
                          {"policy_limit": "50.00"}, {"policy_currency": "EUR"}, {"vat_amount": "43.00"}, {"category": "unrecognized"}):
            with self.subTest(overrides=overrides):
                self.assertEqual(result_status(self.check(expense_payload(**overrides))), "blocked")
        self.assertEqual(result_status(self.check(expense_payload(policy_limit="42.00", policy_currency="EUR", vat_amount="4.20"))), "needs_review")

    def test_missing_original_false_provenance_or_changed_receipt_stops(self):
        original = task(expense_payload())
        for source in (None, {}, dict(original["payload"]["_document_source"], human_verified=False),
                       dict(original["payload"]["_document_source"], sha256="fake")):
            changed = deepcopy(original)
            changed["payload"]["_document_source"] = source
            self.assertEqual(result_status(analyze(changed, expense_duplicate_ids=[])), "blocked")
        for field, value in (("merchant", "Other"), ("total_amount", "99.00"), ("currency", "USD"), ("expense_date", "2026-09-29")):
            changed = deepcopy(original)
            changed["payload"][field] = value
            self.assertEqual(result_status(analyze(changed, expense_duplicate_ids=[])), "blocked")

    def test_multiple_vat_rates_can_be_reviewed_without_tax_computation(self):
        value = task(expense_payload())
        value["payload"]["_document_source"]["document_risk_flags"] = [{"code": "multiple_tax_rates", "page": 1, "quote": "TVA 10 % et TVA 20 %"}, {"code": "special_vat", "page": 1, "quote": "autoliquidation"}]
        result = analyze(value, expense_duplicate_ids=[])
        self.assertEqual(result_status(result), "needs_review")
        self.assertFalse(any(check["name"] == "vat_arithmetic" for check in result["checks"]))
        for code in ("partial_payment", "credit_note", "bank_change", "retention", "unknown"):
            value["payload"]["_document_source"]["document_risk_flags"] = [{"code": code}]
            self.assertEqual(result_status(analyze(value, expense_duplicate_ids=[])), "blocked")

    def test_current_duplicate_check_is_required_and_compares_other_claimants(self):
        self.assertEqual(result_status(self.check(duplicates=None)), "blocked")
        self.assertEqual(result_status(self.check(duplicates=["other-id"])), "blocked")
        first, second = task(expense_payload()), task(expense_payload(merchant=" restaurant   demo ", total_amount="42", employee_ref="OTHER"))
        second["id"] = "second"
        self.assertEqual(expense_duplicates(first, [first, second]), ["second"])
        second["payload"]["currency"] = "USD"
        self.assertEqual(expense_duplicates(first, [second]), [])


def receipt_extraction():
    text = "Commerçant: Restaurant Demo\nDate: 2026-09-30\nTotal: 42,00\nDevise: EUR"
    fields = expense_payload()
    return {"version": 1, "media_type": "application/pdf", "review_required": True, "engine": {"name": "poppler+tesseract"}, "warnings": [],
            "pages": [{"number": 1, "text": text, "method": "native", "width": 600, "height": 800, "words": []}],
            "candidates": {field: {"value": fields[field], "page": 1, "quote": line, "bbox": [0.1, 0.1, 0.8, 0.9], "method": "native"}
                           for field, line in zip(("merchant", "expense_date", "total_amount", "currency"), text.splitlines())}}


@unittest.skipUnless(PRODUCTION, "Production dependencies required")
class ExpenseDocumentTests(unittest.TestCase):
    def setUp(self):
        from admin_agent.production import ProductionConfig, create_app
        self.temp = tempfile.TemporaryDirectory()
        config = ProductionConfig("expense-test", "Test synthétique", "https://expense.test", Path(self.temp.name) / "db.sqlite3", secrets.token_hex(32).encode())
        class OCR:
            def extract(self, *_args):
                return receipt_extraction()
        self.app = create_app(config, ocr_client=OCR())
        self.docs, self.store = self.app.extensions["documents"], self.app.extensions["store"]

    def tearDown(self):
        self.temp.cleanup()

    def promote(self, suffix="1", **changes):
        doc, _ = self.docs.add(b"%PDF-1.7\nsynthetic" + suffix.encode(), "receipt.pdf")
        doc = self.docs.extract(doc["id"], {"version": 0, "language": "fra"})
        payload = expense_payload(**changes)
        data = {"title": "Reçu synthétique", "description": "Original relu", "country": "FR", "skill_id": "expense-review",
                "payload": payload, "extraction_version": 1, "human_verified": True, "verified_fields": list(payload)}
        return self.docs.create_task(doc["id"], data)[0]

    def test_original_review_creates_expense_and_false_source_is_rejected(self):
        created = self.promote()
        source = created["payload"]["_document_source"]
        self.assertEqual(source["fields"]["merchant"]["origin"], "candidate")
        result = analyze(created, expense_duplicate_ids=[])
        self.assertEqual(result_status(result), "needs_review")
        forged = task(expense_payload())
        forged.pop("id")
        with self.assertRaises(AppError):
            self.store.create(forged)
        with self.assertRaises(AppError):
            self.store.update(created["id"], {"version": created["version"], "payload": dict(created["payload"], _document_source={})})

    def test_duplicate_created_after_analysis_blocks_approval_in_transaction(self):
        first = self.promote()
        reviewed = self.store.save_analysis(first["id"], analyze(first, expense_duplicate_ids=[]), first["version"])
        self.promote("2", employee_ref="OTHER-PERSON")
        with self.assertRaises(AppError) as duplicate:
            self.store.review(first["id"], "approve", "Vérifié", reviewed["version"])
        self.assertEqual(duplicate.exception.code, "expense_duplicate_detected")

    def test_document_requires_individual_confirmation_for_expense_fields(self):
        doc, _ = self.docs.add(b"%PDF-1.7 synthetic missing confirmation", "receipt.pdf")
        self.docs.extract(doc["id"], {"version": 0})
        payload = expense_payload()
        with self.assertRaises(AppError):
            self.docs.create_task(doc["id"], {"title": "Expense", "description": "Test", "country": "FR", "skill_id": "expense-review", "payload": payload,
                                            "extraction_version": 1, "human_verified": True, "verified_fields": ["merchant"]})

    def test_edited_receipt_requires_explicit_reconfirmation_and_preserves_history(self):
        first = self.promote()
        source = deepcopy(first["payload"]["_document_source"])
        changed = self.store.update(first["id"], {"version": first["version"], "payload": dict(first["payload"], total_amount="43.00")})
        self.assertEqual(result_status(analyze(changed, expense_duplicate_ids=[])), "blocked")
        request = {"task_version": changed["version"], "extraction_version": 1, "human_verified": True,
                   "verified_fields": ["merchant", "expense_date", "total_amount", "currency"]}
        confirmed, _ = self.docs.reverify_expense(source["document_id"], request)
        self.assertIsNone(confirmed["result"])
        self.assertEqual(confirmed["status"], "new")
        self.assertEqual(confirmed["version"], changed["version"] + 1)
        final_source = confirmed["payload"]["_document_source"]
        self.assertEqual(final_source["fields"], source["fields"])
        self.assertEqual(final_source["sha256"], source["sha256"])
        self.assertEqual(final_source["receipt_reviews"][-1]["fields"]["total_amount"]["reviewed_value"], "43.00")
        self.assertEqual(result_status(analyze(confirmed, expense_duplicate_ids=[])), "needs_review")
        with self.assertRaises(AppError) as stale:
            self.docs.reverify_expense(source["document_id"], request)
        self.assertEqual(stale.exception.code, "version_conflict")

    def test_reconfirmation_rejects_false_partial_confirmation_and_stale_extraction(self):
        first = self.promote()
        source = first["payload"]["_document_source"]
        request = {"task_version": first["version"], "extraction_version": 1, "human_verified": True,
                   "verified_fields": ["merchant", "expense_date", "total_amount", "currency"]}
        for changes in ({"human_verified": False}, {"verified_fields": ["merchant"]}, {"task_version": True}, {"extraction_version": 2}):
            with self.subTest(changes=changes), self.assertRaises(AppError):
                self.docs.reverify_expense(source["document_id"], dict(request, **changes))


@unittest.skipUnless(all(tool.is_file() for tool in ocr.TOOLS.values()), "Native OCR tools required")
class ReceiptOCRTests(unittest.TestCase):
    def test_native_french_spanish_receipts_have_source_candidates(self):
        for lines in (["Commerçant: Restaurant Demo", "Date: 2026-09-30", "Total TTC: 42,00", "Devise: EUR", "Reçu synthétique sans numéro de facture ni client déclaré."],
                      ["Comercio: Restaurante Demo", "Fecha: 2026-09-30", "Importe total: 42,00", "Moneda: EUR", "Recibo sintetico de prueba, sin numero de factura ni cliente."]):
            result = ocr.extract_document(make_pdf(lines), "application/pdf", "eng")
            self.assertEqual(result["candidates"]["expense_date"]["value"], "2026-09-30")
            self.assertEqual(result["candidates"]["total_amount"]["value"], "42.00")
            self.assertIn("merchant", result["candidates"])
            self.assertNotIn("paid_by_company", result["candidates"])
            self.assertNotIn("reimbursed", result["candidates"])
            for candidate in result["candidates"].values():
                self.assertIn(candidate["quote"], result["pages"][candidate["page"] - 1]["text"])

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow required")
    def test_real_png_receipt_produces_only_document_facts(self):
        result = ocr.extract_document(make_image(["Merchant: Demo Restaurant", "Receipt date: 2026-09-30", "Total: 42.00", "Currency: EUR", "Payment unknown - synthetic exercise"]), "image/png", "eng")
        self.assertEqual(result["candidates"]["merchant"]["value"], "Demo Restaurant")
        self.assertEqual(result["candidates"]["expense_date"]["value"], "2026-09-30")
        self.assertEqual(result["candidates"]["total_amount"]["value"], "42.00")
        self.assertFalse({"paid_by_company", "reimbursed", "policy_confirmed", "payment_confirmed"} & set(result["candidates"]))

    @unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow required")
    def test_real_french_spanish_png_receipts(self):
        model_dir = Path(os.environ.get("ADMIN_AGENT_OCR_TESSDATA_DIR", "/usr/share/tesseract-ocr/5/tessdata"))
        if not all((model_dir / (lang + ".traineddata")).is_file() for lang in ("fra", "spa")):
            self.skipTest("French and Spanish OCR models required")
        for language, lines in (("fra", ["Commercant: Restaurant Demo", "Date: 2026-09-30", "Total: 42,00", "Devise: EUR", "EXERCICE SYNTHETIQUE SANS REMBOURSEMENT"]),
                                ("spa", ["Comercio: Restaurante Demo", "Fecha: 2026-09-30", "Importe total: 42,00", "Moneda: EUR", "EJERCICIO SINTETICO SIN REEMBOLSO"])):
            with self.subTest(language=language):
                result = ocr.extract_document(make_image(lines), "image/png", language)
                self.assertEqual(result["candidates"]["total_amount"]["value"], "42.00")
                self.assertEqual(result["candidates"]["expense_date"]["value"], "2026-09-30")
                self.assertIn("merchant", result["candidates"])


if __name__ == "__main__":
    unittest.main()
