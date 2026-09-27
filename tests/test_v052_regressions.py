"""
Regression tests for v0.5.2.

Three fixes, each isolated:

1. check_with_evidence(): a whitespace-only `answer` now normalizes to
   `.answer is None` in the EMPTY_ANSWER result, matching the
   empty-string case (previously only the empty string was normalized;
   whitespace passed through as the literal string).
2. check_with_evidence(): a boolean-False compare_fn rejection now
   produces detail="compare_fn returned False" instead of a fabricated
   "score X below evidence_threshold Y" message (evidence_threshold is
   documented as not applied to boolean returns at all).
3. check()/acheck(): a non-str `prompt` or non-callable `call_fn` now
   raises TypeError immediately, instead of crashing deep inside
   _build_prompt() or the retry loop.
"""

import asyncio

import pytest

import booth


# ---------------------------------------------------------------------
# Fix 1: whitespace-only answer normalization in EMPTY_ANSWER result
# ---------------------------------------------------------------------

def _dummy_compare(answer, evidence):
    return True


def test_empty_string_answer_normalizes_to_none():
    result = booth.check_with_evidence(
        answer="", evidence=["e"], compare_fn=_dummy_compare,
    )
    assert result.status == booth.UNCERTAIN
    assert result.reason == booth.EMPTY_ANSWER
    assert result.answer is None
    assert result.detail == "answer was empty or whitespace-only"


def test_whitespace_only_answer_normalizes_to_none():
    result = booth.check_with_evidence(
        answer="   ", evidence=["e"], compare_fn=_dummy_compare,
    )
    assert result.status == booth.UNCERTAIN
    assert result.reason == booth.EMPTY_ANSWER
    # Previously this was the literal "   " string, not None.
    assert result.answer is None
    assert result.detail == "answer was empty or whitespace-only"


def test_tab_and_newline_only_answer_normalizes_to_none():
    result = booth.check_with_evidence(
        answer="\t\n  \n", evidence=["e"], compare_fn=_dummy_compare,
    )
    assert result.status == booth.UNCERTAIN
    assert result.reason == booth.EMPTY_ANSWER
    assert result.answer is None


def test_empty_and_whitespace_answer_produce_identical_result_shape():
    """The whole point of the fix: two inputs with the same
    status/reason/detail should no longer diverge on .answer."""
    empty_result = booth.check_with_evidence(
        answer="", evidence=["e"], compare_fn=_dummy_compare,
    )
    whitespace_result = booth.check_with_evidence(
        answer="   ", evidence=["e"], compare_fn=_dummy_compare,
    )
    assert empty_result.answer == whitespace_result.answer == None
    assert empty_result.status == whitespace_result.status
    assert empty_result.reason == whitespace_result.reason
    assert empty_result.detail == whitespace_result.detail


def test_none_answer_still_normalizes_to_none():
    """Not a regression target, but confirms the None-answer path
    (already correct before this fix) still works after the edit."""
    result = booth.check_with_evidence(
        answer=None, evidence=["e"], compare_fn=_dummy_compare,
    )
    assert result.status == booth.UNCERTAIN
    assert result.reason == booth.EMPTY_ANSWER
    assert result.answer is None


# ---------------------------------------------------------------------
# Fix 2: boolean-False compare_fn detail no longer fabricates a
# threshold comparison
# ---------------------------------------------------------------------

def test_boolean_false_compare_fn_detail_does_not_mention_threshold():
    def compare_false(answer, evidence):
        return False

    result = booth.check_with_evidence(
        answer="some answer",
        evidence=["some evidence"],
        compare_fn=compare_false,
        evidence_threshold=0.8,
    )
    assert result.status == booth.BLOCKED
    assert result.reason == booth.EVIDENCE_DISAGREES
    assert result.detail == "compare_fn returned False"
    assert "threshold" not in result.detail
    assert "0.8" not in result.detail


def test_boolean_true_compare_fn_has_no_detail():
    def compare_true(answer, evidence):
        return True

    result = booth.check_with_evidence(
        answer="some answer",
        evidence=["some evidence"],
        compare_fn=compare_true,
    )
    assert result.status == booth.ACCEPTED
    assert result.reason is None
    assert result.detail is None


def test_numeric_score_below_threshold_detail_unchanged():
    """The score/threshold detail message is only wrong for the
    boolean path -- the numeric path's existing message is correct
    and must not change."""
    def compare_score(answer, evidence):
        return 0.62

    result = booth.check_with_evidence(
        answer="some answer",
        evidence=["some evidence"],
        compare_fn=compare_score,
        evidence_threshold=0.8,
    )
    assert result.status == booth.BLOCKED
    assert result.reason == booth.EVIDENCE_DISAGREES
    assert result.detail == "score 0.62 below evidence_threshold 0.8"


