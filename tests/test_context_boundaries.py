import unittest
from unittest.mock import Mock, patch

from admin_agent.errors import AppError
from admin_agent.server import analyze_task


class ContextBoundaryTests(unittest.TestCase):
    def test_missing_or_truncated_skill_prevents_provider_call(self):
        task = {"id": "test", "version": 1, "title": "Test", "description": "Classer la facture",
                "skill_id": "admin-triage", "country": "FR", "payload": {}}
        for body in (("", False), ("partial instructions", True)):
            with self.subTest(body=body), patch("admin_agent.server.skill_body", return_value=body), \
                    patch("admin_agent.llm.enrich_with_ai") as provider:
                with self.assertRaises(AppError) as caught:
                    analyze_task(Mock(), task, use_ai=True)
                self.assertEqual(caught.exception.code, "context_unavailable")
                provider.assert_not_called()
