"""Tests for the parse_fn structured-output escape hatch."""

import asyncio

import pytest

import booth


def test_parse_fn_bypasses_default_string_extraction():
    seen = []

    def parse_fn(raw):
        seen.append(raw)
        return {"answer": "Paris", "confidence": "0.9", "source": "provider"}

    result = booth.check(
        lambda prompt: "provider-native-payload",
        "q",
        parse_fn=parse_fn,
    )

    assert result.status == booth.ACCEPTED
    assert result.confidence == 0.9
    assert result.parsed["confidence"] == "0.9"
    assert seen == ["provider-native-payload"]


def test_non_callable_parse_fn_is_rejected_before_call_fn():
    calls = []

    with pytest.raises(TypeError, match="parse_fn must be callable"):
        booth.check(
            lambda prompt: calls.append(prompt),
            "q",
            parse_fn="not-callable",
        )

    assert calls == []


@pytest.mark.parametrize("parsed", [None, ["not a dict"], "not a dict"])
def test_parse_fn_none_and_non_dict_results_are_parse_failures(parsed):
    result = booth.check(
        lambda prompt: "provider-native-payload",
        "q",
        parse_fn=lambda raw: parsed,
        max_retries=0,
    )

    assert result.status == booth.UNCERTAIN
    assert result.method == "parse_failure"
    assert result.call_failed is False
    assert result.attempts[0].call_failed is False
    assert result.attempts[0].parse_ok is False


def test_parse_fn_result_that_fails_validation_is_parse_failure():
    result = booth.check(
        lambda prompt: "provider-native-payload",
        "q",
        parse_fn=lambda raw: {"answer": "Paris", "confidence": 1.1},
        max_retries=0,
    )

    assert result.status == booth.UNCERTAIN
    assert result.method == "parse_failure"
    assert result.call_failed is False
    assert "out of the [0.0, 1.0] range" in result.attempts[0].error


def test_parse_fn_ambiguous_result_is_ambiguous():
    result = booth.check(
        lambda prompt: "provider-native-payload",
        "q",
        parse_fn=lambda raw: {
            "ambiguous": True,
            "interpretations": ["a", "b"],
            "chosen_interpretation": "a",
            "answer": "x",
            "confidence": 0.9,
        },
    )

    assert result.status == booth.AMBIGUOUS
    assert result.ambiguous is True
    assert result.call_failed is False


def test_parse_fn_is_used_by_acheck():
    async def call_fn(prompt):
        return "provider-native-payload"

    result = asyncio.run(
        booth.acheck(
            call_fn,
            "q",
            parse_fn=lambda raw: {"answer": "Paris", "confidence": 0.9},
        )
    )

    assert result.status == booth.ACCEPTED
    assert result.answer == "Paris"


def test_parse_fn_none_keeps_default_behavior():
    result = booth.check(
        lambda prompt: '{"answer": "Paris", "confidence": 0.9}',
        "q",
        parse_fn=None,
    )

    assert result.status == booth.ACCEPTED
    assert result.answer == "Paris"


def test_parse_fn_failure_keeps_json_style_retry_prompt():
    seen_prompts = []
    parse_calls = {"n": 0}

    def call_fn(prompt):
        seen_prompts.append(prompt)
        return "provider-native-payload"

    def parse_fn(raw):
        parse_calls["n"] += 1
        if parse_calls["n"] == 1:
            return None
        return {"answer": "Paris", "confidence": 0.9}

    result = booth.check(call_fn, "q", parse_fn=parse_fn, max_retries=1)

    assert result.status == booth.REPAIRED
    assert "could not be parsed" in seen_prompts[1]
    assert seen_prompts[1] != seen_prompts[0]


def test_async_parse_fn_is_rejected():
    async def parse_fn(raw):
        return {"answer": "Paris", "confidence": 0.9}

    with pytest.raises(TypeError, match="parse_fn must be synchronous"):
        booth.check(lambda prompt: "payload", "q", parse_fn=parse_fn)


def test_parse_fn_is_publicly_exported():
    assert booth.ParseFn is not None
