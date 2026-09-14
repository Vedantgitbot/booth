"""
Regression tests for the v0.4.8 batch.

BREAKING CHANGE: VERIFIED is renamed to ACCEPTED. There is no backward
compatible alias, per explicit decision: fix the naming early, while
BOOTH has few real dependents, rather than carry a misleading name
forward. `from booth import VERIFIED` now fails; every caller must
move to `booth.ACCEPTED`. The underlying status STRING also changed
from "VERIFIED" to "ACCEPTED" (not just the importable name) — any
code comparing against a hardcoded "VERIFIED" string literal (rather
than the exported constant) will silently stop matching. This was
always the wrong pattern to rely on; the constant was always the
documented interface.

Four confirmed bugs, all reproduced against the actual v0.4.7 tag
before being fixed here:
  1. check() had no defense against an async call_fn (acheck() already
     rejected the opposite direction). Fixed symmetrically.
  2. check()/acheck() crashed (AttributeError) if call_fn succeeded
     but returned something other than a string. Now becomes a failed
     Attempt, same treatment as a call_fn exception.
  3. max_retries=1.5 passed _validate_args() silently, then crashed
     deep in range(max_retries + 1) with an unhelpful TypeError.
  4. A non-string `answer` field (e.g. a dict) was silently
     str()-coerced into a Python repr and reported ACCEPTED at high
     confidence, instead of being rejected as a schema violation the
     same way a boolean `confidence` already was.
"""

import asyncio
import warnings

import pytest

import booth
from booth.core import ACCEPTED as _ACCEPTED_DIRECT  # sanity: importable from core too


def _run(coro):
    return asyncio.run(coro)


def _make_valid_raw(answer="42", confidence=0.95):
    return (
        '{"ambiguous": false, "interpretations": [], '
        f'"chosen_interpretation": null, "answer": "{answer}", '
        f'"confidence": {confidence}}}'
    )


# ---------------------------------------------------------------------
# ACCEPTED rename
# ---------------------------------------------------------------------

def test_accepted_is_exported_and_correct_value():
    assert booth.ACCEPTED == "ACCEPTED"
    assert _ACCEPTED_DIRECT == "ACCEPTED"


def test_verified_no_longer_exists():
    assert not hasattr(booth, "VERIFIED")
    with pytest.raises(ImportError):
        from booth import VERIFIED  # noqa: F401


def test_check_returns_accepted_not_verified():
    def call_fn(prompt):
        return _make_valid_raw()

    result = booth.check(call_fn, "q")
    assert result.status == booth.ACCEPTED
    assert result.status == "ACCEPTED"
    assert result.ok is True


def test_check_with_evidence_returns_accepted():
    result = booth.check_with_evidence(
        answer="Paris", evidence=["Paris is the capital."], compare_fn=lambda a, e: True
    )
    assert result.status == booth.ACCEPTED


def test_to_dict_reports_accepted_status():
    def call_fn(prompt):
        return _make_valid_raw()

    result = booth.check(call_fn, "q")
    d = result.to_dict()
    assert d["status"] == "ACCEPTED"
    assert d["ok"] is True


def test_repaired_still_distinct_from_accepted():
    calls = {"n": 0}

    def call_fn(prompt):
        calls["n"] += 1
        conf = 0.3 if calls["n"] == 1 else 0.95
        return _make_valid_raw(confidence=conf)

    result = booth.check(call_fn, "q", max_retries=1)
    assert result.status == booth.REPAIRED
    assert result.status != booth.ACCEPTED
    assert result.ok is True  # REPAIRED is still ok, unchanged


# ---------------------------------------------------------------------
# Bug 1: check() must reject an async call_fn
# ---------------------------------------------------------------------

def test_check_rejects_async_call_fn():
    async def async_call_fn(prompt):
        return _make_valid_raw()

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a leaked coroutine warning would fail this test
        with pytest.raises(TypeError):
            booth.check(async_call_fn, "q")


def test_check_rejects_async_callable_object():
    class AsyncClient:
        async def __call__(self, prompt):
            return _make_valid_raw()

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(TypeError):
            booth.check(AsyncClient(), "q")


def test_check_still_accepts_plain_sync_call_fn():
    def call_fn(prompt):
        return _make_valid_raw()

    result = booth.check(call_fn, "q")
    assert result.status == booth.ACCEPTED


