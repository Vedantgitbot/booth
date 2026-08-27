"""
Tests for validator=, added in 0.4.2. Covers check() and acheck(),
the full _run_validator normalization contract, ordering relative to
ambiguity/parse/confidence, and the new method="validation" value.
Run: python3 tests/test_validator.py
"""
import asyncio
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import booth as bth


def make_mock(sequence):
    calls = {"n": 0}
    def call_fn(p):
        i = calls["n"]
        calls["n"] += 1
        answer, confidence = sequence[min(i, len(sequence) - 1)]
        return json.dumps({"answer": answer, "confidence": confidence})
    return call_fn


def test_validator_none_is_pure_noop_full_regression():
    """The single most important test in this file: validator=None
    must reproduce every pre-0.4.2 behavior exactly. Runs a battery of
    the existing test_core.py scenarios with validator explicitly
    passed as None (not omitted) to prove the parameter itself is
    inert."""
    r1 = bth.check(make_mock([("Paris", 0.95)]), "q", validator=None)
    assert r1.status == bth.VERIFIED and r1.method == "confidence"

    r2 = bth.check(make_mock([("Lyon", 0.3), ("Paris", 0.9)]), "q", max_retries=1, validator=None)
    assert r2.status == bth.REPAIRED and r2.method == "confidence"

    def amb(p):
        return json.dumps({"ambiguous": True, "interpretations": ["a", "b"],
                            "chosen_interpretation": "a", "answer": "x", "confidence": 0.9})
    r3 = bth.check(amb, "q", validator=None)
    assert r3.status == bth.AMBIGUOUS and r3.method == "ambiguity"
    print("PASS: validator=None reproduces pre-0.4.2 behavior exactly (VERIFIED/REPAIRED/AMBIGUOUS)")


def test_validator_bool_true_passes_first_try():
    call_fn = make_mock([("Paris", 0.9)])
    r = bth.check(call_fn, "q", validator=lambda a: True)
    assert r.status == bth.VERIFIED
    assert r.attempts[0].passed_validation is True
    assert r.attempts[0].validation_error is None
    print("PASS: validator returning True -> passes, VERIFIED")


def test_validator_bool_false_triggers_retry_generic_message():
    calls = {"n": 0}
    def call_fn(p):
        calls["n"] += 1
        return json.dumps({"answer": "x", "confidence": 0.9})
    r = bth.check(call_fn, "q", max_retries=1, validator=lambda a: False)
    assert r.status == bth.UNCERTAIN, r.status
    assert calls["n"] == 2, "should have retried once"
    assert r.attempts[0].passed_validation is False
    assert r.attempts[0].validation_error == "Validator returned False"
    assert r.method == "validation"
    print("PASS: validator returning bare False -> generic message, retries, method='validation'")


def test_validator_tuple_false_with_custom_message():
    def call_fn(p):
        return json.dumps({"answer": "x", "confidence": 0.9})
    r = bth.check(call_fn, "q", max_retries=0, validator=lambda a: (False, "must be numeric"))
    assert r.status == bth.UNCERTAIN
    assert r.attempts[0].validation_error == "must be numeric"
    assert r.method == "validation"
    print("PASS: validator returning (False, 'reason') -> custom message preserved")


def test_validator_exception_treated_as_failure_not_propagated():
    def broken_validator(a):
        raise RuntimeError("boom")
    def call_fn(p):
        return json.dumps({"answer": "x", "confidence": 0.9})
    r = bth.check(call_fn, "q", max_retries=0, validator=broken_validator)
    assert r.status == bth.UNCERTAIN
    assert "RuntimeError" in r.attempts[0].validation_error
    assert "boom" in r.attempts[0].validation_error
    assert r.method == "validation"
    print("PASS: validator exception caught, treated as failure, never propagates out of check()")


def test_validator_invalid_return_type_treated_as_failure():
    def call_fn(p):
        return json.dumps({"answer": "x", "confidence": 0.9})
    r = bth.check(call_fn, "q", max_retries=0, validator=lambda a: "not a bool")
    assert r.status == bth.UNCERTAIN
    assert "invalid type" in r.attempts[0].validation_error.lower()
    print("PASS: validator returning a non-bool/tuple type -> treated as failure, no crash")


