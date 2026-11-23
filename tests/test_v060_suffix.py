"""v0.6.0: suffix=, DEFAULT_SUFFIX / REASONING_SUFFIX, the validator on
ambiguous attempts, and Attempt.pre_json_text.

The default prompt is pinned here as a literal copy of the 0.5.9 text, not
built from the library constant, so an accidental wording change fails.
"""
import asyncio
import json

import pytest

import booth
from booth.core import (
    DEFAULT_SUFFIX,
    REASONING_SUFFIX,
    _CONFIDENCE_SUFFIX,
    _iter_top_level_objects,
    _parse_response,
)

# The 0.5.9 default suffix, copied literally.
V059_SUFFIX = """

After answering, output your response as a single JSON object on its \
own line, with exactly these keys, IN THIS ORDER:
{"ambiguous": true/false, "interpretations": ["<reading 1>", "<reading 2>", ...], "chosen_interpretation": "<which reading you answered under, or null if not ambiguous>", "answer": "<your answer, concise>", "confidence": <float 0.0-1.0>}

Set "ambiguous" to true if the question has more than one reasonable, \
meaningfully different answer depending on interpretation (different \
named entities sharing a name, different metrics like assets vs. \
market cap, different time periods, etc.). List those readings in \
"interpretations" (empty list if not ambiguous). If ambiguous, still \
answer under your best-guess interpretation, and name it in \
"chosen_interpretation".

"confidence" is your own honest estimate of the probability that \
"answer" is factually correct, given the interpretation you chose. Do \
not pad the confidence toward 1.0 out of politeness — under-confidence \
and over-confidence are both penalized. Output ONLY the JSON object, \
nothing else."""

P = "What is 2+2?"

FORMAT_LINE = "\n\nAnswer format: one quantity such as 12.34 USD."
CUSTOM_SUFFIX = V059_SUFFIX + FORMAT_LINE


def reply(answer="4", confidence=0.9, **extra):
    obj = {
        "ambiguous": False,
        "interpretations": [],
        "chosen_interpretation": None,
        "answer": answer,
        "confidence": confidence,
    }
    obj.update(extra)
    return json.dumps(obj)


def ambiguous_reply(answer="4", confidence=0.9):
    return json.dumps({
        "ambiguous": True,
        "interpretations": ["reading a", "reading b"],
        "chosen_interpretation": "reading a",
        "answer": answer,
        "confidence": confidence,
    })


def make_call(replies):
    """Sync call_fn that records prompts and replays `replies` in order."""
    prompts = []
    queue = list(replies)

    def call_fn(prompt):
        prompts.append(prompt)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return call_fn, prompts


def make_acall(replies):
    prompts = []
    queue = list(replies)

    async def call_fn(prompt):
        prompts.append(prompt)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return call_fn, prompts


# --- templates and exports -------------------------------------------------


def test_default_suffix_is_byte_identical_to_059():
    assert DEFAULT_SUFFIX == V059_SUFFIX


def test_private_alias_still_points_at_the_default():
    assert _CONFIDENCE_SUFFIX is DEFAULT_SUFFIX


def test_templates_are_exported():
    assert booth.DEFAULT_SUFFIX is DEFAULT_SUFFIX
    assert booth.REASONING_SUFFIX is REASONING_SUFFIX
    assert "DEFAULT_SUFFIX" in booth.__all__
    assert "REASONING_SUFFIX" in booth.__all__
    for name in booth.__all__:
        assert hasattr(booth, name), name


def test_version():
    assert booth.__version__ == "0.6.0"


def test_reasoning_suffix_keeps_the_schema_and_guidance():
    schema = next(
        line for line in DEFAULT_SUFFIX.splitlines() if line.startswith('{"ambiguous"')
    )
    assert schema in REASONING_SUFFIX
    ambiguity_paragraph = DEFAULT_SUFFIX.split("\n\n")[2]
    assert ambiguity_paragraph.startswith('Set "ambiguous"')
    assert ambiguity_paragraph in REASONING_SUFFIX
    assert REASONING_SUFFIX.startswith("\n\n")


