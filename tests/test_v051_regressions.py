import asyncio
import json

import pytest

import booth
from booth.core import BoothResult


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("answer", ["", "   ", "\n\t  "])
def test_check_with_evidence_empty_answer_has_distinct_reason(answer):
    r = booth.check_with_evidence(
        answer,
        ["Paris is the capital of France."],
        lambda a, e: True,
    )

    assert r.status == booth.UNCERTAIN
    assert r.reason == "EMPTY_ANSWER"
    assert r.detail is not None
    assert r.checker_failed is False


def test_empty_answer_does_not_call_compare_fn():
    calls = {"n": 0}

    def compare_fn(answer, evidence):
        calls["n"] += 1
        return True

    r = booth.check_with_evidence("", ["evidence"], compare_fn)

    assert r.reason == "EMPTY_ANSWER"
    assert calls["n"] == 0


@pytest.mark.parametrize("evidence", [[], (), ""])
def test_check_with_evidence_empty_evidence_has_distinct_reason(evidence):
    r = booth.check_with_evidence(
        "Paris",
        evidence,
        lambda a, e: True,
    )

    assert r.status == booth.UNCERTAIN
    assert r.reason == "NO_EVIDENCE"
    assert r.detail is not None
    assert r.checker_failed is False


def test_no_evidence_does_not_call_compare_fn():
    calls = {"n": 0}

    def compare_fn(answer, evidence):
        calls["n"] += 1
        return True

    r = booth.check_with_evidence("Paris", [], compare_fn)

    assert r.reason == "NO_EVIDENCE"
    assert calls["n"] == 0


def test_check_with_evidence_compare_exception_has_compare_failed_reason():
    def compare_fn(answer, evidence):
        raise RuntimeError("comparator service unavailable")

    r = booth.check_with_evidence(
        "Paris",
        ["Paris is the capital of France."],
        compare_fn,
    )

    assert r.status == booth.UNCERTAIN
    assert r.reason == "COMPARE_FAILED"
    assert r.checker_failed is True
    assert r.detail is not None
    assert "RuntimeError" in r.detail
    assert "comparator service unavailable" in r.detail


def test_compare_failed_detail_truncates_exception_message_to_200_chars():
    long_message = "x" * 500

    def compare_fn(answer, evidence):
        raise ValueError(long_message)

    r = booth.check_with_evidence(
        "Paris",
        ["Paris is the capital of France."],
        compare_fn,
    )

    assert r.status == booth.UNCERTAIN
    assert r.reason == "COMPARE_FAILED"
    assert r.checker_failed is True
    assert r.detail is not None
    assert r.detail.startswith("ValueError: ")
    assert long_message not in r.detail
    assert r.detail == f"ValueError: {long_message[:200]}"
    assert len(r.detail) == len("ValueError: ") + 200


@pytest.mark.parametrize(
    "invalid_score",
    [
        "yes",
        "not a score",
        "0.8x",
        None,
        object(),
        -0.01,
        1.01,
        -1,
        2,
    ],
)
def test_check_with_evidence_invalid_score_has_distinct_reason(invalid_score):
    r = booth.check_with_evidence(
        "Paris",
        ["Paris is the capital of France."],
        lambda a, e: invalid_score,
    )

    assert r.status == booth.UNCERTAIN
    assert r.reason == "INVALID_SCORE"
    assert r.detail is not None
    assert r.checker_failed is True


def test_numeric_string_score_is_accepted_as_a_valid_score():
    r = booth.check_with_evidence(
        "Paris",
        ["Paris is the capital of France."],
        lambda a, e: "0.8",
        evidence_threshold=0.5,
    )

    assert r.status == booth.ACCEPTED
    assert r.reason is None
    assert r.detail is None
    assert r.checker_failed is False


def test_invalid_score_detail_identifies_bad_score():
    r = booth.check_with_evidence(
        "Paris",
        ["Paris is the capital of France."],
        lambda a, e: 1.5,
    )

    assert r.reason == "INVALID_SCORE"
    assert r.detail is not None
    assert "1.5" in r.detail


def test_check_with_evidence_disagreement_has_evidence_disagrees_reason():
    r = booth.check_with_evidence(
        "Berlin",
        ["Paris is the capital of France."],
        lambda a, e: False,
    )

    assert r.status == booth.BLOCKED
    assert r.reason == "EVIDENCE_DISAGREES"
    assert r.detail is not None
    assert r.checker_failed is False


def test_evidence_disagrees_for_score_below_threshold():
    r = booth.check_with_evidence(
        "Berlin",
        ["Paris is the capital of France."],
        lambda a, e: 0.4,
        evidence_threshold=0.5,
    )

    assert r.status == booth.BLOCKED
    assert r.reason == "EVIDENCE_DISAGREES"
    assert r.checker_failed is False


