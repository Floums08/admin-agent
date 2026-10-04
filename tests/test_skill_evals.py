"""Executable fixture assertions; behavioral specifications are deliberately separate."""

from datetime import date
import json
from pathlib import Path
import re
import unittest

from admin_agent.engine import analyze, result_status


ROOT = Path(__file__).resolve().parent.parent


class SkillCatalogTests(unittest.TestCase):
    def test_catalog_and_skill_documents(self):
        rows = json.loads((ROOT / "data/skills.json").read_text(encoding="utf-8"))["skills"]
        required = {"id", "name", "description", "priority", "agent", "inputs", "outputs", "status", "path"}
        core = {"invoice-check", "receivables-followup", "bookkeeping-pack", "admin-triage", "expense-review"}
        self.assertEqual(len(rows), 12)
        self.assertEqual(len({row["id"] for row in rows}), 12)
        self.assertEqual(len({row["agent"] for row in rows}), 6)
        self.assertEqual({row["id"] for row in rows if row["status"] == "implemented"}, core)
        for row in rows:
            with self.subTest(skill=row["id"]):
                self.assertEqual(set(row), required)
                self.assertRegex(row["id"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                self.assertIn(row["priority"], {"P0", "P1", "P2"})
                self.assertIn(row["status"], {"implemented", "guided"})
                self.assertEqual(row["path"], f"skills/{row['id']}/SKILL.md")
                self.assertTrue(all(isinstance(row[field], str) and row[field].strip()
                                    for field in ("name", "description", "agent")))
                for field in ("inputs", "outputs"):
                    self.assertIsInstance(row[field], list)
                    self.assertTrue(row[field])
                    self.assertTrue(all(isinstance(item, str) and item.strip() for item in row[field]))
                path = ROOT / row["path"]
                body = path.read_text(encoding="utf-8")
                self.assertTrue(body.startswith(f"---\nname: {row['id']}\ndescription: "))
                self.assertEqual(body.count("\n---\n"), 1)
                self.assertLessEqual(len(body.splitlines()), 180)
                self.assertLess(len(body.encode("utf-8")), 18_000)
                for reference in re.findall(r"\]\((\.\./[^)]+)\)", body):
                    self.assertTrue((path.parent / reference).resolve().is_file(), reference)


class SkillFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((ROOT / "data/skill-evals.json").read_text(encoding="utf-8"))

    def test_fixture_schema_separates_executable_and_behavioral_cases(self):
        fixture = self.fixture
        self.assertEqual(fixture["schema_version"], "1.0")
        self.assertEqual(fixture["data_classification"], "synthetic_only")
        cases = fixture["cases"]
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        self.assertEqual(sum(case["evaluation_type"] == "deterministic" for case in cases), 24)
        self.assertEqual(sum(case["evaluation_type"] == "behavioral" for case in cases), 16)
        catalog_ids = {row["id"] for row in json.loads(
            (ROOT / "data/skills.json").read_text(encoding="utf-8"))["skills"]}
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertIn(case["skill_id"], catalog_ids)
                self.assertIn(case["evaluation_type"], {"deterministic", "behavioral"})
                if case["evaluation_type"] == "behavioral":
                    self.assertTrue(case["input_prompt"].strip())
                    self.assertIn(case["country"], {"FR", "ES"})
                    self.assertTrue(case["expected_criteria"]["must"])
                    self.assertTrue(case["expected_criteria"]["must_not"])
                    self.assertTrue(case["execution_note"])
                    continue
                self.assertIn(case["input"]["country"], {"FR", "ES"})
                self.assertIsInstance(case["input"]["payload"], dict)
                self.assertIsInstance(date.fromisoformat(case["as_of"]), date)
                self.assertIn(case["expected"]["status"], {"blocked", "needs_review"})
                self.assertLessEqual(set(case["expected"]), {
                    "mode", "outbound_executed", "status", "missing_fields", "finding_fields",
                    "draft_empty", "draft_contains", "draft_excludes", "checks_pass", "checks_fail",
                })

    def test_deterministic_fixture_results(self):
        for case in self.fixture["cases"]:
            if case["evaluation_type"] != "deterministic":
                continue
            with self.subTest(case=case["id"]):
                task = dict(case["input"], skill_id=case["skill_id"])
                result = analyze(task, today=date.fromisoformat(case["as_of"]))
                expected = case["expected"]
                self.assertEqual(result_status(result), expected["status"])
                self.assertEqual(result["mode"], expected["mode"])
                self.assertIs(result["outbound_executed"], expected["outbound_executed"])
                self.assertEqual(result["analyzed_on"], case["as_of"])
                self.assertFalse(result["context"]["other_tasks_included"])
                for field in expected.get("missing_fields", []):
                    self.assertIn(field, result["missing_fields"])
                for field in expected.get("finding_fields", []):
                    self.assertIn(field, [finding.get("field") for finding in result["findings"]])
                if expected.get("draft_empty"):
                    self.assertEqual(result["draft"], "")
                for phrase in expected.get("draft_contains", []):
                    self.assertIn(phrase, result["draft"])
                for phrase in expected.get("draft_excludes", []):
                    self.assertNotIn(phrase, result["draft"])
                for key, passed in (("checks_pass", True), ("checks_fail", False)):
                    for name in expected.get(key, []):
                        self.assertTrue(any(check["name"] == name and check["passed"] is passed
                                            for check in result["checks"]), f"Missing {name}={passed}")


if __name__ == "__main__":
    unittest.main()
