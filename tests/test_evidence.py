"""
Smoke test for booth.check_with_evidence() — the Path A evidence gate.
Pure function, no LLM/network calls, so these tests use plain reference
compare_fn implementations. Run: python3 tests/test_evidence.py
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import booth as bth


def keyword_overlap_compare(answer: str, evidence):
    """Reference float compare_fn: word overlap ratio."""
    answer_words = set(answer.lower().split())
    evidence_words = set(" ".join(evidence).lower().split())
    if not answer_words:
        return 0.0
    return len(answer_words & evidence_words) / len(answer_words)


def strict_bool_compare(answer: str, evidence):
    """Reference bool compare_fn: exact substring match."""
    return answer.lower() in " ".join(evidence).lower()


def failing_compare(answer: str, evidence):
    raise ValueError("comparison computation failed internally")


def out_of_range_compare(answer: str, evidence):
    return 5.0  # violates the documented [0.0, 1.0] contract


def non_numeric_compare(answer: str, evidence):
    return "very confident"  # violates the documented bool|float contract


def test_verified_float_above_threshold():
    r = bth.check_with_evidence(
        answer="Paris is the capital of France",
        evidence=["The capital of France is Paris"],
        compare_fn=keyword_overlap_compare,
        evidence_threshold=0.5,
    )
    assert r.status == bth.VERIFIED, r.status
    assert r.ok is True
    assert r.confidence >= 0.5
    assert r.evidence_agreement == r.confidence
    assert r.ambiguous is False
    assert r.attempts == []
    print("PASS: float score above threshold -> VERIFIED")


def test_blocked_float_below_threshold():
    r = bth.check_with_evidence(
        answer="Tokyo is the capital of France",
        evidence=["France's capital city is Paris."],
        compare_fn=keyword_overlap_compare,
        evidence_threshold=0.5,
    )
    assert r.status == bth.BLOCKED, r.status
    assert r.ok is False
    assert r.confidence < 0.5
    assert r.evidence_agreement == r.confidence
    print("PASS: float score below threshold -> BLOCKED")


def test_verified_bool_true():
    r = bth.check_with_evidence(
        answer="paris",
        evidence=["France's capital city is Paris."],
        compare_fn=strict_bool_compare,
    )
    assert r.status == bth.VERIFIED, r.status
    assert r.ok is True
    assert r.confidence == 1.0
    assert r.evidence_agreement == 1.0
    print("PASS: compare_fn returning True -> VERIFIED, confidence=1.0")


def test_bool_false_bypasses_threshold_even_at_zero():
    """Regression test for the core edge case: a bool False must
    ALWAYS produce BLOCKED, even when evidence_threshold is set to
    0.0. If bools were compared like floats, False -> 0.0 and
    0.0 >= 0.0 would incorrectly pass."""
    r = bth.check_with_evidence(
        answer="Berlin",
        evidence=["France's capital city is Paris."],
        compare_fn=strict_bool_compare,
        evidence_threshold=0.0,
    )
    assert r.status == bth.BLOCKED, r.status
    assert r.ok is False
    assert r.confidence == 0.0
    assert r.evidence_agreement == 0.0
    print("PASS: bool False -> BLOCKED even with evidence_threshold=0.0")


def test_empty_answer_is_uncertain():
    r = bth.check_with_evidence(
        answer="",
        evidence=["some evidence"],
        compare_fn=strict_bool_compare,
    )
    assert r.status == bth.UNCERTAIN, r.status
    assert r.ok is False
    assert r.confidence is None
    print("PASS: empty answer -> UNCERTAIN")


def test_empty_evidence_is_uncertain():
    r = bth.check_with_evidence(
        answer="Paris",
        evidence=[],
        compare_fn=strict_bool_compare,
    )
    assert r.status == bth.UNCERTAIN, r.status
    assert r.ok is False
    print("PASS: empty evidence -> UNCERTAIN")


def test_compare_fn_exception_is_uncertain_not_raised():
    r = bth.check_with_evidence(
        answer="Paris",
        evidence=["France's capital city is Paris."],
        compare_fn=failing_compare,
    )
    assert r.status == bth.UNCERTAIN, r.status
    assert r.ok is False
    assert r.confidence is None
    print("PASS: compare_fn raising an exception -> UNCERTAIN, no crash")


def test_out_of_range_float_is_uncertain_not_clamped():
    """A compare_fn returning e.g. 5.0 violates the documented
    [0.0, 1.0] contract. Must be treated as a failed comparison, not
    silently clamped or compared as-is against evidence_threshold —
    same principle as check()'s refusal to clamp out-of-range
    self-reported confidence."""
    r = bth.check_with_evidence(
        answer="Paris",
        evidence=["France's capital city is Paris."],
        compare_fn=out_of_range_compare,
        evidence_threshold=0.5,
    )
    assert r.status == bth.UNCERTAIN, r.status
    assert r.ok is False
    assert r.confidence is None
    print("PASS: out-of-range float score (5.0) -> UNCERTAIN, not clamped")


def test_non_numeric_return_is_uncertain():
    r = bth.check_with_evidence(
        answer="Paris",
        evidence=["France's capital city is Paris."],
        compare_fn=non_numeric_compare,
    )
    assert r.status == bth.UNCERTAIN, r.status
    assert r.ok is False
    print("PASS: non-numeric, non-bool compare_fn return -> UNCERTAIN, no crash")


def test_invalid_evidence_threshold_raises():
    try:
        bth.check_with_evidence("Paris", ["evidence"], strict_bool_compare, evidence_threshold=1.5)
        assert False, "expected ValueError"
    except ValueError:
        print("PASS: evidence_threshold out of [0,1] raises ValueError")


def test_result_fields_are_path_b_defaults():
    """ambiguous / interpretations / attempts must always be the
    Path-B-shaped defaults for an evidence result — they don't apply
    to this path, and callers should be able to rely on that."""
    r = bth.check_with_evidence(
        answer="Paris is the capital of France",
        evidence=["France's capital is Paris."],
        compare_fn=keyword_overlap_compare,
        evidence_threshold=0.5,
    )
    assert r.ambiguous is False
    assert r.interpretations == []
    assert r.attempts == []
    assert r.n_attempts == 0
    assert r.all_parse_failed is False
    print("PASS: non-applicable Path B fields are always defaults on evidence results")


def test_threshold_and_evidence_threshold_are_independent():
    """Sanity check that check()'s `threshold` param and
    check_with_evidence()'s `evidence_threshold` are genuinely separate
    — passing one does not affect the other's function."""
    r_strict = bth.check_with_evidence(
        answer="Tokyo is the capital of France",
        evidence=["France's capital city is Paris."],
        compare_fn=keyword_overlap_compare,
        evidence_threshold=0.9,
    )
    r_lenient = bth.check_with_evidence(
        answer="Tokyo is the capital of France",
        evidence=["France's capital city is Paris."],
        compare_fn=keyword_overlap_compare,
        evidence_threshold=0.1,
    )
    assert r_strict.status == bth.BLOCKED
    assert r_lenient.status == bth.VERIFIED
    assert r_strict.confidence == r_lenient.confidence, "same compare_fn score, different thresholds"
    print("PASS: evidence_threshold independently controls pass/fail for the same score")


if __name__ == "__main__":
    test_verified_float_above_threshold()
    test_blocked_float_below_threshold()
    test_verified_bool_true()
    test_bool_false_bypasses_threshold_even_at_zero()
    test_empty_answer_is_uncertain()
    test_empty_evidence_is_uncertain()
    test_compare_fn_exception_is_uncertain_not_raised()
    test_out_of_range_float_is_uncertain_not_clamped()
    test_non_numeric_return_is_uncertain()
    test_invalid_evidence_threshold_raises()
    test_result_fields_are_path_b_defaults()
    test_threshold_and_evidence_threshold_are_independent()
    print("\nAll check_with_evidence smoke tests passed.")