def test_reasoning_suffix_allows_working_before_the_json():
    assert REASONING_SUFFIX != DEFAULT_SUFFIX
    assert "Output ONLY the JSON object" not in REASONING_SUFFIX
    assert "last" in REASONING_SUFFIX


# --- golden tests: the default prompts, through the public check() ---------


def test_golden_first_prompt():
    call_fn, prompts = make_call([reply()])
    booth.check(call_fn, P)
    assert prompts == [P + V059_SUFFIX]


def test_golden_low_confidence_retry_prompt():
    call_fn, prompts = make_call([reply("4", 0.3), reply("4", 0.9)])
    result = booth.check(call_fn, P)
    assert result.status == booth.REPAIRED
    assert prompts[1] == (
        f"{P}\n\n"
        'On a previous attempt you answered: "4" with confidence 0.3.\n'
        "Reconsider carefully. If that answer is correct, restate it. "
        "If it is wrong, give the corrected answer."
        f"{V059_SUFFIX}"
    )


def test_golden_parse_failure_retry_prompt():
    call_fn, prompts = make_call(["not json at all", reply()])
    booth.check(call_fn, P)
    assert prompts[1] == (
        f"{P}\n\n"
        "Your previous response could not be parsed: it did not contain a "
        "valid JSON object with the required keys. Output your response as "
        "a single JSON object with exactly the required keys, and nothing "
        "else — no markdown code fences, no commentary before or after it."
        f"{V059_SUFFIX}"
    )


def test_golden_validation_failure_retry_prompt():
    verdicts = iter([(False, "must be 5"), (True, "")])
    call_fn, prompts = make_call([reply("4"), reply("5")])
    booth.check(call_fn, P, validator=lambda a: next(verdicts))
    assert prompts[1] == (
        f"{P}\n\n"
        'Your previous answer was: "4"\n\n'
        "That answer failed validation: must be 5\n\n"
        "Reconsider carefully and provide a corrected answer that "
        "satisfies the validation requirement."
        f"{V059_SUFFIX}"
    )


def test_golden_retry_after_a_failed_call_is_the_first_prompt_again():
    call_fn, prompts = make_call([RuntimeError("boom"), reply()])
    result = booth.check(call_fn, P)
    assert result.status == booth.REPAIRED
    assert prompts == [P + V059_SUFFIX, P + V059_SUFFIX]


@pytest.mark.parametrize("prompt", [P + "\n\n", P + "   ", P + " \n \t\n"])
def test_trailing_whitespace_in_the_prompt_is_trimmed_everywhere(prompt):
    call_fn, prompts = make_call(["junk", reply("4", 0.3), reply("4", 0.9)])
    booth.check(call_fn, prompt, max_retries=2)
    reference_fn, reference = make_call(["junk", reply("4", 0.3), reply("4", 0.9)])
    booth.check(reference_fn, P, max_retries=2)
    assert prompts == reference


def test_leading_whitespace_in_the_prompt_is_kept():
    call_fn, prompts = make_call([reply()])
    booth.check(call_fn, "  " + P)
    assert prompts[0] == "  " + P + V059_SUFFIX


# --- suffix= ---------------------------------------------------------------


def test_explicit_default_suffix_behaves_like_no_suffix():
    a_fn, a_prompts = make_call(["junk", reply()])
    b_fn, b_prompts = make_call(["junk", reply()])
    booth.check(a_fn, P)
    booth.check(b_fn, P, suffix=DEFAULT_SUFFIX)
    assert a_prompts == b_prompts


def test_custom_suffix_is_on_the_first_call():
    call_fn, prompts = make_call([reply()])
    booth.check(call_fn, P, suffix=CUSTOM_SUFFIX)
    assert prompts == [P + CUSTOM_SUFFIX]