def test_validator_never_runs_on_ambiguous_attempt():
    """The key ordering guarantee: an attempt flagged ambiguous must
    never even be handed to the validator — confirmed by call count,
    not just by final status."""
    calls = {"n": 0}
    def spy_validator(a):
        calls["n"] += 1
        return True
    def call_fn(p):
        return json.dumps({"ambiguous": True, "interpretations": ["a", "b"],
                            "chosen_interpretation": "a", "answer": "x", "confidence": 0.9})
    r = bth.check(call_fn, "q", validator=spy_validator)
    assert r.status == bth.AMBIGUOUS
    assert calls["n"] == 0, "validator must never be called for an ambiguous attempt"
    print("PASS: validator is never invoked on an ambiguous attempt (0 calls)")


def test_validator_never_runs_on_parse_failure():
    calls = {"n": 0}
    def spy_validator(a):
        calls["n"] += 1
        return True
    def call_fn(p):
        return "not json at all"
    r = bth.check(call_fn, "q", max_retries=0, validator=spy_validator)
    assert r.status == bth.UNCERTAIN
    assert calls["n"] == 0, "validator must never be called when the response didn't parse"
    assert r.method == "parse_failure"
    print("PASS: validator is never invoked on an unparseable attempt (0 calls)")


def test_validator_fail_then_pass_produces_repaired():
    calls = {"n": 0}
    def alternating_validator(a):
        calls["n"] += 1
        return calls["n"] >= 2  # fails first call, passes second
    def call_fn(p):
        return json.dumps({"answer": "x", "confidence": 0.9})
    r = bth.check(call_fn, "q", max_retries=1, validator=alternating_validator)
    assert r.status == bth.REPAIRED, r.status
    assert r.attempts[0].passed_validation is False
    assert r.attempts[1].passed_validation is True
    assert r.method == "confidence"  # last attempt's determining factor was confidence, not validation
    print("PASS: validation fail-then-pass -> REPAIRED (not a new status), final method='confidence'")


def test_validation_retry_prompt_shows_the_specific_error():
    seen_prompts = []
    def call_fn(p):
        seen_prompts.append(p)
        return json.dumps({"answer": "x", "confidence": 0.9})
    bth.check(call_fn, "q", max_retries=1, validator=lambda a: (False, "must start with a digit"))
    assert len(seen_prompts) == 2
    assert "must start with a digit" in seen_prompts[1]
    assert "could not be parsed" not in seen_prompts[1], "must not reuse the parse-failure prompt"
    assert "previous attempt you answered" not in seen_prompts[1], "must not reuse the confidence-retry prompt template"
    print("PASS: validation-failure retry prompt is distinct and shows the specific validation_error")


def test_mixed_three_way_history_method_reflects_last_attempt():
    """The real stress test: parse failure -> validation failure ->
    (retries exhausted). method must be 'validation', reflecting the
    LAST attempt's actual failure reason, not the first."""
    calls = {"n": 0}
    def call_fn(p):
        calls["n"] += 1
        if calls["n"] == 1:
            return "garbage, not json"
        return json.dumps({"answer": "x", "confidence": 0.9})
    r = bth.check(call_fn, "q", max_retries=1, validator=lambda a: False)
    assert calls["n"] == 2
    assert r.status == bth.UNCERTAIN
    assert r.attempts[0].parse_ok is False
    assert r.attempts[1].parse_ok is True
    assert r.attempts[1].passed_validation is False
    assert r.all_parse_failed is False  # attempt 2 DID parse
    assert r.method == "validation"
    print("PASS: parse-failure-then-validation-failure -> method='validation' (last attempt's reason)")


