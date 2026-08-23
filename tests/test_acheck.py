"""
Smoke test for booth.acheck() using a mock async call_fn — validates
that the async path matches check()'s retry/status/error-handling
logic exactly (both are driven by the same internal _evaluate() step),
plus the acheck-specific concerns: rejecting a sync call_fn, not
propagating exceptions raised by an awaited call_fn, and correctness
under concurrent calls. Run: python3 tests/test_acheck.py
"""

import asyncio
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import booth as bth


def make_async_mock(sequence):
    """sequence: list of (answer, confidence) tuples, one per call."""
    calls = {"n": 0}

    async def call_fn(prompt):
        i = calls["n"]
        calls["n"] += 1
        answer, confidence = sequence[min(i, len(sequence) - 1)]
        return json.dumps({"answer": answer, "confidence": confidence})

    return call_fn


def run(coro):
    return asyncio.run(coro)


def test_acheck_verified_first_try():
    call_fn = make_async_mock([("Paris", 0.95)])

    async def go():
        return await bth.acheck(call_fn, "Capital of France?", threshold=0.7, max_retries=1)

    r = run(go())
    assert r.status == bth.VERIFIED, r.status
    assert r.answer == "Paris"
    assert r.n_attempts == 1
    assert r.ok is True
    print("PASS: acheck verified on first try")


def test_acheck_repaired_on_retry():
    call_fn = make_async_mock([("maybe Lyon?", 0.4), ("Paris", 0.9)])

    async def go():
        return await bth.acheck(call_fn, "Capital of France?", threshold=0.7, max_retries=1)

    r = run(go())
    assert r.status == bth.REPAIRED, r.status
    assert r.answer == "Paris"
    assert r.n_attempts == 2
    assert r.ok is True
    print("PASS: acheck repaired after retry")


def test_acheck_retry_prompt_shows_previous_answer():
    seen_prompts = []

    async def call_fn(prompt):
        seen_prompts.append(prompt)
        i = len(seen_prompts)
        if i == 1:
            return json.dumps({"answer": "Lyon", "confidence": 0.3})
        return json.dumps({"answer": "Paris", "confidence": 0.9})

    async def go():
        return await bth.acheck(call_fn, "Capital of France?", threshold=0.7, max_retries=1)

    r = run(go())
    assert len(seen_prompts) == 2
    assert seen_prompts[0] != seen_prompts[1]
    assert "Lyon" in seen_prompts[1], "retry prompt should reference the previous answer"
    assert "0.3" in seen_prompts[1], "retry prompt should reference the previous confidence"
    assert r.status == bth.REPAIRED
    print("PASS: acheck retry prompt references previous answer, using the real _build_retry_prompt signature")


def test_acheck_uncertain_after_exhausting_retries():
    call_fn = make_async_mock([("maybe Lyon?", 0.4), ("possibly Marseille?", 0.5)])

    async def go():
        return await bth.acheck(call_fn, "Capital of France?", threshold=0.7, max_retries=1)

    r = run(go())
    assert r.status == bth.UNCERTAIN, r.status
    assert r.n_attempts == 2
    assert r.answer == "possibly Marseille?"
    assert r.ok is False
    print("PASS: acheck uncertain after exhausting retries")


def test_acheck_malformed_response_does_not_crash():
    async def call_fn(prompt):
        return "I think it's Paris but I won't give you JSON."

    async def go():
        return await bth.acheck(call_fn, "Capital of France?", threshold=0.7, max_retries=1)

    r = run(go())
    assert r.status == bth.UNCERTAIN, r.status
    assert r.answer is None, "answer must be None on total parse failure, not raw model text"
    print("PASS: acheck malformed response -> uncertain, answer=None, no crash")


def test_acheck_rejects_sync_call_fn():
    def sync_call_fn(prompt):
        return json.dumps({"answer": "Paris", "confidence": 0.9})

    async def go():
        return await bth.acheck(sync_call_fn, "Capital of France?")

    try:
        run(go())
        assert False, "expected TypeError"
    except TypeError:
        print("PASS: acheck rejects a synchronous call_fn with TypeError instead of silently misbehaving")


