"""
Regression tests for v0.5.0: BoothResult.unwrap(), .unwrap_or(), and
the new BoothRejected exception.

Locked design decisions this batch tests directly:
  - unwrap() uses exactly the same predicate as .ok (status in
    (ACCEPTED, REPAIRED)) -- the two can never disagree, because
    unwrap() literally calls .ok internally rather than reimplementing
    the check.
  - .answer is UNCHANGED on rejected results (AMBIGUOUS/UNCERTAIN/
    BLOCKED) -- it stays populated exactly as in every prior version,
    for debugging/logging visibility. unwrap() is purely additive on
    top, not a replacement for .answer.
  - BoothRejected carries the full BoothResult as `.result`, and its
    own string message does NOT include the raw rejected answer text,
    since exception messages tend to end up in logs.
"""
import asyncio
import json

import pytest

import booth
from booth.core import BoothRejected, BoothResult, Attempt


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------
# unwrap() on the "ok" statuses
# ---------------------------------------------------------------------

def test_unwrap_returns_answer_on_accepted():
    def call_fn(p):
        return json.dumps({"answer": "Paris", "confidence": 0.95})

    r = booth.check(call_fn, "q")
    assert r.status == booth.ACCEPTED
    assert r.unwrap() == "Paris"
    assert isinstance(r.unwrap(), str)


def test_unwrap_returns_answer_on_repaired():
    calls = {"n": 0}
    def call_fn(p):
        calls["n"] += 1
        conf = 0.3 if calls["n"] == 1 else 0.95
        return json.dumps({"answer": "Paris", "confidence": conf})

    r = booth.check(call_fn, "q", max_retries=1)
    assert r.status == booth.REPAIRED
    assert r.unwrap() == "Paris"


def test_unwrap_works_on_acheck_result():
    async def call_fn(p):
        return json.dumps({"answer": "Paris", "confidence": 0.9})

    r = _run(booth.acheck(call_fn, "q"))
    assert r.status == booth.ACCEPTED
    assert r.unwrap() == "Paris"


def test_unwrap_works_on_check_with_evidence_accepted():
    r = booth.check_with_evidence("Paris", ["Paris is the capital."], lambda a, e: True)
    assert r.status == booth.ACCEPTED
    assert r.unwrap() == "Paris"


# ---------------------------------------------------------------------
# unwrap() on the "not ok" statuses -- must raise BoothRejected
# ---------------------------------------------------------------------

def test_unwrap_raises_on_uncertain():
    def call_fn(p):
        return "not json at all"

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.status == booth.UNCERTAIN
    with pytest.raises(BoothRejected):
        r.unwrap()


def test_unwrap_raises_on_ambiguous():
    def call_fn(p):
        return json.dumps({
            "ambiguous": True,
            "interpretations": ["a", "b"],
            "chosen_interpretation": "a",
            "answer": "x",
            "confidence": 0.9,
        })

    r = booth.check(call_fn, "q")
    assert r.status == booth.AMBIGUOUS
    with pytest.raises(BoothRejected):
        r.unwrap()


def test_unwrap_raises_on_blocked():
    r = booth.check_with_evidence("Berlin", ["Paris is the capital."], lambda a, e: False)
    assert r.status == booth.BLOCKED
    with pytest.raises(BoothRejected):
        r.unwrap()


def test_unwrap_raises_on_uncertain_from_acheck():
    async def call_fn(p):
        return "not json"

    r = _run(booth.acheck(call_fn, "q", max_retries=0))
    assert r.status == booth.UNCERTAIN
    with pytest.raises(BoothRejected):
        r.unwrap()


# ---------------------------------------------------------------------
# unwrap() predicate must exactly match .ok, for every status
# ---------------------------------------------------------------------

def test_unwrap_predicate_matches_ok_for_every_reachable_status():
    scenarios = []

    def accepted_fn(p):
        return json.dumps({"answer": "x", "confidence": 0.9})
    scenarios.append(booth.check(accepted_fn, "q"))

    calls = {"n": 0}
    def repaired_fn(p):
        calls["n"] += 1
        conf = 0.3 if calls["n"] == 1 else 0.9
        return json.dumps({"answer": "x", "confidence": conf})
    scenarios.append(booth.check(repaired_fn, "q", max_retries=1))

    def ambiguous_fn(p):
        return json.dumps({
            "ambiguous": True, "interpretations": ["a", "b"],
            "chosen_interpretation": "a", "answer": "x", "confidence": 0.9,
        })
    scenarios.append(booth.check(ambiguous_fn, "q"))

    def uncertain_fn(p):
        return "garbage"
    scenarios.append(booth.check(uncertain_fn, "q", max_retries=0))

    scenarios.append(booth.check_with_evidence("Berlin", ["Paris is the capital."], lambda a, e: False))

    for r in scenarios:
        if r.ok:
            assert r.unwrap() == r.answer, f"status={r.status} is ok but unwrap() disagreed with .answer"
        else:
            with pytest.raises(BoothRejected):
                r.unwrap()


