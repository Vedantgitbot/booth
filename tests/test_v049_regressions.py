"""
Regression tests for the v0.4.9 batch.

Six items, in ship order:
  1. Empty/whitespace-only `answer` accepted by check() -- now rejected
     unless the attempt is AMBIGUOUS (interpretations carry the signal
     instead).
  2. Brace-like content inside `answer` could defeat the flat regex
     fallback extractor when the object was embedded in surrounding
     prose -- json.JSONDecoder.raw_decode is now tried as a further
     fallback, since it correctly treats braces inside a JSON string
     value as ordinary content rather than structure.
  3. check_with_evidence() robustness: a non-str answer crashed with
     AttributeError; numpy-array evidence crashed the `not evidence`
     truthiness check; an async (or async-wrapping) compare_fn neither
     raised cleanly nor was rejected, and could leak a coroutine
     RuntimeWarning either way.
  4. Numeric and boolean `answer` values (e.g. {"answer": 42}) are now
     coerced to their string form instead of being treated as parse
     failures. Structured values (dict/list) are still rejected.
  5. Attempt.error now carries a human-readable reason when parsing
     fails, instead of being left None.
  6. evidence_threshold gets the same TypeError-on-bad-type treatment
     max_retries already has, for str/None/bool.
"""
import asyncio
import json

import pytest

import booth
from booth.core import check_with_evidence, _is_empty_evidence, _iter_raw_decoded_objects


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------
# Item 1: empty / whitespace-only answer
# ---------------------------------------------------------------------

def test_empty_string_answer_rejected():
    def call_fn(p):
        return json.dumps({"answer": "", "confidence": 0.99})

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.status == booth.UNCERTAIN
    assert r.answer is None
    assert "empty" in r.attempts[0].error.lower()


def test_whitespace_only_answer_rejected():
    def call_fn(p):
        return json.dumps({"answer": "   \n\t  ", "confidence": 0.99})

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.status == booth.UNCERTAIN
    assert r.answer is None


def test_ambiguous_attempt_with_blank_answer_is_exempt():
    """The core exemption: an AMBIGUOUS attempt must not be discarded
    just because `answer` is blank -- the interpretations carry the
    real signal in that case, not `answer`."""
    def call_fn(p):
        return json.dumps({
            "ambiguous": True,
            "interpretations": ["reading A", "reading B"],
            "chosen_interpretation": None,
            "answer": "",
            "confidence": 0.9,
        })

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.status == booth.AMBIGUOUS
    assert r.interpretations == ["reading A", "reading B"]


def test_normal_nonblank_answer_unaffected():
    def call_fn(p):
        return json.dumps({"answer": "Paris", "confidence": 0.9})

    r = booth.check(call_fn, "q")
    assert r.status == booth.ACCEPTED
    assert r.answer == "Paris"


# ---------------------------------------------------------------------
# Item 2: raw_decode fallback for brace-like content in `answer`
# ---------------------------------------------------------------------

def test_nested_brace_in_answer_embedded_in_prose_now_recovers():
    """The regex fallback (\\{[^{}]*\\}) cannot match an object
    containing nested braces in a string value. Wrapped in commentary
    (so the primary whole-string and last-line paths both miss too),
    this previously always fell through to UNCERTAIN. raw_decode
    parses the full, valid, nested-brace-containing object correctly."""
    def call_fn(p):
        return (
            "Sure, here's my answer:\n"
            '{"answer": "the config is {mode: fast, retries: 3}", "confidence": 0.91}\n'
            "Hope that helps!"
        )

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.status == booth.ACCEPTED, r.status
    assert r.answer == "the config is {mode: fast, retries: 3}"


def test_genuinely_malformed_outer_json_still_fails_safe():
    """Sanity check: this fix recovers a *complete, valid* object
    hidden among nested braces -- it must not start hallucinating a
    result out of genuinely incomplete/malformed JSON (missing closing
    brace). Locks in the same "document, don't assume" principle as
    the original 0.4.4 gap9 test."""
    raw = '{"answer": "the config is {foo: 1}", "confidence": 0.9'  # missing closing }
    def call_fn(p):
        return raw

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.status == booth.UNCERTAIN
    assert r.all_parse_failed is True


def test_iter_raw_decoded_objects_finds_object_regardless_of_position():
    text = 'noise before {"a": 1, "b": {"nested": true}} noise after'
    found = list(_iter_raw_decoded_objects(text))
    assert {"a": 1, "b": {"nested": True}} in found


# ---------------------------------------------------------------------
# Item 3: check_with_evidence() robustness
# ---------------------------------------------------------------------

def test_non_str_answer_raises_typeerror_not_attributeerror():
    with pytest.raises(TypeError):
        check_with_evidence(answer=123, evidence=["e"], compare_fn=lambda a, e: True)


def test_list_answer_raises_typeerror():
    with pytest.raises(TypeError):
        check_with_evidence(answer=["not", "a", "string"], evidence=["e"], compare_fn=lambda a, e: True)


def test_none_answer_still_gracefully_uncertain_not_typeerror():
    """None was already safe pre-0.4.9 (short-circuits via `not answer`)
    -- must stay that way, not suddenly start raising."""
    r = check_with_evidence(answer=None, evidence=["e"], compare_fn=lambda a, e: True)
    assert r.status == booth.UNCERTAIN


def test_numpy_array_evidence_no_longer_crashes():
    np = pytest.importorskip("numpy")
    r = check_with_evidence(
        answer="Paris",
        evidence=np.array(["Paris is the capital of France.", "Some other fact."]),
        compare_fn=lambda a, e: a.lower() in " ".join(e).lower(),
    )
    assert r.status == booth.ACCEPTED