def test_custom_suffix_is_on_the_low_confidence_retry():
    call_fn, prompts = make_call([reply("4", 0.3), reply("4", 0.9)])
    booth.check(call_fn, P, suffix=CUSTOM_SUFFIX)
    assert prompts[1].endswith(CUSTOM_SUFFIX)
    assert "Reconsider carefully" in prompts[1]


def test_custom_suffix_is_on_the_validation_retry():
    verdicts = iter([(False, "nope"), (True, "")])
    call_fn, prompts = make_call([reply("4"), reply("5")])
    booth.check(call_fn, P, suffix=CUSTOM_SUFFIX, validator=lambda a: next(verdicts))
    assert prompts[1].endswith(CUSTOM_SUFFIX)
    assert "failed validation: nope" in prompts[1]


def test_custom_suffix_is_on_the_retry_after_a_failed_call():
    call_fn, prompts = make_call([RuntimeError("boom"), reply()])
    booth.check(call_fn, P, suffix=CUSTOM_SUFFIX)
    assert prompts == [P + CUSTOM_SUFFIX, P + CUSTOM_SUFFIX]


def test_custom_suffix_parse_failure_retry_drops_the_nothing_else_line():
    call_fn, prompts = make_call(["junk", reply()])
    booth.check(call_fn, P, suffix=CUSTOM_SUFFIX)
    retry = prompts[1]
    assert retry.endswith(CUSTOM_SUFFIX)
    assert "could not be parsed" in retry
    assert "no commentary" not in retry
    assert "and nothing else" not in retry
    assert "ends with the single JSON object" in retry


def test_default_parse_failure_retry_keeps_the_nothing_else_line():
    call_fn, prompts = make_call(["junk", reply()])
    booth.check(call_fn, P)
    assert "no commentary before or after it" in prompts[1]


def test_every_attempt_carries_the_same_format_line():
    verdicts = iter([(False, "bad"), (True, "")])
    call_fn, prompts = make_call(["junk", reply("4", 0.3), reply("5", 0.9), reply("5")])
    booth.check(
        call_fn, P, suffix=CUSTOM_SUFFIX, max_retries=3,
        validator=lambda a: next(verdicts),
    )
    assert len(prompts) >= 3
    for prompt in prompts:
        assert FORMAT_LINE in prompt
        assert prompt.endswith(CUSTOM_SUFFIX)


@pytest.mark.parametrize("bad", [123, 1.5, ["x"], b"bytes", object()])
def test_non_string_suffix_raises_type_error_before_any_call(bad):
    call_fn, prompts = make_call([reply()])
    with pytest.raises(TypeError, match="suffix"):
        booth.check(call_fn, P, suffix=bad)
    assert prompts == []


@pytest.mark.parametrize("bad", ["", "   ", "\n\n", " \t\n "])
def test_blank_suffix_raises_value_error_before_any_call(bad):
    call_fn, prompts = make_call([reply()])
    with pytest.raises(ValueError, match="suffix"):
        booth.check(call_fn, P, suffix=bad)
    assert prompts == []


@pytest.mark.parametrize("bad", [123, ["x"]])
def test_acheck_rejects_non_string_suffix_before_any_call(bad):
    call_fn, prompts = make_acall([reply()])
    with pytest.raises(TypeError, match="suffix"):
        asyncio.run(booth.acheck(call_fn, P, suffix=bad))
    assert prompts == []


@pytest.mark.parametrize("bad", ["", "  \n"])
def test_acheck_rejects_blank_suffix_before_any_call(bad):
    call_fn, prompts = make_acall([reply()])
    with pytest.raises(ValueError, match="suffix"):
        asyncio.run(booth.acheck(call_fn, P, suffix=bad))
    assert prompts == []


def test_suffix_is_keyword_only():
    call_fn, _ = make_call([reply()])
    with pytest.raises(TypeError):
        booth.check(call_fn, P, 0.7, 1, None, CUSTOM_SUFFIX)  # type: ignore[misc]


