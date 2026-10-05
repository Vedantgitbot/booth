"""
Regression tests for v0.5.3.

One fix:

1. check()/acheck(): a non-callable `on_attempt` now raises TypeError
   immediately, before the retry loop runs. Previously:
     - check() only guarded against an *async* on_attempt
       (_is_async_callable() returns False for any non-callable too,
       so a non-callable silently passed), then crashed with a bare
       TypeError at the `on_attempt(i, attempt)` call site inside the
       retry loop -- after call_fn had already run and consumed a
       real attempt.
     - acheck() had no on_attempt validation at all and crashed the
       same way, from its own `on_attempt(i, attempt)` call site.
"""

import asyncio

import pytest

import booth


def _valid_call_fn(prompt: str) -> str:
    return '{"answer": "Paris", "confidence": 0.95}'


async def _valid_async_call_fn(prompt: str) -> str:
    return '{"answer": "Paris", "confidence": 0.95}'


# ---------------------------------------------------------------------
# check(): non-callable on_attempt rejected upfront, call_fn never runs
# ---------------------------------------------------------------------

@pytest.mark.parametrize("bad_on_attempt", ["not_callable", 123, [], {}, 3.14])
def test_check_rejects_non_callable_on_attempt(bad_on_attempt):
    called = {"count": 0}

    def call_fn(prompt):
        called["count"] += 1
        return _valid_call_fn(prompt)

    with pytest.raises(TypeError, match="on_attempt must be callable"):
        booth.check(call_fn, "What is the capital of France?", on_attempt=bad_on_attempt)

    # The whole point of the fix: call_fn must never run once
    # on_attempt validation fails -- no wasted LLM call before the
    # error surfaces.
    assert called["count"] == 0


def test_check_none_on_attempt_still_allowed():
    """on_attempt=None (the default) must be unaffected by the new
    check -- it's explicitly exempted, not merely "happens to pass
    callable()"."""
    result = booth.check(_valid_call_fn, "What is the capital of France?", on_attempt=None)
    assert result.ok


def test_check_valid_sync_on_attempt_still_works():
    seen = []

    def on_attempt(i, attempt):
        seen.append((i, attempt.answer))

    result = booth.check(_valid_call_fn, "What is the capital of France?", on_attempt=on_attempt)
    assert result.ok
    assert seen == [(0, "Paris")]


def test_check_async_on_attempt_still_raises_its_own_specific_error():
    """An async on_attempt is callable, so it must pass the new
    callable() check and still hit the existing, more specific
    "cannot await" error -- not get a generic "must be callable"
    message instead."""
    async def async_on_attempt(i, attempt):
        pass

    with pytest.raises(TypeError, match="cannot await an async on_attempt"):
        booth.check(_valid_call_fn, "What is the capital of France?", on_attempt=async_on_attempt)


def test_check_non_callable_on_attempt_checked_before_call_fn_runs_even_with_retries():
    """Confirms the fix point precisely: validation happens once,
    upfront, not on each retry iteration -- call_fn is never invoked
    at all, regardless of max_retries."""
    called = {"count": 0}

    def call_fn(prompt):
        called["count"] += 1
        return _valid_call_fn(prompt)

    with pytest.raises(TypeError, match="on_attempt must be callable"):
        booth.check(call_fn, "What is the capital of France?", on_attempt="nope", max_retries=3)

    assert called["count"] == 0


# ---------------------------------------------------------------------
# acheck(): same fix, mirrored -- previously had NO guard at all
# ---------------------------------------------------------------------

@pytest.mark.parametrize("bad_on_attempt", ["not_callable", 123, [], {}, 3.14])
def test_acheck_rejects_non_callable_on_attempt(bad_on_attempt):
    called = {"count": 0}

    async def call_fn(prompt):
        called["count"] += 1
        return await _valid_async_call_fn(prompt)

    async def run():
        with pytest.raises(TypeError, match="on_attempt must be callable"):
            await booth.acheck(call_fn, "What is the capital of France?", on_attempt=bad_on_attempt)

    asyncio.run(run())
    assert called["count"] == 0


def test_acheck_none_on_attempt_still_allowed():
    async def run():
        return await booth.acheck(
            _valid_async_call_fn, "What is the capital of France?", on_attempt=None
        )

    result = asyncio.run(run())
    assert result.ok


def test_acheck_valid_sync_on_attempt_still_called():
    seen = []

    def on_attempt(i, attempt):
        seen.append((i, attempt.answer))

    async def run():
        return await booth.acheck(
            _valid_async_call_fn, "What is the capital of France?", on_attempt=on_attempt
        )

    result = asyncio.run(run())
    assert result.ok
    assert seen == [(0, "Paris")]


def test_acheck_valid_async_on_attempt_still_awaited():
    seen = []

    async def on_attempt(i, attempt):
        seen.append((i, attempt.answer))

    async def run():
        return await booth.acheck(
            _valid_async_call_fn, "What is the capital of France?", on_attempt=on_attempt
        )

    result = asyncio.run(run())
    assert result.ok
    assert seen == [(0, "Paris")]


def test_acheck_non_callable_on_attempt_checked_before_call_fn_runs_even_with_retries():
    called = {"count": 0}

    async def call_fn(prompt):
        called["count"] += 1
        return await _valid_async_call_fn(prompt)

    async def run():
        with pytest.raises(TypeError, match="on_attempt must be callable"):
            await booth.acheck(
                call_fn, "What is the capital of France?", on_attempt="nope", max_retries=3
            )

    asyncio.run(run())
    assert called["count"] == 0


# ---------------------------------------------------------------------
# Audit confirmation: validator / compare_fn were checked for the same
# bug class and found already safe -- these tests pin that behavior so
# a future change can't silently regress it.
# ---------------------------------------------------------------------

def test_non_callable_validator_degrades_gracefully_not_crash():
    """validator is NOT fixed in this release -- it was already safe.
    _run_validator() wraps the call in try/except, so a non-callable
    validator produces a clear rejection (UNCERTAIN, with the TypeError
    captured in attempt.validation_error) instead of crashing. This
    test documents and pins that existing, correct behavior."""
    result = booth.check(
        _valid_call_fn, "What is the capital of France?", validator="not_callable"
    )
    assert result.status == booth.UNCERTAIN
    assert result.attempts[-1].passed_validation is False
    assert "not callable" in result.attempts[-1].validation_error


def test_non_callable_compare_fn_degrades_gracefully_not_crash():
    """compare_fn is NOT fixed in this release -- it was already safe.
    check_with_evidence()'s compare_fn call is wrapped in try/except,
    so a non-callable compare_fn produces COMPARE_FAILED instead of
    crashing. Pins the existing, correct behavior."""
    result = booth.check_with_evidence(
        answer="some answer", evidence=["some evidence"], compare_fn="not_callable"
    )
    assert result.status == booth.UNCERTAIN
    assert result.reason == booth.COMPARE_FAILED
    assert result.checker_failed is True