def test_acheck_call_fn_exception_does_not_crash():
    """The core reason acheck exists: under concurrent load, call_fn
    (a real provider client) is far more likely to raise (rate limits,
    timeouts). This must degrade to a failed Attempt, never propagate."""
    calls = {"n": 0}

    async def flaky_call_fn(prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("simulated network blip")
        return json.dumps({"answer": "Paris", "confidence": 0.9})

    async def go():
        return await bth.acheck(flaky_call_fn, "Capital of France?", threshold=0.7, max_retries=1)

    r = run(go())
    assert r.status == bth.REPAIRED, r.status
    assert r.answer == "Paris"
    assert r.attempts[0].error is not None
    print("PASS: acheck call_fn exception on attempt 1 handled, recovers on retry")


def test_acheck_call_fn_exception_every_attempt_returns_uncertain_not_crash():
    async def always_fails(prompt):
        raise TimeoutError("simulated timeout")

    async def go():
        return await bth.acheck(always_fails, "Capital of France?", threshold=0.7, max_retries=1)

    r = run(go())
    assert r.status == bth.UNCERTAIN, r.status
    assert r.answer is None
    assert all(a.error is not None for a in r.attempts)
    print("PASS: acheck call_fn fails every attempt -> UNCERTAIN, no crash")


def test_acheck_ambiguous_short_circuits():
    async def call_fn(prompt):
        return json.dumps({
            "ambiguous": True,
            "interpretations": ["Georgia (US state) -> Atlanta", "Georgia (country) -> Tbilisi"],
            "chosen_interpretation": "Georgia (country) -> Tbilisi",
            "answer": "Tbilisi",
            "confidence": 0.93,
        })

    async def go():
        return await bth.acheck(call_fn, "What is the capital of Georgia?", threshold=0.7, max_retries=1)

    r = run(go())
    assert r.status == bth.AMBIGUOUS, r.status
    assert r.ok is False
    assert r.n_attempts == 1, "ambiguity should short-circuit, not retry"
    print("PASS: acheck ambiguous question -> AMBIGUOUS, not VERIFIED, no retry")


def test_acheck_on_attempt_sync_callback():
    log = []
    call_fn = make_async_mock([("Lyon", 0.3), ("Paris", 0.9)])

    def on_attempt(i, a):
        log.append((i, a.confidence))

    async def go():
        return await bth.acheck(
            call_fn, "Capital of France?", threshold=0.7, max_retries=1,
            on_attempt=on_attempt,
        )

    r = run(go())
    assert log == [(0, 0.3), (1, 0.9)], log
    print("PASS: acheck accepts a synchronous on_attempt callback without awaiting it")


def test_acheck_on_attempt_async_callback():
    log = []
    call_fn = make_async_mock([("Paris", 0.95)])

    async def on_attempt(i, a):
        await asyncio.sleep(0)  # prove it's actually awaited, not just called
        log.append((i, a.confidence))

    async def go():
        return await bth.acheck(call_fn, "Capital of France?", on_attempt=on_attempt)

    r = run(go())
    assert log == [(0, 0.95)], log
    print("PASS: acheck awaits an async on_attempt callback")


def test_check_rejects_async_on_attempt():
    """Symmetric guard on the sync side: check() must not silently
    no-op an async on_attempt (which is what a bare `on_attempt(i, a)`
    call on a coroutine function would otherwise do)."""
    call_fn = lambda p: json.dumps({"answer": "Paris", "confidence": 0.9})

    async def on_attempt(i, a):
        pass

    try:
        bth.check(call_fn, "Capital of France?", on_attempt=on_attempt)
        assert False, "expected TypeError"
    except TypeError:
        print("PASS: check() rejects an async on_attempt with TypeError instead of silently doing nothing")


def test_check_and_acheck_agree_on_same_inputs():
    """Both entry points are driven by the same _evaluate() step, so
    given equivalent responses they must reach the same status."""
    sync_call_fn = lambda seq: (lambda p, c={"n": 0}: (
        c.__setitem__("n", c["n"] + 1),
        json.dumps({"answer": seq[min(c["n"] - 1, len(seq) - 1)][0],
                    "confidence": seq[min(c["n"] - 1, len(seq) - 1)][1]}),
    )[1])

    seq = [("maybe Lyon?", 0.4), ("Paris", 0.9)]
    r_sync = bth.check(sync_call_fn(seq), "Capital of France?", threshold=0.7, max_retries=1)

    async_call_fn = make_async_mock(seq)

    async def go():
        return await bth.acheck(async_call_fn, "Capital of France?", threshold=0.7, max_retries=1)

    r_async = run(go())

    assert r_sync.status == r_async.status == bth.REPAIRED
    assert r_sync.answer == r_async.answer == "Paris"
    print("PASS: check() and acheck() agree on status/answer for equivalent inputs (shared _evaluate)")


def test_acheck_concurrent_calls_are_independent():
    """Regression test for the original concurrency question: results
    for N simultaneous acheck() calls must not cross-contaminate, since
    check()/acheck() hold no shared/module-level mutable state."""
    N = 25

    def make_call_fn(tag):
        async def call_fn(prompt):
            await asyncio.sleep(0.01)
            return json.dumps({"answer": f"answer_{tag}", "confidence": 0.9})
        return call_fn

    async def go():
        return await asyncio.gather(*[
            bth.acheck(make_call_fn(i), f"question {i}") for i in range(N)
        ])

    results = run(go())
    for i, r in enumerate(results):
        assert r.answer == f"answer_{i}", f"cross-contamination at index {i}: got {r.answer}"
    print(f"PASS: {N} concurrent acheck() calls returned independent, uncontaminated results")


if __name__ == "__main__":
    test_acheck_verified_first_try()
    test_acheck_repaired_on_retry()
    test_acheck_retry_prompt_shows_previous_answer()
    test_acheck_uncertain_after_exhausting_retries()
    test_acheck_malformed_response_does_not_crash()
    test_acheck_rejects_sync_call_fn()
    test_acheck_call_fn_exception_does_not_crash()
    test_acheck_call_fn_exception_every_attempt_returns_uncertain_not_crash()
    test_acheck_ambiguous_short_circuits()
    test_acheck_on_attempt_sync_callback()
    test_acheck_on_attempt_async_callback()
    test_check_rejects_async_on_attempt()
    test_check_and_acheck_agree_on_same_inputs()
    test_acheck_concurrent_calls_are_independent()
    print("\nAll acheck smoke tests passed.")