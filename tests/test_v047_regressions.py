"""
Regression tests for the v0.4.7 bugfix batch.

Two confirmed bugs, both about making on_attempt's async-callable
detection consistent with call_fn's (fixed for call_fn in v0.4.6, but
call_fn and on_attempt had separate, independent checks — the
on_attempt ones were never updated):

  1. check(): a bare inspect.iscoroutinefunction(on_attempt) missed an
     object whose __call__ is itself async def (fn itself is a normal
     instance, not a coroutine function) — such an on_attempt was
     silently treated as sync instead of raising TypeError, and would
     produce a coroutine object that check()'s sync call site never
     awaits, leaking it and never running the callback's logic at all.
  2. acheck(): the same bare check decided whether to await on_attempt.
     An async-__call__ object failed the check, so acheck() called it
     WITHOUT awaiting — silently leaking the coroutine, same as above,
     but in acheck() this produces no error at all, just a callback
     that never actually runs.

Plus one new feature: BoothResult.to_dict(), which must include both
the stored dataclass fields AND the computed @property fields (ok,
method, n_attempts, all_parse_failed) — dataclasses.asdict() alone
silently omits every property, which would otherwise make method and
ok simply vanish from a logged to_dict() with no error.

Async tests use plain asyncio.run() (no pytest-asyncio dependency).
"""

import asyncio
import json
import warnings

import pytest

import booth
from booth.core import _is_async_callable


def _run(coro):
    return asyncio.run(coro)


def _make_valid_raw(answer="42", confidence=0.95):
    return (
        '{"ambiguous": false, "interpretations": [], '
        f'"chosen_interpretation": null, "answer": "{answer}", '
        f'"confidence": {confidence}}}'
    )


def _sync_call_fn(prompt):
    return _make_valid_raw()


async def _async_call_fn(prompt):
    return _make_valid_raw()


# ---------------------------------------------------------------------
# check() — on_attempt must be synchronous; an async on_attempt of
# either shape (plain function or async-__call__ object) must raise.
# ---------------------------------------------------------------------

def test_check_sync_function_on_attempt_works():
    calls = []

    def on_attempt(i, attempt):
        calls.append((i, attempt.answer))

    result = booth.check(_sync_call_fn, "q", on_attempt=on_attempt)
    assert result.status == booth.ACCEPTED
    assert calls == [(0, "42")]


def test_check_sync_callable_object_on_attempt_works():
    calls = []

    class SyncLogger:
        def __call__(self, i, attempt):
            calls.append((i, attempt.answer))

    result = booth.check(_sync_call_fn, "q", on_attempt=SyncLogger())
    assert result.status == booth.ACCEPTED
    assert calls == [(0, "42")]


def test_check_async_function_on_attempt_raises():
    async def on_attempt(i, attempt):
        pass

    with pytest.raises(TypeError):
        booth.check(_sync_call_fn, "q", on_attempt=on_attempt)


def test_check_async_callable_object_on_attempt_raises():
    # This is the actual v0.4.7 fix for check(): previously this
    # object passed the bare iscoroutinefunction() check (since the
    # instance itself isn't a coroutine function) and was silently
    # treated as sync instead of raising.
    class AsyncLogger:
        async def __call__(self, i, attempt):
            pass

    with pytest.raises(TypeError):
        booth.check(_sync_call_fn, "q", on_attempt=AsyncLogger())


# ---------------------------------------------------------------------
# acheck() — on_attempt may be sync OR async; an async on_attempt of
# either shape must actually be awaited (proven by observing a side
# effect only the coroutine's body can produce), not silently skipped.
# ---------------------------------------------------------------------

def test_acheck_sync_function_on_attempt_called():
    calls = []

    def on_attempt(i, attempt):
        calls.append((i, attempt.answer))

    result = _run(booth.acheck(_async_call_fn, "q", on_attempt=on_attempt))
    assert result.status == booth.ACCEPTED
    assert calls == [(0, "42")]


def test_acheck_sync_callable_object_on_attempt_called():
    calls = []

    class SyncLogger:
        def __call__(self, i, attempt):
            calls.append((i, attempt.answer))

    result = _run(booth.acheck(_async_call_fn, "q", on_attempt=SyncLogger()))
    assert result.status == booth.ACCEPTED
    assert calls == [(0, "42")]


