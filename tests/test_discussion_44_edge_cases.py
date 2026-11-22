"""Edge cases the maintainer decided in Discussion #44.

Each test pins one answer from
https://github.com/Vedantgitbot/booth/discussions/44: behaviour the suite
passed either way before. The nesting guard is tested directly, never through
an end-to-end parse at the limit, which depends on Python's recursion limit.
"""

from booth.core import (
    Attempt,
    _build_parse_failure_prompt,
    _build_prompt,
    _build_retry_prompt,
    _build_validation_failure_prompt,
    _exceeds_json_nesting_limit,
)


def test_attempt_that_does_not_say_is_not_ambiguous():
    attempt = Attempt(raw_text="x", answer=None, confidence=None, parse_ok=False)

    assert attempt.ambiguous is False


def test_prompt_trailing_whitespace_is_trimmed():
    assert _build_prompt("What is 2+2?\n\n") == _build_prompt("What is 2+2?")
    assert _build_prompt("What is 2+2?   ") == _build_prompt("What is 2+2?")


def test_prompt_leading_whitespace_is_kept():
    assert _build_prompt("  What is 2+2?").startswith("  What is 2+2?")


def test_retry_prompt_trims_trailing_whitespace_the_same_way():
    previous = Attempt(raw_text="not json", answer=None, confidence=None, parse_ok=False, error="no JSON object")

    assert _build_retry_prompt("What is 2+2?\n\n", previous) == _build_retry_prompt("What is 2+2?", previous)


def test_parse_and_validation_failure_prompts_trim_trailing_whitespace():
    previous = Attempt(raw_text="5", answer="5", confidence=0.5, parse_ok=True, validation_error="too big")

    assert _build_parse_failure_prompt("What is 2+2?\n\n", previous) == _build_parse_failure_prompt(
        "What is 2+2?", previous
    )
    assert _build_validation_failure_prompt("What is 2+2?  ", previous) == _build_validation_failure_prompt(
        "What is 2+2?", previous
    )


def test_nesting_guard_accepts_exactly_the_default_limit():
    assert _exceeds_json_nesting_limit("[" * 1024 + "]" * 1024) is False


def test_nesting_guard_rejects_one_past_the_default_limit():
    assert _exceeds_json_nesting_limit("[" * 1025 + "]" * 1025) is True


def test_flat_object_has_depth_one():
    assert _exceeds_json_nesting_limit('{"a": 1}', limit=1) is False
    assert _exceeds_json_nesting_limit('{"a": {"b": 1}}', limit=1) is True


def test_brackets_inside_strings_do_not_count():
    assert _exceeds_json_nesting_limit('{"a": "{{{{[[[["}', limit=1) is False


def test_brackets_after_an_escaped_quote_stay_inside_the_string():
    # The JSON string is x\"{{{{ : the escaped quote does not end it.
    assert _exceeds_json_nesting_limit('{"a": "x\\"{{{{"}', limit=1) is False


def test_braces_and_brackets_both_add_a_level():
    assert _exceeds_json_nesting_limit("{" * 3, limit=2) is True
    assert _exceeds_json_nesting_limit("[" * 3, limit=2) is True


def test_stray_closers_never_take_depth_below_zero():
    assert _exceeds_json_nesting_limit("]]][[[", limit=2) is True
