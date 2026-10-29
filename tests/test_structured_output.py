"""Tests for structured call_fn returns and the parse_fn escape hatch."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import booth as bth


def test_check_accepts_preparsed_dict_without_string_scraping():
    def call_fn(prompt):
        return {"answer": "Paris", "confidence": 0.9, "source": "provider"}

    result = bth.check(call_fn, "q")

    assert result.status == bth.ACCEPTED
    assert result.answer == "Paris"
    assert result.parsed == {"answer": "Paris", "confidence": 0.9, "source": "provider"}
    assert result.call_failed is False
    assert result.attempts[0].call_failed is False


def test_parse_fn_bypasses_default_string_extraction():
    seen = []

    def parse_fn(raw):
        seen.append(raw)
        return {"answer": "Paris", "confidence": "0.9", "source": "provider"}

    result = bth.check(lambda prompt: "provider-native-payload", "q", parse_fn=parse_fn)

    assert result.status == bth.ACCEPTED
    assert result.confidence == 0.9
    assert result.parsed["confidence"] == "0.9"
    assert seen == ["provider-native-payload"]


def test_invalid_parse_fn_result_is_parse_failure_not_call_failure():
    result = bth.check(
        lambda prompt: "provider-native-payload",
        "q",
        parse_fn=lambda raw: {"answer": "missing confidence"},
        max_retries=0,
    )

    assert result.status == bth.UNCERTAIN
    assert result.method == "parse_failure"
    assert result.call_failed is False
    assert result.attempts[0].call_failed is False
    assert "confidence" in result.attempts[0].error


def test_parse_fn_exception_is_parse_failure_and_can_retry():
    calls = {"n": 0}

    def parse_fn(raw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("provider payload was incomplete")
        return {"answer": "Paris", "confidence": 0.9}

    result = bth.check(
        lambda prompt: "provider-native-payload",
        "q",
        parse_fn=parse_fn,
        max_retries=1,
    )

    assert result.status == bth.REPAIRED
    assert result.n_attempts == 2
    assert result.attempts[0].call_failed is False


def test_acheck_accepts_preparsed_dict_with_same_pipeline():
    async def call_fn(prompt):
        return {"answer": "Paris", "confidence": 0.9}

    result = asyncio.run(bth.acheck(call_fn, "q"))

    assert result.status == bth.ACCEPTED
    assert result.answer == "Paris"
    assert result.parsed == {"answer": "Paris", "confidence": 0.9}


def test_parse_fn_must_be_synchronous():
    async def parse_fn(raw):
        return {"answer": "Paris", "confidence": 0.9}

    try:
        bth.check(lambda prompt: "payload", "q", parse_fn=parse_fn)
    except TypeError as exc:
        assert "parse_fn must be synchronous" in str(exc)
    else:
        raise AssertionError("async parse_fn should be rejected")


def test_parse_fn_is_publicly_exported():
    assert bth.ParseFn is not None