def test_numpy_boolish_false_uses_boolean_detail_wording():
    """numpy.bool_(False) is boolish per _is_boolish() and must take
    the same detail path as a native False."""
    np = pytest.importorskip("numpy")

    def compare_np_false(answer, evidence):
        return np.bool_(False)

    result = booth.check_with_evidence(
        answer="some answer",
        evidence=["some evidence"],
        compare_fn=compare_np_false,
        evidence_threshold=0.0,
    )
    assert result.status == booth.BLOCKED
    assert result.detail == "compare_fn returned False"


# ---------------------------------------------------------------------
# Fix 3: prompt / call_fn type validation in check() / acheck()
# ---------------------------------------------------------------------

def _valid_call_fn(prompt: str) -> str:
    return '{"answer": "Paris", "confidence": 0.95}'


async def _valid_async_call_fn(prompt: str) -> str:
    return '{"answer": "Paris", "confidence": 0.95}'


@pytest.mark.parametrize("bad_prompt", [123, None, ["a", "list"], {"a": 1}, 3.14])
def test_check_rejects_non_str_prompt(bad_prompt):
    called = {"count": 0}

    def call_fn(prompt):
        called["count"] += 1
        return _valid_call_fn(prompt)

    with pytest.raises(TypeError, match="prompt must be a str"):
        booth.check(call_fn, bad_prompt)

    # call_fn must never be invoked once prompt validation fails.
    assert called["count"] == 0


@pytest.mark.parametrize("bad_call_fn", ["not_callable", 123, None, ["a", "list"]])
def test_check_rejects_non_callable_call_fn(bad_call_fn):
    with pytest.raises(TypeError, match="call_fn must be callable"):
        booth.check(bad_call_fn, "What is the capital of France?")


def test_check_valid_args_unaffected_by_new_validation():
    result = booth.check(_valid_call_fn, "What is the capital of France?")
    assert result.ok
    assert result.answer == "Paris"


@pytest.mark.parametrize("bad_prompt", [123, None, ["a", "list"], {"a": 1}, 3.14])
def test_acheck_rejects_non_str_prompt(bad_prompt):
    called = {"count": 0}

    async def call_fn(prompt):
        called["count"] += 1
        return await _valid_async_call_fn(prompt)

    async def run():
        with pytest.raises(TypeError, match="prompt must be a str"):
            await booth.acheck(call_fn, bad_prompt)

    asyncio.run(run())
    assert called["count"] == 0


@pytest.mark.parametrize("bad_call_fn", ["not_callable", 123, None, ["a", "list"]])
def test_acheck_rejects_non_callable_call_fn(bad_call_fn):
    async def run():
        with pytest.raises(TypeError, match="call_fn must be callable"):
            await booth.acheck(bad_call_fn, "What is the capital of France?")

    asyncio.run(run())


def test_acheck_valid_args_unaffected_by_new_validation():
    async def run():
        return await booth.acheck(
            _valid_async_call_fn, "What is the capital of France?"
        )

    result = asyncio.run(run())
    assert result.ok
    assert result.answer == "Paris"


def test_check_prompt_validation_runs_before_threshold_validation():
    """Type errors on the entry-point arguments should surface before
    value errors -- a non-str prompt should raise its own clear
    TypeError even if threshold is also invalid, rather than getting
    a confusing error about threshold instead."""
    with pytest.raises(TypeError, match="prompt must be a str"):
        booth.check(_valid_call_fn, 123, threshold=1.5)


def test_acheck_sync_call_fn_still_raises_its_own_specific_error():
    """A sync call_fn passed to acheck() should still be rejected for
    being sync -- not accidentally swallowed by the new callable()
    check, since a sync function is still callable."""
    async def run():
        with pytest.raises(TypeError, match="acheck\\(\\) requires an async call_fn"):
            await booth.acheck(_valid_call_fn, "What is the capital of France?")

    asyncio.run(run())


def test_check_async_call_fn_still_raises_its_own_specific_error():
    """An async call_fn passed to check() should still be rejected for
    being async -- not accidentally swallowed by the new callable()
    check, since an async function is still callable."""
    with pytest.raises(TypeError, match="check\\(\\) requires a synchronous call_fn"):
        booth.check(_valid_async_call_fn, "What is the capital of France?")