# ---------------------------------------------------------------------
# Bug 2: non-string call_fn return becomes a failed Attempt, not a crash
# ---------------------------------------------------------------------

def test_check_none_return_becomes_uncertain():
    def returns_none(prompt):
        return None

    result = booth.check(returns_none, "q", max_retries=0)
    assert result.status == booth.UNCERTAIN
    assert result.all_parse_failed is True
    assert "call_fn returned NoneType" in result.attempts[0].error


def test_check_dict_return_becomes_uncertain():
    def returns_dict(prompt):
        return {"answer": "Paris"}

    result = booth.check(returns_dict, "q", max_retries=0)
    assert result.status == booth.UNCERTAIN
    assert result.all_parse_failed is True
    assert "call_fn returned dict" in result.attempts[0].error


def test_acheck_none_return_becomes_uncertain():
    async def returns_none(prompt):
        return None

    result = _run(booth.acheck(returns_none, "q", max_retries=0))
    assert result.status == booth.UNCERTAIN
    assert result.all_parse_failed is True


def test_check_recovers_after_bad_return_then_good_retry():
    calls = {"n": 0}

    def call_fn(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return _make_valid_raw()

    result = booth.check(call_fn, "q", max_retries=1)
    assert result.status == booth.REPAIRED
    assert result.attempts[0].parse_ok is False
    assert result.attempts[1].parse_ok is True


# ---------------------------------------------------------------------
# Bug 3: max_retries must be a real int
# ---------------------------------------------------------------------

def test_max_retries_float_rejected():
    def call_fn(prompt):
        return _make_valid_raw()

    with pytest.raises(TypeError):
        booth.check(call_fn, "q", max_retries=1.5)


def test_max_retries_bool_still_allowed():
    # Explicit decision: bool is a harmless int subtype here (True=1,
    # False=0 retries), unlike the dangerous bool-as-confidence case.
    # Not rejected.
    def call_fn(prompt):
        return _make_valid_raw()

    result = booth.check(call_fn, "q", max_retries=False)
    assert result.status == booth.ACCEPTED


def test_max_retries_negative_int_still_rejected_by_value_error():
    def call_fn(prompt):
        return _make_valid_raw()

    with pytest.raises(ValueError):
        booth.check(call_fn, "q", max_retries=-1)


# ---------------------------------------------------------------------
# Bug 4: non-string answer is rejected, not silently stringified
# ---------------------------------------------------------------------

def test_dict_answer_rejected_not_coerced():
    def call_fn(prompt):
        return (
            '{"ambiguous": false, "interpretations": [], '
            '"chosen_interpretation": null, "answer": {"foo": "bar"}, '
            '"confidence": 0.95}'
        )

    result = booth.check(call_fn, "q", max_retries=0)
    assert result.status == booth.UNCERTAIN
    assert result.all_parse_failed is True
    # Confirms the old dangerous behavior (a stringified repr reported
    # as a trustworthy ACCEPTED answer) no longer happens.
    assert result.answer is None


def test_list_answer_rejected_not_coerced():
    def call_fn(prompt):
        return (
            '{"ambiguous": false, "interpretations": [], '
            '"chosen_interpretation": null, "answer": [1, 2, 3], '
            '"confidence": 0.95}'
        )

    result = booth.check(call_fn, "q", max_retries=0)
    assert result.status == booth.UNCERTAIN


def test_string_answer_still_works_normally():
    def call_fn(prompt):
        return _make_valid_raw(answer="Paris")

    result = booth.check(call_fn, "q")
    assert result.status == booth.ACCEPTED
    assert result.answer == "Paris"


def test_interpretations_non_list_still_coerced_to_empty_unchanged():
    # Explicit decision: unlike answer, interpretations' non-list
    # coercion to [] is left as-is (informational, doesn't drive
    # status, benign default) — not touched in this batch.
    def call_fn(prompt):
        return (
            '{"ambiguous": false, "interpretations": "not-a-list", '
            '"chosen_interpretation": null, "answer": "Paris", '
            '"confidence": 0.95}'
        )

    result = booth.check(call_fn, "q")
    assert result.status == booth.ACCEPTED
    assert result.interpretations == []