"""
Smoke test for booth.check() using a mock call_fn — validates the
retry/status/error-handling logic in isolation before wiring up a real
model. Run: python3 tests/test_smoke.py
"""

import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import booth as bth


def make_mock(sequence):
    """sequence: list of (answer, confidence) tuples, one per call."""
    calls = {"n": 0}

    def call_fn(prompt):
        i = calls["n"]
        calls["n"] += 1
        answer, confidence = sequence[min(i, len(sequence) - 1)]
        return json.dumps({"answer": answer, "confidence": confidence})

    return call_fn


def test_verified_first_try():
    call_fn = make_mock([("Paris", 0.95)])
    r = bth.check(call_fn, "Capital of France?", threshold=0.7, max_retries=1)
    assert r.status == bth.VERIFIED, r.status
    assert r.answer == "Paris"
    assert r.n_attempts == 1
    assert r.ok is True
    print("PASS: verified on first try")


def test_repaired_on_retry():
    call_fn = make_mock([("maybe Lyon?", 0.4), ("Paris", 0.9)])
    r = bth.check(call_fn, "Capital of France?", threshold=0.7, max_retries=1)
    assert r.status == bth.REPAIRED, r.status
    assert r.answer == "Paris"
    assert r.n_attempts == 2
    assert r.ok is True
    print("PASS: repaired after retry")


def test_retry_prompt_shows_previous_answer():
    seen_prompts = []

    def call_fn(prompt):
        seen_prompts.append(prompt)
        i = len(seen_prompts)
        if i == 1:
            return json.dumps({"answer": "Lyon", "confidence": 0.3})
        return json.dumps({"answer": "Paris", "confidence": 0.9})

    r = bth.check(call_fn, "Capital of France?", threshold=0.7, max_retries=1)
    assert len(seen_prompts) == 2
    assert seen_prompts[0] != seen_prompts[1]
    assert "Lyon" in seen_prompts[1], "retry prompt should reference the previous answer"
    assert "0.3" in seen_prompts[1], "retry prompt should reference the previous confidence"
    assert r.status == bth.REPAIRED
    print("PASS: retry prompt references previous answer (reconsideration, not resampling)")


def test_uncertain_after_exhausting_retries():
    call_fn = make_mock([("maybe Lyon?", 0.4), ("possibly Marseille?", 0.5)])
    r = bth.check(call_fn, "Capital of France?", threshold=0.7, max_retries=1)
    assert r.status == bth.UNCERTAIN, r.status
    assert r.n_attempts == 2
    assert r.answer == "possibly Marseille?"
    assert r.ok is False
    print("PASS: uncertain after exhausting retries")


def test_malformed_response_treated_as_low_confidence():
    def call_fn(prompt):
        return "I think it's Paris but I won't give you JSON."

    r = bth.check(call_fn, "Capital of France?", threshold=0.7, max_retries=1)
    assert r.status == bth.UNCERTAIN, r.status
    assert r.answer is None, "answer must be None on total parse failure, not raw model text"
    print("PASS: malformed response -> uncertain, answer=None, no crash")


def test_max_retries_zero_means_single_shot():
    call_fn = make_mock([("Paris", 0.5)])
    r = bth.check(call_fn, "Capital of France?", threshold=0.7, max_retries=0)
    assert r.status == bth.UNCERTAIN, r.status
    assert r.n_attempts == 1
    print("PASS: max_retries=0 -> exactly one attempt")


