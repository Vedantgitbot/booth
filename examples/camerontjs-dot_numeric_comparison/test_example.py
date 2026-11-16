"""Comparator, BOOTH integration and fail-closed I/O controls; no model inference."""
import argparse
import base64
import http.client
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error

import booth
import run_example as example


class NumericCheckpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads((example.HERE / "cases.json").read_text())["cases"]

    def test_all_declared_positive_and_negative_controls_against_source(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertTrue(example.numeric_decision(case["correct_answer"], [case["source"]], case["target"], case["round_places"])["passed"])
                self.assertFalse(example.numeric_decision(case["wrong_answer"], [case["source"]], case["target"], case["round_places"])["passed"])

    def test_correct_and_wrong_payloads_execute_real_booth_checkpoints(self):
        case = self.cases[0]
        for candidate, passed in ((case["correct_answer"], True), (case["wrong_answer"], False)):
            raw = json.dumps({"answer": candidate, "confidence": 0.99, "ambiguous": False})
            row = example.checkpoints(case, raw)
            self.assertTrue(row["arms"]["check"]["ok"])
            self.assertEqual(row["arms"]["validator"]["ok"], passed)
            self.assertEqual(row["arms"]["numeric_evidence"]["ok"], passed)
            if not passed:
                self.assertEqual(row["arms"]["validator"]["status"], booth.UNCERTAIN)
                self.assertEqual(row["arms"]["numeric_evidence"]["status"], booth.BLOCKED)

    def test_ambiguity_and_confidence_checks_are_not_evidence_checks(self):
        case = self.cases[0]
        for confidence, ambiguous, status in ((0.2, False, booth.UNCERTAIN), (0.99, True, booth.AMBIGUOUS)):
            raw = json.dumps({"answer": case["correct_answer"], "confidence": confidence, "ambiguous": ambiguous, "interpretations": ["one", "two"] if ambiguous else []})
            row = example.checkpoints(case, raw)
            self.assertEqual(row["arms"]["check"]["status"], status)
            self.assertEqual(row["arms"]["validator"]["status"], status)
            self.assertTrue(row["arms"]["numeric_evidence"]["ok"])

    def test_wrong_field_and_currency_can_pass_weak_lexical_check(self):
        for case_id in ("invoice_total", "cad_not_usd", "account_scope"):
            case = next(c for c in self.cases if c["id"] == case_id)
            self.assertGreaterEqual(example.keyword_overlap(case["wrong_answer"], [case["source"]]), 0.5)
            self.assertFalse(example.numeric_decision(case["wrong_answer"], [case["source"]], case["target"])["passed"])

    def test_missing_duplicate_and_conflicting_target_fail_closed(self):
        for evidence in ([], ["Other: 12 CAD"], ["Total: 12 CAD\nTotal: 12 CAD"], ["Total: 12 CAD", "Total: 14 CAD"], ["Total: unknown CAD"]):
            self.assertFalse(example.numeric_decision("12 CAD", evidence, "Total")["passed"])
        self.assertTrue(example.numeric_decision("12 CAD", ["Total: 12 CAD", "Other: 14 CAD"], "Total")["passed"])

    def test_currency_unit_and_percentage_point_mutations(self):
        for source, answer in (("Value: 12 CAD", "12 USD"), ("Value: 12 days", "12 months"), ("Value: 5 percent", "5 percentage points"), ("Value: 2 percentage points", "0.02 fraction")):
            self.assertFalse(example.numeric_decision(answer, [source], "Value")["passed"])

    def test_exact_value_scaling_and_rate_conversions(self):
        for source, answer in (("Value: 1.25 million CAD", "1,250,000 CAD"), ("Value: 250 thousand USD", "0.25 million USD"), ("Value: 0.075 fraction", "7.5%"), ("Value: -12 USD", "(12) USD")):
            self.assertTrue(example.numeric_decision(answer, [source], "Value")["passed"])
        self.assertFalse(example.numeric_decision("12.00001 CAD", ["Value: 12 CAD"], "Value")["passed"])

    def test_supported_format_variants_keep_the_same_quantity(self):
        for source, answer in (("Value: -12 CAD", "(12 CAD)"), ("Value: 0.5 USD", ".5 USD"), ("Value: 12 CAD", "CAD12"), ("Value: 1 days", "1 day"), ("Value: 1 percentage points", "1 percentage point")):
            self.assertTrue(example.numeric_decision(answer, [source], "Value")["passed"], answer)

    def test_half_up_rounds_source_once_without_tolerance_or_answer_rounding(self):
        for source, correct, wrong in (("Value: 2.225 USD", "2.23 USD", "2.22 USD"), ("Value: -2.225 CAD", "-2.23 CAD", "-2.22 CAD")):
            self.assertTrue(example.numeric_decision(correct, [source], "Value", 2)["passed"])
            self.assertFalse(example.numeric_decision(wrong, [source], "Value", 2)["passed"])
        self.assertFalse(example.numeric_decision("2.229 USD", ["Value: 2.225 USD"], "Value", 2)["passed"])
        self.assertFalse(example.numeric_decision("12.35 percent", ["Value: 12.345 percent"], "Value", 2)["passed"])

    def test_unsupported_answer_grammar_is_withheld(self):
        for answer in ("12", "$12", "12 CAD and 12 USD", "The total is 12 CAD", "1,20 CAD", "NaN CAD", "Infinity USD", "1e2 CAD", "12 CAD USD"):
            self.assertFalse(example.numeric_decision(answer, ["Value: 12 CAD"], "Value")["passed"], answer)

    def test_replay_requires_identical_provider_prompt(self):
        result = example.replay_check('{"answer":"12 CAD","confidence":1}', "question", expected_prompt="different")
        self.assertTrue(result.call_failed)
        self.assertFalse(result.ok)

    def test_provider_disconnection_preserves_failed_call_without_success(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = example.Provider("http://127.0.0.1:1", "absent", {}, 0.01, Path(directory))
            with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("disconnected")):
                result = booth.check(provider, "question", max_retries=0)
            self.assertTrue(result.call_failed)
            self.assertFalse(result.ok)
            trace = json.loads((Path(directory) / "provider_calls.jsonl").read_text())
            self.assertIn("disconnected", trace["error"])
            self.assertNotIn("raw_reply", trace)

    def test_raw_http_and_reply_whitespace_retained_before_booth_parsing(self):
        raw = '  reasoning\n{"answer":"12 CAD","confidence":1,"ambiguous":false}\n\n'
        response = json.dumps({"response": raw, "done": True, "done_reason": "stop"}).encode()
        with tempfile.TemporaryDirectory() as directory:
            provider = example.Provider("http://127.0.0.1:1", "unit-test-fixture", {}, 1, Path(directory))
            with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(response)):
                result = booth.check(provider, "test", max_retries=0)
            self.assertEqual(result.answer, "12 CAD")
            trace = json.loads((Path(directory) / "provider_calls.jsonl").read_text())
            self.assertEqual(trace["raw_reply"], raw)
            self.assertEqual(trace["response_text"].encode(), response)
            self.assertEqual(trace["response_sha256"], example.sha_bytes(response))

    def test_token_limit_is_failure_with_raw_reply_preserved(self):
        response = json.dumps({"response": "unfinished", "done": True, "done_reason": "length"}).encode()
        with tempfile.TemporaryDirectory() as directory:
            provider = example.Provider("http://127.0.0.1:1", "unit-test-fixture", {}, 1, Path(directory))
            with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(response)):
                with self.assertRaises(example.ProviderFailure):
                    provider("test")
            trace = json.loads((Path(directory) / "provider_calls.jsonl").read_text())
            self.assertEqual(trace["raw_reply"], "unfinished")
            self.assertTrue(trace["error"])

    def test_invalid_utf8_and_partial_response_bytes_are_preserved(self):
        for received, partial in ((b'{"response":"\xff"}', False), (b'{"response":"partial', True)):
            with self.subTest(partial=partial), tempfile.TemporaryDirectory() as directory:
                provider = example.Provider("http://127.0.0.1:1", "unit-test-fixture", {}, 1, Path(directory))
                response = mock.MagicMock()
                response.__enter__.return_value = response
                if partial:
                    response.read.side_effect = http.client.IncompleteRead(received, 42)
                else:
                    response.read.return_value = received
                with mock.patch("urllib.request.urlopen", return_value=response):
                    with self.assertRaises(example.ProviderFailure):
                        provider("test")
                trace = json.loads((Path(directory) / "provider_calls.jsonl").read_text())
                self.assertEqual(base64.b64decode(trace["response_base64"]), received)
                self.assertEqual(trace["response_sha256"], example.sha_bytes(received))
                self.assertTrue(trace["error"])

    def test_run_preflight_disconnection_has_nonzero_exit_and_no_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "fresh"
            args = argparse.Namespace(out=str(out), smoke=True, controls_only=False, host="http://127.0.0.1:1", model="absent", expected_digest=None, seed=42, num_predict=1024, timeout=1)
            with mock.patch.object(example, "model_identity", side_effect=example.ProviderFailure("missing backend")):
                self.assertEqual(example.run(args), 2)
            self.assertEqual(json.loads((out / "failure.json").read_text())["status"], "blocked")
            self.assertFalse((out / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
