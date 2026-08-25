"""
Tests for BoothResult.method, added in 0.4.1. A pure computed property
— no new stored state, so these tests are really confirming the
derivation logic against every status/attempts/all_parse_failed
combination the three public functions (check, acheck,
check_with_evidence) can actually produce.
Run: python3 tests/test_method.py
"""
import asyncio
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import booth as bth


def test_method_confidence_on_verified():
    def call_fn(p):
        return json.dumps({"answer": "Paris", "confidence": 0.9})
    r = bth.check(call_fn, "q")
    assert r.status == bth.VERIFIED
    assert r.method == "confidence"
    print("PASS: method='confidence' on VERIFIED")


def test_method_confidence_on_repaired():
    calls = {"n": 0}
    def call_fn(p):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"answer": "Lyon", "confidence": 0.3})
        return json.dumps({"answer": "Paris", "confidence": 0.9})
    r = bth.check(call_fn, "q", max_retries=1)
    assert r.status == bth.REPAIRED
    assert r.method == "confidence"
    print("PASS: method='confidence' on REPAIRED")


def test_method_ambiguity():
    def call_fn(p):
        return json.dumps({
            "ambiguous": True,
            "interpretations": ["a", "b"],
            "chosen_interpretation": "a",
            "answer": "x",
            "confidence": 0.9,
        })
    r = bth.check(call_fn, "q")
    assert r.status == bth.AMBIGUOUS
    assert r.method == "ambiguity"
    print("PASS: method='ambiguity' on AMBIGUOUS")


def test_method_ambiguity_detected_only_on_retry():
    """Ambiguity discovered on the SECOND attempt, not the first —
    confirms method depends only on final status, not on when in the
    attempt history ambiguity was found."""
    calls = {"n": 0}
    def call_fn(p):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"answer": "x", "confidence": 0.3})  # low confidence, not ambiguous
        return json.dumps({
            "ambiguous": True, "interpretations": ["a", "b"],
            "chosen_interpretation": "a", "answer": "x", "confidence": 0.9,
        })
    r = bth.check(call_fn, "q", max_retries=1)
    assert r.status == bth.AMBIGUOUS
    assert r.method == "ambiguity"
    print("PASS: method='ambiguity' even when ambiguity is only discovered on a retry")


def test_method_parse_failure_all_attempts_unparseable():
    def call_fn(p):
        return "not json at all"
    r = bth.check(call_fn, "q", max_retries=1)
    assert r.status == bth.UNCERTAIN
    assert r.all_parse_failed is True
    assert r.method == "parse_failure"
    print("PASS: method='parse_failure' when every attempt fails to parse")


def test_method_parse_failure_all_attempts_raise_exception():
    """Every call_fn call raises (not malformed text — an actual
    exception). all_parse_failed's existing definition already treats
    this the same as literal unparseable text (both are parse_ok=False),
    so method should too."""
    def always_fails(p):
        raise TimeoutError("simulated")
    r = bth.check(always_fails, "q", max_retries=1)
    assert r.status == bth.UNCERTAIN
    assert r.all_parse_failed is True
    assert r.method == "parse_failure"
    print("PASS: method='parse_failure' when every attempt raised an exception "
          "(not just literal unparseable text) — consistent with all_parse_failed's existing definition")


def test_method_confidence_on_uncertain_from_low_confidence():
    def call_fn(p):
        return json.dumps({"answer": "x", "confidence": 0.2})
    r = bth.check(call_fn, "q", max_retries=1)
    assert r.status == bth.UNCERTAIN
    assert r.all_parse_failed is False
    assert r.method == "confidence"
    print("PASS: method='confidence' on UNCERTAIN from persistent low confidence")


def test_method_confidence_on_mixed_parse_failure_then_low_confidence():
    """THE key mixed-history case: attempt 1 fails to parse, attempt 2
    parses but stays under threshold. all_parse_failed is correctly
    False (not every attempt failed). method must fall through to
    'confidence', NOT 'parse_failure' — even though a parse failure
    genuinely happened earlier in the same run. method summarizes the
    FINAL determining factor, same as status already does; the full
    per-attempt story lives in result.attempts, not in this property."""
    calls = {"n": 0}
    def call_fn(p):
        calls["n"] += 1
        if calls["n"] == 1:
            return "garbage, not json"
        return json.dumps({"answer": "x", "confidence": 0.2})
    r = bth.check(call_fn, "q", max_retries=1)
    assert r.status == bth.UNCERTAIN
    assert r.all_parse_failed is False
    assert r.method == "confidence"
    print("PASS: mixed parse-failure-then-low-confidence -> method='confidence', "
          "not 'parse_failure' (matches all_parse_failed's own False here)")


