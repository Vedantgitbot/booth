"""Regression tests for parser candidate order and top-level objects."""

import asyncio
import json

import pytest

import booth
from booth.core import _iter_top_level_objects, _parse_response


EARLY = '{"answer": "early", "confidence": 0.9}'
FINAL = '{"answer": "final", "confidence": 0.9}'


def check(raw):
    return booth.check(lambda prompt: raw, "review", max_retries=0)


@pytest.mark.parametrize("raw", [
    FINAL,
    "Reasoning first.\n" + FINAL,
    "Reasoning first.\n{\n  \"answer\": \"final\",\n  \"confidence\": 0.9\n}\nDone.",
    FINAL + "\nDone.",
    EARLY + "\n" + FINAL,
])
def test_existing_single_and_final_line_behavior_remains(raw):
    result = check(raw)
    assert result.status == booth.ACCEPTED
    assert result.answer == "final"


@pytest.mark.parametrize("tail", [
    '{"debug": "done"}',
    '{"answer": "final"}',
    '{"answer": "final", "confidence": 2}',
    '{"answer": "final", "confidence": 0.9',
])
def test_invalid_or_unrelated_later_object_keeps_existing_fallback(tail):
    result = check(EARLY + "\n" + tail + "\nDone.")
    assert result.status == booth.ACCEPTED
    assert result.answer == "early"


def test_later_valid_candidate_is_chosen_even_with_trailing_prose():
    result = check(EARLY + " " + FINAL + " trailing prose")
    assert result.status == booth.ACCEPTED
    assert result.answer == "final"


def test_math_braces_before_final_json_are_not_candidates():
    raw = r"Working: \frac{1}{2} = 0.5." + "\n" + FINAL + "\nDone."
    result = check(raw)
    assert result.status == booth.ACCEPTED
    assert result.answer == "final"


def test_escaped_quotes_and_braces_inside_answer_are_preserved():
    answer = 'The value of "{key}" is 1.'
    raw = "Reasoning first.\n" + json.dumps({"answer": answer, "confidence": 0.9}) + "\nDone."
    result = check(raw)
    assert result.status == booth.ACCEPTED
    assert result.answer == answer


def test_custom_parse_fn_receives_original_response():
    raw = EARLY + " " + FINAL + " trailing prose"
    seen = []

    def parse_fn(text):
        seen.append(text)
        return {"answer": "custom", "confidence": 0.9}

    result = booth.check(lambda prompt: raw, "review", max_retries=0, parse_fn=parse_fn)
    assert result.status == booth.ACCEPTED
    assert result.answer == "custom"
    assert seen == [raw]


def test_several_invalid_objects_report_last_objects_error():
    raw = '{"answer": "", "confidence": 0.9} {"answer": "final", "confidence": 2} trailing prose'
    result = check(raw)
    assert result.status == booth.UNCERTAIN
    assert result.call_failed is False
    assert "out of the [0.0, 1.0] range" in result.attempts[-1].error


def response_with_outer_and_inner(outer_answer="outer"):
    outer = {
        "answer": outer_answer,
        "confidence": 0.9,
        "meta": {"answer": "inner", "confidence": 0.8},
    }
    return "Reasoning first.\n" + json.dumps(outer, indent=2) + "\nDone."


def test_pretty_printed_outer_object_wins_over_nested_answer():
    result = check(response_with_outer_and_inner())
    assert result.status == booth.ACCEPTED
    assert result.answer == "outer"
    assert result.confidence == 0.9
    assert result.parsed["meta"]["answer"] == "inner"


def test_last_valid_top_level_object_wins_not_its_nested_metadata():
    result = check(EARLY + "\n" + response_with_outer_and_inner())
    assert result.status == booth.ACCEPTED
    assert result.answer == "outer"
    assert result.confidence == 0.9


def test_invalid_outer_dict_answer_is_parse_failure_not_nested_success():
    raw = response_with_outer_and_inner({"answer": "nested answer", "confidence": 0.95})
    result = check(raw)
    assert result.status == booth.UNCERTAIN
    assert result.answer is None
    assert result.method == "parse_failure"
    assert result.call_failed is False
    assert result.attempts[0].parse_ok is False


def test_invalid_outer_triggers_retry_then_recovers():
    prompts = []
    responses = iter([
        response_with_outer_and_inner({"answer": "nested answer", "confidence": 0.95}),
        FINAL,
    ])

    def call_fn(prompt):
        prompts.append(prompt)
        return next(responses)

    result = booth.check(call_fn, "review", max_retries=1)
    assert result.status == booth.REPAIRED
    assert result.answer == "final"
    assert len(result.attempts) == 2
    assert result.attempts[0].parse_ok is False
    assert result.attempts[0].call_failed is False
    assert "could not be parsed" in prompts[1]


def test_nested_only_answer_does_not_count_as_top_level_answer():
    raw = 'Reasoning\n' + json.dumps({"meta": {"answer": "inner", "confidence": 0.8}}, indent=2) + '\nDone.'
    result = check(raw)
    assert result.status == booth.UNCERTAIN
    assert result.answer is None
    assert result.method == "parse_failure"
    assert result.call_failed is False


def test_acheck_also_uses_outer_object():
    async def call_fn(prompt):
        return response_with_outer_and_inner()

    result = asyncio.run(booth.acheck(call_fn, "review", max_retries=0))
    assert result.status == booth.ACCEPTED
    assert result.answer == "outer"
    assert result.confidence == 0.9


def test_acheck_invalid_outer_retries_without_using_inner_answer():
    prompts = []
    responses = iter([
        response_with_outer_and_inner({"answer": "nested answer", "confidence": 0.95}),
        FINAL,
    ])

    async def call_fn(prompt):
        prompts.append(prompt)
        return next(responses)

    result = asyncio.run(booth.acheck(call_fn, "review", max_retries=1))
    assert result.status == booth.REPAIRED
    assert result.answer == "final"
    assert len(result.attempts) == 2
    assert result.attempts[0].parse_ok is False
    assert result.attempts[0].call_failed is False
    assert "could not be parsed" in prompts[1]


DOUBLED_BRACES = '{{"answer": "A", "confidence": 0.9}}'
NO_JSON_EXTRACTED = "no JSON object could be extracted from the response"


def test_iter_top_level_objects_handles_doubled_braces():
    # A reply that copies a str.format-escaped example: the first "{" fails to
    # decode, and the one right after it must still be tried.
    assert list(_iter_top_level_objects(DOUBLED_BRACES)) == [
        {"answer": "A", "confidence": 0.9}
    ]


def test_parse_response_reads_doubled_braces():
    attempt = _parse_response(DOUBLED_BRACES)
    assert attempt.parse_ok is True
    assert attempt.answer == "A"
    assert attempt.confidence == 0.9


@pytest.mark.parametrize("raw", ["", "  \n\t "])
def test_empty_or_whitespace_reply_reports_no_json_extracted(raw):
    attempt = _parse_response(raw)
    assert attempt.parse_ok is False
    assert attempt.error == NO_JSON_EXTRACTED


def test_prose_without_braces_keeps_its_current_message():
    # Pins today's wording, so a change to it is deliberate.
    attempt = _parse_response("The answer is probably yes.")
    assert attempt.parse_ok is False
    assert attempt.error == "no candidate contained a valid JSON object"