def test_call_fn_exception_does_not_crash():
    calls = {"n": 0}

    def flaky_call_fn(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("simulated network blip")
        return json.dumps({"answer": "Paris", "confidence": 0.9})

    r = bth.check(flaky_call_fn, "Capital of France?", threshold=0.7, max_retries=1)
    assert r.status == bth.REPAIRED, r.status
    assert r.answer == "Paris"
    assert r.attempts[0].error is not None
    print("PASS: call_fn exception on attempt 1 handled, recovers on retry")


def test_call_fn_exception_every_attempt_returns_uncertain_not_crash():
    def always_fails(prompt):
        raise TimeoutError("simulated timeout")

    r = bth.check(always_fails, "Capital of France?", threshold=0.7, max_retries=1)
    assert r.status == bth.UNCERTAIN, r.status
    assert r.answer is None
    assert all(a.error is not None for a in r.attempts)
    print("PASS: call_fn fails every attempt -> UNCERTAIN, no crash")


def test_exception_raw_text_carries_error_too():
    """raw_text should not be empty on an exception — anything that only
    logs raw_text (and ignores the separate `error` field) still needs
    to see what went wrong."""
    def always_fails(prompt):
        raise TimeoutError("simulated timeout")

    r = bth.check(always_fails, "Capital of France?", threshold=0.7, max_retries=0)
    assert r.attempts[0].raw_text != "", "raw_text should contain the error, not be blank"
    assert "TimeoutError" in r.attempts[0].raw_text
    print("PASS: raw_text carries error text on exception, not blank")


def test_confidence_out_of_range_is_rejected_not_clamped():
    """An out-of-range confidence (e.g. 1.5, 17, -3) violates the
    contract we asked the model to follow. Clamping it into range would
    silently turn a malformed response into a falsely maximal-confidence
    one — worse than surfacing the failure. It must be treated as
    unparseable, not repaired into 1.0."""
    call_fn = make_mock([("Paris", 17)])
    r = bth.check(call_fn, "Capital of France?", threshold=0.7, max_retries=0)
    assert r.status == bth.UNCERTAIN, r.status
    assert r.answer is None, "out-of-range confidence must not be silently clamped into an accepted answer"
    print("PASS: out-of-range confidence (17) rejected as unparseable, not clamped")


def test_confidence_non_numeric_treated_as_unparseable():
    def call_fn(prompt):
        return json.dumps({"answer": "Paris", "confidence": "very confident"})

    r = bth.check(call_fn, "Capital of France?", threshold=0.7, max_retries=0)
    assert r.status == bth.UNCERTAIN, r.status
    assert r.answer is None
    print("PASS: non-numeric confidence -> unparseable, no crash on float()")


def test_json_with_surrounding_commentary_still_parses():
    def call_fn(prompt):
        return (
            'Sure, here is my answer.\n'
            '{"answer": "Paris", "confidence": 0.92}\n'
            'Let me know if you need anything else!'
        )

    r = bth.check(call_fn, "Capital of France?", threshold=0.7, max_retries=0)
    assert r.status == bth.VERIFIED, r.status
    assert r.answer == "Paris"
    print("PASS: JSON with surrounding commentary still parses via fallback")


def test_on_attempt_callback_fires_for_every_attempt():
    log = []
    call_fn = make_mock([("Lyon", 0.3), ("Paris", 0.9)])
    r = bth.check(
        call_fn, "Capital of France?", threshold=0.7, max_retries=1,
        on_attempt=lambda i, a: log.append((i, a.confidence)),
    )
    assert log == [(0, 0.3), (1, 0.9)], log
    print("PASS: on_attempt callback fires with correct index/confidence per attempt")


def test_invalid_threshold_raises():
    try:
        bth.check(lambda p: "{}", "q", threshold=1.5)
        assert False, "expected ValueError"
    except ValueError:
        print("PASS: threshold out of [0,1] raises ValueError")


def test_negative_max_retries_raises():
    try:
        bth.check(lambda p: "{}", "q", max_retries=-1)
        assert False, "expected ValueError"
    except ValueError:
        print("PASS: negative max_retries raises ValueError")


if __name__ == "__main__":
    test_verified_first_try()
    test_repaired_on_retry()
    test_retry_prompt_shows_previous_answer()
    test_uncertain_after_exhausting_retries()
    test_malformed_response_treated_as_low_confidence()
    test_max_retries_zero_means_single_shot()
    test_call_fn_exception_does_not_crash()
    test_call_fn_exception_every_attempt_returns_uncertain_not_crash()
    test_exception_raw_text_carries_error_too()
    test_confidence_out_of_range_is_rejected_not_clamped()
    test_confidence_non_numeric_treated_as_unparseable()
    test_json_with_surrounding_commentary_still_parses()
    test_on_attempt_callback_fires_for_every_attempt()
    test_invalid_threshold_raises()
    test_negative_max_retries_raises()
    print("\nAll smoke tests passed.")