def test_check_with_evidence_accepted_has_no_reason_or_detail():
    r = booth.check_with_evidence(
        "Paris",
        ["Paris is the capital of France."],
        lambda a, e: True,
    )

    assert r.status == booth.ACCEPTED
    assert r.reason is None
    assert r.detail is None
    assert r.checker_failed is False


def test_check_with_evidence_accepted_numeric_score_has_no_reason_or_detail():
    r = booth.check_with_evidence(
        "Paris",
        ["Paris is the capital of France."],
        lambda a, e: 0.9,
        evidence_threshold=0.8,
    )

    assert r.status == booth.ACCEPTED
    assert r.reason is None
    assert r.detail is None
    assert r.checker_failed is False


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        (None, False),
        ("EMPTY_ANSWER", False),
        ("NO_EVIDENCE", False),
        ("COMPARE_FAILED", True),
        ("INVALID_SCORE", True),
        ("EVIDENCE_DISAGREES", False),
    ],
)
def test_checker_failed_is_exactly_derived_from_reason(reason, expected):
    r = BoothResult(
        answer="x",
        status=booth.UNCERTAIN,
        reason=reason,
    )

    assert r.checker_failed is expected


def test_check_result_defaults_new_diagnostic_fields_to_none_and_false():
    def call_fn(prompt):
        return json.dumps({"answer": "Paris", "confidence": 0.9})

    r = booth.check(call_fn, "What is the capital of France?")

    assert r.status == booth.ACCEPTED
    assert r.reason is None
    assert r.detail is None
    assert r.checker_failed is False


def test_check_uncertain_result_defaults_new_diagnostic_fields_to_none_and_false():
    def call_fn(prompt):
        return "not json"

    r = booth.check(call_fn, "q", max_retries=0)

    assert r.status == booth.UNCERTAIN
    assert r.reason is None
    assert r.detail is None
    assert r.checker_failed is False


def test_acheck_result_defaults_new_diagnostic_fields_to_none_and_false():
    async def call_fn(prompt):
        return json.dumps({"answer": "Paris", "confidence": 0.9})

    r = _run(booth.acheck(call_fn, "What is the capital of France?"))

    assert r.status == booth.ACCEPTED
    assert r.reason is None
    assert r.detail is None
    assert r.checker_failed is False


def test_acheck_uncertain_result_defaults_new_diagnostic_fields_to_none_and_false():
    async def call_fn(prompt):
        return "not json"

    r = _run(booth.acheck(call_fn, "q", max_retries=0))

    assert r.status == booth.UNCERTAIN
    assert r.reason is None
    assert r.detail is None
    assert r.checker_failed is False


def test_to_dict_includes_new_diagnostic_keys_on_normal_check_result():
    def call_fn(prompt):
        return json.dumps({"answer": "Paris", "confidence": 0.9})

    r = booth.check(call_fn, "q")
    data = r.to_dict()

    assert "reason" in data
    assert "detail" in data
    assert "checker_failed" in data
    assert data["reason"] is None
    assert data["detail"] is None
    assert data["checker_failed"] is False


def test_to_dict_includes_compare_failure_diagnostics():
    def compare_fn(answer, evidence):
        raise KeyError("missing expected field")

    r = booth.check_with_evidence(
        "Paris",
        ["Paris is the capital of France."],
        compare_fn,
    )
    data = r.to_dict()

    assert data["reason"] == "COMPARE_FAILED"
    assert data["detail"] == r.detail
    assert data["checker_failed"] is True


def test_to_dict_includes_evidence_disagreement_diagnostics():
    r = booth.check_with_evidence(
        "Berlin",
        ["Paris is the capital of France."],
        lambda a, e: False,
    )
    data = r.to_dict()

    assert data["reason"] == "EVIDENCE_DISAGREES"
    assert data["detail"] == r.detail
    assert data["checker_failed"] is False


def test_all_five_check_with_evidence_reason_codes_are_reachable():
    def crashing_compare_fn(answer, evidence):
        raise RuntimeError("boom")

    cases = [
        (
            booth.check_with_evidence(
                "",
                ["evidence"],
                lambda a, e: True,
            ),
            "EMPTY_ANSWER",
            False,
        ),
        (
            booth.check_with_evidence(
                "answer",
                [],
                lambda a, e: True,
            ),
            "NO_EVIDENCE",
            False,
        ),
        (
            booth.check_with_evidence(
                "answer",
                ["evidence"],
                crashing_compare_fn,
            ),
            "COMPARE_FAILED",
            True,
        ),
        (
            booth.check_with_evidence(
                "answer",
                ["evidence"],
                lambda a, e: "not a score",
            ),
            "INVALID_SCORE",
            True,
        ),
        (
            booth.check_with_evidence(
                "answer",
                ["evidence"],
                lambda a, e: False,
            ),
            "EVIDENCE_DISAGREES",
            False,
        ),
    ]

    for result, expected_reason, expected_checker_failed in cases:
        assert result.reason == expected_reason
        assert result.detail is not None
        assert result.checker_failed is expected_checker_failed