def test_check_and_acheck_agree_with_a_custom_suffix():
    scenario = ["junk", reply("4", 0.3), reply("4", 0.9)]
    sync_fn, sync_prompts = make_call(scenario)
    async_fn, async_prompts = make_acall(scenario)
    sync_result = booth.check(sync_fn, P, suffix=CUSTOM_SUFFIX, max_retries=2)
    async_result = asyncio.run(
        booth.acheck(async_fn, P, suffix=CUSTOM_SUFFIX, max_retries=2)
    )
    assert sync_prompts == async_prompts
    assert sync_result.to_dict() == async_result.to_dict()


def test_reasoning_suffix_end_to_end():
    raw = "2 plus 2: two and two make four.\n\n" + reply("4", 0.95)
    call_fn, prompts = make_call([raw])
    result = booth.check(call_fn, P, suffix=REASONING_SUFFIX)
    assert prompts == [P + REASONING_SUFFIX]
    assert result.status == booth.ACCEPTED
    assert result.answer == "4"
    assert result.attempts[0].pre_json_text == "2 plus 2: two and two make four."


# --- validator on ambiguous attempts --------------------------------------


def test_validator_runs_on_an_ambiguous_attempt_and_fails_it():
    seen = []

    def validator(answer):
        seen.append(answer)
        return False, "nope"

    call_fn, prompts = make_call([ambiguous_reply("4")])
    result = booth.check(call_fn, P, validator=validator, max_retries=2)
    assert seen == ["4"]
    assert result.status == booth.AMBIGUOUS
    assert result.ok is False
    assert result.method == "ambiguity"
    attempt = result.attempts[0]
    assert attempt.passed_validation is False
    assert attempt.validation_error == "nope"
    assert len(prompts) == 1  # ambiguity is still never retried


def test_validator_runs_on_an_ambiguous_attempt_and_passes_it():
    call_fn, _ = make_call([ambiguous_reply("4")])
    result = booth.check(call_fn, P, validator=lambda a: True, max_retries=0)
    assert result.status == booth.AMBIGUOUS
    assert result.ok is False
    assert result.attempts[0].passed_validation is True
    assert result.attempts[0].validation_error is None


def test_validator_exception_on_an_ambiguous_attempt_is_contained():
    def validator(answer):
        raise ValueError("kaboom")

    call_fn, _ = make_call([ambiguous_reply("4")])
    result = booth.check(call_fn, P, validator=validator, max_retries=0)
    assert result.status == booth.AMBIGUOUS
    assert result.attempts[0].passed_validation is False
    assert result.attempts[0].validation_error.startswith("Validator raised ValueError")


def test_validator_sees_a_blank_ambiguous_answer():
    seen = []

    def validator(answer):
        seen.append(answer)
        return True

    call_fn, _ = make_call([ambiguous_reply("")])
    result = booth.check(call_fn, P, validator=validator, max_retries=0)
    assert seen == [""]
    assert result.status == booth.AMBIGUOUS


def test_no_validator_leaves_ambiguous_attempts_alone():
    call_fn, _ = make_call([ambiguous_reply("4")])
    result = booth.check(call_fn, P, max_retries=0)
    assert result.status == booth.AMBIGUOUS
    assert result.attempts[0].validation_error is None


def test_acheck_runs_the_validator_on_ambiguous_attempts_too():
    seen = []

    def validator(answer):
        seen.append(answer)
        return False, "nope"

    call_fn, _ = make_acall([ambiguous_reply("4")])
    result = asyncio.run(booth.acheck(call_fn, P, validator=validator, max_retries=0))
    assert seen == ["4"]
    assert result.status == booth.AMBIGUOUS
    assert result.attempts[0].passed_validation is False
    assert result.attempts[0].validation_error == "nope"


def test_non_ambiguous_validation_flow_is_unchanged():
    verdicts = iter([(False, "bad"), (True, "")])
    call_fn, _ = make_call([reply("4"), reply("5")])
    result = booth.check(call_fn, P, validator=lambda a: next(verdicts))
    assert result.status == booth.REPAIRED
    assert result.answer == "5"


