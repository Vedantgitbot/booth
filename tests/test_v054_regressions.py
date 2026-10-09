"""
Regression tests for v0.5.4.

1. A failed call_fn (raised, or returned a non-str) is now marked on the
   attempt (Attempt.call_failed) and on the result (BoothResult.call_failed),
   so it can be told apart from a model that returned garbage.
2. After a failed call, the retry sends the original prompt instead of the
   "your previous response could not be parsed" prompt.

status and method are unchanged for call failures.
"""

import asyncio
import json

import pytest

import booth

GOOD = '{"answer": "Paris", "confidence": 0.95}'
LOW = '{"answer": "Paris", "confidence": 0.2}'
AMBIGUOUS_REPLY = (
    '{"ambiguous": true, "interpretations": ["a", "b"], '
    '"chosen_interpretation": "a", "answer": "x", "confidence": 0.9}'
)
PARSE_MARKER = "could not be parsed"


def scripted(*steps):
    """Sync call_fn that plays back steps in order and records the prompts it saw.

    A step is either a string to return or an Exception to raise.
    """
    seen = []
    it = iter(steps)

    def call_fn(prompt):
        seen.append(prompt)
        step = next(it)
        if isinstance(step, Exception):
            raise step
        return step

    call_fn.seen = seen
    return call_fn


def ascripted(*steps):
    seen = []
    it = iter(steps)

    async def call_fn(prompt):
        seen.append(prompt)
        step = next(it)
        if isinstance(step, Exception):
            raise step
        return step

    call_fn.seen = seen
    return call_fn


# ---------------------------------------------------------------------
# Fix 1: call_failed on Attempt and BoothResult
# ---------------------------------------------------------------------

def test_attempt_call_failed_defaults_to_false():
    a = booth.Attempt(raw_text="x", answer=None, confidence=None, parse_ok=False)
    assert a.call_failed is False


def test_raising_call_fn_marks_every_attempt_and_the_result():
    fn = scripted(RuntimeError("401 bad key"), RuntimeError("401 bad key"))
    result = booth.check(fn, "q", max_retries=1)

    assert result.status == booth.UNCERTAIN
    assert result.answer is None
    assert result.n_attempts == 2
    assert all(a.call_failed for a in result.attempts)
    assert result.call_failed is True
    assert result.attempts[-1].error == "401 bad key"


def test_call_failure_keeps_status_and_method_unchanged():
    fn = scripted(RuntimeError("boom"), RuntimeError("boom"))
    result = booth.check(fn, "q", max_retries=1)

    assert result.status == booth.UNCERTAIN
    assert result.method == "parse_failure"
    assert result.all_parse_failed is True


def test_single_attempt_call_failure():
    fn = scripted(RuntimeError("boom"))
    result = booth.check(fn, "q", max_retries=0)

    assert result.n_attempts == 1
    assert result.call_failed is True


@pytest.mark.parametrize("bad_return", [None, {"answer": "x"}, 42, ["a"]])
def test_non_str_return_counts_as_call_failure(bad_return):
    fn = scripted(bad_return, bad_return)
    result = booth.check(fn, "q", max_retries=1)

    assert result.status == booth.UNCERTAIN
    assert all(a.call_failed for a in result.attempts)
    assert result.call_failed is True
    assert "expected str" in result.attempts[-1].error


def test_garbage_response_is_not_a_call_failure():
    fn = scripted("not json at all", "still not json")
    result = booth.check(fn, "q", max_retries=1)

    assert result.all_parse_failed is True
    assert result.call_failed is False
    assert not any(a.call_failed for a in result.attempts)


def test_low_confidence_is_not_a_call_failure():
    fn = scripted(LOW, LOW)
    result = booth.check(fn, "q", max_retries=1)

    assert result.status == booth.UNCERTAIN
    assert result.call_failed is False


def test_failed_call_then_success_is_repaired_and_result_not_call_failed():
    fn = scripted(RuntimeError("blip"), GOOD)
    result = booth.check(fn, "q", max_retries=1)

    assert result.status == booth.REPAIRED
    assert result.attempts[0].call_failed is True
    assert result.attempts[1].call_failed is False
    assert result.call_failed is False


def test_low_confidence_then_failed_call_is_not_result_call_failed():
    """Only 'every attempt failed' counts, same rule as all_parse_failed."""
    fn = scripted(LOW, RuntimeError("boom"))
    result = booth.check(fn, "q", max_retries=1)

    assert result.status == booth.UNCERTAIN
    assert result.attempts[-1].call_failed is True
    assert result.call_failed is False


def test_failed_call_then_ambiguous_reply_is_not_call_failed():
    fn = scripted(RuntimeError("blip"), AMBIGUOUS_REPLY)
    result = booth.check(fn, "q", max_retries=1)

    assert result.status == booth.AMBIGUOUS
    assert result.call_failed is False