def test_is_empty_evidence_numpy_array():
    np = pytest.importorskip("numpy")
    assert _is_empty_evidence(np.array([])) is True
    assert _is_empty_evidence(np.array(["a", "b"])) is False


def test_is_empty_evidence_plain_list():
    assert _is_empty_evidence([]) is True
    assert _is_empty_evidence(["a"]) is False


def test_async_compare_fn_raises_typeerror_not_silent():
    async def async_compare(answer, evidence):
        return True

    with pytest.raises(TypeError):
        check_with_evidence(answer="Paris", evidence=["e"], compare_fn=async_compare)


def test_sync_wrapper_returning_coroutine_raises_typeerror():
    """The second failure shape from the patch note: a *sync* function
    that internally calls an async comparator and returns the
    resulting coroutine without awaiting it."""
    async def _inner(answer, evidence):
        return True

    def sync_wrapper(answer, evidence):
        return _inner(answer, evidence)  # returns a coroutine, never awaited

    with pytest.raises(TypeError):
        check_with_evidence(answer="Paris", evidence=["e"], compare_fn=sync_wrapper)


def test_async_compare_fn_no_leaked_warning():
    import warnings

    async def async_compare(answer, evidence):
        return True

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(TypeError):
            check_with_evidence(answer="Paris", evidence=["e"], compare_fn=async_compare)


# ---------------------------------------------------------------------
# Item 4: numeric / boolean answer accepted, dict/list still rejected
# ---------------------------------------------------------------------

def test_integer_answer_coerced_to_string():
    def call_fn(p):
        return json.dumps({"answer": 42, "confidence": 0.9})

    r = booth.check(call_fn, "q")
    assert r.status == booth.ACCEPTED
    assert r.answer == "42"
    assert isinstance(r.answer, str)
    # parsed keeps the raw, uncoerced type
    assert r.parsed["answer"] == 42
    assert isinstance(r.parsed["answer"], int)


def test_float_answer_coerced_to_string():
    def call_fn(p):
        return json.dumps({"answer": 3.14, "confidence": 0.9})

    r = booth.check(call_fn, "q")
    assert r.status == booth.ACCEPTED
    assert r.answer == "3.14"


def test_boolean_answer_coerced_to_string():
    def call_fn(p):
        return json.dumps({"answer": True, "confidence": 0.9})

    r = booth.check(call_fn, "q")
    assert r.status == booth.ACCEPTED
    assert r.answer == "True"


def test_dict_answer_still_rejected():
    def call_fn(p):
        return json.dumps({"answer": {"foo": "bar"}, "confidence": 0.9})

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.status == booth.UNCERTAIN
    assert r.answer is None


def test_list_answer_still_rejected():
    def call_fn(p):
        return json.dumps({"answer": [1, 2, 3], "confidence": 0.9})

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.status == booth.UNCERTAIN


# ---------------------------------------------------------------------
# Item 5: Attempt.error carries a reason on parse failure
# ---------------------------------------------------------------------

def test_error_reason_for_missing_keys():
    def call_fn(p):
        return json.dumps({"foo": "bar"})  # no answer/confidence at all

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.attempts[0].error is not None
    assert "answer" in r.attempts[0].error or "confidence" in r.attempts[0].error


def test_error_reason_for_out_of_range_confidence():
    def call_fn(p):
        return json.dumps({"answer": "x", "confidence": 17})

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.attempts[0].error is not None
    assert "range" in r.attempts[0].error.lower()


def test_error_reason_for_no_json_at_all():
    def call_fn(p):
        return "not json at all, just prose"

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.attempts[0].error is not None


def test_error_reason_for_empty_answer():
    def call_fn(p):
        return json.dumps({"answer": "", "confidence": 0.9})

    r = booth.check(call_fn, "q", max_retries=0)
    assert r.attempts[0].error is not None
    assert "empty" in r.attempts[0].error.lower()


# ---------------------------------------------------------------------
# Item 6: evidence_threshold type validation
# ---------------------------------------------------------------------

def test_evidence_threshold_string_raises_typeerror():
    with pytest.raises(TypeError):
        check_with_evidence("Paris", ["e"], lambda a, e: True, evidence_threshold="0.8")


def test_evidence_threshold_none_raises_typeerror():
    with pytest.raises(TypeError):
        check_with_evidence("Paris", ["e"], lambda a, e: True, evidence_threshold=None)


def test_evidence_threshold_bool_raises_typeerror():
    """Deliberate divergence from max_retries: a bool threshold is
    rejected outright rather than treated as a harmless 0/1, since it's
    far more likely to be a caller mistake than an intentional choice."""
    with pytest.raises(TypeError):
        check_with_evidence("Paris", ["e"], lambda a, e: True, evidence_threshold=True)


def test_evidence_threshold_out_of_range_still_valueerror():
    """Sanity check: a correctly-typed but out-of-range threshold must
    still raise ValueError, not get swallowed by the new type check."""
    with pytest.raises(ValueError):
        check_with_evidence("Paris", ["e"], lambda a, e: True, evidence_threshold=1.5)


def test_evidence_threshold_valid_float_unaffected():
    r = check_with_evidence("Paris", ["Paris is the capital."], lambda a, e: True, evidence_threshold=0.9)
    assert r.status == booth.ACCEPTED


def test_evidence_threshold_valid_int_unaffected():
    """An int like 1 or 0 is a legitimate real number for a threshold,
    unlike a bool -- must not be rejected by the new type check."""
    r = check_with_evidence("Paris", ["Paris is the capital."], lambda a, e: True, evidence_threshold=1)
    assert r.status == booth.ACCEPTED