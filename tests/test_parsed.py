"""
Tests for Attempt.parsed / BoothResult.parsed, added in 0.4.3. The
central claim being tested: parsed exposes the model's RAW JSON object,
which can legitimately disagree in representation with BOOTH's own
coerced fields (str(answer), float(confidence), etc.) — that divergence
is the point, not a bug to be fixed.
Run: python3 tests/test_parsed.py
"""
import asyncio
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import booth as bth


def test_parsed_matches_raw_object_including_type_divergence_and_extra_fields():
    """THE anchor test from the spec: confidence as a JSON string
    coerced to float on .confidence but left as a string in .parsed,
    plus a field BOOTH doesn't itself use (extra_field) surviving
    untouched in .parsed. This is what actually proves the API
    contract, not just that the field exists."""
    def call_fn(p):
        return json.dumps({
            "answer": "30 days",
            "confidence": "0.95",  # string, not a float — BOOTH coerces this for .confidence
            "ambiguous": False,
            "extra_field": {"source": "policy.pdf"},  # not part of BOOTH's own schema at all
        })
    r = bth.check(call_fn, "q")
    assert r.status == bth.VERIFIED, r.status

    # BOOTH's own coerced fields
    assert r.answer == "30 days"
    assert r.confidence == 0.95
    assert isinstance(r.confidence, float)

    # The raw object: confidence STAYS a string here, by design
    assert r.parsed["confidence"] == "0.95"
    assert isinstance(r.parsed["confidence"], str)
    assert r.parsed["answer"] == "30 days"
    assert r.parsed["extra_field"] == {"source": "policy.pdf"}
    print("PASS: parsed exposes the raw object — type divergence from .confidence "
          "and an untouched extra field both confirmed")


def test_parsed_present_on_verified():
    def call_fn(p):
        return json.dumps({"answer": "Paris", "confidence": 0.9})
    r = bth.check(call_fn, "q")
    assert r.status == bth.VERIFIED
    assert r.parsed == {"answer": "Paris", "confidence": 0.9}
    print("PASS: parsed present and correct on VERIFIED")


def test_parsed_present_on_repaired_is_the_winning_attempt():
    calls = {"n": 0}
    def call_fn(p):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"answer": "Lyon", "confidence": 0.3, "tag": "first"})
        return json.dumps({"answer": "Paris", "confidence": 0.9, "tag": "second"})
    r = bth.check(call_fn, "q", max_retries=1)
    assert r.status == bth.REPAIRED
    assert r.parsed["tag"] == "second", "parsed must reflect the WINNING attempt, not the first"
    print("PASS: parsed on REPAIRED reflects the winning (later) attempt, not the failed first one")


def test_parsed_present_on_ambiguous():
    def call_fn(p):
        return json.dumps({
            "ambiguous": True, "interpretations": ["a", "b"],
            "chosen_interpretation": "a", "answer": "x", "confidence": 0.9,
            "tag": "ambiguous-attempt",
        })
    r = bth.check(call_fn, "q")
    assert r.status == bth.AMBIGUOUS
    assert r.parsed["tag"] == "ambiguous-attempt"
    print("PASS: parsed present on AMBIGUOUS")


def test_parsed_none_on_total_parse_failure():
    def call_fn(p):
        return "not json at all"
    r = bth.check(call_fn, "q", max_retries=1)
    assert r.status == bth.UNCERTAIN
    assert r.all_parse_failed is True
    assert r.parsed is None
    print("PASS: parsed is None when nothing ever parsed")


def test_parsed_reflects_last_successful_attempt_on_uncertain_mixed_history():
    """Mixed history: attempt 1 parses (low confidence), attempt 2 fails
    to parse. Final UNCERTAIN. parsed must come from attempt 1 (the
    LAST one that actually parsed), not be None just because the final
    attempt didn't parse."""
    calls = {"n": 0}
    def call_fn(p):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"answer": "x", "confidence": 0.2, "tag": "parsed-ok"})
        return "garbage on retry"
    r = bth.check(call_fn, "q", max_retries=1)
    assert r.status == bth.UNCERTAIN
    assert r.all_parse_failed is False  # attempt 1 DID parse
    assert r.parsed is not None
    assert r.parsed["tag"] == "parsed-ok"
    print("PASS: parsed on mixed-history UNCERTAIN comes from the last successfully-parsed attempt")