def test_acheck_async_function_on_attempt_awaited():
    calls = []

    async def on_attempt(i, attempt):
        calls.append((i, attempt.answer))

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # promote leaked-coroutine warning to a failure
        result = _run(booth.acheck(_async_call_fn, "q", on_attempt=on_attempt))

    assert result.status == booth.ACCEPTED
    assert calls == [(0, "42")]


def test_acheck_async_callable_object_on_attempt_awaited():
    # This is the actual v0.4.7 fix for acheck(): previously this
    # object failed the bare iscoroutinefunction() check, so acheck()
    # called it WITHOUT awaiting — the append below would never have
    # executed at all, and a RuntimeWarning would have leaked.
    calls = []

    class AsyncLogger:
        async def __call__(self, i, attempt):
            calls.append((i, attempt.answer))

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = _run(booth.acheck(_async_call_fn, "q", on_attempt=AsyncLogger()))

    assert result.status == booth.ACCEPTED
    assert calls == [(0, "42")], "on_attempt's coroutine body never ran — it was leaked, not awaited"


# ---------------------------------------------------------------------
# _is_async_callable() reused correctly — sanity check that on_attempt
# and call_fn now share one implementation, not two that could drift.
# ---------------------------------------------------------------------

def test_is_async_callable_matrix():
    def sync_fn(*a):
        pass

    async def async_fn(*a):
        pass

    class SyncObj:
        def __call__(self, *a):
            pass

    class AsyncObj:
        async def __call__(self, *a):
            pass

    assert _is_async_callable(sync_fn) is False
    assert _is_async_callable(async_fn) is True
    assert _is_async_callable(SyncObj()) is False
    assert _is_async_callable(AsyncObj()) is True


# ---------------------------------------------------------------------
# BoothResult.to_dict()
# ---------------------------------------------------------------------

def test_to_dict_includes_computed_properties():
    result = booth.check(_sync_call_fn, "q")
    d = result.to_dict()

    # Stored fields
    for key in ("answer", "status", "confidence", "attempts", "ambiguous",
                "interpretations", "evidence_agreement", "parsed"):
        assert key in d, f"missing stored field: {key}"

    # Computed properties — the actual point of to_dict() existing,
    # since dataclasses.asdict() alone silently drops all of these.
    for key in ("ok", "method", "n_attempts", "all_parse_failed"):
        assert key in d, f"missing computed property: {key}"

    assert d["ok"] is True
    assert d["method"] == "confidence"
    assert d["n_attempts"] == 1
    assert d["all_parse_failed"] is False


def test_to_dict_attempts_are_plain_dicts_not_attempt_objects():
    result = booth.check(_sync_call_fn, "q")
    d = result.to_dict()
    assert isinstance(d["attempts"], list)
    assert len(d["attempts"]) == 1
    assert isinstance(d["attempts"][0], dict)
    assert d["attempts"][0]["answer"] == "42"
    assert d["attempts"][0]["parse_ok"] is True


def test_to_dict_is_json_serializable():
    result = booth.check(_sync_call_fn, "q")
    d = result.to_dict()
    # Should not raise.
    serialized = json.dumps(d)
    reloaded = json.loads(serialized)
    assert reloaded["status"] == booth.ACCEPTED
    assert reloaded["method"] == "confidence"


def test_to_dict_on_evidence_result_has_no_attempts():
    result = booth.check_with_evidence(
        answer="Paris",
        evidence=["Paris is the capital of France."],
        compare_fn=lambda a, e: True,
    )
    d = result.to_dict()
    assert d["attempts"] == []
    assert d["method"] == "evidence"
    assert d["ok"] is True
    assert d["evidence_agreement"] == 1.0


def test_to_dict_on_uncertain_result():
    def always_fails(prompt):
        return "not valid json"

    result = booth.check(always_fails, "q", max_retries=0)
    d = result.to_dict()
    assert d["status"] == booth.UNCERTAIN
    assert d["ok"] is False
    assert d["method"] == "parse_failure"
    assert d["all_parse_failed"] is True
    assert d["n_attempts"] == 1