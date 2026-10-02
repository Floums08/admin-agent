"""Regression: retaining source risk is as important as retaining its amounts."""
from datetime import date
import unittest

from admin_agent.engine import analyze, result_status


def invoice_task(skill="invoice-check", **payload):
    fields = {"invoice_number": "SYNTHETIC-1", "supplier": "Demo supplier", "customer": "Demo customer",
              "issue_date": "2026-01-01", "due_date": "2026-01-31", "net_amount": "100.00",
              "vat_rate": "20", "vat_amount": "20.00", "total_amount": "120.00", "currency": "EUR",
              "paid": False, "disputed": False}
    fields.update(payload)
    return {"skill_id": skill, "country": "FR", "title": "Document synthétique", "description": "Description modifiée sans indice de risque.", "payload": fields}


class DocumentRiskEngineTests(unittest.TestCase):
    def test_preserved_document_flags_block_both_workflows_after_description_edit(self):
        evidence = {"partial_payment": "Acompte déjà versé : 40 EUR", "credit_note": "Avoir à rapprocher",
                    "special_vat": "Autoliquidation", "bank_change": "Nouvel IBAN",
                    "retention": "Retenue de garantie", "multiple_tax_rates": "TVA 20 % et TVA 5,5 %"}
        for code, quote in evidence.items():
            for skill in ("invoice-check", "receivables-followup"):
                with self.subTest(code=code, skill=skill):
                    result = analyze(invoice_task(skill, _document_source={"document_risk_flags": [{"code": code, "page": 1, "quote": quote}]}), date(2026, 10, 2))
                    self.assertEqual(result_status(result), "blocked")
                    self.assertEqual(result["draft"], "")
                    self.assertFalse(result["outbound_executed"])
                    self.assertTrue(any(finding.get("field") == "_document_source.document_risk_flags" for finding in result["findings"]))

    def test_missing_or_unsupported_source_scope_never_passes(self):
        for source in ({}, None, {"document_risk_flags": "none"}, {"document_risk_flags": [{"code": ["partial_payment"], "page": 1, "quote": "texte"}]}, {"document_risk_flags": [{"code": "unknown", "page": 1, "quote": "texte"}]},
                       {"document_risk_flags": [{"code": "partial_payment", "page": True, "quote": "texte"}]}):
            with self.subTest(source=source):
                result = analyze(invoice_task(_document_source=source), date(2026, 10, 2))
                self.assertEqual(result_status(result), "blocked")
                self.assertEqual(result["draft"], "")

    def test_no_detected_document_marker_still_requires_human_review(self):
        result = analyze(invoice_task(_document_source={"document_risk_flags": []}), date(2026, 10, 2))
        self.assertEqual(result_status(result), "needs_review")
        self.assertFalse(result["outbound_executed"])

    def test_remaining_amount_blocks_reminder_without_reinterpreting_total(self):
        for value in ("80.00", "0.00", None):
            result = analyze(invoice_task("receivables-followup", remaining_amount=value), date(2026, 10, 2))
            self.assertEqual(result_status(result), "blocked")
            self.assertEqual(result["draft"], "")

    def test_connector_imported_partial_values_survive_visible_field_removal(self):
        for field in ("paid_amount", "credit_amount", "amount_paid", "remaining_amount"):
            result = analyze(invoice_task("receivables-followup", _connector_source={"imported_values": {field: "40.00"}}), date(2026, 10, 2))
            self.assertEqual(result_status(result), "blocked")
            self.assertEqual(result["draft"], "")

    def test_plain_manual_invoice_and_connector_without_partial_remain_usable(self):
        for extra in ({}, {"_connector_source": {"imported_values": {"total_amount": "120.00"}}}):
            result = analyze(invoice_task("receivables-followup", **extra), date(2026, 10, 2))
            self.assertEqual(result_status(result), "needs_review")
            self.assertIn("120.00 EUR", result["draft"])

    def test_triage_reads_verified_payload_text_with_empty_context(self):
        task = invoice_task("admin-triage", text="Merci de contrôler cette facture fournisseur.")
        task["description"] = ""
        result = analyze(task, date(2026, 10, 2))
        self.assertEqual(result_status(result), "needs_review")
        self.assertIn("invoice-check", result["summary"])
        self.assertNotIn("description", result["missing_fields"])

    def test_triage_preserves_context_and_rejects_invalid_request_text(self):
        task = invoice_task("admin-triage", text="Facture fournisseur")
        task["description"] = "Nouveau RIB à vérifier"
        result = analyze(task, date(2026, 10, 2))
        self.assertEqual(result_status(result), "blocked")
        for value in (True, {}, ["facture"], "x" * 12001):
            with self.subTest(value_type=type(value).__name__):
                result = analyze(invoice_task("admin-triage", text=value), date(2026, 10, 2))
                self.assertEqual(result_status(result), "blocked")


if __name__ == "__main__":
    unittest.main()