# ---------------------------------------------------------------------
# .answer stays populated on rejected results -- unchanged, on purpose
# ---------------------------------------------------------------------

def test_answer_field_still_populated_on_uncertain_unaffected_by_unwrap():
    def call_fn(p):
        return json.dumps({"answer": "maybe Lyon?", "confidence": 0.3})

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.status == booth.UNCERTAIN
    assert r.answer == "maybe Lyon?", ".answer must remain populated on UNCERTAIN, unchanged from prior versions"
    with pytest.raises(BoothRejected):
        r.unwrap()


def test_answer_field_still_populated_on_blocked_unaffected_by_unwrap():
    r = booth.check_with_evidence("90 days", ["Refund window is 45 days."], lambda a, e: False)
    assert r.status == booth.BLOCKED
    assert r.answer == "90 days", ".answer must remain populated on BLOCKED, unchanged from prior versions"
    with pytest.raises(BoothRejected):
        r.unwrap()


# ---------------------------------------------------------------------
# BoothRejected: carries full result, message excludes raw answer text
# ---------------------------------------------------------------------

def test_boothrejected_carries_full_result():
    def call_fn(p):
        return "garbage"

    r = booth.check(call_fn, "q", max_retries=0)
    try:
        r.unwrap()
        assert False, "expected BoothRejected"
    except BoothRejected as e:
        assert e.result is r
        assert e.result.status == booth.UNCERTAIN
        assert e.result.method == "parse_failure"


def test_boothrejected_message_excludes_raw_answer_text():
    """Exception messages tend to end up in logs -- the rejected
    answer text must not leak into str(exception) by default, even
    though it's still reachable via e.result.answer."""
    secret_looking_answer = "SENSITIVE_TOKEN_abc123xyz"

    def call_fn(p):
        return json.dumps({"answer": secret_looking_answer, "confidence": 0.2})

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.status == booth.UNCERTAIN
    try:
        r.unwrap()
        assert False, "expected BoothRejected"
    except BoothRejected as e:
        assert secret_looking_answer not in str(e)
        assert e.result.answer == secret_looking_answer  # still reachable explicitly


def test_boothrejected_message_mentions_status_and_method():
    def call_fn(p):
        return "garbage"

    r = booth.check(call_fn, "q", max_retries=0)
    try:
        r.unwrap()
        assert False, "expected BoothRejected"
    except BoothRejected as e:
        assert "UNCERTAIN" in str(e)
        assert "parse_failure" in str(e)


# ---------------------------------------------------------------------
# unwrap_or()
# ---------------------------------------------------------------------

def test_unwrap_or_returns_answer_when_ok():
    def call_fn(p):
        return json.dumps({"answer": "Paris", "confidence": 0.9})

    r = booth.check(call_fn, "q")
    assert r.unwrap_or("fallback") == "Paris"


def test_unwrap_or_returns_default_when_rejected():
    def call_fn(p):
        return "garbage"

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.unwrap_or("fallback") == "fallback"


def test_unwrap_or_returns_default_on_blocked():
    r = booth.check_with_evidence("Berlin", ["Paris is the capital."], lambda a, e: False)
    assert r.unwrap_or("no answer available") == "no answer available"


def test_unwrap_or_never_raises():
    def call_fn(p):
        return json.dumps({
            "ambiguous": True, "interpretations": ["a", "b"],
            "chosen_interpretation": "a", "answer": "x", "confidence": 0.9,
        })

    r = booth.check(call_fn, "q")
    # Should not raise, regardless of status.
    result = r.unwrap_or("fallback")
    assert result == "fallback"


# ---------------------------------------------------------------------
# Sanity: hand-built BoothResult (defensive, matches existing
# test_method_undefined_construction_documented_not_crashing style)
# ---------------------------------------------------------------------

def test_unwrap_on_hand_built_ok_result():
    r = BoothResult(answer="x", status=booth.ACCEPTED)
    assert r.unwrap() == "x"


def test_unwrap_on_hand_built_result_with_none_answer_raises_not_crashes():
    """Defensive case: a hand-built BoothResult claiming an ok status
    but with answer=None (not reachable through the public API) must
    still raise BoothRejected rather than returning None from a
    function typed to return str."""
    r = BoothResult(answer=None, status=booth.ACCEPTED)
    with pytest.raises(BoothRejected):
        r.unwrap()