def test_method_confidence_on_mixed_exception_then_low_confidence():
    """Same mixed-history principle, but the first failure is a call_fn
    exception rather than malformed text."""
    calls = {"n": 0}
    def call_fn(p):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("blip")
        return json.dumps({"answer": "x", "confidence": 0.2})
    r = bth.check(call_fn, "q", max_retries=1)
    assert r.status == bth.UNCERTAIN
    assert r.all_parse_failed is False
    assert r.method == "confidence"
    print("PASS: mixed exception-then-low-confidence -> method='confidence'")


def test_method_evidence_on_verified():
    r = bth.check_with_evidence("Paris", ["Paris is the capital"], lambda a, e: True)
    assert r.status == bth.VERIFIED
    assert r.attempts == []
    assert r.method == "evidence"
    print("PASS: method='evidence' on check_with_evidence VERIFIED")


def test_method_evidence_on_blocked():
    r = bth.check_with_evidence("Lyon", ["Paris is the capital"], lambda a, e: False)
    assert r.status == bth.BLOCKED
    assert r.method == "evidence"
    print("PASS: method='evidence' on check_with_evidence BLOCKED")


def test_method_evidence_on_uncertain_empty_evidence():
    r = bth.check_with_evidence("Paris", [], lambda a, e: True)
    assert r.status == bth.UNCERTAIN
    assert r.method == "evidence"
    print("PASS: method='evidence' on check_with_evidence UNCERTAIN (empty evidence)")


def test_method_evidence_on_uncertain_compare_fn_exception():
    def broken(a, e):
        raise RuntimeError("boom")
    r = bth.check_with_evidence("Paris", ["e"], broken)
    assert r.status == bth.UNCERTAIN
    assert r.method == "evidence"
    print("PASS: method='evidence' on check_with_evidence UNCERTAIN (compare_fn raised)")


def test_method_evidence_on_uncertain_out_of_range_score():
    r = bth.check_with_evidence("Paris", ["e"], lambda a, e: 5.0)
    assert r.status == bth.UNCERTAIN
    assert r.method == "evidence"
    print("PASS: method='evidence' on check_with_evidence UNCERTAIN (out-of-range score)")


def test_method_undefined_construction_documented_not_crashing():
    """Not a supported case — status=BLOCKED is documented as
    unreachable from check()/acheck(), so a hand-built BoothResult with
    BLOCKED + non-empty attempts is outside the property's designed
    domain. This test only confirms it doesn't crash, not that the
    returned value is meaningful."""
    fake_attempt = bth.Attempt(raw_text="x", answer="x", confidence=0.9, parse_ok=True)
    r = bth.BoothResult(answer="x", status=bth.BLOCKED, attempts=[fake_attempt])
    _ = r.method  # must not raise
    print(f"PASS: hand-built BLOCKED-with-attempts doesn't crash (method='{r.method}', undefined by design)")


def test_method_async_parity_confidence():
    async def call_fn(p):
        return json.dumps({"answer": "Paris", "confidence": 0.9})
    r = asyncio.run(bth.acheck(call_fn, "q"))
    assert r.method == "confidence"
    print("PASS: acheck() VERIFIED -> method='confidence'")


def test_method_async_parity_ambiguity():
    async def call_fn(p):
        return json.dumps({
            "ambiguous": True, "interpretations": ["a", "b"],
            "chosen_interpretation": "a", "answer": "x", "confidence": 0.9,
        })
    r = asyncio.run(bth.acheck(call_fn, "q"))
    assert r.method == "ambiguity"
    print("PASS: acheck() AMBIGUOUS -> method='ambiguity'")


def test_method_async_parity_parse_failure():
    async def call_fn(p):
        return "not json"
    r = asyncio.run(bth.acheck(call_fn, "q", max_retries=0))
    assert r.method == "parse_failure"
    print("PASS: acheck() all-parse-failed UNCERTAIN -> method='parse_failure'")


if __name__ == "__main__":
    test_method_confidence_on_verified()
    test_method_confidence_on_repaired()
    test_method_ambiguity()
    test_method_ambiguity_detected_only_on_retry()
    test_method_parse_failure_all_attempts_unparseable()
    test_method_parse_failure_all_attempts_raise_exception()
    test_method_confidence_on_uncertain_from_low_confidence()
    test_method_confidence_on_mixed_parse_failure_then_low_confidence()
    test_method_confidence_on_mixed_exception_then_low_confidence()
    test_method_evidence_on_verified()
    test_method_evidence_on_blocked()
    test_method_evidence_on_uncertain_empty_evidence()
    test_method_evidence_on_uncertain_compare_fn_exception()
    test_method_evidence_on_uncertain_out_of_range_score()
    test_method_undefined_construction_documented_not_crashing()
    test_method_async_parity_confidence()
    test_method_async_parity_ambiguity()
    test_method_async_parity_parse_failure()
    print("\nAll method property tests passed.")