def test_on_attempt_sees_call_failed_flag():
    flags = []
    fn = scripted(RuntimeError("boom"), GOOD)
    booth.check(fn, "q", max_retries=1, on_attempt=lambda i, a: flags.append(a.call_failed))

    assert flags == [True, False]


def test_unwrap_on_call_failure_carries_call_failed_on_the_exception():
    fn = scripted(RuntimeError("boom"), RuntimeError("boom"))
    result = booth.check(fn, "q", max_retries=1)

    with pytest.raises(booth.BoothRejected) as exc:
        result.unwrap()
    assert exc.value.result.call_failed is True


def test_result_with_no_attempts_is_not_call_failed():
    assert booth.BoothResult(answer=None, status=booth.UNCERTAIN).call_failed is False


def test_check_with_evidence_results_are_never_call_failed():
    result = booth.check_with_evidence("a", ["e"], lambda a, e: True)
    assert result.call_failed is False

    empty = booth.check_with_evidence("", ["e"], lambda a, e: True)
    assert empty.call_failed is False


def test_acheck_marks_call_failure_the_same_way():
    fn = ascripted(RuntimeError("401 bad key"), RuntimeError("401 bad key"))
    result = asyncio.run(booth.acheck(fn, "q", max_retries=1))

    assert result.status == booth.UNCERTAIN
    assert result.method == "parse_failure"
    assert result.call_failed is True
    assert result.attempts[-1].error == "401 bad key"


def test_acheck_non_str_return_counts_as_call_failure():
    fn = ascripted(None, None)
    result = asyncio.run(booth.acheck(fn, "q", max_retries=1))

    assert result.call_failed is True


def test_acheck_failed_call_then_success_is_repaired():
    fn = ascripted(RuntimeError("blip"), GOOD)
    result = asyncio.run(booth.acheck(fn, "q", max_retries=1))

    assert result.status == booth.REPAIRED
    assert result.attempts[0].call_failed is True
    assert result.call_failed is False


def test_to_dict_includes_call_failed_everywhere():
    fn = scripted(RuntimeError("boom"), GOOD)
    result = booth.check(fn, "q", max_retries=1)
    payload = result.to_dict()

    assert payload["call_failed"] is False
    assert payload["attempts"][0]["call_failed"] is True
    assert payload["attempts"][1]["call_failed"] is False
    json.dumps(payload)


def test_to_dict_call_failed_true_when_every_attempt_failed():
    fn = scripted(RuntimeError("boom"), RuntimeError("boom"))
    payload = booth.check(fn, "q", max_retries=1).to_dict()

    assert payload["call_failed"] is True
    json.dumps(payload)


# ---------------------------------------------------------------------
# Fix 2: retry prompt after a failed call
# ---------------------------------------------------------------------

def test_retry_after_raised_call_sends_the_original_prompt():
    fn = scripted(RuntimeError("blip"), GOOD)
    booth.check(fn, "What is the capital of France?", max_retries=1)

    assert fn.seen[1] == fn.seen[0]
    assert PARSE_MARKER not in fn.seen[1]


def test_retry_after_non_str_return_sends_the_original_prompt():
    fn = scripted(None, GOOD)
    booth.check(fn, "What is the capital of France?", max_retries=1)

    assert fn.seen[1] == fn.seen[0]
    assert PARSE_MARKER not in fn.seen[1]


def test_acheck_retry_after_raised_call_sends_the_original_prompt():
    fn = ascripted(RuntimeError("blip"), GOOD)
    asyncio.run(booth.acheck(fn, "What is the capital of France?", max_retries=1))

    assert fn.seen[1] == fn.seen[0]
    assert PARSE_MARKER not in fn.seen[1]


def test_retry_after_garbage_response_still_gets_the_parse_failure_prompt():
    fn = scripted("not json at all", GOOD)
    booth.check(fn, "What is the capital of France?", max_retries=1)

    assert PARSE_MARKER in fn.seen[1]
    assert fn.seen[1] != fn.seen[0]


def test_retry_after_low_confidence_still_asks_to_reconsider():
    fn = scripted(LOW, GOOD)
    booth.check(fn, "What is the capital of France?", max_retries=1)

    assert "Reconsider carefully" in fn.seen[1]
    assert PARSE_MARKER not in fn.seen[1]


def test_retry_after_validation_failure_still_shows_the_reason():
    fn = scripted(GOOD, GOOD)
    booth.check(
        fn,
        "What is the capital of France?",
        max_retries=1,
        validator=lambda answer: (False, "must be numeric"),
    )

    assert "failed validation: must be numeric" in fn.seen[1]


def test_three_calls_mixed_failure_then_garbage_picks_the_right_prompt_each_time():
    fn = scripted(RuntimeError("boom"), "garbage", GOOD)
    result = booth.check(fn, "q", max_retries=2)

    assert result.status == booth.REPAIRED
    assert fn.seen[1] == fn.seen[0]  # after the raised call
    assert PARSE_MARKER in fn.seen[2]  # after the garbage response