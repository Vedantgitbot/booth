"""
Regression tests for the v0.4.6 bugfix batch: callable compatibility
hardening.

Two confirmed bugs, both in async-callable dispatch:
  1. acheck() rejected an object whose __call__ is itself `async def`,
     because inspect.iscoroutinefunction(obj) is False for an instance
     even when obj.__call__ is a coroutine function.
  2. An accidentally-async validator (`async def validator(...)`) was
     already correctly rejected as an invalid return type, but the
     resulting coroutine was never awaited or closed, leaking a
     RuntimeWarning to stderr on every occurrence.

Also locks in, as explicit passing/failing behavior (not just
inspection), the two related cases that were investigated and
confirmed to need NO code change:
  - functools.partial wrapping an async function already works,
    because inspect.iscoroutinefunction unwraps partial internally
    (since Python 3.8) — this is a positive regression test, not a
    fix, guarding against a future change accidentally breaking it.
  - functools.partial wrapping a SYNC function is correctly still
    rejected by acheck() — the negative case, proving the async
    detection isn't accidentally permissive for any partial.

Async tests use plain asyncio.run() rather than a pytest-asyncio
marker, since the project's dev dependencies are pytest only.
"""

import asyncio
import functools
import warnings

import pytest

import booth
from booth.core import _is_async_callable, _run_validator


def _run(coro):
    return asyncio.run(coro)


def _make_valid_raw(answer="42", confidence=0.95):
    return (
        '{"ambiguous": false, "interpretations": [], '
        f'"chosen_interpretation": null, "answer": "{answer}", '
        f'"confidence": {confidence}}}'
    )


# ---------------------------------------------------------------------
# _is_async_callable() — the new helper directly
# ---------------------------------------------------------------------

def test_is_async_callable_plain_async_function():
    async def f(prompt):
        return "hi"

    assert _is_async_callable(f) is True


def test_is_async_callable_plain_sync_function():
    def f(prompt):
        return "hi"

    assert _is_async_callable(f) is False


def test_is_async_callable_async_call_object():
    class AsyncClient:
        async def __call__(self, prompt):
            return "hi"

    assert _is_async_callable(AsyncClient()) is True


def test_is_async_callable_sync_call_object():
    class SyncClient:
        def __call__(self, prompt):
            return "hi"

    assert _is_async_callable(SyncClient()) is False


def test_is_async_callable_partial_async_function():
    async def f(prompt):
        return "hi"

    assert _is_async_callable(functools.partial(f)) is True


def test_is_async_callable_partial_sync_function():
    def f(prompt):
        return "hi"

    assert _is_async_callable(functools.partial(f)) is False


# ---------------------------------------------------------------------
# acheck() end-to-end with each callable shape
# ---------------------------------------------------------------------

def test_acheck_plain_async_function_works():
    async def call_fn(prompt):
        return _make_valid_raw()

    result = _run(booth.acheck(call_fn, "What is 6*7?"))
    assert result.status == booth.VERIFIED
    assert result.answer == "42"


def test_acheck_async_call_object_works():
    class AsyncClient:
        async def __call__(self, prompt):
            return _make_valid_raw()

    result = _run(booth.acheck(AsyncClient(), "What is 6*7?"))
    assert result.status == booth.VERIFIED
    assert result.answer == "42"


def test_acheck_partial_async_function_works():
    async def call_fn(prompt, suffix=""):
        return _make_valid_raw()

    wrapped = functools.partial(call_fn, suffix="ignored")
    result = _run(booth.acheck(wrapped, "What is 6*7?"))
    assert result.status == booth.VERIFIED


def test_acheck_sync_callable_object_rejected():
    class SyncClient:
        def __call__(self, prompt):
            return _make_valid_raw()

    with pytest.raises(TypeError):
        _run(booth.acheck(SyncClient(), "What is 6*7?"))


def test_acheck_partial_sync_function_rejected():
    def call_fn(prompt, suffix=""):
        return _make_valid_raw()

    wrapped = functools.partial(call_fn, suffix="ignored")

    with pytest.raises(TypeError):
        _run(booth.acheck(wrapped, "What is 6*7?"))


def test_acheck_plain_sync_function_still_rejected():
    # Pre-existing behavior, unaffected by the 0.4.6 change.
    def call_fn(prompt):
        return _make_valid_raw()

    with pytest.raises(TypeError):
        _run(booth.acheck(call_fn, "What is 6*7?"))


def test_check_sync_callable_object_still_works():
    # No regression on the sync path: check() never did async
    # detection at all, so a callable object always just worked.
    class SyncClient:
        def __call__(self, prompt):
            return _make_valid_raw()

    result = booth.check(SyncClient(), "What is 6*7?")
    assert result.status == booth.VERIFIED
    assert result.answer == "42"


# ---------------------------------------------------------------------
# Async validator: clean failure, no leaked RuntimeWarning
# ---------------------------------------------------------------------

def test_run_validator_async_validator_fails_cleanly():
    async def async_validator(answer):
        return True

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # promote RuntimeWarning to an exception
        passed, message = _run_validator(async_validator, "some answer")

    assert passed is False
    assert "coroutine" in message.lower()
    assert "synchronous" in message.lower()


def test_check_async_validator_produces_uncertain_no_warning():
    async def async_validator(answer):
        return True

    def call_fn(prompt):
        return _make_valid_raw()

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = booth.check(
            call_fn, "What is 6*7?", validator=async_validator, max_retries=0
        )

    assert result.status == booth.UNCERTAIN
    assert result.method == "validation"
    assert "coroutine" in result.attempts[0].validation_error.lower()


def test_acheck_async_validator_produces_uncertain_no_warning():
    async def async_validator(answer):
        return True

    async def call_fn(prompt):
        return _make_valid_raw()

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = _run(
            booth.acheck(
                call_fn, "What is 6*7?", validator=async_validator, max_retries=0
            )
        )

    assert result.status == booth.UNCERTAIN
    assert result.method == "validation"