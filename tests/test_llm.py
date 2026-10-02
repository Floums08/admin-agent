import copy
import json
import os
import unittest
from unittest.mock import patch

from admin_agent import llm


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.task = {"title": "Contrôle", "description": "Vérifier sans envoyer", "country": "FR",
                     "payload": {"total_amount": "120.00"}, "other_tenant_secret": "MUST_NOT_LEAK"}
        self.result = {"summary": "Écart", "findings": [{"severity": "error", "message": "Écart de TVA"}],
                       "missing_fields": [], "checks": [], "mode": "offline"}
        self.skill = {"id": "invoice-check", "body": "Comparer les montants."}
        self.advice = {"summary": "À vérifier", "suggested_draft": "Brouillon", "questions": [],
                       "evidence_fields": ["payload.total_amount"]}

    def response(self, advice=None):
        return {"status": "completed", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(advice if advice is not None else self.advice)}]}],
                "usage": {"input_tokens": 100, "output_tokens": 40, "total_tokens": 140}}

    @patch.dict(os.environ, {}, clear=True)
    def test_disabled_makes_no_network_call(self):
        with patch.object(llm, "_call_provider") as provider:
            with self.assertRaises(ValueError):
                llm.enrich_with_ai(self.task, self.result, self.skill)
            provider.assert_not_called()

    def test_context_is_selective_and_oversize_is_rejected(self):
        value, metadata, paths = llm.build_context(self.task, self.result, self.skill)
        self.assertNotIn("MUST_NOT_LEAK", value)
        self.assertIn("payload.total_amount", paths)
        self.assertFalse(metadata["cross_task_context"])
        self.task["description"] = "é" * 30000
        with self.assertRaises(ValueError):
            llm.build_context(self.task, self.result, self.skill)

    @patch.dict(os.environ, {"ADMIN_AGENT_AI_ENABLED": "1", "OPENAI_API_KEY": "fake", "OPENAI_MODEL": "configured-test-model"})
    def test_advice_cannot_replace_deterministic_checks(self):
        original = copy.deepcopy(self.result)
        with patch.object(llm, "_call_provider", return_value=self.response()) as provider:
            enriched = llm.enrich_with_ai(self.task, self.result, self.skill)
        self.assertEqual(self.result, original)
        self.assertEqual(enriched["findings"], original["findings"])
        self.assertEqual(enriched["summary"], original["summary"])
        self.assertEqual(enriched["ai_advice"], self.advice)
        payload = provider.call_args.args[0]
        self.assertFalse(payload["store"])
        self.assertNotIn("tools", payload)
        self.assertEqual(enriched["context"]["usage"]["total_tokens"], 140)

    def test_unknown_fields_and_fabricated_evidence_are_rejected(self):
        for change in ({"status": "ready"}, {"evidence_fields": ["payload.iban"]}):
            with self.subTest(change=change):
                advice = dict(self.advice, **change)
                with self.assertRaises(ValueError):
                    llm._parse_response(self.response(advice), {"payload.total_amount"})

    def test_incomplete_refusal_and_tool_calls_fail_closed(self):
        for response in ({"status": "incomplete"}, {"status": "completed", "output": [
                {"type": "message", "content": [{"type": "refusal"}]}]},
                {"status": "completed", "output": [{"type": "function_call", "name": "send_email"}]}):
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    llm._parse_response(response, {"payload.total_amount"})

    def test_malformed_provider_content_is_controlled(self):
        for content in (None, 12, {"text": "bad"}, [{"type": "output_text", "text": None}]):
            with self.subTest(content=content), self.assertRaises(ValueError):
                llm._parse_response({"status": "completed", "output": [
                    {"type": "message", "content": content}]}, set())

    def test_invalid_key_and_provider_errors_never_expose_secrets(self):
        with patch.object(llm.request, "build_opener") as opener:
            with self.assertRaises(ValueError) as caught:
                llm._call_provider({}, "secret\ninjected")
            opener.assert_not_called()
            self.assertNotIn("secret", str(caught.exception))
            opener.return_value.open.side_effect = ValueError("Invalid header secret")
            with self.assertRaises(ValueError) as caught:
                llm._call_provider({}, "secret\n")
            self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