# --- pre_json_text ---------------------------------------------------------


def test_pre_json_text_after_reasoning():
    attempt = _parse_response("Let me work it out: 2+2=4.\n\n" + reply())
    assert attempt.parse_ok
    assert attempt.pre_json_text == "Let me work it out: 2+2=4."


def test_pre_json_text_is_empty_when_the_object_starts_the_reply():
    attempt = _parse_response(reply())
    assert attempt.parse_ok
    assert attempt.pre_json_text == ""


def test_pre_json_text_is_taken_before_the_selected_object_not_the_first():
    draft = reply("3", 0.5)
    final = reply("4", 0.95)
    attempt = _parse_response(f"Draft: {draft}\nFinal:\n{final}")
    assert attempt.answer == "4"
    assert attempt.pre_json_text == f"Draft: {draft}\nFinal:"


def test_pre_json_text_follows_the_selected_object_when_a_later_one_is_invalid():
    good = reply("4", 0.9)
    attempt = _parse_response(f"Working. {good}\nThen: " + '{"answer": "x"}')
    assert attempt.answer == "4"
    assert attempt.pre_json_text == "Working."


def test_pre_json_text_survives_braces_in_the_working():
    working = r"Half of it is \frac{1}{2}, so the sum is {4}."
    attempt = _parse_response(working + "\n" + reply())
    assert attempt.parse_ok
    assert attempt.pre_json_text == working


def test_pre_json_text_ignores_a_nested_object():
    outer = reply("4", 0.9, meta={"answer": "x", "confidence": 0.1})
    attempt = _parse_response("Reasoning here.\n" + outer)
    assert attempt.answer == "4"
    assert attempt.pre_json_text == "Reasoning here."


def test_pre_json_text_is_none_when_nothing_parsed():
    assert _parse_response("no json here").pre_json_text is None
    assert _parse_response("").pre_json_text is None
    assert _parse_response('{"answer": "x"}').pre_json_text is None


def test_pre_json_text_is_none_with_a_custom_parse_fn():
    call_fn, _ = make_call(["thinking... DONE"])
    result = booth.check(
        call_fn, P, max_retries=0,
        parse_fn=lambda raw: {"answer": "4", "confidence": 0.9},
    )
    assert result.status == booth.ACCEPTED
    assert result.attempts[0].pre_json_text is None


def test_pre_json_text_is_none_when_the_call_failed():
    call_fn, _ = make_call([RuntimeError("boom")])
    result = booth.check(call_fn, P, max_retries=0)
    assert result.attempts[0].call_failed is True
    assert result.attempts[0].pre_json_text is None


def test_acheck_fills_pre_json_text():
    call_fn, _ = make_acall(["Thinking first.\n" + reply()])
    result = asyncio.run(booth.acheck(call_fn, P, max_retries=0))
    assert result.attempts[0].pre_json_text == "Thinking first."


def test_pre_json_text_is_in_to_dict():
    call_fn, _ = make_call(["Thinking first.\n" + reply()])
    result = booth.check(call_fn, P, max_retries=0)
    dumped = json.loads(json.dumps(result.to_dict()))
    assert dumped["attempts"][0]["pre_json_text"] == "Thinking first."


def test_the_iterator_still_yields_plain_objects():
    first = {"answer": "a", "confidence": 0.1}
    second = {"answer": "b", "confidence": 0.2}
    text = f"x {json.dumps(first)} y {json.dumps(second)}"
    assert list(_iter_top_level_objects(text)) == [first, second]


# --- long, brace-heavy replies --------------------------------------------


def test_long_reasoning_reply_with_many_balanced_braces_still_parses():
    working = "Half of it is \\frac{1}{2}. " * 3000
    assert len(working) > 80_000
    attempt = _parse_response(working + "\n" + reply("4", 0.9))
    assert attempt.parse_ok
    assert attempt.answer == "4"
    assert attempt.pre_json_text.endswith("\\frac{1}{2}.")