def test_parsed_on_uncertain_from_persistent_low_confidence():
    def call_fn(p):
        return json.dumps({"answer": "x", "confidence": 0.2, "tag": "always-low"})
    r = bth.check(call_fn, "q", max_retries=1)
    assert r.status == bth.UNCERTAIN
    assert r.parsed["tag"] == "always-low"
    print("PASS: parsed present on UNCERTAIN from persistent low confidence")


def test_attempt_level_parsed_matches_result_level_parsed():
    """Attempt.parsed and the winning BoothResult.parsed should be the
    exact same object for the winning attempt."""
    def call_fn(p):
        return json.dumps({"answer": "Paris", "confidence": 0.9})
    r = bth.check(call_fn, "q")
    assert r.attempts[-1].parsed == r.parsed
    print("PASS: Attempt.parsed and the winning BoothResult.parsed agree")


def test_attempt_parsed_is_none_on_a_failed_attempt():
    def call_fn(p):
        return "no json here"
    r = bth.check(call_fn, "q", max_retries=0)
    assert r.attempts[0].parse_ok is False
    assert r.attempts[0].parsed is None
    print("PASS: Attempt.parsed is None for an attempt that failed to parse")


def test_check_with_evidence_parsed_always_none():
    """check_with_evidence() has no LLM JSON parse involved at all —
    parsed must stay None regardless of outcome, same as
    evidence_agreement stays None for check()/acheck() results."""
    r1 = bth.check_with_evidence("Paris", ["Paris is the capital"], lambda a, e: True)
    r2 = bth.check_with_evidence("Lyon", ["Paris is the capital"], lambda a, e: False)
    r3 = bth.check_with_evidence("", ["e"], lambda a, e: True)
    assert r1.parsed is None
    assert r2.parsed is None
    assert r3.parsed is None
    print("PASS: check_with_evidence() results always have parsed=None (VERIFIED/BLOCKED/UNCERTAIN)")


def test_parsed_unaffected_by_validator():
    """parsed must still reflect the raw object even when a validator
    is involved — confirms the two 0.4.x features compose cleanly."""
    def call_fn(p):
        return json.dumps({"answer": "x", "confidence": 0.9, "tag": "with-validator"})
    r = bth.check(call_fn, "q", validator=lambda a: True)
    assert r.status == bth.VERIFIED
    assert r.parsed["tag"] == "with-validator"
    print("PASS: parsed works correctly alongside validator=")


def test_async_parity_parsed():
    async def call_fn(p):
        return json.dumps({"answer": "Paris", "confidence": "0.9", "tag": "async"})
    r = asyncio.run(bth.acheck(call_fn, "q"))
    assert r.status == bth.VERIFIED
    assert r.confidence == 0.9
    assert isinstance(r.confidence, float)
    assert r.parsed["confidence"] == "0.9"
    assert isinstance(r.parsed["confidence"], str)
    assert r.parsed["tag"] == "async"
    print("PASS: acheck() parsed matches check()'s contract, including type divergence")


if __name__ == "__main__":
    test_parsed_matches_raw_object_including_type_divergence_and_extra_fields()
    test_parsed_present_on_verified()
    test_parsed_present_on_repaired_is_the_winning_attempt()
    test_parsed_present_on_ambiguous()
    test_parsed_none_on_total_parse_failure()
    test_parsed_reflects_last_successful_attempt_on_uncertain_mixed_history()
    test_parsed_on_uncertain_from_persistent_low_confidence()
    test_attempt_level_parsed_matches_result_level_parsed()
    test_attempt_parsed_is_none_on_a_failed_attempt()
    test_check_with_evidence_parsed_always_none()
    test_parsed_unaffected_by_validator()
    test_async_parity_parsed()
    print("\nAll parsed tests passed.")