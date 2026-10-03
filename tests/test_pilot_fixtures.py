"""Synthetic pack integrity and real extraction workflow, not client accuracy."""
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from scripts.pilot_fixtures import ROOT, case_definitions, generate_pack

try:
    import PIL
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


@unittest.skipUnless(HAS_PILLOW, "Pillow is optional; installed in the OCR QA environment")
class PilotFixtureTests(unittest.TestCase):
    def test_pack_is_deterministic_private_and_truth_is_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            first, second = Path(temp) / "first", Path(temp) / "second"
            manifest = generate_pack(first)
            self.assertEqual(manifest, generate_pack(second))
            self.assertEqual(len(manifest["cases"]), 10)
            self.assertTrue(manifest["synthetic"])
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(len(set(case["case_id"] for case in manifest["cases"])), 10)
            self.assertEqual(len(list((first / "documents").iterdir())), 10)
            self.assertEqual(json.loads((first / "expected/manifest.json").read_text()), manifest)
            for path in first.rglob("*"):
                if path.is_file():
                    self.assertEqual(path.read_bytes(), (second / path.relative_to(first)).read_bytes())
                    if os.name == "posix":
                        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            if os.name == "posix":
                self.assertEqual(first.stat().st_mode & 0o777, 0o700)
            for case in manifest["cases"]:
                content = (first / case["file"]).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(), case["sha256"])
                self.assertNotIn("paid", case["expected_fields"])
                self.assertNotIn("disputed", case["expected_fields"])
                self.assertTrue(case["case_id"].startswith("synthetic-fr-"))

    def test_existing_output_and_symlink_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "pack"
            generate_pack(target)
            original = (target / "expected/manifest.json").read_bytes()
            with self.assertRaises(ValueError):
                generate_pack(target)
            self.assertEqual((target / "expected/manifest.json").read_bytes(), original)
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(ValueError):
                generate_pack(link / "other")
            with self.assertRaises(ValueError):
                generate_pack(ROOT / "examples" / "unsafe-pilot-pack")
            with self.assertRaises(ValueError):
                generate_pack(ROOT / "runtime" / ".." / "examples" / "unsafe-pilot-pack")

    def test_truth_keeps_source_errors_and_stops_ambiguous_date(self):
        cases = {case["case_id"]: case for case in case_definitions()}
        self.assertEqual(cases["synthetic-fr-003"]["expected_fields"]["total_amount"], "245.00")
        self.assertEqual(cases["synthetic-fr-004"]["expected_fields"]["vat_amount"], "19.00")
        self.assertNotIn("due_date", cases["synthetic-fr-006"]["expected_fields"])
        self.assertEqual(cases["synthetic-fr-006"]["expected_missing_fields"], ["due_date"])
        self.assertTrue(all(line.isascii() for line in cases["synthetic-fr-002"]["source_pages"][0]))
        self.assertEqual(cases["synthetic-fr-002"]["expected_fields"]["customer"], "Entreprise Demo")
        self.assertEqual([case["expected_scope"] for case in cases.values()], ["in_scope"] * 6 + ["out_of_scope"] * 4)

    def test_real_ten_document_extract_then_truth_review_and_invoice_checks(self):
        from admin_agent import ocr
        from admin_agent.documents import document_risk_flags, validate_extraction
        from admin_agent.engine import analyze, result_status
        if not all(tool.is_file() for tool in ocr.TOOLS.values()):
            self.skipTest("Poppler/Tesseract/prlimit are optional locally")
        model_dir = Path(os.environ.get("ADMIN_AGENT_OCR_TESSDATA_DIR", "/usr/share/tesseract-ocr/5/tessdata"))
        if not (model_dir / "fra.traineddata").is_file():
            self.skipTest("French Tesseract model is required for the real synthetic pack test")
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "pack"
            manifest = generate_pack(folder)
            for case in manifest["cases"]:
                with self.subTest(case_id=case["case_id"]):
                    extracted = ocr.extract_document((folder / case["file"]).read_bytes(), case["media_type"], "fra")
                    validate_extraction(extracted, case["media_type"])
                    flags = document_risk_flags(extracted)
                    self.assertEqual(sorted({flag["code"] for flag in flags}), sorted(case["expected_risk_codes"]))
                    self.assertNotIn("paid", extracted["candidates"])
                    self.assertNotIn("disputed", extracted["candidates"])
                    for candidate in extracted["candidates"].values():
                        self.assertIn(candidate["quote"], extracted["pages"][candidate["page"] - 1]["text"])
                    if case["case_id"] == "synthetic-fr-001":
                        self.assertEqual({field: value["value"] for field, value in extracted["candidates"].items()}, case["expected_fields"])
                    # Explicit synthetic review uses the separately authored truth.
                    # This does NOT assert OCR got every field right automatically.
                    payload = dict(case["expected_fields"], **case["human_review_context"]["asserted_fields"], _document_source={"document_risk_flags": flags})
                    result = analyze({"title": case["title"], "description": "Revue synthétique à partir du corrigé séparé.", "skill_id": "invoice-check", "country": "FR", "payload": payload}, date.fromisoformat(manifest["analysis_date"]))
                    self.assertEqual(result_status(result), case["expected_status"])
                    self.assertEqual(sorted(result["missing_fields"]), sorted(case["expected_missing_fields"]))
                    self.assertEqual(sorted(check["name"] for check in result["checks"] if not check["passed"]), sorted(case["expected_checks_failed"]))
                    self.assertFalse(result["outbound_executed"])
                    if result_status(result) == "blocked":
                        self.assertEqual(result["draft"], "")


if __name__ == "__main__":
    unittest.main()
