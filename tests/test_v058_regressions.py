"""Regression tests for #30: malformed model output is a parse failure."""

import asyncio
import sys

import pytest

import booth


HAS_INT_DIGIT_LIMIT = (
    hasattr(sys, "get_int_max_str_digits") and sys.get_int_max_str_digits() > 0
)

BAD_JSON_OUTPUTS = [
    '{"answer": "x", "confidence": ' + '9' * 400 + '}',
    '{"answer": "x", "confidence": ' + '9' * 5000 + '}',
    '{"a":' * 1100 + '1' + '}' * 1100,
]
if HAS_INT_DIGIT_LIMIT:
    BAD_JSON_OUTPUTS.append('{"answer": ' + '1' * 5000 + ', "confidence": 0.9}')


def assert_parse_failure(result):
    assert result.status == booth.UNCERTAIN
    assert result.method == "parse_failure"
    assert result.call_failed is False
    assert result.n_attempts == 1
    attempt = result.attempts[0]
    assert attempt.parse_ok is False
    assert attempt.call_failed is False
    assert attempt.error


@pytest.mark.parametrize("raw", BAD_JSON_OUTPUTS)
def test_malformed_numbers_are_parse_failures_sync(raw):
    assert_parse_failure(booth.check(lambda prompt: raw, "q", max_retries=0))


@pytest.mark.parametrize("raw", BAD_JSON_OUTPUTS)
def test_malformed_numbers_are_parse_failures_async(raw):
    async def call_fn(prompt):
        return raw

    assert_parse_failure(asyncio.run(booth.acheck(call_fn, "q", max_retries=0)))


@pytest.mark.parametrize("case", ["oversized_confidence", "oversized_answer"])
def test_parse_fn_large_numbers_are_parse_failures(case):
    if case == "oversized_answer" and not HAS_INT_DIGIT_LIMIT:
        pytest.skip("Python integer-string digit limit is disabled")
    parsed = (
        {"answer": "x", "confidence": 10**400}
        if case == "oversized_confidence"
        else {"answer": 10**5000, "confidence": 0.9}
    )
    result = booth.check(
        lambda prompt: "provider-native-payload",
        "q",
        parse_fn=lambda raw: parsed,
        max_retries=0,
    )
    assert_parse_failure(result)
    assert ("answer" if case == "oversized_answer" else "confidence") in result.attempts[0].error


@pytest.mark.parametrize("raw", BAD_JSON_OUTPUTS[:3])
def test_parse_failures_keep_json_retry_prompt(raw):
    prompts = []

    def call_fn(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            return raw
        return '{"answer": "ok", "confidence": 0.9}'

    result = booth.check(call_fn, "q", max_retries=1)
    assert result.status == booth.REPAIRED
    assert result.attempts[0].parse_ok is False
    assert result.attempts[0].call_failed is False
    assert "could not be parsed" in prompts[1]


def test_valid_output_still_accepted():
    valid = '{"answer": "ok", "confidence": 0.9}'
    assert booth.check(lambda prompt: valid, "q", max_retries=0).status == booth.ACCEPTED


def test_valid_output_async_still_accepted():
    async def call_fn(prompt):
        return '{"answer": "ok", "confidence": 0.9}'

    assert asyncio.run(booth.acheck(call_fn, "q", max_retries=0)).status == booth.ACCEPTED


def test_fifty_thousand_nested_json_objects_fail_without_repeated_decoding():
    raw = '{"a":' * 50000 + '1' + '}' * 50000
    result = booth.check(lambda prompt: raw, "q", max_retries=0)
    assert_parse_failure(result)
    assert "nesting" in result.attempts[0].error


def test_braces_in_a_valid_string_do_not_count_as_nesting():
    raw = '{"answer": "' + '{' * 2000 + '", "confidence": 0.9}'
    result = booth.check(lambda prompt: raw, "q", max_retries=0)
    assert result.status == booth.ACCEPTED