def test_mixed_validation_then_confidence_method_reflects_last_attempt():
    """Reverse mix: attempt 1 fails validation, attempt 2 passes
    validation but fails confidence. Final method should be
    'confidence' — validation passed on the deciding attempt."""
    calls = {"n": 0}
    def alternating_validator(a):
        calls["n"] += 1
        return calls["n"] >= 2
    def call_fn(p):
        return json.dumps({"answer": "x", "confidence": 0.2})  # always low confidence
    r = bth.check(call_fn, "q", max_retries=1, validator=alternating_validator)
    assert r.status == bth.UNCERTAIN
    assert r.attempts[0].passed_validation is False
    assert r.attempts[1].passed_validation is True
    assert r.method == "confidence"
    print("PASS: validation-failure-then-confidence-failure -> method='confidence' (validation passed last)")


def test_evidence_results_unaffected_by_validator_addition():
    """Regression: check_with_evidence() has no validator concept at
    all and must be completely untouched by this release."""
    r = bth.check_with_evidence("Paris", ["Paris is the capital"], lambda a, e: True)
    assert r.status == bth.VERIFIED
    assert r.method == "evidence"
    print("PASS: check_with_evidence() unaffected by validator addition")


def test_async_validator_parity_pass():
    async def call_fn(p):
        return json.dumps({"answer": "x", "confidence": 0.9})
    r = asyncio.run(bth.acheck(call_fn, "q", validator=lambda a: True))
    assert r.status == bth.VERIFIED
    print("PASS: acheck() validator pass -> VERIFIED")


def test_async_validator_parity_fail_then_repaired():
    calls = {"n": 0}
    def alternating_validator(a):
        calls["n"] += 1
        return calls["n"] >= 2
    async def call_fn(p):
        return json.dumps({"answer": "x", "confidence": 0.9})
    r = asyncio.run(bth.acheck(call_fn, "q", max_retries=1, validator=alternating_validator))
    assert r.status == bth.REPAIRED
    print("PASS: acheck() validation fail-then-pass -> REPAIRED")


def test_async_validator_never_runs_on_ambiguous():
    calls = {"n": 0}
    def spy_validator(a):
        calls["n"] += 1
        return True
    async def call_fn(p):
        return json.dumps({"ambiguous": True, "interpretations": ["a", "b"],
                            "chosen_interpretation": "a", "answer": "x", "confidence": 0.9})
    r = asyncio.run(bth.acheck(call_fn, "q", validator=spy_validator))
    assert r.status == bth.AMBIGUOUS
    assert calls["n"] == 0
    print("PASS: acheck() validator never invoked on ambiguous attempt")


def test_check_and_acheck_agree_with_validator():
    """Same shared-_evaluate() parity check as the acheck test suite
    already has for the base flow, extended to cover validator."""
    def sync_call_fn(p):
        return json.dumps({"answer": "x", "confidence": 0.9})
    async def async_call_fn(p):
        return json.dumps({"answer": "x", "confidence": 0.9})

    r_sync = bth.check(sync_call_fn, "q", max_retries=0, validator=lambda a: False)
    r_async = asyncio.run(bth.acheck(async_call_fn, "q", max_retries=0, validator=lambda a: False))

    assert r_sync.status == r_async.status == bth.UNCERTAIN
    assert r_sync.method == r_async.method == "validation"
    print("PASS: check() and acheck() agree on validator outcomes (shared _evaluate/_run_validator)")


if __name__ == "__main__":
    test_validator_none_is_pure_noop_full_regression()
    test_validator_bool_true_passes_first_try()
    test_validator_bool_false_triggers_retry_generic_message()
    test_validator_tuple_false_with_custom_message()
    test_validator_exception_treated_as_failure_not_propagated()
    test_validator_invalid_return_type_treated_as_failure()
    test_validator_never_runs_on_ambiguous_attempt()
    test_validator_never_runs_on_parse_failure()
    test_validator_fail_then_pass_produces_repaired()
    test_validation_retry_prompt_shows_the_specific_error()
    test_mixed_three_way_history_method_reflects_last_attempt()
    test_mixed_validation_then_confidence_method_reflects_last_attempt()
    test_evidence_results_unaffected_by_validator_addition()
    test_async_validator_parity_pass()
    test_async_validator_parity_fail_then_repaired()
    test_async_validator_never_runs_on_ambiguous()
    test_check_and_acheck_agree_with_validator()
    print("\nAll validator tests passed.")